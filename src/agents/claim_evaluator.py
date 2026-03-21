"""Claim Evaluator — evaluates all claims in a single async LLM call.

Uses AsyncAnthropic with structured output (no thinking — incompatible with output_format).
Draft: single call for all claims. TODO: parallelize by primary-claim subtrees.
"""
import json

import anthropic

from ..prompts import load_prompt
from ..schemas.evaluation import ClaimEvaluation, SubtreeEvaluation
from ..utils.graph import EnrichedClaim

_async_client = anthropic.AsyncAnthropic()
_MAX_TEXT_CHARS = 60_000  # leaves room for claims JSON + response


async def evaluate_claims(
    enriched: list[EnrichedClaim],
    paper_text: str,
) -> dict[str, ClaimEvaluation]:
    """Evaluate all claims and return a dict keyed by claim id."""
    claims_data = [
        {
            "id": ec.claim.id,
            "text": ec.claim.text,
            "type": ec.claim.type,
            "section_source": ec.claim.section_source,
            "verbatim_quote": ec.claim.verbatim_quote,
        }
        for ec in enriched
    ]

    template = load_prompt("claim_evaluator")
    prompt = template.substitute(
        paper_text=paper_text[:_MAX_TEXT_CHARS],
        claims_json=json.dumps(claims_data, indent=2),
    )

    response = await _async_client.messages.parse(
        model="claude-opus-4-6",
        max_tokens=16384,
        messages=[{"role": "user", "content": prompt}],
        output_format=SubtreeEvaluation,
    )

    if response.parsed_output is None:
        raise ValueError("Claim evaluator returned no structured output")

    return {ev.node_id: ev for ev in response.parsed_output.evaluations}
