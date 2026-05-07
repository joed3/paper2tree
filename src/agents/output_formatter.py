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


def _support_color(support_level: str) -> str:
    if support_level == "high":
        return "#22c55e"  # green
    elif support_level == "medium":
        return "#eab308"  # yellow
    return "#ef4444"  # red


def _node_size(depth: int) -> int:
    return max(20, 48 - depth * 12)


def _overall_assessment(high: int, low: int, n_claims: int) -> str:
    if high / n_claims >= 0.6:
        quality = "strong"
    elif low / n_claims >= 0.5:
        quality = "weak"
    else:
        quality = "mixed"
    return (
        f"The paper presents {n_claims} claims with {quality} overall support "
        f"({high} high, {low} low)."
    )


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
        support_level = eval_.support_level if eval_ else "medium"

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
                    color=_support_color(support_level),
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

    high_support = sum(1 for e in evaluations.values() if e.support_level == "high")
    low_support = sum(1 for e in evaluations.values() if e.support_level == "low")
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
            overall_assessment=_overall_assessment(high_support, low_support, n_claims),
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
