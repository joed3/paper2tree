from typing import Literal

from pydantic import BaseModel, field_validator


class ClaimEvaluation(BaseModel):
    node_id: str
    validity_score: float
    confidence_level: Literal["high", "medium", "low"]
    is_well_supported: bool
    strengths: list[str]
    weaknesses: list[str]
    alternative_interpretations: list[str]
    required_assumptions: list[str]
    supporting_evidence_quality: Literal["strong", "moderate", "weak", "absent"]
    notes: str

    @field_validator("validity_score")
    @classmethod
    def clamp_score(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class SubtreeEvaluation(BaseModel):
    """Returned by the claim evaluator for a batch of claims."""
    evaluations: list[ClaimEvaluation]
