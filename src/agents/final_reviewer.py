"""Final Reviewer Agent — synthesises a DAG evaluation into an eLife-format prose review."""

import anthropic

from ..prompts import load_prompt
from ..schemas.output import PaperDAG

_client = anthropic.Anthropic()
_MAX_PAPER_CHARS = 80_000
_MAX_DAG_NODE_CHARS = 200


def _build_dag_summary(dag: PaperDAG) -> str:
    lines = [
        f"Title: {dag.paper.title}",
        f"Authors: {', '.join(dag.paper.authors[:5])}{'…' if len(dag.paper.authors) > 5 else ''}",
        f"Abstract: {dag.paper.abstract[:600]}",
        "",
        f"Overall assessment: {dag.summary.overall_assessment}",
        f"Claims: {dag.summary.total_nodes} total | {dag.summary.high_support_nodes} high support | {dag.summary.low_support_nodes} low support",
        "",
        "--- CLAIM EVALUATIONS ---",
    ]

    for node in dag.dag.nodes:
        ev = node.evaluation
        if ev is None:
            continue
        support = ev.get("support_level", "?")
        strengths = ev.get("strengths", [])
        weaknesses = ev.get("weaknesses", [])
        assumptions = ev.get("required_assumptions", [])

        lines.append(f"\n[{node.type.upper()}] {node.claim[:_MAX_DAG_NODE_CHARS]}")
        lines.append(f"  Support: {support}")
        if strengths:
            lines.append(f"  Strengths: {'; '.join(strengths[:2])}")
        if weaknesses:
            lines.append(f"  Weaknesses: {'; '.join(weaknesses[:2])}")
        if assumptions:
            lines.append(f"  Required assumptions: {'; '.join(assumptions[:2])}")

    return "\n".join(lines)


def generate_review(paper_text: str, dag: PaperDAG) -> str:
    """Generate an eLife-format prose review grounded in the DAG evaluation.

    Returns the review as a plain-text string.
    """
    dag_summary = _build_dag_summary(dag)
    template = load_prompt("final_reviewer")
    prompt = template.substitute(
        paper_text=paper_text[:_MAX_PAPER_CHARS],
        dag_summary=dag_summary,
    )

    response = _client.messages.create(
        model="claude-opus-4-7",
        max_tokens=8192,
        thinking={"type": "enabled", "budget_tokens": 8000},
        messages=[{"role": "user", "content": prompt}],
    )

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise ValueError("Final reviewer returned no text block")

    return text_block.text.strip()
