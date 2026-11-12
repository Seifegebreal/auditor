import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Tuple

from pydantic import BaseModel

from src.rubric import load_rubric
from src.state import AgentState, Evidence
from src.tools.doc_tools import (
    PATH_RE,
    Chunk,
    extract_images_from_pdf,
    ingest_pdf,
    term_context,
)
from src.tools.repo_tools import (
    analyze_graph_structure,
    analyze_judge_prompts,
    analyze_justice,
    analyze_state_file,
    git_forensics,
    list_files,
    sandboxed_clone,
    scan_judges,
    scan_tools_security,
)


TERMS = [
    "Dialectical Synthesis",
    "Fan-In",
    "Fan-Out",
    "Metacognition",
    "State Synchronization",
]

SCANNERS = {
    "git_forensic_analysis": git_forensics,
    "state_management_rigor": analyze_state_file,
    "graph_orchestration": analyze_graph_structure,
    "safe_tool_engineering": scan_tools_security,
    "structured_output_enforcement": scan_judges,
    "judicial_nuance": analyze_judge_prompts,
    "chief_justice_synthesis": analyze_justice,
}


def _ev(
    goal: str, result: Dict[str, Any], instruction: str = ""
) -> Evidence:
    return Evidence(
        goal=goal,
        found=bool(result["found"]),
        content=json.dumps(result.get("facts", {}), ensure_ascii=False),
        location=str(result["location"]),
        rationale=(
            f"{instruction} Evidence: {result['rationale']}"
            if instruction
            else str(result["rationale"])
        ),
        confidence=float(result["confidence"]),
    )


def _missing(goal: str, location: str, reason: str) -> Evidence:
    return Evidence(
        goal=goal,
        found=False,
        content=None,
        location=location,
        rationale=reason,
        confidence=0.0,
    )


def _dimensions_for(state: AgentState, target: str) -> List[Dict[str, str]]:
    dimensions = state.get("rubric_dimensions")
    if not dimensions:
        rubric_path = state.get("rubric_path") or os.getenv("AUDITOR_RUBRIC")
        dimensions = (
            load_rubric(rubric_path)["dimensions"]
            if rubric_path
            else load_rubric()["dimensions"]
        )
    return [dimension for dimension in dimensions if dimension["target_artifact"] == target]


def _safe(
    goal: str,
    fn: Any,
    repo: Any,
    forensic_instruction: str = "",
) -> Evidence:
    try:
        return _ev(goal, fn(repo), forensic_instruction)
    except Exception as exc:
        rationale = f"{goal} scanner failed: {exc}"
        if forensic_instruction:
            rationale = f"{forensic_instruction} Evidence: {rationale}"
        return _missing(
            goal,
            goal,
            rationale,
        )


def context_builder_node(state: AgentState) -> Dict[str, Any]:
    rubric_path = state.get("rubric_path") or os.getenv("AUDITOR_RUBRIC")
    config = load_rubric(rubric_path)
    return {
        "rubric_dimensions": config["dimensions"],
        "synthesis_rules": config["synthesis_rules"],
    }


def repo_investigator_node(state: AgentState) -> Dict[str, Any]:
    dimensions = _dimensions_for(state, "github_repo")
    try:
        with sandboxed_clone(state["repo_url"]) as repository:
            evidences = []
            for dimension in dimensions:
                goal = dimension["id"]
                scanner = SCANNERS.get(goal)
                if scanner is None:
                    evidences.append(
                        _missing(
                            goal,
                            goal,
                            f"{dimension['forensic_instruction']} "
                            f"No repository scanner is registered for {goal}",
                        )
                    )
                else:
                    evidences.append(
                        _safe(
                            goal,
                            scanner,
                            repository,
                            dimension["forensic_instruction"],
                        )
                    )
            manifest = list_files(repository)
    except Exception as exc:
        message = f"RepoInvestigator: {exc}"
        return {
            "evidences": {
                "RepoInvestigator": [
                    _missing(dimension["id"], "repository", str(exc))
                    for dimension in dimensions
                ]
            },
            "errors": [message],
        }
    return {
        "evidences": {"RepoInvestigator": evidences},
        "repo_manifest": manifest,
    }


