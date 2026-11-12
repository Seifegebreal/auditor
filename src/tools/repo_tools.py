import ast
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlsplit


_REPO_PATH_PART = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAX_SOURCE_BYTES = 1_000_000


class RepoToolError(RuntimeError):
    """Raised when a repository cannot be inspected safely."""


def validate_repo_url(url: str) -> str:
    if not isinstance(url, str):
        raise RepoToolError("Rejected repo URL: expected a string")
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RepoToolError(f"Rejected repo URL: {url!r}") from exc
    host = (parsed.hostname or "").lower()
    allowed_hosts = {
        candidate.strip().lower()
        for candidate in os.getenv(
            "ALLOWED_GIT_HOSTS", "github.com,gitlab.com"
        ).split(",")
        if candidate.strip()
    }
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "https"
        or host not in allowed_hosts
        or port not in (None, 443)
        or parsed.netloc.lower() != host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or len(parts) != 2
        or any(not part or part in {".", ".."} or not _REPO_PATH_PART.fullmatch(part) for part in parts)
    ):
        raise RepoToolError(f"Rejected repo URL: {url!r}")
    repo_name = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
    if not repo_name or repo_name in {".", ".."}:
        raise RepoToolError(f"Rejected repo URL: {url!r}")
    return f"https://{host}/{parts[0]}/{repo_name}"


