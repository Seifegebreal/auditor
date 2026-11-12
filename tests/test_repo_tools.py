import subprocess
from pathlib import Path

import pytest

from src.tools.repo_tools import (
    RepoToolError,
    analyze_graph_structure,
    analyze_judge_prompts,
    analyze_justice,
    analyze_state_file,
    git_forensics,
    list_files,
    scan_judges,
    scan_tools_security,
    sandboxed_clone,
    validate_repo_url,
)


def test_validate_repo_url_accepts_only_github_repository_https_urls():
    assert validate_repo_url("https://github.com/owner/repository.git") == (
        "https://github.com/owner/repository"
    )
    assert validate_repo_url("https://gitlab.com/group/repository") == (
        "https://gitlab.com/group/repository"
    )
    for url in (
        "-https://github.com/owner/repository",
        "https://github.com/owner/repository/extra",
        "https://github.com.evil.example/owner/repository",
        "file://github.com/owner/repository",
        "https://user:password@github.com/owner/repository",
    ):
        with pytest.raises(RepoToolError):
            validate_repo_url(url)


def test_validate_repo_url_uses_configurable_host_allowlist(monkeypatch):
    monkeypatch.setenv("ALLOWED_GIT_HOSTS", "code.example")
    assert validate_repo_url("https://code.example/group/repository")
    with pytest.raises(RepoToolError):
        validate_repo_url("https://github.com/group/repository")


def test_invalid_clone_url_never_creates_a_temp_directory(monkeypatch):
    import tempfile

    def fail_if_called(*args, **kwargs):
        raise AssertionError("TemporaryDirectory must not be opened for invalid URLs")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", fail_if_called)
    with pytest.raises(RepoToolError):
        with sandboxed_clone("https://example.com/owner/repository"):
            pass


def test_clone_sandbox_is_removed_after_successful_context(monkeypatch):
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["destination"] = Path(command[-1])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with sandboxed_clone("https://github.com/owner/repository") as cloned:
        assert "core.symlinks=false" in observed["command"]
        assert cloned == observed["destination"]
        temporary_root = cloned.parent
        assert temporary_root.exists()
    assert not temporary_root.exists()


def test_graph_ast_scanner_detects_explicit_fan_out_and_fan_in(tmp_path):
    source = tmp_path / "src" / "graph.py"
    source.parent.mkdir()
    source.write_text(
        "\n".join(
            [
                "builder = StateGraph(AgentState)",
                "builder.add_node('RepoInvestigator', repo)",
                "builder.add_node('DocAnalyst', doc)",
                "builder.add_node('EvidenceAggregator', aggregate)",
                "builder.add_node('Prosecutor', prosecutor)",
                "builder.add_node('Defense', defense)",
                "builder.add_node('TechLead', techlead)",
                "builder.add_edge('ContextBuilder', 'RepoInvestigator')",
                "builder.add_edge('ContextBuilder', 'DocAnalyst')",
                "builder.add_edge('RepoInvestigator', 'EvidenceAggregator')",
                "builder.add_edge('DocAnalyst', 'EvidenceAggregator')",
                "builder.add_edge('Dispatch', 'Prosecutor')",
                "builder.add_edge('Dispatch', 'Defense')",
                "builder.add_edge('Dispatch', 'TechLead')",
                "builder.add_conditional_edges('EvidenceAggregator', route, routes)",
            ]
        ),
        encoding="utf-8",
    )
    result = analyze_graph_structure(tmp_path)
    assert result["facts"]["detective_fan_out"]
    assert result["facts"]["judge_fan_out"]
    assert "EvidenceAggregator" in result["facts"]["fan_in"]
    assert result["facts"]["has_conditional_edges"]


