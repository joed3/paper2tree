"""Claim Evaluator — compositional, bottom-up evaluation.

Claims are evaluated one depth level at a time, deepest first. Each parent is
evaluated *conditioned on the evaluations of its children*, so the tree structure
is load-bearing at judgment time: a parent whose supporting sub-claims are weak
inherits that weakness (evidential gap), and a parent that overreaches what its
well-supported children show is flagged (inferential gap).

Siblings at the same depth are independent, so a whole level is evaluated in one
call; only the depth dimension is serialized (deeper levels feed shallower ones).
"""

import json
import re

from pydantic import ValidationError

from .. import llm
from ..kb.schemas import RetrievedPassage
from ..prompts import load_prompt
from ..schemas.evaluation import ClaimEvaluation, SubtreeEvaluation
from ..utils.graph import EnrichedClaim

_MAX_TEXT_CHARS = 60_000  # leaves room for claims JSON + child context + response

# The model occasionally decorates an enum value ("slightly overclaimed",
# "moderately strong"), which would fail strict Literal validation and sink the
# whole paper. Coerce leniently to the nearest allowed value before validating.
_EVIDENCE = ("strong", "moderate", "weak", "absent")
_CALIB = ("overclaimed", "underclaimed", "calibrated")  # check compounds before "calibrated"
_LEVEL = ("high", "medium", "low")


def _coerce_choice(val, options, default):
    if not isinstance(val, str):
        return default
    v = re.sub(r"[^a-z]", "", val.lower())
    for o in options:
        if o in v:
            return o
    return default


def _coerce_enums(ev: dict) -> None:
    if "evidence_strength" in ev:
        ev["evidence_strength"] = _coerce_choice(ev["evidence_strength"], _EVIDENCE, "moderate")
    if "claim_evidence_calibration" in ev:
        ev["claim_evidence_calibration"] = _coerce_choice(
            ev["claim_evidence_calibration"], _CALIB, "calibrated"
        )
    for k in ("novelty_score", "groundedness_score"):
        if ev.get(k) is not None:
            ev[k] = _coerce_choice(ev[k], _LEVEL, None)


def _format_literature_block(retrieved: dict[str, list[RetrievedPassage]]) -> str:
    """Format retrieved passages into a prompt block per claim."""
    if not retrieved:
        return ""
    lines: list[str] = ["Relevant prior literature retrieved for each claim:"]
    for claim_id, passages in retrieved.items():
        if not passages:
            continue
        lines.append(f"\nClaim {claim_id}:")
        for i, p in enumerate(passages, 1):
            authors_str = ", ".join(p.authors[:3])
            if len(p.authors) > 3:
                authors_str += " et al."
            year_str = f" ({p.year})" if p.year else ""
            lines.append(f"  [{i}] {p.title}{year_str} — {authors_str}")
            lines.append(f"      {p.passage[:300]}{'…' if len(p.passage) > 300 else ''}")
            lines.append(f"      URL: {p.url}")
    return "\n".join(lines)


def _format_child_block(
    level_claims: list[EnrichedClaim],
    evaluations: dict[str, ClaimEvaluation],
) -> str:
    """Summarise the already-computed evaluations of each claim's children."""
    lines: list[str] = []
    for ec in level_claims:
        child_evals = [evaluations[cid] for cid in ec.children if cid in evaluations]
        if not child_evals:
            continue
        lines.append(f"\nSupporting sub-claims of {ec.claim.id}:")
        for cev in child_evals:
            weaknesses = "; ".join(cev.weaknesses[:2]) if cev.weaknesses else "none noted"
            lines.append(
                f"  - {cev.node_id}: evidence={cev.evidence_strength}, "
                f"calibration={cev.claim_evidence_calibration}; key weaknesses: {weaknesses}"
            )
    if not lines:
        return ""
    return (
        "Evaluations of this claim's supporting sub-claims (use these — see COMPOSITIONAL EVALUATION):"
        + "\n".join(lines)
    )


async def _evaluate_level(
    level_claims: list[EnrichedClaim],
    paper_text: str,
    child_block: str,
    literature_block: str,
) -> dict[str, ClaimEvaluation]:
    """Evaluate all claims at a single depth level in one call."""
    claims_data = [
        {
            "id": ec.claim.id,
            "text": ec.claim.text,
            "type": ec.claim.type,
            "section_source": ec.claim.section_source,
            "verbatim_quote": ec.claim.verbatim_quote,
        }
        for ec in level_claims
    ]

    template = load_prompt("claim_evaluator")
    prompt = template.substitute(
        paper_text=paper_text[:_MAX_TEXT_CHARS],
        claims_json=json.dumps(claims_data, indent=2),
        child_evaluations_block=child_block,
        literature_block=literature_block,
    )

    raw = llm.extract_json(await llm.complete_async(prompt, max_tokens=32768))

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claim evaluator returned non-JSON: {e}") from e

    for ev in data.get("evaluations", []):
        if isinstance(ev, dict):
            _coerce_enums(ev)

    try:
        result = SubtreeEvaluation.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"Claim evaluator returned invalid JSON: {e}") from e

    return {ev.node_id: ev for ev in result.evaluations}


async def evaluate_claims(
    enriched: list[EnrichedClaim],
    paper_text: str,
    retrieved: dict[str, list[RetrievedPassage]] | None = None,
) -> dict[str, ClaimEvaluation]:
    """Evaluate all claims bottom-up and return a dict keyed by claim id.

    Evaluates the deepest level first so that when a parent is evaluated, the
    evaluations of its children are already available and passed in as context.
    """
    literature_all = retrieved or {}
    evaluations: dict[str, ClaimEvaluation] = {}

    # Deepest depth first so children are always evaluated before their parents.
    depths = sorted({ec.depth for ec in enriched}, reverse=True)

    for depth in depths:
        level_claims = [ec for ec in enriched if ec.depth == depth]
        child_block = _format_child_block(level_claims, evaluations)
        level_literature = {
            ec.claim.id: literature_all[ec.claim.id]
            for ec in level_claims
            if ec.claim.id in literature_all
        }
        literature_block = _format_literature_block(level_literature)
        level_evals = await _evaluate_level(level_claims, paper_text, child_block, literature_block)
        evaluations.update(level_evals)

    return evaluations