def _document_content(path: str) -> Tuple[str, List[Chunk]]:
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".pdf":
        chunks = ingest_pdf(path)
        text = "\n".join(f"{chunk.section}\n{chunk.text}" for chunk in chunks)
        return text, chunks
    if suffix in {".md", ".txt"}:
        with open(path, "r", encoding="utf-8") as document:
            text = document.read()
        chunks: List[Chunk] = []
        section = "Preamble"
        buffer = ""
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                if buffer.strip():
                    chunks.append(
                        Chunk(index=len(chunks), section=section, text=buffer.strip())
                    )
                buffer = ""
                section = line.lstrip("# ").strip() or "Untitled section"
            else:
                buffer += line + " "
                if len(buffer) >= 1200:
                    chunks.append(
                        Chunk(index=len(chunks), section=section, text=buffer.strip())
                    )
                    buffer = ""
        if buffer.strip():
            chunks.append(Chunk(index=len(chunks), section=section, text=buffer.strip()))
        return text, chunks
    raise ValueError("Report must be a PDF, Markdown, or plain-text file")


def doc_analyst_node(state: AgentState) -> Dict[str, Any]:
    report_path = state.get("pdf_path", "")
    goals = [dimension["id"] for dimension in _dimensions_for(state, "pdf_report")]
    if not report_path:
        return {
            "evidences": {
                "DocAnalyst": [
                    _missing(goal, "report", "No PDF report path was supplied")
                    for goal in goals
                ]
            },
            "errors": ["DocAnalyst: no report path supplied"],
        }
    try:
        report_text, chunks = _document_content(report_path)
        depth = {term: term_context(chunks, term) for term in TERMS}
        detailed = any(
            details["hits"] and not details["only_in_summary"]
            for details in depth.values()
        )
        theoretical = Evidence(
            goal="theoretical_depth",
            found=detailed,
            content=json.dumps(depth, ensure_ascii=False),
            location=report_path,
            rationale=(
                f"{sum(bool(details['hits'] and not details['only_in_summary']) for details in depth.values())} required concepts have substantive report coverage"
                if detailed
                else "Required concepts are missing or occur only in introductory material"
            ),
            confidence=0.9,
        )
        claimed_paths = sorted(set(PATH_RE.findall(report_text)))
        output: Dict[str, Any] = {
            "evidences": {"DocAnalyst": [theoretical]},
            "claimed_paths": claimed_paths,
        }
        return output
    except Exception as exc:
        return {
            "evidences": {
                "DocAnalyst": [
                    _missing(goal, report_path, str(exc)) for goal in goals
                ]
            },
            "errors": [f"DocAnalyst: {exc}"],
        }


class DiagramFacts(BaseModel):
    classification: Literal[
        "langgraph_state_machine",
        "sequence_diagram",
        "generic_flowchart",
        "not_a_diagram",
    ]
    shows_parallel_detectives: bool
    shows_parallel_judges: bool
    shows_fan_in_before_judges: bool
    description: str


