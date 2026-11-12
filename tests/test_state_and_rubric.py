import typing

import pytest

from pathlib import Path

from src.rubric import RubricError, load_rubric
from src.state import AgentState, Evidence, JudicialOpinion


def test_parallel_state_reducers_merge_independent_updates():
    hints = typing.get_type_hints(AgentState, include_extras=True)
    evidence_reducer = typing.get_args(hints["evidences"])[1]
    opinions_reducer = typing.get_args(hints["opinions"])[1]
    manifest_reducer = typing.get_args(hints["repo_manifest"])[1]

    evidence_a = {"RepoInvestigator": [Evidence(
        goal="graph_orchestration",
        found=True,
        content="{}",
        location="src/graph.py",
        rationale="AST fan-out detected",
        confidence=0.95,
    )]}
    evidence_b = {"DocAnalyst": [Evidence(
        goal="theoretical_depth",
        found=True,
        content="{}",
        location="report.pdf",
        rationale="Detailed discussion",
        confidence=0.9,
    )]}
    assert evidence_reducer(evidence_a, evidence_b) == {**evidence_a, **evidence_b}
    assert manifest_reducer(["src/state.py"], ["src/graph.py"]) == [
        "src/state.py",
        "src/graph.py",
    ]

    prosecutor = JudicialOpinion(
        judge="Prosecutor",
        criterion_id="graph_orchestration",
        score=1,
        argument="No parallel route.",
        cited_evidence=["graph_orchestration:src/graph.py"],
    )
    tech_lead = prosecutor.model_copy(update={"judge": "TechLead", "score": 3})
    assert opinions_reducer([prosecutor], [tech_lead]) == [prosecutor, tech_lead]


def test_load_rubric_returns_metadata_dimensions_and_synthesis_rules():
    rubric_path = Path(__file__).resolve().parents[1] / "rubric.json"
    config = load_rubric(rubric_path)
    assert len(config["dimensions"]) == 10
    assert config["metadata"]["rubric_name"]
    assert config["synthesis_rules"]["security_override"]


def test_rubric_reports_missing_file(tmp_path):
    with pytest.raises(RubricError, match="not found"):
        load_rubric(tmp_path / "missing.json")
