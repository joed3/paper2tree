"""Central LLM completion helper with two auth paths.

Every pipeline agent routes its Claude calls through this module:

- When ANTHROPIC_API_KEY is set, calls go directly through the anthropic SDK
  (streaming, adaptive thinking, structured outputs — the original behavior).
- When no key is present, calls fall back to the Claude Agent SDK, which uses
  the local Claude Code CLI login. This lets the pipeline (and the MCP plugin)
  work for users who are logged into Claude Code without an API key.
"""

import asyncio
import contextvars
import json
import os
import re
from typing import TypeVar

import anthropic
from pydantic import BaseModel

DEFAULT_MODEL = "claude-opus-4-6"

# Opus-tier pricing (per 1M tokens) for cost accounting in the eval harness.
_INPUT_USD_PER_MTOK = 5.0
_OUTPUT_USD_PER_MTOK = 25.0

T = TypeVar("T", bound=BaseModel)

_sync_client: anthropic.Anthropic | None = None
_async_client: anthropic.AsyncAnthropic | None = None


# ── Usage / cost tracking ────────────────────────────────────────────────────
# Lets the eval harness attribute token spend to a pipeline stage: reset_usage()
# before, get_usage() after. Only the direct-API path reports usage; the agent-SDK
# fallback (no API key) contributes nothing.
#
# The accumulator lives in a ContextVar holding a *mutable dict* so per-paper
# attribution stays correct under concurrency: each paper task calls reset_usage()
# (a fresh dict scoped to that task's context), and record_usage() mutates the dict
# in place. In-place mutation is visible across asyncio.to_thread boundaries (the
# thread gets a copy of the context that references the same dict), while a
# different task's reset_usage() rebinds only its own context — so five papers
# running at once don't cross-contaminate each other's counts.
_usage_var: contextvars.ContextVar[dict] = contextvars.ContextVar("p2t_usage")


def _current_usage() -> dict:
    try:
        return _usage_var.get()
    except LookupError:
        d = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        _usage_var.set(d)
        return d


def reset_usage() -> None:
    _usage_var.set({"input_tokens": 0, "output_tokens": 0, "calls": 0})


def record_usage(usage) -> None:
    """Accumulate an Anthropic response .usage object (no-op if None)."""
    if usage is None:
        return
    d = _current_usage()
    d["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
    d["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
    d["calls"] += 1


def get_usage() -> dict:
    """Return accumulated tokens plus estimated Opus-tier cost in USD."""
    d = _current_usage()
    cost = (
        d["input_tokens"] / 1e6 * _INPUT_USD_PER_MTOK
        + d["output_tokens"] / 1e6 * _OUTPUT_USD_PER_MTOK
    )
    return {**d, "cost_usd": round(cost, 4)}


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _get_sync_client() -> anthropic.Anthropic:
    global _sync_client
    if _sync_client is None:
        _sync_client = anthropic.Anthropic()
    return _sync_client


def _get_async_client() -> anthropic.AsyncAnthropic:
    global _async_client
    if _async_client is None:
        _async_client = anthropic.AsyncAnthropic()
    return _async_client


# ── Text completion ────────────────────────────────────────────────────────────


def complete(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8192,
    thinking: bool = False,
) -> str:
    """Return the text completion for a single-user-message prompt (sync)."""
    if has_api_key():
        return _api_complete(prompt, model=model, max_tokens=max_tokens, thinking=thinking)
    # Sync agents run inside asyncio.to_thread, so no event loop is running here
    return asyncio.run(_agent_complete(prompt, model=model))


async def complete_async(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8192,
    thinking: bool = False,
) -> str:
    """Return the text completion for a single-user-message prompt (async)."""
    if has_api_key():
        return await _api_complete_async(
            prompt, model=model, max_tokens=max_tokens, thinking=thinking
        )
    return await _agent_complete(prompt, model=model)


def _api_complete(prompt: str, *, model: str, max_tokens: int, thinking: bool) -> str:
    kwargs: dict = {}
    if thinking:
        kwargs["thinking"] = {"type": "adaptive"}
    with _get_sync_client().messages.stream(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    ) as stream:
        response = stream.get_final_message()
    return _text_of(response, max_tokens)


async def _api_complete_async(prompt: str, *, model: str, max_tokens: int, thinking: bool) -> str:
    kwargs: dict = {}
    if thinking:
        kwargs["thinking"] = {"type": "adaptive"}
    async with _get_async_client().messages.stream(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    ) as stream:
        response = await stream.get_final_message()
    return _text_of(response, max_tokens)


def _text_of(response, max_tokens: int) -> str:
    record_usage(getattr(response, "usage", None))
    if response.stop_reason == "max_tokens":
        raise ValueError(
            f"LLM hit max_tokens limit ({max_tokens}); response was truncated — "
            "increase max_tokens or reduce input length."
        )
    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise ValueError("LLM returned no text block")
    return text_block.text


async def _agent_complete(prompt: str, *, model: str) -> str:
    """Single-turn completion via the Claude Agent SDK (local Claude Code login)."""
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    last: ResultMessage | None = None
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(allowed_tools=[], max_turns=1, model=model),
    ):
        if isinstance(message, ResultMessage):
            last = message

    if last is None or not last.result:
        raise RuntimeError(
            "Claude Agent SDK returned no result. Ensure the Claude Code CLI is "
            "installed and logged in, or set ANTHROPIC_API_KEY."
        )
    return last.result


# ── Structured output ──────────────────────────────────────────────────────────


def parse_structured(
    prompt: str,
    output_format: type[T],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 16384,
) -> T:
    """Return a validated Pydantic model for the prompt.

    Uses native structured outputs on the API path; on the agent path the
    JSON schema is appended to the prompt and the response parsed manually.
    """
    if has_api_key():
        response = _get_sync_client().messages.parse(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            output_format=output_format,
        )
        record_usage(getattr(response, "usage", None))
        if response.parsed_output is None:
            raise ValueError("LLM returned no structured output")
        return response.parsed_output

    schema = json.dumps(output_format.model_json_schema())
    json_prompt = (
        f"{prompt}\n\n"
        "Respond with ONLY a valid JSON object matching this JSON schema — "
        f"no prose, no code fences:\n{schema}"
    )
    raw = asyncio.run(_agent_complete(json_prompt, model=model))
    return output_format.model_validate_json(extract_json(raw))


def extract_json(raw: str) -> str:
    """Strip code fences and surrounding prose from a JSON-bearing response."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    match = re.search(r"\{[\s\S]*\}", raw)
    return match.group(0) if match else raw