@contextmanager
def sandboxed_clone(repo_url: str, timeout: int = 120) -> Iterator[Path]:
    validated_url = validate_repo_url(repo_url)
    with tempfile.TemporaryDirectory(prefix="auditor_") as temporary_directory:
        destination = Path(temporary_directory) / "repo"
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        command = [
            "git",
            "-c",
            "core.symlinks=false",
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.https.allow=always",
            "clone",
            "--quiet",
            "--no-recurse-submodules",
            "--",
            validated_url,
            str(destination),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=environment,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RepoToolError("git clone timed out") from exc
        except OSError as exc:
            raise RepoToolError(f"Unable to execute git clone: {exc}") from exc
        if result.returncode != 0:
            error = result.stderr.lower()
            if any(
                marker in error
                for marker in ("authentication", "could not read", "not found", "repository not found")
            ):
                raise RepoToolError(
                    "Repository is private, missing, or authentication failed"
                )
            raise RepoToolError(f"git clone failed: {result.stderr.strip()[:300]}")
        yield destination


def _git(repo: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RepoToolError(f"git {arguments[0]} timed out") from exc
    except OSError as exc:
        raise RepoToolError(f"Unable to execute git {arguments[0]}: {exc}") from exc
    if result.returncode != 0:
        raise RepoToolError(
            f"git {arguments[0]} failed: {result.stderr.strip()[:300]}"
        )
    return result.stdout


def extract_git_history(path: str | Path) -> List[Dict[str, str]]:
    output = _git(
        Path(path), "log", "--reverse", "--pretty=format:%h|%aI|%s", "--"
    )
    history: List[Dict[str, str]] = []
    for line in output.splitlines():
        if not line:
            continue
        fields = line.split("|", 2)
        if len(fields) != 3:
            raise RepoToolError("git log returned a malformed commit record")
        commit_hash, date, message = fields
        history.append({"hash": commit_hash, "date": date, "message": message})
    return history


def _extract_git_name_status(path: str | Path) -> List[Dict[str, Any]]:
    output = _git(
        Path(path),
        "log",
        "--name-status",
        "--reverse",
        "--format=@@@%H%x1f%aI%x1f%s",
    )
    commits: List[Dict[str, Any]] = []
    for line in output.splitlines():
        if line.startswith("@@@"):
            fields = line[3:].split("\x1f", 2)
            if len(fields) != 3:
                raise RepoToolError("git log returned a malformed commit record")
            commits.append(
                {
                    "hash": fields[0],
                    "date": fields[1],
                    "message": fields[2],
                    "files": [],
                    "added_files": [],
                }
            )
            continue
        if not line or not commits:
            continue
        fields = line.split("\t")
        status = fields[0]
        paths = fields[1:]
        commits[-1]["files"].extend(paths)
        if status.startswith("A") and paths:
            commits[-1]["added_files"].append(paths[-1])
    return commits


def git_forensics(path: str | Path) -> Dict[str, Any]:
    commits = _extract_git_name_status(path)
    timestamps = [datetime.fromisoformat(commit["date"]) for commit in commits]
    span_minutes = (
        (max(timestamps) - min(timestamps)).total_seconds() / 60
        if timestamps
        else 0.0
    )
    first_touch: Dict[str, Optional[int]] = {
        "pyproject.toml": None,
        "src/tools/": None,
        "src/graph.py": None,
    }
    for index, commit in enumerate(commits, start=1):
        changed_paths = commit["files"]
        if first_touch["pyproject.toml"] is None and "pyproject.toml" in changed_paths:
            first_touch["pyproject.toml"] = index
        if first_touch["src/tools/"] is None and any(
            file_path.startswith("src/tools/") for file_path in changed_paths
        ):
            first_touch["src/tools/"] = index
        if first_touch["src/graph.py"] is None and "src/graph.py" in changed_paths:
            first_touch["src/graph.py"] = index
    sequence = [
        first_touch["pyproject.toml"],
        first_touch["src/tools/"],
        first_touch["src/graph.py"],
    ]
    ordered = (
        all(index is not None for index in sequence)
        and sequence[0] < sequence[1] < sequence[2]
    )
    total_files = len(
        [
            line
            for line in _git(Path(path), "ls-files", "--cached").splitlines()
            if line
        ]
    )
    largest_addition = max(
        (len(commit["added_files"]) for commit in commits), default=0
    )
    bulk_upload = bool(total_files) and largest_addition / total_files > 0.7
    clustered = span_minutes < 15
    public_commits = [
        {
            "hash": commit["hash"],
            "date": commit["date"],
            "message": commit["message"],
            "added_files": commit["added_files"],
        }
        for commit in commits
    ]
    return {
        "found": len(commits) > 3 and ordered and not bulk_upload,
        "location": "git log --name-status --reverse",
        "rationale": (
            f"{len(commits)} commits over {span_minutes:.1f} minutes; "
            f"setup/tool/graph progression ordered={ordered}, bulk_upload={bulk_upload}"
        ),
        "confidence": 1.0,
        "facts": {
            "commit_count": len(commits),
            "span_minutes": span_minutes,
            "clustered": clustered,
            "bulk_upload": bulk_upload,
            "progression_ordered": ordered,
            "first_commit_touching": first_touch,
            "commits": public_commits[:50],
        },
    }


def list_files(path: str | Path) -> List[str]:
    root = Path(path).resolve()
    found: List[str] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        directory_names[:] = [
            name
            for name in directory_names
            if name.lower() != ".git"
            and not (current_path / name).is_symlink()
        ]
        for file_name in file_names:
            candidate = current_path / file_name
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if not candidate.resolve().is_relative_to(root):
                continue
            found.append(candidate.relative_to(root).as_posix())
    return sorted(found)


def _safe_source(root: Path, relative_path: str) -> Tuple[Optional[str], str]:
    source = root / relative_path
    if source.is_symlink() or not source.is_file():
        return None, relative_path
    if not source.resolve().is_relative_to(root.resolve()):
        return None, relative_path
    try:
        if source.stat().st_size > _MAX_SOURCE_BYTES:
            return None, relative_path
        return source.read_text(encoding="utf-8"), relative_path
    except (OSError, UnicodeError):
        return None, relative_path


def _parse_source(root: Path, relative_path: str) -> Tuple[Optional[ast.Module], Optional[str]]:
    text, location = _safe_source(root, relative_path)
    if text is None:
        return None, None
    try:
        return ast.parse(text, filename=location), text
    except SyntaxError as exc:
        return None, f"syntax error in {location}: {exc}"


def _node_label(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _result(
    found: bool,
    location: str,
    rationale: str,
    facts: Optional[Dict[str, Any]] = None,
    confidence: float = 1.0,
) -> Dict[str, Any]:
    return {
        "found": found,
        "location": location,
        "rationale": rationale,
        "confidence": confidence,
        "facts": facts or {},
    }


def analyze_graph_structure(path: str | Path) -> Dict[str, Any]:
    root = Path(path)
    relative_path = "src/graph.py"
    tree, text_or_error = _parse_source(root, relative_path)
    if tree is None:
        reason = text_or_error or f"{relative_path} missing or unreadable"
        return _result(
            False,
            relative_path,
            reason,
            {"syntax_error": bool(text_or_error and text_or_error.startswith("syntax error"))},
        )
    text = text_or_error or ""
    nodes: List[Optional[str]] = []
    edges: List[Tuple[Optional[str], Optional[str]]] = []
    conditional_sources: List[Optional[str]] = []
    relevant_lines: List[int] = []
    has_state_graph = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else _node_label(node.func)
        if name == "StateGraph":
            has_state_graph = True
        elif name == "add_node" and node.args:
            nodes.append(_node_label(node.args[0]))
            relevant_lines.append(node.lineno)
        elif name == "add_edge" and len(node.args) == 2:
            source_arg = node.args[0]
            sources = (
                source_arg.elts
                if isinstance(source_arg, (ast.List, ast.Tuple))
                else [source_arg]
            )
            edges.extend((_node_label(source), _node_label(node.args[1])) for source in sources)
            relevant_lines.append(node.lineno)
        elif name == "add_conditional_edges" and node.args:
            conditional_sources.append(_node_label(node.args[0]))
            relevant_lines.append(node.lineno)

    outgoing: Dict[Optional[str], List[Optional[str]]] = {}
    incoming: Dict[Optional[str], List[Optional[str]]] = {}
    for source, destination in edges:
        outgoing.setdefault(source, []).append(destination)
        incoming.setdefault(destination, []).append(source)
    fan_out = {source: destinations for source, destinations in outgoing.items() if len(destinations) > 1}
    fan_in = {destination: sources for destination, sources in incoming.items() if len(sources) > 1}
    normalized = lambda labels: {str(label).lower() for label in labels}
    facts = {
        "nodes": nodes,
        "edges": edges,
        "conditional_sources": conditional_sources,
        "fan_out": fan_out,
        "fan_in": fan_in,
        "parallel_fan_out": bool(fan_out),
        "detective_fan_out": any(
            {"repoinvestigator", "docanalyst"}.issubset(normalized(destinations))
            for destinations in fan_out.values()
        ),
        "judge_fan_out": any(
            {"prosecutor", "defense", "techlead"}.issubset(normalized(destinations))
            for destinations in fan_out.values()
        ),
        "has_conditional_edges": bool(conditional_sources),
        "snippet": (
            "\n".join(text.splitlines()[min(relevant_lines) - 1 : max(relevant_lines)])
            if relevant_lines
            else ""
        ),
    }
    fanout_count = len(fan_out)
    fanin_count = len(fan_in)
    return _result(
        has_state_graph,
        relative_path,
        f"{fanout_count} fan-out sources, {fanin_count} fan-in targets",
        facts,
        0.95,
    )


def _base_names(class_node: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for base in class_node.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def _is_reducer(annotation: ast.AST, reducer: str) -> bool:
    if not isinstance(annotation, ast.Subscript):
        return False
    if not isinstance(annotation.value, ast.Name) or annotation.value.id != "Annotated":
        return False
    metadata = annotation.slice
    metadata_nodes = metadata.elts if isinstance(metadata, ast.Tuple) else [metadata]
    return any(
        isinstance(item, ast.Attribute)
        and item.attr == reducer
        and isinstance(item.value, ast.Name)
        and item.value.id == "operator"
        for item in metadata_nodes
    )


def analyze_state_file(path: str | Path) -> Dict[str, Any]:
    root = Path(path)
    candidates = ("src/state.py", "src/graph.py")
    files = [(name, *_parse_source(root, name)) for name in candidates]
    parsed = [(name, tree, text) for name, tree, text in files if tree is not None]
    if not parsed:
        errors = [text for _, _, text in files if text]
        reason = "; ".join(errors) if errors else "src/state.py and src/graph.py missing"
        return _result(False, "src/state.py", reason)

    basemodel_classes: List[str] = []
    typeddict_classes: List[str] = []
    reducers: set[str] = set()
    has_evidence_model = False
    has_opinion_model = False
    uses_plain_dict_state = True
    snippets: List[str] = []
    for relative_path, tree, source_text in parsed:
        assert tree is not None and source_text is not None
        source_lines = source_text.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = _base_names(node)
                if "BaseModel" in bases:
                    basemodel_classes.append(node.name)
                    has_evidence_model |= node.name == "Evidence"
                    has_opinion_model |= node.name == "JudicialOpinion"
                    if node.name == "AgentState":
                        uses_plain_dict_state = False
                if "TypedDict" in bases:
                    typeddict_classes.append(node.name)
                    if node.name == "AgentState":
                        uses_plain_dict_state = False
                        snippet = "\n".join(
                            source_lines[node.lineno - 1 : getattr(node, "end_lineno", node.lineno)]
                        )
                        snippets.append(snippet)
            if isinstance(node, ast.AnnAssign) and node.annotation:
                for reducer in ("add", "ior"):
                    if _is_reducer(node.annotation, reducer):
                        reducers.add(f"operator.{reducer}")
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "AgentState"
            ):
                uses_plain_dict_state = True

    facts = {
        "basemodel_classes": sorted(set(basemodel_classes)),
        "typeddict_classes": sorted(set(typeddict_classes)),
        "reducers_used": sorted(reducers),
        "has_evidence_model": has_evidence_model,
        "has_opinion_model": has_opinion_model,
        "uses_plain_dict_state": uses_plain_dict_state,
        "agentstate_snippet": "\n".join(snippets),
    }
    success = bool(typeddict_classes or "AgentState" in basemodel_classes)
    return _result(
        success,
        "src/state.py",
        f"{len(basemodel_classes)} Pydantic models, {len(typeddict_classes)} TypedDicts, "
        f"reducers: {', '.join(sorted(reducers)) or 'none'}",
        facts,
        0.95,
    )


def scan_tools_security(path: str | Path) -> Dict[str, Any]:
    root = Path(path)
    tools_path = root / "src" / "tools"
    if not tools_path.is_dir():
        return _result(False, "src/tools", "src/tools directory missing")

    os_system_calls: List[str] = []
    uses_tempdir = False
    uses_subprocess_run = False
    checks_returncode = False
    validates_url = False
    scanned_files = 0
    for relative_path in list_files(root):
        if not relative_path.startswith("src/tools/") or not relative_path.endswith(".py"):
            continue
        tree, text_or_error = _parse_source(root, relative_path)
        if tree is None:
            continue
        scanned_files += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                name = function.attr if isinstance(function, ast.Attribute) else _node_label(function)
                if (
                    name == "system"
                    and isinstance(function, ast.Attribute)
                    and isinstance(function.value, ast.Name)
                    and function.value.id == "os"
                ):
                    os_system_calls.append(f"{relative_path}:{node.lineno}")
                if name == "TemporaryDirectory":
                    uses_tempdir = True
                if name == "run" and isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
                    uses_subprocess_run |= function.value.id == "subprocess"
                if name == "check_returncode":
                    checks_returncode = True
                if name == "run":
                    checks_returncode |= any(
                        keyword.arg == "check"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                        for keyword in node.keywords
                    )
            if isinstance(node, ast.Attribute) and node.attr == "returncode":
                checks_returncode = True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "validate_repo_url":
                validates_url = True
    facts = {
        "os_system_calls": os_system_calls,
        "uses_tempdir": uses_tempdir,
        "uses_subprocess_run": uses_subprocess_run,
        "checks_returncode": checks_returncode,
        "validates_url": validates_url,
        "scanned_files": scanned_files,
    }
    return _result(
        scanned_files > 0,
        "src/tools/",
        f"Scanned {scanned_files} tool files; "
        f"{len(os_system_calls)} os.system calls",
        facts,
        0.95,
    )


def scan_judges(path: str | Path) -> Dict[str, Any]:
    relative_path = "src/nodes/judges.py"
    tree, text_or_error = _parse_source(Path(path), relative_path)
    if tree is None:
        return _result(
            False,
            relative_path,
            text_or_error or f"{relative_path} missing or unreadable",
        )
    uses_structured_output = False
    bound_to_opinion = False
    has_retry = False
    relevant_lines: List[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else _node_label(node.func)
            if name == "with_structured_output":
                uses_structured_output = True
                relevant_lines.append(node.lineno)
                bound_to_opinion |= any(_node_label(arg) == "JudicialOpinion" for arg in node.args)
        if isinstance(node, (ast.For, ast.While)):
            has_retry = True
    facts = {
        "uses_with_structured_output": uses_structured_output,
        "binds_judicial_opinion": bound_to_opinion,
        "has_retry": has_retry,
        "llm_call_snippet": (
            "\n".join((text_or_error or "").splitlines()[min(relevant_lines) - 1 : max(relevant_lines)])
            if relevant_lines
            else ""
        ),
    }
    return _result(
        uses_structured_output and bound_to_opinion,
        relative_path,
        "Structured output is bound to JudicialOpinion"
        if bound_to_opinion
        else "Structured JudicialOpinion output was not detected",
        facts,
        0.95,
    )


def analyze_judge_prompts(path: str | Path) -> Dict[str, Any]:
    relative_path = "src/nodes/judges.py"
    tree, text_or_error = _parse_source(Path(path), relative_path)
    if tree is None:
        return _result(
            False,
            relative_path,
            text_or_error or f"{relative_path} missing or unreadable",
        )
    prompt_values: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None:
            continue
        prompt = next(
            (
                target.id
                for target in targets
                if isinstance(target, ast.Name) and target.id.endswith("_PROMPT")
            ),
            None,
        )
        if prompt:
            prompt_text = " ".join(
                constant.value
                for constant in ast.walk(value)
                if isinstance(constant, ast.Constant)
                and isinstance(constant.value, str)
            )
            prompt_values[prompt] = prompt_text
        elif any(
            isinstance(target, ast.Name) and target.id == "PROMPTS"
            for target in targets
        ) and isinstance(value, ast.Dict):
            for key, prompt_value in zip(value.keys, value.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value in {"Prosecutor", "Defense", "TechLead"}
                ):
                    prompt_values[str(key.value)] = " ".join(
                        constant.value
                        for constant in ast.walk(prompt_value)
                        if isinstance(constant, ast.Constant)
                        and isinstance(constant.value, str)
                    )
    longest = sorted(prompt_values.items(), key=lambda item: len(item[1]), reverse=True)[:3]
    word_sets = [
        set(re.findall(r"[a-z0-9]+", value.lower()))
        for _, value in longest
    ]
    overlaps = []
    for index, first in enumerate(word_sets):
        for second in word_sets[index + 1 :]:
            union = first | second
            overlaps.append(len(first & second) / len(union) if union else 0.0)
    overlap_pct = round(max(overlaps, default=0.0) * 100, 1)
    facts = {
        "persona_count": len(longest),
        "prompt_overlap_pct": overlap_pct,
        "prompt_names": [name for name, _ in longest],
    }
    return _result(
        len(longest) == 3 and overlap_pct <= 50,
        relative_path,
        f"{len(longest)} judge prompts; maximum pairwise overlap {overlap_pct}%",
        facts,
        0.9,
    )


def analyze_justice(path: str | Path) -> Dict[str, Any]:
    relative_path = "src/nodes/justice.py"
    tree, text_or_error = _parse_source(Path(path), relative_path)
    if tree is None:
        return _result(
            False,
            relative_path,
            text_or_error or f"{relative_path} missing or unreadable",
        )
    source_text = text_or_error or ""
    has_llm_call = False
    writes_markdown = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else _node_label(node.func)
            has_llm_call |= name in {"invoke", "with_structured_output"}
            writes_markdown |= name == "write_text"
            if name == "open" and len(node.args) > 1:
                mode = node.args[1]
                writes_markdown |= isinstance(mode, ast.Constant) and "w" in str(mode.value)
    lower_source = source_text.lower()
    marker_names = {
        "security": ("security", "security negligence"),
        "evidence": ("evidence", "rule of evidence", "fact supremacy"),
        "functionality": ("functionality", "graph_orchestration"),
        "variance": ("variance", "dissent"),
    }
    rule_markers = [
        marker
        for marker, aliases in marker_names.items()
        if any(alias in lower_source for alias in aliases)
    ]
    facts = {
        "has_llm_call": has_llm_call,
        "rule_markers": rule_markers,
        "writes_markdown": writes_markdown,
    }
    return _result(
        not has_llm_call and writes_markdown,
        relative_path,
        "Deterministic synthesis with Markdown report output"
        if not has_llm_call and writes_markdown
        else "Deterministic synthesis or Markdown output is missing",
        facts,
        0.9,
    )
