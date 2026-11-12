import pytest


def test_judicial_dispatch_preserves_error_reducer_with_empty_update():
    pytest.importorskip("langgraph")
    from src.graph import judicial_dispatch_node

    assert judicial_dispatch_node({}) == {"errors": []}


def test_application_graph_has_explicit_detective_and_judge_fan_outs():
    from pathlib import Path

    from src.tools.repo_tools import analyze_graph_structure

    repository = Path(__file__).resolve().parents[1]
    facts = analyze_graph_structure(repository)["facts"]
    assert facts["detective_fan_out"]
    assert facts["judge_fan_out"]
    assert "EvidenceAggregator" in facts["fan_in"]
    assert "ChiefJustice" in facts["fan_in"]
    assert facts["has_conditional_edges"]


def test_graph_compiles_with_both_explicit_parallel_layers():
    pytest.importorskip("langgraph")
    from src.graph import build_graph

    graph = build_graph()
    assert graph is not None


def test_full_graph_runs_with_injected_fake_chat_model(tmp_path, monkeypatch):
    import html
    import json
    import re
    from contextlib import nullcontext
    from pathlib import Path

    pytest.importorskip("langgraph")
    import src.nodes.detectives as detectives
    from src.graph import build_graph

    class FakeChatModel:
        def with_structured_output(self, schema, **kwargs):
            return self

        def invoke(self, messages):
            human = messages[1].content if hasattr(messages[1], "content") else messages[1][1]
            criterion_id = re.search(r"\(([^()]+)\)", human).group(1)
            match = re.search(r"<evidence>\s*(.*?)\s*</evidence>", human, re.DOTALL)
            evidence = json.loads(html.unescape(match.group(1))) if match else []
            citation = (
                f"{evidence[0]['goal']}:{evidence[0]['location']}"
                if evidence
                else f"{criterion_id}:n/a"
            )
            return {
                "score": 3,
                "argument": "src/state.py: retain typed state and reducers.",
                "cited_evidence": [citation],
            }

    repository = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(detectives, "sandboxed_clone", lambda url: nullcontext(repository))
    monkeypatch.delenv("VISION_MODEL", raising=False)
    report_path = tmp_path / "architecture.md"
    report_path.write_text(
        "# Architecture\n"
        "Dialectical Synthesis occurs when Prosecutor, Defense, and TechLead evaluate "
        "the same evidence independently and ChiefJustice resolves their scores. "
        "Fan-In / Fan-Out occurs at explicit graph edges, with reducers synchronizing "
        "parallel state updates. Metacognition is implemented by evaluating the auditor "
        "itself against its rubric. State Synchronization uses state reducers.\n"
        "The implementation is in src/state.py and src/graph.py.",
        encoding="utf-8",
    )
    rubric_path = repository / "rubric.json"
    result = build_graph(
        llm_factory=lambda model, **kwargs: FakeChatModel()
    ).invoke(
        {
            "repo_url": "https://github.com/example/repo",
            "pdf_path": str(report_path),
            "rubric_path": str(rubric_path),
            "output_dir": str(tmp_path / "audit"),
            "repo_manifest": [],
            "claimed_paths": [],
            "errors": [],
            "evidences": {},
            "opinions": [],
        }
    )
    assert len(result["final_report"].criteria) == 10
    assert len(result["final_report"].criteria[0].judge_opinions) == 3
    assert Path(result["report_path"]).is_file()