def test_graph_ast_scanner_rejects_linear_graph(tmp_path):
    source = tmp_path / "src" / "graph.py"
    source.parent.mkdir()
    source.write_text(
        "builder = StateGraph(State)\nbuilder.add_edge('A', 'B')\n",
        encoding="utf-8",
    )
    result = analyze_graph_structure(tmp_path)
    assert result["found"]
    assert not result["facts"]["parallel_fan_out"]
    assert not result["facts"]["fan_in"]


def test_graph_ast_scanner_reports_syntax_errors(tmp_path):
    source = tmp_path / "src" / "graph.py"
    source.parent.mkdir()
    source.write_text("builder.add_edge(", encoding="utf-8")
    result = analyze_graph_structure(tmp_path)
    assert not result["found"]
    assert result["facts"]["syntax_error"]


def test_persona_prompts_have_three_distinct_low_overlap_texts():
    repository = Path(__file__).resolve().parents[1]
    result = analyze_judge_prompts(repository)
    assert result["facts"]["persona_count"] == 3
    assert result["facts"]["prompt_overlap_pct"] <= 50


def test_repo_scanners_recognize_this_implementation():
    repository = Path(__file__).resolve().parents[1]
    assert analyze_state_file(repository)["facts"]["has_evidence_model"]
    assert analyze_state_file(repository)["facts"]["has_opinion_model"]
    assert {"operator.add", "operator.ior"}.issubset(
        analyze_state_file(repository)["facts"]["reducers_used"]
    )
    security = scan_tools_security(repository)["facts"]
    assert security["uses_tempdir"]
    assert security["uses_subprocess_run"]
    assert security["validates_url"]
    assert not security["os_system_calls"]
    judge = scan_judges(repository)["facts"]
    assert judge["binds_judicial_opinion"]
    assert judge["has_retry"]
    assert "security" in analyze_justice(repository)["facts"]["rule_markers"]


def test_file_manifest_excludes_git_metadata(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "state.py").write_text("pass", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("private", encoding="utf-8")
    assert list_files(tmp_path) == ["src/state.py"]


def test_git_forensics_captures_order_timing_and_bulk_upload(monkeypatch, tmp_path):
    log = (
        "@@@a\x1f2026-01-01T00:00:00+00:00\x1fsetup\n"
        "A\tpyproject.toml\n"
        + "".join(f"A\tfile{i}.py\n" for i in range(7))
        + "@@@b\x1f2026-01-01T00:20:00+00:00\x1ftools\n"
        "A\tsrc/tools/repo_tools.py\n"
        "@@@c\x1f2026-01-01T00:40:00+00:00\x1fgraph\n"
        "A\tsrc/graph.py\n"
        "@@@d\x1f2026-01-01T01:00:00+00:00\x1ftests\n"
        "A\ttests/test_graph.py\n"
    )

    def fake_git(repository, *arguments):
        if arguments[0] == "log":
            return log
        if arguments[0] == "ls-files":
            return "\n".join(f"tracked{i}.py" for i in range(10))
        raise AssertionError(arguments)

    monkeypatch.setattr("src.tools.repo_tools._git", fake_git)
    result = git_forensics(tmp_path)
    facts = result["facts"]
    assert facts["progression_ordered"]
    assert facts["first_commit_touching"] == {
        "pyproject.toml": 1,
        "src/tools/": 2,
        "src/graph.py": 3,
    }
    assert facts["span_minutes"] == 60
    assert not facts["clustered"]
    assert facts["bulk_upload"]


def test_scanner_file_reads_are_capped_at_one_megabyte(tmp_path):
    from src.tools.repo_tools import _safe_source

    source = tmp_path / "large.py"
    source.write_bytes(b"x" * 1_000_001)
    assert _safe_source(tmp_path, "large.py") == (None, "large.py")


def test_file_manifest_skips_symlinks(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}_outside.py"
    outside.write_text("secret = True", encoding="utf-8")
    link = tmp_path / "linked.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not supported by this environment")
    try:
        assert "linked.py" not in list_files(tmp_path)
    finally:
        outside.unlink(missing_ok=True)
