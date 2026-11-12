import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.state import (
    AgentState,
    AuditReport,
    CriterionResult,
    Evidence,
    JudicialOpinion,
)


WEIGHTS = {
    "default": {"Prosecutor": 0.3, "Defense": 0.3, "TechLead": 0.4},
    "graph_orchestration": {"Prosecutor": 0.2, "Defense": 0.2, "TechLead": 0.6},
}
CONFIG = {"variance_threshold": 2, "security_cap": 3}

STATUTES = [
    (
        "graph_orchestration",
        lambda facts: not facts.get("graph_orchestration", {}).get("parallel_fan_out"),
        1,
        "Orchestration Fraud",
    ),
    (
        "judicial_nuance",
        lambda facts: not facts.get("structured_output_enforcement", {}).get(
            "binds_judicial_opinion"
        ),
        2,
        "Hallucination Liability",
    ),
    (
        "state_management_rigor",
        lambda facts: facts.get("state_management_rigor", {}).get(
            "uses_plain_dict_state", True
        ),
        3,
        "Technical Debt",
    ),
    (
        "safe_tool_engineering",
        lambda facts: bool(
            facts.get("safe_tool_engineering", {}).get("os_system_calls")
        )
        or not facts.get("safe_tool_engineering", {}).get("uses_tempdir", False)
        or not facts.get("safe_tool_engineering", {}).get("validates_url", False),
        3,
        "Security Negligence",
    ),
]


def _grounded(opinion: JudicialOpinion, evidence: List[Evidence]) -> bool:
    available = {f"{item.goal}:{item.location}" for item in evidence}
    for citation in opinion.cited_evidence:
        if citation in available:
            return True
        if any(
            citation.startswith(f"{item.goal}:")
            and citation[len(item.goal) + 1 :] == item.location
            for item in evidence
        ):
            return True
    return False


def resolve(
    dimension: Dict[str, str],
    opinions: List[JudicialOpinion],
    evidence: List[Evidence],
    facts: Dict[str, Dict[str, Any]],
) -> Tuple[CriterionResult, List[str]]:
    criterion_id = dimension["id"]
    criterion_opinions = [
        opinion for opinion in opinions if opinion.criterion_id == criterion_id
    ]
    latest_rounds: Dict[str, int] = {}
    for opinion in criterion_opinions:
        latest_rounds[opinion.judge] = max(
            latest_rounds.get(opinion.judge, 0), opinion.round
        )
    opinions_for_criterion = [
        opinion
        for opinion in criterion_opinions
        if opinion.round == latest_rounds[opinion.judge]
    ]
    grounded_opinions = [
        opinion
        for opinion in opinions_for_criterion
        if _grounded(opinion, evidence)
    ]
    notes = [
        f"[fact_supremacy] Discarded ungrounded opinion from {opinion.judge}"
        for opinion in opinions_for_criterion
        if opinion not in grounded_opinions
    ]
    criterion_evidence = [item for item in evidence if item.goal == criterion_id]
    if not any(item.found for item in criterion_evidence):
        if any(opinion.judge == "Defense" for opinion in grounded_opinions):
            notes.append(
                "[fact_supremacy] Defense overruled because no supporting artifact was found"
            )
        grounded_opinions = [
            opinion for opinion in grounded_opinions if opinion.judge != "Defense"
        ]

    spread = (
        max(opinion.score for opinion in opinions_for_criterion)
        - min(opinion.score for opinion in opinions_for_criterion)
        if opinions_for_criterion
        else 0
    )
    if spread > CONFIG["variance_threshold"]:
        notes.append(
            "[variance_re_evaluation] Re-evaluate the citations and use grounded "
            "Tech Lead opinion as tie-breaker"
        )
    tech_lead = [
        opinion
        for opinion in grounded_opinions
        if opinion.judge == "TechLead"
    ]
    if not grounded_opinions:
        score = 1
        notes.append(
            "[fact_supremacy] No grounded opinions; defaulted to 1"
        )
    elif spread > CONFIG["variance_threshold"] and tech_lead:
        score = tech_lead[0].score
    else:
        weights = WEIGHTS.get(criterion_id, WEIGHTS["default"])
        applicable_weight = sum(
            weights[opinion.judge]
            for opinion in grounded_opinions
            if opinion.judge in weights
        )
        if applicable_weight:
            weighted_score = sum(
                    weights[opinion.judge] * opinion.score
                    for opinion in grounded_opinions
                    if opinion.judge in weights
            )
            score = int(weighted_score / applicable_weight + 0.5)
        else:
            score = 1

    if criterion_id == "graph_orchestration":
        notes.append("[functionality_weight] Tech Lead carries the highest architecture weight")

    charges: List[str] = []
    for dimension_id, violated, cap, charge in STATUTES:
        if dimension_id == criterion_id and violated(facts):
            charges.append(charge)
            rule_key = (
                "security_override"
                if charge == "Security Negligence"
                else "functionality_weight"
                if charge == "Orchestration Fraud"
                else "fact_supremacy"
            )
            notes.append(
                f"[{rule_key}] {charge}: score capped at {cap}"
                if score > cap
                else f"[{rule_key}] {charge} rule evaluated; score remains within cap {cap}"
            )
            score = min(score, cap)

    dissent = None
    if spread > CONFIG["variance_threshold"]:
        notes.append(
            "[dissent_requirement] High-variance criterion includes both extreme arguments."
        )
        lo = min(opinions_for_criterion, key=lambda opinion: opinion.score)
        hi = max(opinions_for_criterion, key=lambda opinion: opinion.score)
        dissent = (
            lo.judge
            + " ("
            + str(lo.score)
            + ") argued: "
            + lo.argument[:240]
            + " | "
            + hi.judge
            + " ("
            + str(hi.score)
            + ") argued: "
            + hi.argument[:240]
            + " | Resolution: "
            + " ".join(notes)
        )

    remediation = [
        f"{item.location}: {item.rationale}"
        for item in criterion_evidence
        if not item.found
    ]
    remediation.extend(
        opinion.argument
        for opinion in tech_lead
        if ":" in opinion.argument
    )
    result = CriterionResult(
        dimension_id=criterion_id,
        dimension_name=dimension["name"],
        final_score=score,
        judge_opinions=opinions_for_criterion,
        dissent_summary=dissent,
        remediation=" ".join(remediation) or "No action required.",
        rule_notes=notes,
    )
    return result, charges


