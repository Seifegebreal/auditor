import argparse
import os
import re
import subprocess
import warnings
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

from src.tools.doc_tools import PATH_RE, ingest_pdf


ARCHITECTURE_HEADINGS = re.compile(
    r"architecture|system design|orchestration|implementation details|typed state|"
    r"parallel graph|repository inspection|report ingestion|fan[\s/-]*in|"
    r"fan[\s/-]*out|state synchronization|dialectical synthesis|metacognition|"
    r"deterministic synthesis",
    re.IGNORECASE,
)
EXPLANATION_CUES = re.compile(
    r"\b(implemented|because|through|when|where|allows|enables|synchroniz|"
    r"branches|aggregat|evaluat|resolv|reducers?)\b",
    re.IGNORECASE,
)
REQUIRED_CONCEPTS = {
    "Dialectical Synthesis": re.compile(r"dialectical\s+synthesis", re.IGNORECASE),
    "Fan-In / Fan-Out": re.compile(
        r"fan[\s-]*in.{0,100}fan[\s/-]*out|fan[\s/-]*out.{0,100}fan[\s-]*in",
        re.IGNORECASE | re.DOTALL,
    ),
    "Metacognition": re.compile(r"metacognition", re.IGNORECASE),
    "State Synchronization": re.compile(r"state\s+synchronization", re.IGNORECASE),
}


def _tracked_files(repository: Path) -> Set[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        if "not a git repository" in result.stderr.lower():
            warnings.warn(
                "repo-root is not a Git repository; checking cited paths against "
                "files present on disk instead of Git-tracked files",
                RuntimeWarning,
                stacklevel=2,
            )
            ignored_directories = {
                ".git",
                ".pytest_cache",
                ".venv",
                "__pycache__",
            }
            files: Set[str] = set()
            for directory, subdirectories, filenames in os.walk(repository):
                subdirectories[:] = [
                    name
                    for name in subdirectories
                    if name not in ignored_directories
                ]
                base = Path(directory)
                files.update(
                    (base / filename).relative_to(repository).as_posix()
                    for filename in filenames
                )
            return files
        raise RuntimeError(f"git ls-files failed: {result.stderr.strip()}")
    return {
        line.replace("\\", "/").removeprefix("./")
        for line in result.stdout.splitlines()
        if line
    }


def _report_text(path: Path) -> str:
    return "\n".join(
        f"# {chunk.section}\n{chunk.text}" for chunk in ingest_pdf(str(path))
    )


def _claimed_paths(report_text: str) -> Set[str]:
    return {
        match.replace("\\", "/").removeprefix("./")
        for match in PATH_RE.findall(report_text)
    }


def _architecture_text(report_text: str) -> str:
    sections: List[str] = []
    current_heading = ""
    current_lines: List[str] = []
    for line in report_text.splitlines():
        if line.lstrip().startswith("#"):
            if ARCHITECTURE_HEADINGS.search(current_heading):
                sections.append(f"{current_heading}\n" + "\n".join(current_lines))
            current_heading = line.lstrip("# ").strip()
            current_lines = []
        else:
            current_lines.append(line)
    if ARCHITECTURE_HEADINGS.search(current_heading):
        sections.append(f"{current_heading}\n" + "\n".join(current_lines))
    return "\n".join(sections)


def _unexplained_concepts(architecture_text: str) -> List[str]:
    unexplained = []
    for concept, pattern in REQUIRED_CONCEPTS.items():
        match = pattern.search(architecture_text)
        if not match:
            unexplained.append(concept)
            continue
        context = architecture_text[max(0, match.start() - 180) : match.end() + 320]
        if len(context) < 80 or not EXPLANATION_CUES.search(context):
            unexplained.append(concept)
    return unexplained


def check_report(report_path: Path, repository: Path) -> Tuple[Set[str], List[str]]:
    report_text = _report_text(report_path)
    repository = repository.resolve()
    tracked = _tracked_files(repository)
    missing_paths = sorted(
        path
        for path in _claimed_paths(report_text)
        if path not in tracked or not (repository / path).is_file()
    )
    unexplained = _unexplained_concepts(_architecture_text(report_text))
    return set(missing_paths), unexplained


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate report paths and architecture explanations."
    )
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    arguments = parser.parse_args()
    if not arguments.pdf.is_file():
        parser.error(f"PDF report does not exist: {arguments.pdf}")
    missing_paths, unexplained = check_report(
        arguments.pdf, arguments.repo_root.resolve()
    )
    if missing_paths:
        print("Untracked or nonexistent report paths:")
        for path in sorted(missing_paths):
            print(f"- {path}")
    if unexplained:
        print("Concepts not explained in an architecture section:")
        for concept in unexplained:
            print(f"- {concept}")
    if not missing_paths and not unexplained:
        print("Report paths and architecture explanations verified.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
