"""DAG Builder — pure Python.

Validates the ClaimGraph and computes depths. No LLM call needed.
Re-exports EnrichedClaim and graph utilities for use by other agents.
"""

from ..schemas.claim import ClaimGraph
from ..utils.graph import EnrichedClaim, build_dag, get_subtrees

__all__ = ["build_dag", "get_subtrees", "EnrichedClaim", "ClaimGraph"]
