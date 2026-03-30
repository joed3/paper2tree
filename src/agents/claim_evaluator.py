"""Claim Evaluator — evaluates all claims in a single async LLM call.

Draft: single call for all claims. TODO: parallelize by primary-claim subtrees.
"""

import json
import re

import anthropic
from pydantic import ValidationError

from ..kb.schemas import RetrievedPassage
from ..prompts import load_prompt
from ..schemas.evaluation import ClaimEvaluation, SubtreeEvaluation
from ..utils.graph import EnrichedClaim

_async_client = anthropic.AsyncAnthropic()
_MAX_TEXT_CHARS = 60_000  # leaves room for claims JSON + response


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


async def evaluate_claims(
    enriched: list[EnrichedClaim],
    paper_text: str,
    retrieved: dict[str, list[RetrievedPassage]] | None = None,
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

    literature_block = _format_literature_block(retrieved or {})

    template = load_prompt("claim_evaluator")
    prompt = template.substitute(
        paper_text=paper_text[:_MAX_TEXT_CHARS],
        claims_json=json.dumps(claims_data, indent=2),
        literature_block=literature_block,
    )

    async with _async_client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=32768,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = await stream.get_final_message()

    if response.stop_reason == "max_tokens":
        raise ValueError(
            f"Claim evaluator hit max_tokens limit ({response.usage.output_tokens} output tokens). "
            "Response was truncated — reduce claims or paper length."
        )

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise ValueError("Claim evaluator returned no structured output")

    raw = text_block.text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    json_match = re.search(r"\{[\s\S]*\}", raw)
    if json_match:
        raw = json_match.group(0)

    try:
        result = SubtreeEvaluation.model_validate_json(raw)
    except (ValidationError, json.JSONDecodeError) as e:
        raise ValueError(f"Claim evaluator returned invalid JSON: {e}") from e

    return {ev.node_id: ev for ev in result.evaluations}
