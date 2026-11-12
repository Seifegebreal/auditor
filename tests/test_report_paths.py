from pathlib import Path
import warnings

from scripts.check_report_paths import (
    _architecture_text,
    _claimed_paths,
    _tracked_files,
    _unexplained_concepts,
    check_report,
)
from src.tools.doc_tools import Chunk


def test_architecture_check_ignores_summary_only_concepts():
    text = (
        "# Executive Summary\n"
        "Dialectical Synthesis, Fan-In / Fan-Out, Metacognition, and State "
        "Synchronization are important.\n"
        "# Architecture\n"
        "Dialectical Synthesis is implemented because three independent judges "
        "evaluate evidence before the deterministic justice node resolves conflicts. "
        "Fan-In / Fan-Out occurs through explicit parallel edges that aggregate the "
        "detectives before judges run. Metacognition enables the auditor to evaluate "
        "its own scoring loop. State Synchronization uses reducers to merge updates "
        "from concurrently running nodes."
    )
    assert _unexplained_concepts(_architecture_text(text)) == []


def test_architecture_check_includes_topic_headings_with_their_explanations():
    text = (
        "# Fan-In / Fan-Out\n"
        "Fan-Out is implemented by explicit graph edges from the setup node to "
        "parallel investigators. Fan-In is implemented through aggregation before "
        "the judges run."
    )

    assert _unexplained_concepts(_architecture_text(text)) == [
        "Dialectical Synthesis",
        "Metacognition",
        "State Synchronization",
    ]


def test_paths_are_extracted_and_summary_does_not_count_as_architecture():
    text = (
        "# Executive Summary\n"
        "Metacognition is useful; src/state.py implements typed state.\n"
        "# Architecture\n"
        "Dialectical Synthesis is implemented through independent judges. "
        "Fan-In / Fan-Out allows parallel graph execution. "
        "State Synchronization uses reducers."
    )
    assert _claimed_paths(text) == {"src/state.py"}
    assert _unexplained_concepts(_architecture_text(text)) == ["Metacognition"]


def test_report_checker_compares_with_git_tracked_paths_and_explanations(
    tmp_path, monkeypatch
):
    report_path = tmp_path / "final.pdf"
    report_path.write_bytes(b"fixture")
    report = (
        "# Architecture\n"
        "Dialectical Synthesis is implemented through independent judges. "
        "Fan-In / Fan-Out occurs through synchronized edges. "
        "Metacognition enables the auditor to evaluate itself. "
        "State Synchronization uses reducers.\n"
        "Cited source: src/state.py, src/missing.py, and src/deleted.py."
    )
    monkeypatch.setattr(
        "scripts.check_report_paths._tracked_files",
        lambda repository: {"src/state.py", "src/deleted.py"},
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "state.py").write_text("class AgentState: ...", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.check_report_paths.ingest_pdf",
        lambda path: [Chunk(index=0, section="Architecture", text=report)],
    )
    missing, unexplained = check_report(report_path, tmp_path)
    assert missing == {"src/missing.py", "src/deleted.py"}
    assert unexplained == []


def test_untracked_workspace_falls_back_to_files_present_on_disk(tmp_path):
    source = tmp_path / "src" / "state.py"
    source.parent.mkdir()
    source.write_text("class AgentState: ...", encoding="utf-8")
    ignored = tmp_path / ".venv" / "Lib" / "site.py"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("# dependency", encoding="utf-8")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        files = _tracked_files(tmp_path)

    assert files == {"src/state.py"}
    assert len(caught) == 1
    assert "not a Git repository" in str(caught[0].message)
    assert "files present on disk" in str(caught[0].message)
