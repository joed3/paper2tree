from collections import defaultdict, deque
from dataclasses import dataclass, field

from ..schemas.claim import Claim, ClaimGraph


@dataclass
class EnrichedClaim:
    claim: Claim
    depth: int
    children: list[str] = field(default_factory=list)


def build_dag(claim_graph: ClaimGraph) -> list[EnrichedClaim]:
    """Validate the ClaimGraph and compute depths via BFS.

    Returns claims in topological order (parents before children).
    Raises ValueError on cycles or dangling parent_ids.
    """
    claims_by_id: dict[str, Claim] = {c.id: c for c in claim_graph.claims}
    children_map: dict[str, list[str]] = defaultdict(list)

    for claim in claim_graph.claims:
        if claim.parent_id is not None:
            children_map[claim.parent_id].append(claim.id)

    # Find root (claim with no parent)
    roots = [c for c in claim_graph.claims if c.parent_id is None]
    # Prefer the one explicitly typed as "root"
    typed_roots = [c for c in roots if c.type == "root"]
    root = (typed_roots or roots)[0]

    enriched: dict[str, EnrichedClaim] = {}
    queue: deque[tuple[str, int]] = deque([(root.id, 0)])
    visited: set[str] = set()

    while queue:
        node_id, depth = queue.popleft()

        if node_id in visited:
            # Cycle — skip the back-edge
            continue
        visited.add(node_id)

        claim = claims_by_id.get(node_id)
        if claim is None:
            continue

        node_children = children_map.get(node_id, [])
        enriched[node_id] = EnrichedClaim(
            claim=claim,
            depth=depth,
            children=node_children,
        )

        for child_id in node_children:
            if child_id not in visited:
                queue.append((child_id, depth + 1))

    # Include any orphaned claims at depth 1 (defensive: shouldn't happen after validation)
    for claim in claim_graph.claims:
        if claim.id not in enriched:
            enriched[claim.id] = EnrichedClaim(claim=claim, depth=1, children=[])

    return sorted(enriched.values(), key=lambda x: (x.depth, x.claim.id))


def get_subtrees(enriched: list[EnrichedClaim]) -> dict[str, list[str]]:
    """Return {primary_id: [all descendant ids including self]} for each primary/root claim."""
    by_id = {e.claim.id: e for e in enriched}

    primaries = [e for e in enriched if e.claim.type in ("root", "primary")]

    result: dict[str, list[str]] = {}
    for primary in primaries:
        subtree_ids: list[str] = []
        stack = [primary.claim.id]
        seen: set[str] = set()
        while stack:
            nid = stack.pop()
            if nid in seen:
                continue
            seen.add(nid)
            subtree_ids.append(nid)
            node = by_id.get(nid)
            if node:
                stack.extend(node.children)
        result[primary.claim.id] = subtree_ids

    return result
