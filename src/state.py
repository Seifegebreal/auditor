import operator
from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class Evidence(BaseModel):
    goal: str = Field(description="Rubric dimension ID this evidence answers")
    found: bool
    verification_status: Optional[Literal["verified", "unverified"]] = None
    content: Optional[str] = Field(
        default=None, description="JSON facts or a supporting source snippet"
    )
    location: str = Field(description="File path, commit hash, or report path")
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)


class JudicialOpinion(BaseModel):
    judge: Literal["Prosecutor", "Defense", "TechLead"]
    criterion_id: str
    score: int = Field(ge=1, le=5)
    argument: str
    cited_evidence: List[str] = Field(
        description="Evidence references formatted as goal:location"
    )
    round: int = Field(default=1, ge=1, le=2)


class CriterionResult(BaseModel):
    dimension_id: str
    dimension_name: str
    status: Literal["evaluated", "unverified"] = "evaluated"
    final_score: Optional[int] = Field(default=None, ge=1, le=5)
    judge_opinions: List[JudicialOpinion]
    dissent_summary: Optional[str] = Field(
        default=None, description="Required when grounded scores differ by more than 2"
    )
    remediation: str
    rule_notes: List[str] = Field(default_factory=list)


class AuditReport(BaseModel):
    repo_url: str
    executive_summary: str
    overall_score: Optional[float] = None
    criteria: List[CriterionResult]
    remediation_plan: str


class AgentState(TypedDict, total=False):
    repo_url: str
    pdf_path: str
    output_dir: str
    rubric_path: str
    rubric_dimensions: List[Dict[str, str]]
    synthesis_rules: Dict[str, str]
    repo_manifest: Annotated[List[str], operator.add]
    claimed_paths: Annotated[List[str], operator.add]
    errors: Annotated[List[str], operator.add]
    evidences: Annotated[Dict[str, List[Evidence]], operator.ior]
    opinions: Annotated[List[JudicialOpinion], operator.add]
    final_report: AuditReport
    report_markdown: str
    report_path: str