def vision_inspector_node(state: AgentState) -> Dict[str, Any]:
    goals = [dimension["id"] for dimension in _dimensions_for(state, "pdf_images")]
    report_path = state.get("pdf_path", "")
    if not report_path:
        return {
            "evidences": {
                "VisionInspector": [
                    _missing(goal, "report", "No PDF report path was supplied")
                    for goal in goals
                ]
            }
        }
    model_name = os.getenv("VISION_MODEL")
    if not model_name:
        return {
            "evidences": {
                "VisionInspector": [
                    _missing(goal, report_path, "Vision inspection not run: VISION_MODEL is unset")
                    for goal in goals
                ]
            }
        }
    try:
        from langchain.chat_models import init_chat_model

        model = init_chat_model(model_name).with_structured_output(DiagramFacts)
        with tempfile.TemporaryDirectory(prefix="auditor_images_") as temporary_directory:
            image_paths = extract_images_from_pdf(report_path, temporary_directory)
            diagrams = []
            for image_path in image_paths:
                from langchain_core.messages import HumanMessage

                encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
                messages = [
                    HumanMessage(
                        content=[
                            {
                                "type": "text",
                                "text": (
                                    "Classify this report image. Is it a StateGraph or generic diagram? "
                                    "Does it show parallel detectives, parallel judges, and a fan-in "
                                    "before judges? Be factual and describe visible evidence."
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{encoded}"},
                            },
                        ]
                    )
                ]
                diagram = model.invoke(messages)
                diagrams.append(diagram.model_dump())
        accurate_diagram = any(
            diagram["classification"] == "langgraph_state_machine"
            and diagram["shows_parallel_detectives"]
            and diagram["shows_parallel_judges"]
            and diagram["shows_fan_in_before_judges"]
            for diagram in diagrams
        )
        result = Evidence(
            goal="swarm_visual",
            found=accurate_diagram,
            content=json.dumps({"diagrams": diagrams}, ensure_ascii=False),
            location=report_path,
            rationale=(
                "Vision model verified a StateGraph diagram with both parallel layers"
                if accurate_diagram
                else f"Vision model analyzed {len(diagrams)} image(s); none showed the full required flow"
            ),
            confidence=0.85 if diagrams else 0.0,
        )
        return {"evidences": {"VisionInspector": [result]}}
    except Exception as exc:
        return {
            "evidences": {
                "VisionInspector": [
                    _missing(goal, report_path, f"Vision inspection failed: {exc}")
                    for goal in goals
                ]
            },
            "errors": [f"VisionInspector: {exc}"],
        }


def evidence_aggregator_node(state: AgentState) -> Dict[str, Any]:
    manifest = set(state.get("repo_manifest", []))
    claimed_paths = state.get("claimed_paths", [])
    verified = sorted(
        {
            claimed
            for claimed in claimed_paths
            if claimed in manifest or any(path.endswith("/" + claimed) for path in manifest)
        }
    )
    hallucinated = sorted(set(claimed_paths) - set(verified))
    all_evidence = [
        item
        for group in state.get("evidences", {}).values()
        for item in group
    ]
    graph_evidence = next(
        (item for item in all_evidence if item.goal == "graph_orchestration"),
        None,
    )
    visual_evidence = next(
        (item for item in all_evidence if item.goal == "swarm_visual"),
        None,
    )
    graph_facts: Dict[str, Any] = {}
    visual_facts: Dict[str, Any] = {}
    if graph_evidence and graph_evidence.content:
        try:
            graph_facts = json.loads(graph_evidence.content)
        except json.JSONDecodeError:
            graph_facts = {}
    if visual_evidence and visual_evidence.content:
        try:
            visual_facts = json.loads(visual_evidence.content)
        except json.JSONDecodeError:
            visual_facts = {}
    diagrams = visual_facts.get("diagrams", [])
    diagram_matches_code = bool(diagrams) and any(
        diagram.get("shows_parallel_detectives")
        == bool(graph_facts.get("detective_fan_out"))
        and diagram.get("shows_parallel_judges")
        == bool(graph_facts.get("judge_fan_out"))
        for diagram in diagrams
    )
    report_path = state.get("pdf_path", "n/a")
    evidence = Evidence(
        goal="report_accuracy",
        found=bool(manifest) and not hallucinated,
        content=json.dumps(
            {
                "verified_paths": verified,
                "hallucinated_paths": hallucinated,
                "claimed_path_count": len(set(claimed_paths)),
                "diagram_matches_code": diagram_matches_code,
            },
            ensure_ascii=False,
        ),
        location=report_path,
        rationale=(
            f"{len(verified)} verified, {len(hallucinated)} hallucinated report paths; "
            f"diagram_matches_code={diagram_matches_code}"
        ),
        confidence=0.9 if manifest else 0.0,
    )
    return {"evidences": {"Aggregator": [evidence]}}


def route_after_aggregation(state: AgentState) -> str:
    return "evidence_ok" if state.get("repo_manifest") else "evidence_missing"
