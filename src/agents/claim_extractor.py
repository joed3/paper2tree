"""Claim Extractor — identifies the hierarchical claim structure of a paper.

Uses adaptive thinking (no structured output — the two are incompatible).
Parses the JSON response manually with Pydantic and retries on validation failure.
"""

import json
import re

import anthropic
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_fixed

from ..prompts import load_prompt
from ..schemas.claim import ClaimGraph

_client = anthropic.Anthropic()
_MAX_TEXT_CHARS = 150_000


def extract_claims(paper_text: str) -> ClaimGraph:
    """Extract a hierarchical ClaimGraph from paper text. Retries up to 3 times."""
    truncated = paper_text[:_MAX_TEXT_CHARS]
    return _extract_with_retry(truncated)


@retry(stop=stop_after_attempt(3), wait=wait_fixed(3))
def _extract_with_retry(paper_text: str) -> ClaimGraph:
    template = load_prompt("claim_extractor")
    prompt = template.substitute(paper_text=paper_text)

    with _client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=16384,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "max_tokens":
        raise ValueError(
            f"Claim extractor hit max_tokens limit ({response.usage.output_tokens} output tokens). "
            "Response was truncated — increase max_tokens or reduce paper length."
        )

    # Thinking blocks come first; find the text block
    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise ValueError("Claim extractor: no text block in response")

    raw = text_block.text.strip()

    # Strip markdown code fences if the model wrapped the JSON
    if raw.startswith("```"):
        lines = raw.splitlines()
        # Remove first line (```json or ```) and last line (```)
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # Attempt to extract JSON object if there's surrounding prose
    json_match = re.search(r"\{[\s\S]*\}", raw)
    if json_match:
        raw = json_match.group(0)

    try:
        return ClaimGraph.model_validate_json(raw)
    except (ValidationError, json.JSONDecodeError) as e:
        raise ValueError(f"Claim extractor returned invalid JSON: {e}\n\nRaw:\n{raw[:500]}") from e
