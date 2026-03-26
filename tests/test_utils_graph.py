"""Tests for build_dag() and get_subtrees()."""

from src.schemas.claim import ClaimGraph
from src.utils.graph import build_dag, get_subtrees
from tests.conftest import make_claim

# ── build_dag: depths ──────────────────────────────────────────────────────────


def test_single_root_depth_zero():
    graph = ClaimGraph(claims=[make_claim("c1", type="root", parent_id=None)])
    enriched = build_dag(graph)
    assert len(enriched) == 1
    assert enriched[0].depth == 0
    assert enriched[0].claim.id == "c1"


def test_linear_chain_depths():
    graph = ClaimGraph(
        claims=[
            make_claim("c1", type="root", parent_id=None),
            make_claim("c1.1", type="primary", parent_id="c1"),
            make_claim("c1.1.1", type="supporting", parent_id="c1.1"),
            make_claim("c1.1.1.1", type="evidence", parent_id="c1.1.1"),
        ]
    )
    enriched = build_dag(graph)
    depths = {e.claim.id: e.depth for e in enriched}
    assert depths == {"c1": 0, "c1.1": 1, "c1.1.1": 2, "c1.1.1.1": 3}


def test_wide_tree_depths(wide_claim_graph: ClaimGraph):
    enriched = build_dag(wide_claim_graph)
    depths = {e.claim.id: e.depth for e in enriched}
    assert depths["c1"] == 0
    assert depths["c1.1"] == 1
    assert depths["c1.2"] == 1
    assert depths["c1.1.1"] == 2
    assert depths["c1.2.1"] == 2


# ── build_dag: children ────────────────────────────────────────────────────────


def test_root_children_populated(wide_claim_graph: ClaimGraph):
    enriched = build_dag(wide_claim_graph)
    root = next(e for e in enriched if e.claim.id == "c1")
    assert sorted(root.children) == ["c1.1", "c1.2"]


def test_leaf_has_no_children(wide_claim_graph: ClaimGraph):
    enriched = build_dag(wide_claim_graph)
    leaf = next(e for e in enriched if e.claim.id == "c1.1.1")
    assert leaf.children == []


def test_intermediate_children_correct(linear_claim_graph: ClaimGraph):
    enriched = build_dag(linear_claim_graph)
    primary = next(e for e in enriched if e.claim.id == "c1.1")
    assert primary.children == ["c1.1.1"]


# ── build_dag: topological order ──────────────────────────────────────────────


def test_topological_order_parents_before_children():
    """Every node must appear after all its ancestors."""
    graph = ClaimGraph(
        claims=[
            make_claim("c1", type="root", parent_id=None),
            make_claim("c1.1", type="primary", parent_id="c1"),
            make_claim("c1.2", type="primary", parent_id="c1"),
            make_claim("c1.1.1", type="supporting", parent_id="c1.1"),
            make_claim("c1.2.1", type="supporting", parent_id="c1.2"),
        ]
    )
    enriched = build_dag(graph)
    position = {e.claim.id: i for i, e in enumerate(enriched)}
    assert position["c1"] < position["c1.1"]
    assert position["c1"] < position["c1.2"]
    assert position["c1.1"] < position["c1.1.1"]
    assert position["c1.2"] < position["c1.2.1"]


# ── build_dag: cycle handling ──────────────────────────────────────────────────


def test_all_nodes_returned_count(wide_claim_graph: ClaimGraph):
    enriched = build_dag(wide_claim_graph)
    assert len(enriched) == len(wide_claim_graph.claims)


def test_ids_match_claims(linear_claim_graph: ClaimGraph):
    enriched = build_dag(linear_claim_graph)
    enriched_ids = {e.claim.id for e in enriched}
    claim_ids = {c.id for c in linear_claim_graph.claims}
    assert enriched_ids == claim_ids


# ── build_dag: orphaned nodes ──────────────────────────────────────────────────


def test_orphaned_node_included_at_depth_one():
    """A node not reachable from the root still appears at depth 1."""
    # Note: ClaimGraph validation only checks parent_id references exist,
    # not full reachability. We can create an "orphaned" subtree by having
    # a claim that points to a non-root parent that is itself unreachable.
    # The simplest case: two claims both with parent_id=None where one is
    # typed "root" — the other is a valid root candidate but not the typed root.
    # Actually ClaimGraph allows only one *typed* root but multiple parent_id=None.
    graph = ClaimGraph(
        claims=[
            make_claim("c1", type="root", parent_id=None),
            make_claim("c2", type="primary", parent_id=None),  # second parentless claim
        ]
    )
    enriched = build_dag(graph)
    ids = {e.claim.id for e in enriched}
    assert "c2" in ids
    orphan = next(e for e in enriched if e.claim.id == "c2")
    assert orphan.depth == 1


# ── get_subtrees ───────────────────────────────────────────────────────────────


def test_subtrees_keys_are_root_and_primaries(wide_claim_graph: ClaimGraph):
    enriched = build_dag(wide_claim_graph)
    subtrees = get_subtrees(enriched)
    assert set(subtrees.keys()) == {"c1", "c1.1", "c1.2"}


def test_root_subtree_contains_all_nodes(wide_claim_graph: ClaimGraph):
    enriched = build_dag(wide_claim_graph)
    subtrees = get_subtrees(enriched)
    all_ids = {e.claim.id for e in enriched}
    assert set(subtrees["c1"]) == all_ids


def test_primary_subtree_contains_itself_and_descendants(wide_claim_graph: ClaimGraph):
    enriched = build_dag(wide_claim_graph)
    subtrees = get_subtrees(enriched)
    assert set(subtrees["c1.1"]) == {"c1.1", "c1.1.1"}
    assert set(subtrees["c1.2"]) == {"c1.2", "c1.2.1"}


def test_subtrees_include_self():
    """Each primary/root claim includes itself in its own subtree."""
    graph = ClaimGraph(
        claims=[
            make_claim("c1", type="root", parent_id=None),
            make_claim("c1.1", type="primary", parent_id="c1"),
        ]
    )
    enriched = build_dag(graph)
    subtrees = get_subtrees(enriched)
    assert "c1" in subtrees["c1"]
    assert "c1.1" in subtrees["c1.1"]


def test_evidence_nodes_not_subtree_keys():
    """Evidence nodes are not keys in the subtrees dict."""
    graph = ClaimGraph(
        claims=[
            make_claim("c1", type="root", parent_id=None),
            make_claim("c1.1", type="primary", parent_id="c1"),
            make_claim("c1.1.1", type="evidence", parent_id="c1.1"),
        ]
    )
    enriched = build_dag(graph)
    subtrees = get_subtrees(enriched)
    assert "c1.1.1" not in subtrees


def test_single_node_subtrees():
    graph = ClaimGraph(claims=[make_claim("c1", type="root", parent_id=None)])
    enriched = build_dag(graph)
    subtrees = get_subtrees(enriched)
    assert subtrees == {"c1": ["c1"]}
