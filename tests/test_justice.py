import json

from src.nodes.justice import chief_justice_node, resolve
from src.state import Evidence, JudicialOpinion


def _opinion(judge, score, citation="state_management_rigor:src/state.py"):
    return JudicialOpinion(
        judge=judge,
        criterion_id="state_management_rigor",
        score=score,
        argument=f"{judge} assessment",
        cited_evidence=[citation],
    )


def _dimension(identifier="state_management_rigor"):
    return {"id": identifier, "name": identifier.replace("_", " ").title()}


def test_missing_artifact_overrules_defense_opinion():
    evidence = [
        Evidence(
            goal="state_management_rigor",
            found=False,
            content=None,
            location="src/state.py",
            rationale="State file missing",
            confidence=0.0,
        )
    ]
    opinions = [
        _opinion("Prosecutor", 1),
        _opinion("Defense", 5),
        _opinion("TechLead", 3),
    ]
    result, _ = resolve(_dimension(), opinions, evidence, {})
    assert result.final_score == 3
    assert "[fact_supremacy] Defense overruled" in result.dissent_summary


def test_unverified_criterion_is_not_scored_or_included_in_overall(tmp_path):
    dimension = {"id": "swarm_visual", "name": "Architectural Diagram Analysis"}
    evidence = Evidence(
        goal="swarm_visual",
        found=False,
        verification_status="unverified",
        content='{"verification_status":"unverified","verification_scope":"pdf_images"}',
        location="report.pdf",
        rationale="Vision is not configured; PDF diagram was not inspected.",
        confidence=0.0,
    )
    opinions = [
        JudicialOpinion(
            judge=judge,
            criterion_id="swarm_visual",
            score=1,
            argument="No diagram.",
            cited_evidence=["swarm_visual:report.pdf"],
        )
        for judge in ("Prosecutor", "Defense", "TechLead")
    ]

    result, charges = resolve(dimension, opinions, [evidence], {})
    assert result.status == "unverified"
    assert result.final_score is None
    assert result.judge_opinions == []
    assert not charges

    report_result = chief_justice_node(
        {
            "repo_url": "https://github.com/owner/repo",
            "output_dir": str(tmp_path),
            "rubric_dimensions": [dimension],
            "opinions": opinions,
            "evidences": {"VisionInspector": [evidence]},
        }
    )
    report = report_result["final_report"]
    assert report.overall_score is None
    assert report.criteria[0].final_score is None
    assert report.criteria[0].status == "unverified"
    assert "1 unverified" in report.executive_summary
    assert "Overall score not computed" in report.executive_summary
    assert "Overall score:** Not computed" in report_result["report_markdown"]
    assert (
        "### Architectural Diagram Analysis: Unverified"
        in report_result["report_markdown"]
    )


def test_variance_over_two_uses_grounded_tech_lead_and_records_dissent():
    evidence = [
        Evidence(
            goal="state_management_rigor",
            found=True,
            content="{}",
            location="src/state.py",
            rationale="Typed reducers found",
            confidence=1.0,
        )
    ]
    opinions = [
        _opinion("Prosecutor", 1),
        _opinion("Defense", 5, "made-up:path"),
        _opinion("TechLead", 3),
    ]
    result, _ = resolve(_dimension(), opinions, evidence, {})
    assert result.final_score == 3
    assert "Tech Lead opinion as tie-breaker" in result.dissent_summary
    assert "Discarded ungrounded opinion from Defense" in result.dissent_summary
    assert result.dissent_summary.startswith(
        "Prosecutor (1) argued: Prosecutor assessment | Defense (5) argued: "
        "Defense assessment | Resolution: "
    )
    assert "[variance_re_evaluation]" in result.dissent_summary
    assert "[dissent_requirement]" in result.dissent_summary


def test_remediation_ignores_colon_prose_and_keeps_perfect_score_clean():
    evidence = [
        Evidence(
            goal="report_accuracy",
            found=True,
            content="{}",
            location="reports/final_report.pdf",
            rationale="All cited paths are present.",
            confidence=1.0,
        )
    ]
    opinions = [
        JudicialOpinion(
            judge="TechLead",
            criterion_id="report_accuracy",
            score=5,
            argument=(
                "Opposing view: diagram mismatch suggests inaccuracies; "
                "however, source diagram matches code, confirming path accuracy."
            ),
            cited_evidence=["report_accuracy:reports/final_report.pdf"],
        )
    ]

    result, _ = resolve(
        {"id": "report_accuracy", "name": "Report Accuracy"},
        opinions,
        evidence,
        {},
    )

    assert result.final_score == 5
    assert result.remediation == "No action required."


