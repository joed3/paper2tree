"""Shared fixtures and factories for the test suite."""

import pytest

from src.schemas.claim import Claim, ClaimGraph
from src.schemas.evaluation import ClaimEvaluation
from src.schemas.paper import ExtractedPaper
from src.utils.graph import EnrichedClaim, build_dag

# ── Factory helpers ────────────────────────────────────────────────────────────


def make_claim(
    id: str,
    text: str = "A claim.",
    type: str = "primary",
    parent_id: str | None = None,
    section_source: str = "Introduction",
    verbatim_quote: str = "A verbatim quote.",
) -> Claim:
    return Claim(
        id=id,
        text=text,
        type=type,
        parent_id=parent_id,
        section_source=section_source,
        verbatim_quote=verbatim_quote,
    )


def make_evaluation(
    node_id: str,
    evidence_strength: str = "strong",
    claim_evidence_calibration: str = "calibrated",
    strengths: list[str] | None = None,
    weaknesses: list[str] | None = None,
) -> ClaimEvaluation:
    return ClaimEvaluation(
        node_id=node_id,
        evidence_strength=evidence_strength,
        claim_evidence_calibration=claim_evidence_calibration,
        strengths=strengths or ["Strong evidence"],
        weaknesses=weaknesses or [],
        alternative_interpretations=[],
        required_assumptions=[],
        notes="",
    )


def make_extracted_paper(
    title: str = "Test Paper",
    authors: list[str] | None = None,
    abstract: str = "An abstract.",
    word_count: int = 100,
) -> ExtractedPaper:
    return ExtractedPaper(
        title=title,
        authors=authors or ["Author A"],
        abstract=abstract,
        sections=[],
        full_text="Full text here.",
        word_count=word_count,
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def linear_claim_graph() -> ClaimGraph:
    """Root → primary → supporting linear chain."""
    return ClaimGraph(
        claims=[
            make_claim("c1", type="root", parent_id=None, text="Root claim."),
            make_claim("c1.1", type="primary", parent_id="c1", text="Primary claim."),
            make_claim("c1.1.1", type="supporting", parent_id="c1.1", text="Supporting claim."),
        ]
    )


@pytest.fixture
def wide_claim_graph() -> ClaimGraph:
    """Root with two primary children, each with one evidence node."""
    return ClaimGraph(
        claims=[
            make_claim("c1", type="root", parent_id=None),
            make_claim("c1.1", type="primary", parent_id="c1"),
            make_claim("c1.2", type="primary", parent_id="c1"),
            make_claim("c1.1.1", type="evidence", parent_id="c1.1"),
            make_claim("c1.2.1", type="evidence", parent_id="c1.2"),
        ]
    )


@pytest.fixture
def linear_enriched(linear_claim_graph: ClaimGraph) -> list[EnrichedClaim]:
    return build_dag(linear_claim_graph)


@pytest.fixture
def wide_enriched(wide_claim_graph: ClaimGraph) -> list[EnrichedClaim]:
    return build_dag(wide_claim_graph)
