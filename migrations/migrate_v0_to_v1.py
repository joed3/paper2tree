"""
Migrate dag.json artifacts from project v0.x.x to v1.0.0 (schema_version 0 → 1).

v0 evaluation: validity_score (float 0-1), no support_level
v0 summary:    mean_validity_score, high_confidence_nodes, low_confidence_nodes

v1 evaluation: support_level ('high'|'medium'|'low'), no validity_score
v1 summary:    high_support_nodes, low_support_nodes
v1 top-level:  schema_version: 1
"""
import json
from pathlib import Path

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"

SUPPORT_COLOR = {
    "high": "#22c55e",
    "medium": "#eab308",
    "low": "#ef4444",
}


def score_to_support_level(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def migrate_dag(dag: dict) -> tuple[dict, bool]:
    """Return (migrated_dag, was_changed)."""
    changed = False

    if dag.get("schema_version", 0) >= 1:
        return dag, False

    for node in dag["dag"]["nodes"]:
        ev = node.get("evaluation")
        if ev is None:
            continue
        if "validity_score" in ev:
            score = ev.pop("validity_score")
            ev["support_level"] = score_to_support_level(score)
            node["visual"]["color"] = SUPPORT_COLOR[ev["support_level"]]
            changed = True

    summary = dag["summary"]
    if "mean_validity_score" in summary:
        summary.pop("mean_validity_score")
        changed = True
    if "high_confidence_nodes" in summary:
        summary["high_support_nodes"] = summary.pop("high_confidence_nodes")
        changed = True
    if "low_confidence_nodes" in summary:
        summary["low_support_nodes"] = summary.pop("low_confidence_nodes")
        changed = True

    dag["schema_version"] = 1
    changed = True

    return dag, changed


def rebuild_index(outputs_dir: Path) -> None:
    entries = []
    for paper_dir in sorted(outputs_dir.iterdir()):
        dag_path = paper_dir / "dag.json"
        if not dag_path.exists() or not paper_dir.is_dir():
            continue
        dag = json.loads(dag_path.read_text())
        paper = dag["paper"]
        summary = dag["summary"]
        abstract = paper["abstract"]
        if len(abstract) > 250:
            abstract = abstract[:250] + "…"
        entries.append({
            "paper_id": paper["paper_id"],
            "title": paper["title"],
            "authors": paper["authors"],
            "url": paper["url"],
            "abstract_short": abstract,
            "processed_at": paper["processed_at"],
            "high_support_count": summary["high_support_nodes"],
            "total_claims": summary["total_nodes"],
            "result_path": f"{paper['paper_id']}/dag.json",
        })
    entries.sort(key=lambda e: e["processed_at"], reverse=True)
    index_path = outputs_dir / "index.json"
    index_path.write_text(json.dumps({"version": 1, "papers": entries}, indent=2))
    print(f"  index.json → {len(entries)} papers")


def main() -> None:
    paper_dirs = [
        d for d in OUTPUTS_DIR.iterdir()
        if d.is_dir() and (d / "dag.json").exists()
    ]

    for paper_dir in paper_dirs:
        dag_path = paper_dir / "dag.json"
        dag = json.loads(dag_path.read_text())
        dag, changed = migrate_dag(dag)
        if changed:
            dag_path.write_text(json.dumps(dag, indent=2))
            print(f"migrated   {paper_dir.name}")
        else:
            print(f"up-to-date {paper_dir.name}")

    print()
    rebuild_index(OUTPUTS_DIR)
    print("done.")


if __name__ == "__main__":
    main()
