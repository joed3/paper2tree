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


def _validity_color(score: float) -> str:
    if score >= 0.8:
        return "#22c55e"   # green
    elif score >= 0.5:
        return "#eab308"   # yellow
    return "#ef4444"       # red


def _node_size(depth: int) -> int:
    return max(20, 48 - depth * 12)


def _overall_assessment(mean_score: float, n_claims: int) -> str:
    if mean_score >= 0.8:
        quality = "strong"
    elif mean_score >= 0.6:
        quality = "moderate"
    else:
        quality = "weak"
    return (
        f"The paper presents {n_claims} claims with {quality} overall support "
        f"(mean validity score: {mean_score:.2f})."
    )


def format_output(
    paper_id: str,
    url: str,
    extracted: ExtractedPaper,
    enriched: list[EnrichedClaim],
    evaluations: dict[str, ClaimEvaluation],
) -> PaperDAG:
    """Build the PaperDAG object from pipeline outputs."""
    nodes: list[DAGNode] = []
    edges: list[DAGEdge] = []

    for ec in enriched:
        claim = ec.claim
        eval_ = evaluations.get(claim.id)
        score = eval_.validity_score if eval_ else 0.5

        nodes.append(DAGNode(
            id=claim.id,
            label=claim.text[:80] + ("…" if len(claim.text) > 80 else ""),
            claim=claim.text,
            type=claim.type,
            depth=ec.depth,
            section_source=claim.section_source,
            verbatim_quote=claim.verbatim_quote,
            evaluation=eval_.model_dump() if eval_ else None,
            visual=VisualMeta(
                color=_validity_color(score),
                size=_node_size(ec.depth),
                border_width=3 if ec.depth == 0 else 1,
            ),
        ))

        if claim.parent_id is not None:
            edges.append(DAGEdge(
                id=f"e_{claim.parent_id}_{claim.id}",
                source=claim.parent_id,
                target=claim.id,
                relationship="supports",
                label="supports",
            ))

    scores = [e.validity_score for e in evaluations.values()]
    mean_score = round(sum(scores) / len(scores), 3) if scores else 0.0
    high_conf = sum(1 for e in evaluations.values() if e.validity_score >= 0.8)
    low_conf = sum(1 for e in evaluations.values() if e.validity_score < 0.5)
    max_depth = max((ec.depth for ec in enriched), default=0)

    return PaperDAG(
        paper=PaperMeta(
            paper_id=paper_id,
            title=extracted.title,
            authors=extracted.authors,
            url=url,
            abstract=extracted.abstract,
            word_count=extracted.word_count,
            processed_at=datetime.now(timezone.utc).isoformat(),
        ),
        dag=DAGData(nodes=nodes, edges=edges),
        summary=DAGSummary(
            total_nodes=len(nodes),
            total_edges=len(edges),
            max_depth=max_depth,
            mean_validity_score=mean_score,
            high_confidence_nodes=high_conf,
            low_confidence_nodes=low_conf,
            overall_assessment=_overall_assessment(mean_score, len(nodes)),
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
        index = PaperIndex.model_validate_json(index_path.read_text())
    else:
        index = PaperIndex()

    paper_id = paper_dag.paper.paper_id
    # Remove existing entry for this paper if present (for --force re-runs)
    index.papers = [p for p in index.papers if p.paper_id != paper_id]

    abstract_short = paper_dag.paper.abstract
    if len(abstract_short) > 250:
        abstract_short = abstract_short[:250] + "…"

    index.papers.append(PaperIndexEntry(
        paper_id=paper_id,
        title=paper_dag.paper.title,
        authors=paper_dag.paper.authors,
        url=paper_dag.paper.url,
        abstract_short=abstract_short,
        processed_at=paper_dag.paper.processed_at,
        mean_validity_score=paper_dag.summary.mean_validity_score,
        total_claims=paper_dag.summary.total_nodes,
        result_path=f"{paper_id}/dag.json",
    ))

    # Keep newest-first
    index.papers.sort(key=lambda p: p.processed_at, reverse=True)
    index_path.write_text(index.model_dump_json(indent=2))
