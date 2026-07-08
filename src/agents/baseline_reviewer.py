"""Baseline Reviewer Agent — single-agent eLife-format review with no DAG intermediate."""

import anthropic

from .. import llm
from ..prompts import load_prompt

_client = anthropic.Anthropic()
_MAX_PAPER_CHARS = 80_000


def generate_baseline_review(paper_text: str, prompt_name: str = "baseline_reviewer") -> str:
    """Generate a prose review from paper text alone (no DAG).

    Returns the review as a plain-text string.
    """
    template = load_prompt(prompt_name)
    prompt = template.substitute(paper_text=paper_text[:_MAX_PAPER_CHARS])

    response = _client.messages.create(
        model="claude-opus-4-6",
        max_tokens=8192,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )

    llm.record_usage(getattr(response, "usage", None))

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise ValueError("Baseline reviewer returned no text block")

    return text_block.text.strip()
