"""Tests for make_paper_id()."""

import re

from src.utils.paper_id import make_paper_id

_SAFE_CHARS = re.compile(r"^[a-z0-9\-]+$")
_URL_A = "https://arxiv.org/abs/1706.03762"
_URL_B = "https://arxiv.org/abs/1810.04805"


# ── Format and safety ──────────────────────────────────────────────────────────


def test_basic_slug_and_hash():
    pid = make_paper_id("Attention Is All You Need", _URL_A)
    assert pid.startswith("attention-is-all-you-need-")
    assert len(pid.split("-")[-1]) == 8  # 8-char hash suffix


def test_result_is_filesystem_safe():
    pid = make_paper_id("Some Paper: Version 2.0!", _URL_A)
    assert _SAFE_CHARS.match(pid), f"Unsafe characters in: {pid!r}"


def test_special_chars_stripped():
    pid = make_paper_id("Paper: A Study of X=Y?", _URL_A)
    assert ":" not in pid
    assert "?" not in pid
    assert "=" not in pid


def test_unicode_chars_stripped():
    pid = make_paper_id("Café Résumé Paper", _URL_A)
    assert _SAFE_CHARS.match(pid), f"Non-ASCII characters in: {pid!r}"


# ── Length limits ──────────────────────────────────────────────────────────────


def test_long_title_truncated():
    long_title = "A" * 100  # 100 'a' chars
    pid = make_paper_id(long_title, _URL_A)
    slug_part = pid[: pid.rfind("-")]  # everything before the last hyphen+hash
    assert len(slug_part) <= 50


def test_title_at_exact_50_chars_not_truncated():
    title = "word " * 9 + "word"  # exactly 49 chars; slug has hyphens instead of spaces
    pid = make_paper_id(title, _URL_A)
    assert _SAFE_CHARS.match(pid)


# ── Hash stability and uniqueness ──────────────────────────────────────────────


def test_same_url_same_hash():
    pid1 = make_paper_id("Title One", _URL_A)
    pid2 = make_paper_id("Title Two", _URL_A)
    # Different slugs, same hash
    hash1 = pid1.split("-")[-1]
    hash2 = pid2.split("-")[-1]
    assert hash1 == hash2


def test_different_urls_different_hashes():
    pid1 = make_paper_id("Same Title", _URL_A)
    pid2 = make_paper_id("Same Title", _URL_B)
    assert pid1 != pid2
    hash1 = pid1.split("-")[-1]
    hash2 = pid2.split("-")[-1]
    assert hash1 != hash2


def test_deterministic():
    """Same inputs always produce the same output."""
    assert make_paper_id("My Paper", _URL_A) == make_paper_id("My Paper", _URL_A)


# ── Edge cases ─────────────────────────────────────────────────────────────────


def test_empty_title_returns_hash_only():
    pid = make_paper_id("", _URL_A)
    assert len(pid) == 8
    assert _SAFE_CHARS.match(pid)


def test_title_with_only_special_chars_returns_hash_only():
    pid = make_paper_id("!@#$%^&*()", _URL_A)
    assert len(pid) == 8
    assert _SAFE_CHARS.match(pid)


def test_title_with_numbers_preserved():
    pid = make_paper_id("Model 3 Results", _URL_A)
    assert "model-3-results" in pid