def render_markdown(report: AuditReport) -> str:
    lines = [
        "# Audit Report",
        "",
        f"**Repository:** {report.repo_url}",
        f"**Overall score:** {report.overall_score:.1f} / 5",
        "",
        "## Executive Summary",
        report.executive_summary,
        "",
        "## Criterion Breakdown",
    ]
    for criterion in report.criteria:
        lines.extend(
            [
                "",
                f"### {criterion.dimension_name}: {criterion.final_score}/5",
            ]
        )
        for opinion in criterion.judge_opinions:
            citations = ", ".join(opinion.cited_evidence) or "none"
            lines.append(
                f"- **{opinion.judge}** ({opinion.score}): {opinion.argument} "
                f"Cited: {citations}"
            )
        if criterion.dissent_summary:
            lines.append(f"- **Dissent:** {criterion.dissent_summary}")
        lines.extend(f"- **Rule:** {note}" for note in criterion.rule_notes)
        lines.append(f"- **Remediation:** {criterion.remediation}")
    lines.extend(["", "## Remediation Plan", report.remediation_plan])
    return "\n".join(lines) + "\n"


def _write(state: AgentState, report: AuditReport) -> Dict[str, Any]:
    markdown = render_markdown(report)
    output_dir = state.get("output_dir")
    if not output_dir:
        raise ValueError("Audit output directory is required in AgentState")
    output_directory = Path(output_dir)
    output_directory.mkdir(parents=True, exist_ok=True)
    report_path = output_directory / "audit_report.md"
    report_path.write_text(markdown, encoding="utf-8")
    return {
        "final_report": report,
        "report_markdown": markdown,
        "report_path": str(report_path),
    }


def chief_justice_node(state: AgentState) -> Dict[str, Any]:
    evidence = [
        item
        for group in state.get("evidences", {}).values()
        for item in group
    ]
    facts: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for item in evidence:
        try:
            content = json.loads(item.content or "")
        except json.JSONDecodeError:
            continue
        if isinstance(content, dict):
            facts[item.goal].update(content)

    results: List[CriterionResult] = []
    charges: List[str] = []
    for dimension in state.get("rubric_dimensions", []):
        result, criterion_charges = resolve(
            dimension, state.get("opinions", []), evidence, facts
        )
        results.append(result)
        charges.extend(criterion_charges)

    overall_score = (
        sum(result.final_score for result in results) / len(results)
        if results
        else 0.0
    )
    if "Security Negligence" in charges:
        overall_score = min(overall_score, float(CONFIG["security_cap"]))
    if results:
        weakest = min(results, key=lambda result: result.final_score)
        weakest_text = f"Weakest: {weakest.dimension_name}."
    else:
        weakest_text = "No criteria were available."
    unique_charges = sorted(set(charges))
    summary = (
        f"Overall {overall_score:.1f}/5 across {len(results)} criteria. "
        f"{weakest_text} Charges: {', '.join(unique_charges) or 'none'}."
    )
    plan = "\n".join(
        f"- **{result.dimension_name}:** {result.remediation}"
        for result in results
        if result.final_score < 5
    )
    return _write(
        state,
        AuditReport(
            repo_url=state.get("repo_url", ""),
            executive_summary=summary,
            overall_score=overall_score,
            criteria=results,
            remediation_plan=plan or "None.",
        ),
    )


def error_report_node(state: AgentState) -> Dict[str, Any]:
    reason = "; ".join(state.get("errors", [])) or "repository evidence is unavailable"
    return _write(
        state,
        AuditReport(
            repo_url=state.get("repo_url", ""),
            executive_summary=f"Audit aborted: {reason}",
            overall_score=0.0,
            criteria=[],
            remediation_plan="Resolve the errors above and rerun the audit.",
        ),
    )
