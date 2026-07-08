"""Claim Extractor — identifies the hierarchical claim structure of a paper.

Uses adaptive thinking (no structured output — the two are incompatible).
Parses the JSON response manually with Pydantic and retries on validation failure.
"""

import json

from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_fixed

from .. import llm
from ..prompts import load_prompt
from ..schemas.claim import ClaimGraph

_MAX_TEXT_CHARS = 150_000


def extract_claims(paper_text: str) -> ClaimGraph:
    """Extract a hierarchical ClaimGraph from paper text. Retries up to 3 times."""
    truncated = paper_text[:_MAX_TEXT_CHARS]
    return _extract_with_retry(truncated)


@retry(stop=stop_after_attempt(3), wait=wait_fixed(3))
def _extract_with_retry(paper_text: str) -> ClaimGraph:
    template = load_prompt("claim_extractor")
    prompt = template.substitute(paper_text=paper_text)

    raw = llm.extract_json(llm.complete(prompt, max_tokens=16384, thinking=True))

    try:
        return ClaimGraph.model_validate_json(raw)
    except (ValidationError, json.JSONDecodeError) as e:
        raise ValueError(f"Claim extractor returned invalid JSON: {e}\n\nRaw:\n{raw[:500]}") from e
