import json
from contextlib import nullcontext

from src.nodes import detectives
from src.nodes.detectives import (
    Evidence,
    doc_analyst_node,
    evidence_aggregator_node,
    repo_investigator_node,
)


def _dimension(identifier, target="github_repo", instruction="Inspect this artifact."):
    return {
        "id": identifier,
        "name": identifier,
        "target_artifact": target,
        "forensic_instruction": instruction,
        "success_pattern": "present",
        "failure_pattern": "missing",
    }


def test_doc_analyst_requires_substantive_coverage_of_every_concept(tmp_path):
    report = tmp_path / "report.md"
    report.write_text(
        "# Introduction\n"
        "Metacognition is one of the required concepts.\n"
        "# Architecture\n"
        "Dialectical Synthesis uses independent judges. Fan-In and Fan-Out "
        "are implemented by graph edges. State Synchronization uses reducers.",
        encoding="utf-8",
    )
    result = doc_analyst_node(
        {
            "pdf_path": str(report),
            "rubric_dimensions": [_dimension("theoretical_depth", "pdf_report")],
        }
    )
    evidence = result["evidences"]["DocAnalyst"][0]

    assert not evidence.found
    assert "4 of 5" in evidence.rationale
    assert "Metacognition" in evidence.rationale


def test_doc_analyst_accepts_detailed_coverage_of_every_concept(tmp_path):
    report = tmp_path / "report.md"
    report.write_text(
        "# Architecture\n"
        "Dialectical Synthesis uses independent judges. Fan-In and Fan-Out "
        "are implemented by graph edges. Metacognition guides human review. "
        "State Synchronization uses reducers.",
        encoding="utf-8",
    )
    result = doc_analyst_node(
        {
            "pdf_path": str(report),
            "rubric_dimensions": [_dimension("theoretical_depth", "pdf_report")],
        }
    )
    evidence = result["evidences"]["DocAnalyst"][0]

    assert evidence.found
    assert "5 of 5" in evidence.rationale


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


def test_repo_investigator_uses_mermaid_fallback_when_vision_is_unset(
    monkeypatch, tmp_path
):
    from contextlib import nullcontext

    diagram = tmp_path / "reports" / "auditor-topology.mmd"
    diagram.parent.mkdir()
    diagram.write_text(
        "graph TD\n"
        "__start__ --> ContextBuilder\n"
        "ContextBuilder --> RepoInvestigator\n"
        "ContextBuilder --> DocAnalyst\n"
        "ContextBuilder --> VisionInspector\n"
        "RepoInvestigator --> EvidenceAggregator\n"
        "DocAnalyst --> EvidenceAggregator\n"
        "VisionInspector --> EvidenceAggregator\n"
        "EvidenceAggregator --> JudicialDispatch\n"
        "JudicialDispatch --> Prosecutor\n"
        "JudicialDispatch --> Defense\n"
        "JudicialDispatch --> TechLead\n"
        "Prosecutor --> ChiefJustice\n"
        "Defense --> ChiefJustice\n"
        "TechLead --> ChiefJustice\n"
        "ChiefJustice --> __end__\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("VISION_MODEL", raising=False)
    monkeypatch.setattr(detectives, "sandboxed_clone", lambda url: nullcontext(tmp_path))
    monkeypatch.setattr(detectives, "list_files", lambda repo: ["reports/auditor-topology.mmd"])
    monkeypatch.setattr(detectives, "SCANNERS", {})

    result = repo_investigator_node(
        {
            "repo_url": "https://github.com/example/repo",
            "rubric_dimensions": [
                _dimension("repository_probe"),
                _dimension("swarm_visual", "pdf_images"),
            ],
        }
    )

    evidence = next(
        item
        for item in result["evidences"]["RepoInvestigator"]
        if item.goal == "swarm_visual_source"
    )
    assert evidence.found
    assert evidence.location == "reports/auditor-topology.mmd"
    assert "PDF inclusion" in evidence.rationale

    monkeypatch.setenv("VISION_MODEL", "configured-vision-model")
    configured_result = repo_investigator_node(
        {
            "repo_url": "https://github.com/example/repo",
            "rubric_dimensions": [
                _dimension("repository_probe"),
                _dimension("swarm_visual", "pdf_images"),
            ],
        }
    )
    assert not any(
        item.goal == "swarm_visual_source"
        for item in configured_result["evidences"]["RepoInvestigator"]
    )
    monkeypatch.delenv("VISION_MODEL", raising=False)
    visual_result = detectives.vision_inspector_node(
        {
            "pdf_path": "report.pdf",
            "rubric_dimensions": [
                _dimension("swarm_visual", "pdf_images"),
            ],
        }
    )
    visual_evidence = visual_result["evidences"]["VisionInspector"][0]
    assert not visual_evidence.found
    assert visual_evidence.verification_status == "unverified"
    assert "unverified" in visual_evidence.rationale


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


def test_evidence_aggregator_selects_mermaid_fallback_when_vision_is_skipped():
    graph_evidence = Evidence(
        goal="graph_orchestration",
        found=True,
        content=json.dumps(
            {
                "detective_fan_out": True,
                "judge_fan_out": True,
                "evidence_aggregator_before_judges": True,
            }
        ),
        location="src/graph.py",
        rationale="Parallel graph",
        confidence=1.0,
    )
    source_evidence = Evidence(
        goal="swarm_visual_source",
        found=True,
        content=json.dumps(
            {
                "analysis_method": "mermaid_source_fallback",
                "pdf_inclusion_verified": False,
                "diagrams": [
                    {
                        "classification": "langgraph_state_machine",
                        "shows_parallel_detectives": True,
                        "shows_parallel_judges": True,
                        "shows_fan_in_before_judges": True,
                    }
                ],
            }
        ),
        location="reports/auditor-topology.mmd",
        rationale="Valid source topology; PDF inclusion unverified.",
        confidence=0.8,
    )
    result = evidence_aggregator_node(
        {
            "repo_manifest": ["src/graph.py", "reports/auditor-topology.mmd"],
            "claimed_paths": [],
            "pdf_path": "report.pdf",
            "evidences": {
                "RepoInvestigator": [graph_evidence, source_evidence],
                "VisionInspector": [
                    Evidence(
                        goal="swarm_visual",
                        found=False,
                        verification_status="unverified",
                        content=json.dumps(
                            {
                                "verification_status": "unverified",
                                "verification_scope": "pdf_images",
                            }
                        ),
                        location="report.pdf",
                        rationale="Vision unavailable",
                        confidence=0.0,
                    )
                ],
            },
        }
    )

    facts = json.loads(result["evidences"]["Aggregator"][0].content)
    assert not facts["diagram_matches_code"]
    assert facts["source_diagram_matches_code"]
    assert facts["diagram_analysis_method"] == "mermaid_source_fallback"
    assert not facts["diagram_pdf_inclusion_verified"]
