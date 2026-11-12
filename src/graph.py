from langgraph.graph import END, START, StateGraph
from langchain_core.runnables import RunnableLambda

from src.nodes.detectives import (
    context_builder_node,
    doc_analyst_node,
    evidence_aggregator_node,
    repo_investigator_node,
    route_after_aggregation,
    vision_inspector_node,
)
from src.nodes.judges import make_judge_node
from src.nodes.justice import chief_justice_node, error_report_node
from src.state import AgentState


def _tagged(node, tags, metadata):
    return RunnableLambda(node).with_config(tags=tags, metadata=metadata)


def judicial_dispatch_node(state: AgentState) -> dict:
    return {"errors": []}


def build_graph(llm_factory=None):
    builder = StateGraph(AgentState)
    builder.add_node(
        "ContextBuilder",
        _tagged(context_builder_node, ["auditor", "context"], {"layer": "setup"}),
        metadata={"layer": "setup"},
    )
    builder.add_node(
        "RepoInvestigator",
        _tagged(
            repo_investigator_node,
            ["auditor", "detective", "repository"],
            {"agent": "RepoInvestigator"},
        ),
        metadata={"agent": "RepoInvestigator"},
    )
    builder.add_node(
        "DocAnalyst",
        _tagged(
            doc_analyst_node,
            ["auditor", "detective", "document"],
            {"agent": "DocAnalyst"},
        ),
        metadata={"agent": "DocAnalyst"},
    )
    builder.add_node(
        "VisionInspector",
        _tagged(
            vision_inspector_node,
            ["auditor", "detective", "vision"],
            {"agent": "VisionInspector"},
        ),
        metadata={"agent": "VisionInspector"},
    )
    builder.add_node(
        "EvidenceAggregator",
        _tagged(
            evidence_aggregator_node,
            ["auditor", "evidence-aggregation"],
            {"layer": "evidence-aggregation"},
        ),
        metadata={"layer": "evidence-aggregation"},
    )
    builder.add_node(
        "JudicialDispatch",
        _tagged(
            judicial_dispatch_node,
            ["auditor", "judicial-dispatch"],
            {"layer": "judicial-dispatch"},
        ),
        metadata={"layer": "judicial-dispatch"},
    )
    builder.add_node(
        "Prosecutor",
        _tagged(
            make_judge_node("Prosecutor", llm_factory),
            ["auditor", "judge", "prosecutor"],
            {"layer": "judges", "judge": "Prosecutor"},
        ),
        metadata={"layer": "judges", "judge": "Prosecutor"},
    )
    builder.add_node(
        "Defense",
        _tagged(
            make_judge_node("Defense", llm_factory),
            ["auditor", "judge", "defense"],
            {"layer": "judges", "judge": "Defense"},
        ),
        metadata={"layer": "judges", "judge": "Defense"},
    )
    builder.add_node(
        "TechLead",
        _tagged(
            make_judge_node("TechLead", llm_factory),
            ["auditor", "judge", "tech-lead"],
            {"layer": "judges", "judge": "TechLead"},
        ),
        metadata={"layer": "judges", "judge": "TechLead"},
    )
    builder.add_node(
        "ChiefJustice",
        _tagged(
            chief_justice_node,
            ["auditor", "chief-justice", "synthesis"],
            {"agent": "ChiefJustice"},
        ),
        metadata={"agent": "ChiefJustice"},
    )
    builder.add_node(
        "ErrorReport",
        _tagged(error_report_node, ["auditor", "error"], {"layer": "error"}),
        metadata={"layer": "error"},
    )

    builder.add_edge(START, "ContextBuilder")
    builder.add_edge("ContextBuilder", "RepoInvestigator")
    builder.add_edge("ContextBuilder", "DocAnalyst")
    builder.add_edge("ContextBuilder", "VisionInspector")
    builder.add_edge("RepoInvestigator", "EvidenceAggregator")
    builder.add_edge("DocAnalyst", "EvidenceAggregator")
    builder.add_edge("VisionInspector", "EvidenceAggregator")
    builder.add_conditional_edges(
        "EvidenceAggregator",
        route_after_aggregation,
        {"evidence_ok": "JudicialDispatch", "evidence_missing": "ErrorReport"},
    )
    builder.add_edge("JudicialDispatch", "Prosecutor")
    builder.add_edge("JudicialDispatch", "Defense")
    builder.add_edge("JudicialDispatch", "TechLead")
    builder.add_edge("Prosecutor", "ChiefJustice")
    builder.add_edge("Defense", "ChiefJustice")
    builder.add_edge("TechLead", "ChiefJustice")
    builder.add_edge("ChiefJustice", END)
    builder.add_edge("ErrorReport", END)
    return builder.compile()
