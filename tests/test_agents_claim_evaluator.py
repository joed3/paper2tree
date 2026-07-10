"""Tests for compositional (bottom-up) claim evaluation.

The LLM call is mocked to echo a canned evaluation for every claim present in a
level's prompt, so we can assert the ordering (deepest first) and that a parent's
prompt carries its children's already-computed evaluations.
"""

import asyncio
import json
import re

from src.agents.claim_evaluator import evaluate_claims
from src.schemas.claim import ClaimGraph
from src.utils.graph import build_dag
from tests.conftest import make_claim


def _fake_llm_factory(recorder: list[str]):
    """Return an async fake for llm.complete_async that records prompts and
    returns a valid SubtreeEvaluation for whichever claim ids appear in the prompt."""

    async def _fake(prompt: str, **kwargs) -> str:
        recorder.append(prompt)
        ids = re.findall(r'"id":\s*"([^"]+)"', prompt)
        evals = [
            {
                "node_id": cid,
                "evidence_strength": "moderate",
                "claim_evidence_calibration": "calibrated",
                "strengths": [],
                "weaknesses": [],
                "alternative_interpretations": [],
                "required_assumptions": [],
                "notes": "",
            }
            for cid in ids
        ]
        return json.dumps({"evaluations": evals})

    return _fake


def test_all_claims_evaluated(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    enriched = build_dag(
        ClaimGraph(
            claims=[
                make_claim("c1", type="root", parent_id=None),
                make_claim("c1.1", type="primary", parent_id="c1"),
                make_claim("c1.1.1", type="supporting", parent_id="c1.1"),
            ]
        )
    )
    recorder: list[str] = []
    monkeypatch.setattr("src.llm.complete_async", _fake_llm_factory(recorder))

    result = asyncio.run(evaluate_claims(enriched, "paper text"))

    assert set(result.keys()) == {"c1", "c1.1", "c1.1.1"}


def test_deepest_level_evaluated_first(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    enriched = build_dag(
        ClaimGraph(
            claims=[
                make_claim("c1", type="root", parent_id=None),
                make_claim("c1.1", type="primary", parent_id="c1"),
                make_claim("c1.1.1", type="supporting", parent_id="c1.1"),
            ]
        )
    )
    recorder: list[str] = []
    monkeypatch.setattr("src.llm.complete_async", _fake_llm_factory(recorder))

    asyncio.run(evaluate_claims(enriched, "paper text"))

    # One call per depth level, deepest first: c1.1.1 (d2), then c1.1 (d1), then c1 (d0).
    assert len(recorder) == 3
    first_ids = re.findall(r'"id":\s*"([^"]+)"', recorder[0])
    last_ids = re.findall(r'"id":\s*"([^"]+)"', recorder[2])
    assert first_ids == ["c1.1.1"]
    assert last_ids == ["c1"]


def test_parent_prompt_includes_child_evaluations(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    enriched = build_dag(
        ClaimGraph(
            claims=[
                make_claim("c1", type="root", parent_id=None),
                make_claim("c1.1", type="primary", parent_id="c1"),
            ]
        )
    )
    recorder: list[str] = []
    monkeypatch.setattr("src.llm.complete_async", _fake_llm_factory(recorder))

    asyncio.run(evaluate_claims(enriched, "paper text"))

    # The root-level prompt (last call) must reference its child c1.1's evaluation.
    root_prompt = recorder[-1]
    assert "supporting sub-claims of c1" in root_prompt.lower()
    assert "c1.1" in root_prompt


def test_decorated_enum_values_are_coerced(monkeypatch):
    """A qualifier like 'slightly overclaimed' must not fail the whole paper."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    enriched = build_dag(ClaimGraph(claims=[make_claim("c1", type="root", parent_id=None)]))

    async def _fake(prompt, **kwargs):
        return json.dumps(
            {
                "evaluations": [
                    {
                        "node_id": "c1",
                        "evidence_strength": "moderately strong",
                        "claim_evidence_calibration": "slightly overclaimed",
                        "strengths": [],
                        "weaknesses": [],
                        "alternative_interpretations": [],
                        "required_assumptions": [],
                        "notes": "",
                    }
                ]
            }
        )

    monkeypatch.setattr("src.llm.complete_async", _fake)
    result = asyncio.run(evaluate_claims(enriched, "paper text"))
    assert result["c1"].evidence_strength == "strong"
    assert result["c1"].claim_evidence_calibration == "overclaimed"
