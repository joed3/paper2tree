"""Output Formatter — pure Python.

Assembles the final PaperDAG JSON from all pipeline outputs,
writes outputs/<paper_id>/dag.json, and upserts outputs/index.json.
"""

from datetime import datetime, timezone
from pathlib import Path

from ..schemas.evaluation import ClaimEvaluation
from ..schemas.index import PaperIndex, PaperIndexEntry
from ..schemas.output import DAGData, DAGEdge, DAGNode, DAGSummary, PaperDAG, PaperMeta, VisualMeta
from ..schemas.paper import ExtractedPaper
from ..utils.graph import EnrichedClaim

_EVIDENCE_COLOR = {
    "strong": "#22c55e",  # green
    "moderate": "#eab308",  # yellow
    "weak": "#f97316",  # orange
    "absent": "#ef4444",  # red
}

# How much each claim contributes to the paper-level verdict. A weak thesis must
# dominate the summary; a weak evidence-leaf must barely move it (§7 of the v2 critique).
_CENTRALITY = {"root": 4.0, "primary": 2.0, "supporting": 1.0, "evidence": 0.5}

# Numeric value of each evidence band, for the weighted aggregate.
_EVIDENCE_SCORE = {"strong": 1.0, "moderate": 0.6, "weak": 0.25, "absent": 0.0}


def _evidence_color(evidence_strength: str) -> str:
    return _EVIDENCE_COLOR.get(evidence_strength, "#ef4444")


def _node_size(depth: int) -> int:
    return max(20, 48 - depth * 12)


def _overall_assessment(
    enriched: list[EnrichedClaim],
    evaluations: dict[str, ClaimEvaluation],
) -> str:
    """Centrality-weighted verdict that tracks whether the paper's *thesis* holds.

    Leads with the most central weakly-supported claims so a triaging reader sees
    the load-bearing problems first ("worth reading?" framing).
    """
    weighted_sum = 0.0
    weight_total = 0.0
    weak_by_centrality: list[tuple[float, str]] = []

    for ec in enriched:
        ev = evaluations.get(ec.claim.id)
        if ev is None:
            continue
        weight = _CENTRALITY.get(ec.claim.type, 1.0)
        score = _EVIDENCE_SCORE.get(ev.evidence_strength, 0.0)
        weighted_sum += weight * score
        weight_total += weight
        if ev.evidence_strength in ("weak", "absent"):
            weak_by_centrality.append((weight, ec.claim.text))

    if weight_total == 0:
        return "No claims were evaluated."

    verdict_score = weighted_sum / weight_total
    if verdict_score >= 0.7:
        quality = "strong"
    elif verdict_score >= 0.45:
        quality = "mixed"
    else:
        quality = "weak"

    n_claims = len(enriched)
    parts = [
        f"The paper's {n_claims} claims show {quality} overall support when weighted by "
        f"centrality (weighted support score {verdict_score:.2f}, where the central thesis "
        f"counts far more than peripheral evidence)."
    ]

    # Surface the highest-centrality weak claims first — the triaging reader's core need.
    weak_by_centrality.sort(key=lambda t: t[0], reverse=True)
    if weak_by_centrality:
        top = weak_by_centrality[0][1]
        snippet = top[:160] + ("…" if len(top) > 160 else "")
        parts.append(
            f"The most load-bearing weakly-supported claim is: “{snippet}” "
            f"({len(weak_by_centrality)} weakly-supported claim(s) total)."
        )
    else:
        parts.append("No central claim was found to be weakly supported.")

    return " ".join(parts)


