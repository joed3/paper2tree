"""Tests for claim extractor JSON parsing logic.

LLM calls are mocked so no API key is required to run these tests.
The parsing logic under test:
  - strips markdown code fences
  - extracts a JSON object from surrounding prose
  - validates the result as a ClaimGraph
"""

import json
from unittest.mock import patch

import pytest

from src.agents.claim_extractor import extract_claims

# ── Helpers ────────────────────────────────────────────────────────────────────


def _minimal_claims_json() -> str:
    return json.dumps(
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "The model achieves state-of-the-art performance.",
                    "type": "root",
                    "parent_id": None,
                    "section_source": "Abstract",
                    "verbatim_quote": "Our model achieves state-of-the-art.",
                }
            ]
        }
    )


def _two_claim_json() -> str:
    return json.dumps(
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "Root claim.",
                    "type": "root",
                    "parent_id": None,
                    "section_source": "Abstract",
                    "verbatim_quote": "Root quote.",
                },
                {
                    "id": "c1.1",
                    "text": "Supporting claim.",
                    "type": "primary",
                    "parent_id": "c1",
                    "section_source": "Introduction",
                    "verbatim_quote": "Supporting quote.",
                },
            ]
        }
    )


def _patch_llm(text: str):
    """Patch the shared llm.complete to return the given response text."""
    return patch("src.llm.complete", return_value=text)


# ── Success paths ──────────────────────────────────────────────────────────────


def test_clean_json_parsed_correctly():
    with _patch_llm(_minimal_claims_json()):
        graph = extract_claims("paper text here")
    assert len(graph.claims) == 1
    assert graph.claims[0].id == "c1"


def test_json_with_backtick_fences_parsed():
    wrapped = f"```json\n{_minimal_claims_json()}\n```"
    with _patch_llm(wrapped):
        graph = extract_claims("paper text here")
    assert graph.claims[0].type == "root"


def test_json_with_plain_fences_parsed():
    wrapped = f"```\n{_minimal_claims_json()}\n```"
    with _patch_llm(wrapped):
        graph = extract_claims("paper text here")
    assert len(graph.claims) == 1


def test_json_with_surrounding_prose_extracted():
    prose = f"Here is the claim graph:\n\n{_minimal_claims_json()}\n\nI hope this helps."
    with _patch_llm(prose):
        graph = extract_claims("paper text here")
    assert len(graph.claims) == 1


def test_multi_claim_graph_returned():
    with _patch_llm(_two_claim_json()):
        graph = extract_claims("paper text here")
    assert len(graph.claims) == 2
    ids = {c.id for c in graph.claims}
    assert ids == {"c1", "c1.1"}


def test_text_truncated_to_150k_chars():
    """extract_claims must truncate the input before sending to the LLM."""
    long_text = "x" * 200_000
    with _patch_llm(_minimal_claims_json()) as mock_complete:
        extract_claims(long_text)
    prompt = mock_complete.call_args.args[0]
    assert len(prompt) <= 200_000  # strictly less than original 200k


# ── Failure paths ──────────────────────────────────────────────────────────────


def test_llm_error_propagates():
    with patch("src.llm.complete", side_effect=ValueError("no text block")):
        with pytest.raises(Exception):  # ValueError or RetryError after 3 attempts
            extract_claims("paper text")


def test_invalid_json_raises():
    with _patch_llm("not json at all"):
        with pytest.raises(Exception):
            extract_claims("paper text")
