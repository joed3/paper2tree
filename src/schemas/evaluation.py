from typing import Literal

from pydantic import BaseModel


class ClaimEvaluation(BaseModel):
    node_id: str
    support_level: Literal["high", "medium", "low"]
    confidence_level: Literal["high", "medium", "low"]
    is_well_supported: bool
    strengths: list[str]
    weaknesses: list[str]
    alternative_interpretations: list[str]
    required_assumptions: list[str]
    supporting_evidence_quality: Literal["strong", "moderate", "weak", "absent"]
    notes: str


class SubtreeEvaluation(BaseModel):
    """Returned by the claim evaluator for a batch of claims."""
    evaluations: list[ClaimEvaluation]
