"""Tests for ClaimGraph schema validation."""

import pytest
from pydantic import ValidationError

from src.schemas.claim import Claim, ClaimGraph
from tests.conftest import make_claim


def make_root(**kwargs) -> Claim:
    return make_claim("c1", type="root", parent_id=None, **kwargs)


# ── Valid graphs ───────────────────────────────────────────────────────────────


def test_single_root_is_valid():
    graph = ClaimGraph(claims=[make_root()])
    assert len(graph.claims) == 1


def test_linear_hierarchy_is_valid():
    graph = ClaimGraph(
        claims=[
            make_claim("c1", type="root", parent_id=None),
            make_claim("c1.1", type="primary", parent_id="c1"),
            make_claim("c1.1.1", type="supporting", parent_id="c1.1"),
        ]
    )
    assert len(graph.claims) == 3


def test_wide_hierarchy_is_valid():
    graph = ClaimGraph(
        claims=[
            make_claim("c1", type="root", parent_id=None),
            make_claim("c1.1", type="primary", parent_id="c1"),
            make_claim("c1.2", type="primary", parent_id="c1"),
            make_claim("c1.3", type="primary", parent_id="c1"),
        ]
    )
    assert len(graph.claims) == 4


# ── Invalid graphs ─────────────────────────────────────────────────────────────


def test_empty_claims_raises():
    with pytest.raises(ValidationError, match="at least one claim"):
        ClaimGraph(claims=[])


def test_no_root_claim_raises():
    """All claims have a parent — no root."""
    with pytest.raises(ValidationError, match="No root claim"):
        ClaimGraph(
            claims=[
                make_claim("c1.1", type="primary", parent_id="c1"),
                make_claim("c1.2", type="primary", parent_id="c1"),
            ]
        )


def test_multiple_typed_roots_raises():
    """Two claims with type='root' — invalid."""
    with pytest.raises(ValidationError, match="Expected exactly 1 root claim"):
        ClaimGraph(
            claims=[
                make_claim("c1", type="root", parent_id=None),
                make_claim("c2", type="root", parent_id=None),
            ]
        )


def test_dangling_parent_id_raises():
    """A claim references a parent_id that doesn't exist."""
    with pytest.raises(ValidationError, match="unknown parent_id"):
        ClaimGraph(
            claims=[
                make_claim("c1", type="root", parent_id=None),
                make_claim("c1.1", type="primary", parent_id="nonexistent"),
            ]
        )


def test_claim_all_types_accepted():
    """All four claim types should be valid."""
    graph = ClaimGraph(
        claims=[
            make_claim("c1", type="root", parent_id=None),
            make_claim("c1.1", type="primary", parent_id="c1"),
            make_claim("c1.1.1", type="supporting", parent_id="c1.1"),
            make_claim("c1.1.1.1", type="evidence", parent_id="c1.1.1"),
        ]
    )
    types = {c.type for c in graph.claims}
    assert types == {"root", "primary", "supporting", "evidence"}


def test_invalid_claim_type_raises():
    with pytest.raises(ValidationError):
        make_claim("c1", type="unknown")  # type: ignore[arg-type]