def format_output(
    paper_id: str,
    url: str,
    extracted: ExtractedPaper,
    enriched: list[EnrichedClaim],
    evaluations: dict[str, ClaimEvaluation],
    has_local_pdf: bool = False,
) -> PaperDAG:
    """Build the PaperDAG object from pipeline outputs."""
    nodes: list[DAGNode] = []
    edges: list[DAGEdge] = []

    for ec in enriched:
        claim = ec.claim
        eval_ = evaluations.get(claim.id)
        evidence_strength = eval_.evidence_strength if eval_ else "moderate"

        nodes.append(
            DAGNode(
                id=claim.id,
                label=claim.text[:80] + ("…" if len(claim.text) > 80 else ""),
                claim=claim.text,
                type=claim.type,
                depth=ec.depth,
                section_source=claim.section_source,
                verbatim_quote=claim.verbatim_quote,
                evaluation=eval_.model_dump() if eval_ else None,
                visual=VisualMeta(
                    color=_evidence_color(evidence_strength),
                    size=_node_size(ec.depth),
                    border_width=3 if ec.depth == 0 else 1,
                ),
                page_number=claim.page_number,
                bbox=claim.bbox,
            )
        )

        if claim.parent_id is not None:
            edges.append(
                DAGEdge(
                    id=f"e_{claim.parent_id}_{claim.id}",
                    source=claim.parent_id,
                    target=claim.id,
                    relationship="supports",
                    label="supports",
                )
            )

    # "high support" = strong evidence; "low support" = weak or absent evidence.
    high_support = sum(1 for e in evaluations.values() if e.evidence_strength == "strong")
    low_support = sum(1 for e in evaluations.values() if e.evidence_strength in ("weak", "absent"))
    max_depth = max((ec.depth for ec in enriched), default=0)
    n_claims = len(nodes)

    return PaperDAG(
        paper=PaperMeta(
            paper_id=paper_id,
            title=extracted.title,
            authors=extracted.authors,
            url=url,
            abstract=extracted.abstract,
            word_count=extracted.word_count,
            processed_at=datetime.now(timezone.utc).isoformat(),
            has_local_pdf=has_local_pdf,
        ),
        dag=DAGData(nodes=nodes, edges=edges),
        summary=DAGSummary(
            total_nodes=n_claims,
            total_edges=len(edges),
            max_depth=max_depth,
            high_support_nodes=high_support,
            low_support_nodes=low_support,
            overall_assessment=_overall_assessment(enriched, evaluations),
        ),
    )


def write_outputs(
    paper_dag: PaperDAG,
    paper_dir: Path,
    outputs_dir: Path,
) -> None:
    """Write dag.json and update index.json."""
    paper_dir.mkdir(parents=True, exist_ok=True)
    dag_path = paper_dir / "dag.json"
    dag_path.write_text(paper_dag.model_dump_json(indent=2))

    _upsert_index(outputs_dir / "index.json", paper_dag)


def _upsert_index(index_path: Path, paper_dag: PaperDAG) -> None:
    if index_path.exists():
        try:
            index = PaperIndex.model_validate_json(index_path.read_text())
        except Exception:
            # Index uses an incompatible schema (e.g. old mean_validity_score field);
            # start fresh rather than crashing.
            index = PaperIndex()
    else:
        index = PaperIndex()

    paper_id = paper_dag.paper.paper_id
    # Remove existing entry for this paper if present (for --force re-runs)
    index.papers = [p for p in index.papers if p.paper_id != paper_id]

    abstract_short = paper_dag.paper.abstract
    if len(abstract_short) > 250:
        abstract_short = abstract_short[:250] + "…"

    index.papers.append(
        PaperIndexEntry(
            paper_id=paper_id,
            title=paper_dag.paper.title,
            authors=paper_dag.paper.authors,
            url=paper_dag.paper.url,
            abstract_short=abstract_short,
            processed_at=paper_dag.paper.processed_at,
            high_support_count=paper_dag.summary.high_support_nodes,
            total_claims=paper_dag.summary.total_nodes,
            result_path=f"{paper_id}/dag.json",
        )
    )

    # Keep newest-first
    index.papers.sort(key=lambda p: p.processed_at, reverse=True)
    index_path.write_text(index.model_dump_json(indent=2))