def test_remediation_accepts_only_explicit_path_change_line():
    evidence = [
        Evidence(
            goal="report_accuracy",
            found=True,
            content="{}",
            location="reports/final_report.pdf",
            rationale="A cited architecture concept is not explained.",
            confidence=1.0,
        )
    ]
    opinion = JudicialOpinion(
        judge="TechLead",
        criterion_id="report_accuracy",
        score=3,
        argument=(
            "The explanation is incomplete.\n"
            "reports/final_report.pdf: explain fan-in and fan-out using the actual graph."
        ),
        cited_evidence=["report_accuracy:reports/final_report.pdf"],
    )

    result, _ = resolve(
        {"id": "report_accuracy", "name": "Report Accuracy"},
        [opinion],
        evidence,
        {},
    )

    assert result.remediation == (
        "reports/final_report.pdf: explain fan-in and fan-out using the actual graph."
    )


def test_low_score_without_valid_recommendation_does_not_claim_no_action():
    evidence = [
        Evidence(
            goal="report_accuracy",
            found=True,
            content="{}",
            location="reports/final_report.pdf",
            rationale="The concept coverage is incomplete.",
            confidence=1.0,
        )
    ]
    opinion = JudicialOpinion(
        judge="TechLead",
        criterion_id="report_accuracy",
        score=3,
        argument="Opposing view: the report lacks detail.",
        cited_evidence=["report_accuracy:reports/final_report.pdf"],
    )

    result, _ = resolve(
        {"id": "report_accuracy", "name": "Report Accuracy"},
        [opinion],
        evidence,
        {},
    )

    assert "no validated path: change recommendation" in result.remediation
    assert "No action required" not in result.remediation


def test_chief_justice_uses_only_highest_opinion_round():
    evidence = [
        Evidence(
            goal="state_management_rigor",
            found=True,
            content="{}",
            location="src/state.py",
            rationale="Typed state",
            confidence=1.0,
        )
    ]
    opinions = [
        _opinion("Prosecutor", 1),
        _opinion("Prosecutor", 4).model_copy(update={"round": 2}),
        _opinion("Defense", 5),
        _opinion("TechLead", 3),
    ]
    result, _ = resolve(_dimension(), opinions, evidence, {})
    assert [opinion.score for opinion in result.judge_opinions] == [4, 5, 3]
    assert result.dissent_summary is None


def test_chief_justice_handles_missing_opinion_and_evidence_keys(tmp_path):
    report = chief_justice_node(
        {
            "repo_url": "https://github.com/owner/repo",
            "output_dir": str(tmp_path),
            "rubric_dimensions": [],
        }
    )["final_report"]
    assert report.criteria == []
    assert report.overall_score is None


def test_security_rule_caps_criterion_and_total_score(tmp_path):
    dimensions = [
        {"id": "safe_tool_engineering", "name": "Safe Tool Engineering"}
    ]
    evidence = Evidence(
        goal="safe_tool_engineering",
        found=True,
        content=json.dumps(
            {
                "os_system_calls": ["src/tools/repo_tools.py:10"],
                "uses_tempdir": True,
                "validates_url": True,
            }
        ),
        location="src/tools/repo_tools.py",
        rationale="Unsafe shell call detected",
        confidence=1.0,
    )
    citation = "safe_tool_engineering:src/tools/repo_tools.py"
    opinions = [
        JudicialOpinion(
            judge=judge,
            criterion_id="safe_tool_engineering",
            score=5,
            argument="High score.",
            cited_evidence=[citation],
        )
        for judge in ("Prosecutor", "Defense", "TechLead")
    ]
    state = {
        "repo_url": "https://github.com/owner/repo",
        "output_dir": str(tmp_path),
        "rubric_dimensions": dimensions,
        "opinions": opinions,
        "evidences": {"RepoInvestigator": [evidence]},
    }
    result = chief_justice_node(state)["final_report"]
    assert result.criteria[0].final_score == 3
    assert result.overall_score == 3.0
    assert "Security Negligence" in result.executive_summary
    assert any(
        "[security_override]" in note for note in result.criteria[0].rule_notes
    )
