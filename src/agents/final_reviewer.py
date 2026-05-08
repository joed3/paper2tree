"""Final Reviewer Agent — synthesises a DAG evaluation into an eLife-format prose review."""

import anthropic

from ..prompts import load_prompt
from ..schemas.output import PaperDAG

_client = anthropic.Anthropic()
_MAX_PAPER_CHARS = 80_000
_MAX_DAG_NODE_CHARS = 200
_MAX_DAG_NODE_CHARS_DETAILED = 600

# Prompt names that rely solely on the DAG (no paper_text substitution needed).
_DAG_ONLY_PROMPTS = {"final_reviewer_elife_dag_only"}


def _build_dag_summary(dag: PaperDAG, detailed: bool = False) -> str:
    max_claim_chars = _MAX_DAG_NODE_CHARS_DETAILED if detailed else _MAX_DAG_NODE_CHARS
    abstract = dag.paper.abstract if detailed else dag.paper.abstract[:600]

    lines = [
        f"Title: {dag.paper.title}",
        f"Authors: {', '.join(dag.paper.authors[:5])}{'…' if len(dag.paper.authors) > 5 else ''}",
        f"Abstract: {abstract}",
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
        alt_interp = ev.get("alternative_interpretations", [])

        lines.append(f"\n[{node.type.upper()}] {node.claim[:max_claim_chars]}")
        lines.append(f"  Support: {support}")
        if strengths:
            limit = None if detailed else 2
            lines.append(f"  Strengths: {'; '.join(strengths[:limit])}")
        if weaknesses:
            limit = None if detailed else 2
            lines.append(f"  Weaknesses: {'; '.join(weaknesses[:limit])}")
        if assumptions:
            limit = None if detailed else 2
            lines.append(f"  Required assumptions: {'; '.join(assumptions[:limit])}")
        if detailed and alt_interp:
            lines.append(f"  Alternative interpretations: {'; '.join(alt_interp)}")

    return "\n".join(lines)


def generate_review(paper_text: str, dag: PaperDAG, prompt_name: str = "final_reviewer") -> str:
    """Generate a prose review grounded in the DAG evaluation.

    Returns the review as a plain-text string.
    """
    dag_only = prompt_name in _DAG_ONLY_PROMPTS
    dag_summary = _build_dag_summary(dag, detailed=dag_only)
    template = load_prompt(prompt_name)

    subs: dict[str, str] = {"dag_summary": dag_summary}
    if not dag_only:
        subs["paper_text"] = paper_text[:_MAX_PAPER_CHARS]

    prompt = template.substitute(subs)

    response = _client.messages.create(
        model="claude-opus-4-6",
        max_tokens=8192,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise ValueError("Final reviewer returned no text block")

    return text_block.text.strip()
