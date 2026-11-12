import json
from contextlib import nullcontext

from src.nodes import detectives
from src.nodes.detectives import Evidence, evidence_aggregator_node, repo_investigator_node


def _dimension(identifier, target="github_repo", instruction="Inspect this artifact."):
    return {
        "id": identifier,
        "name": identifier,
        "target_artifact": target,
        "forensic_instruction": instruction,
        "success_pattern": "present",
        "failure_pattern": "missing",
    }


def test_repo_scanner_failure_is_isolated_and_instructions_are_attached(monkeypatch, tmp_path):
    def broken_scanner(repository):
        raise RuntimeError("scanner-specific failure")

    def successful_scanner(repository):
        return {
            "found": True,
            "location": "src/graph.py",
            "rationale": "AST parsed",
            "confidence": 0.9,
            "facts": {},
        }

    monkeypatch.setattr(
        detectives, "sandboxed_clone", lambda url: nullcontext(tmp_path)
    )
    monkeypatch.setattr(detectives, "list_files", lambda repo: ["src/graph.py"])
    monkeypatch.setattr(
        detectives,
        "SCANNERS",
        {"failing": broken_scanner, "successful": successful_scanner},
    )
    result = repo_investigator_node(
        {
            "repo_url": "https://github.com/example/repo",
            "rubric_dimensions": [
                _dimension("failing", instruction="Look for failures."),
                _dimension("successful", instruction="Check graph topology."),
                _dimension("unregistered", instruction="Check missing scanner."),
            ],
        }
    )
    evidence = {item.goal: item for item in result["evidences"]["RepoInvestigator"]}
    assert not evidence["failing"].found
    assert "scanner failed" in evidence["failing"].rationale
    assert evidence["successful"].found
    assert evidence["successful"].rationale.startswith("Check graph topology.")
    assert not evidence["unregistered"].found
    assert "No repository scanner" in evidence["unregistered"].rationale
    assert "errors" not in result


def test_evidence_aggregator_compares_diagram_and_graph_facts():
    graph_evidence = Evidence(
        goal="graph_orchestration",
        found=True,
        content=json.dumps(
            {"detective_fan_out": True, "judge_fan_out": True}
        ),
        location="src/graph.py",
        rationale="Parallel graph",
        confidence=1.0,
    )
    visual_evidence = Evidence(
        goal="swarm_visual",
        found=True,
        content=json.dumps(
            {
                "diagrams": [
                    {
                        "shows_parallel_detectives": True,
                        "shows_parallel_judges": False,
                    }
                ]
            }
        ),
        location="report.pdf",
        rationale="One visual",
        confidence=0.8,
    )
    state = {
        "repo_manifest": ["src/graph.py"],
        "claimed_paths": ["src/graph.py"],
        "pdf_path": "report.pdf",
        "evidences": {
            "RepoInvestigator": [graph_evidence],
            "VisionInspector": [visual_evidence],
        },
    }
    result = evidence_aggregator_node(state)
    facts = json.loads(result["evidences"]["Aggregator"][0].content)
    assert not facts["diagram_matches_code"]
