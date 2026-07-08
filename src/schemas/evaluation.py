from typing import Literal

from pydantic import BaseModel


class LiteratureCitation(BaseModel):
    title: str
    authors: list[str]
    year: int | None = None
    url: str | None = None
    relevance: str  # one-sentence explanation of relevance to the claim
    stance: Literal["supports", "contradicts", "extends", "neutral"]


class ClaimEvaluation(BaseModel):
    node_id: str
    # How good is the evidence for this claim? (absorbs the former support_level,
    # is_well_supported, and supporting_evidence_quality into one axis).
    evidence_strength: Literal["strong", "moderate", "weak", "absent"]
    # Does the strength of the claim match the strength of its evidence?
    claim_evidence_calibration: Literal["overclaimed", "calibrated", "underclaimed"]
    strengths: list[str]
    weaknesses: list[str]
    alternative_interpretations: list[str]
    required_assumptions: list[str]
    notes: str
    literature_citations: list[LiteratureCitation] = []
    novelty_score: Literal["high", "medium", "low"] | None = None
    groundedness_score: Literal["high", "medium", "low"] | None = None


class SubtreeEvaluation(BaseModel):
    """Returned by the claim evaluator for a batch of claims."""

    evaluations: list[ClaimEvaluation]
