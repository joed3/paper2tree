"""Evaluation metrics for the paper2tree pilot study.

Computes BERTScore F1, ROUGE-L, embedding cosine similarity,
and eLife Assessment alignment for a pair of (generated, reference) reviews.
"""

from __future__ import annotations

import re
from functools import lru_cache

import numpy as np

# Heavy dependencies are imported lazily so the module can be imported
# even when the eval extras are not installed.


@lru_cache(maxsize=1)
def _bert_scorer():
    from bert_score import BERTScorer  # type: ignore[import]

    return BERTScorer(model_type="roberta-large", lang="en", rescale_with_baseline=False)


@lru_cache(maxsize=1)
def _rouge_scorer():
    from rouge_score import rouge_scorer as rs  # type: ignore[import]

    return rs.RougeScorer(["rougeL"], use_stemmer=True)


@lru_cache(maxsize=1)
def _sentence_model():
    from sentence_transformers import SentenceTransformer  # type: ignore[import]

    return SentenceTransformer("all-MiniLM-L6-v2")


# ── Individual metrics ─────────────────────────────────────────────────────────


def bertscore_f1(candidate: str, reference: str) -> float:
    """BERTScore F1 between candidate and reference using DeBERTa-xlarge-mnli."""
    scorer = _bert_scorer()
    _, _, F = scorer.score([candidate], [reference])
    return float(F[0])


def rouge_l(candidate: str, reference: str) -> float:
    """ROUGE-L F-measure between candidate and reference."""
    scorer = _rouge_scorer()
    scores = scorer.score(reference, candidate)
    return float(scores["rougeL"].fmeasure)


def cosine_similarity(text_a: str, text_b: str) -> float:
    """Cosine similarity between sentence embeddings of two texts."""
    model = _sentence_model()
    # Truncate to ~500 tokens worth of text for speed
    a = text_a[:4000]
    b = text_b[:4000]
    embs = model.encode([a, b], normalize_embeddings=True)
    return float(np.dot(embs[0], embs[1]))


# ── Recommendation extraction ──────────────────────────────────────────────────

_RECOMMENDATION_PATTERNS = [
    (re.compile(r"\baccept\b", re.IGNORECASE), "Accept"),
    (re.compile(r"\bminor revisions?\b", re.IGNORECASE), "Minor Revisions"),
    (re.compile(r"\bmajor revisions?\b", re.IGNORECASE), "Major Revisions"),
    (re.compile(r"\breject\b", re.IGNORECASE), "Reject"),
]

_ORDINAL: dict[str, float] = {
    "Accept": 3.0,
    "Minor Revisions": 2.0,
    "Major Revisions": 1.0,
    "Reject": 0.0,
}

_ELIFE_SIG_ORDINAL: dict[str, float] = {
    "landmark": 3.0,
    "fundamental": 3.0,
    "important": 2.5,
    "valuable": 2.0,
    "useful": 1.5,
    "incomplete": 1.0,
    "inadequate": 0.0,
}

_ELIFE_EV_ORDINAL: dict[str, float] = {
    "exceptional": 3.0,
    "compelling": 2.5,
    "convincing": 2.0,
    "solid": 1.5,
    "incomplete": 1.0,
    "inadequate": 0.0,
}


def extract_recommendation(review_text: str) -> str | None:
    """Extract recommendation from a generated review.

    Looks for the **Recommendation** section and then matches keywords.
    Returns one of: "Accept", "Minor Revisions", "Major Revisions", "Reject", or None.
    """
    # Try to isolate the Recommendation section first
    section_match = re.search(
        r"\*\*Recommendation\*\*\s*\n(.*?)(?=\n\*\*|\Z)",
        review_text,
        re.DOTALL | re.IGNORECASE,
    )
    search_text = section_match.group(1) if section_match else review_text

    # Check from most specific to least specific
    if re.search(r"\bminor revisions?\b", search_text, re.IGNORECASE):
        return "Minor Revisions"
    if re.search(r"\bmajor revisions?\b", search_text, re.IGNORECASE):
        return "Major Revisions"
    if re.search(r"\baccept\b", search_text, re.IGNORECASE):
        return "Accept"
    if re.search(r"\breject\b", search_text, re.IGNORECASE):
        return "Reject"
    return None


def elife_assessment_ordinal(assessment_text: str) -> float | None:
    """Map an eLife Assessment text to a 0–3 ordinal scale.

    Uses the significance and evidence vocabulary defined by eLife.
    Returns the average of the matched significance and evidence ordinals,
    or None if no keywords are found.
    """
    lower = assessment_text.lower()
    sig_scores = [v for k, v in _ELIFE_SIG_ORDINAL.items() if k in lower]
    ev_scores = [v for k, v in _ELIFE_EV_ORDINAL.items() if k in lower]

    all_scores = sig_scores + ev_scores
    if not all_scores:
        return None
    return float(np.mean(all_scores))


def recommendation_ordinal(recommendation: str | None) -> float | None:
    if recommendation is None:
        return None
    return _ORDINAL.get(recommendation)


def assessment_alignment(
    generated_recommendation: str | None,
    elife_assessment_text: str | None,
) -> float | None:
    """Ordinal distance between generated recommendation and eLife Assessment.

    Returns a value in [0, 1] where 1 = perfect alignment, 0 = maximum distance.
    Returns None if either input cannot be parsed.
    """
    gen_ord = recommendation_ordinal(generated_recommendation)
    if gen_ord is None:
        return None
    if not elife_assessment_text:
        return None
    human_ord = elife_assessment_ordinal(elife_assessment_text)
    if human_ord is None:
        return None

    max_distance = 3.0
    distance = abs(gen_ord - human_ord)
    return float(1.0 - distance / max_distance)


# ── Batch computation ──────────────────────────────────────────────────────────


def compute_metrics(
    candidate: str,
    reference: str,
    elife_assessment: str | None = None,
) -> dict[str, float | None]:
    """Compute all pilot metrics for a (candidate, reference) review pair.

    Returns a dict with keys:
      bertscore_f1, rouge_l, cosine_similarity,
      recommendation (str), assessment_alignment
    """
    rec = extract_recommendation(candidate)
    return {
        "bertscore_f1": bertscore_f1(candidate, reference),
        "rouge_l": rouge_l(candidate, reference),
        "cosine_similarity": cosine_similarity(candidate, reference),
        "recommendation": rec,
        "assessment_alignment": assessment_alignment(rec, elife_assessment),
    }
