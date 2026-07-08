"""Tests for the central LLM helper (src/llm.py) — auth routing and JSON extraction."""

import asyncio
from unittest.mock import AsyncMock, patch

from src import llm

# ── has_api_key / routing ──────────────────────────────────────────────────────


def test_has_api_key_true(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert llm.has_api_key()


def test_has_api_key_false(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert not llm.has_api_key()


def test_complete_uses_api_when_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with patch("src.llm._api_complete", return_value="api result") as api_mock:
        assert llm.complete("hi") == "api result"
    api_mock.assert_called_once()


def test_complete_falls_back_to_agent_sdk(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("src.llm._agent_complete", new_callable=AsyncMock, return_value="agent result"):
        assert llm.complete("hi") == "agent result"


def test_complete_async_falls_back_to_agent_sdk(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("src.llm._agent_complete", new_callable=AsyncMock, return_value="agent result"):
        assert asyncio.run(llm.complete_async("hi")) == "agent result"


def test_agent_path_receives_model(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("src.llm._agent_complete", new_callable=AsyncMock, return_value="x") as agent_mock:
        llm.complete("hi", model="claude-haiku-4-5-20251001")
    assert agent_mock.call_args.kwargs["model"] == "claude-haiku-4-5-20251001"


# ── extract_json ───────────────────────────────────────────────────────────────


def test_extract_json_plain():
    assert llm.extract_json('{"a": 1}') == '{"a": 1}'


def test_extract_json_strips_fences():
    assert llm.extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_strips_plain_fences():
    assert llm.extract_json('```\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_from_prose():
    raw = 'Here you go:\n{"a": 1}\nHope that helps!'
    assert llm.extract_json(raw) == '{"a": 1}'


def test_extract_json_no_object_returns_input():
    assert llm.extract_json("no json here") == "no json here"
