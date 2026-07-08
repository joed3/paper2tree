"""
Migrate dag.json artifacts from schema_version 2 to 3 (project v1.7.x → v2.0.0).

The v2.0 scoring model collapses the old per-claim evaluation onto two axes and
drops three fields. This migration rewrites each node's `evaluation` block:

  removed:  support_level, confidence_level, is_well_supported,
            supporting_evidence_quality
  added:    evidence_strength          (derived from the removed fields)
            claim_evidence_calibration ("calibrated" — a neutral default; the
                                        original judgment cannot be reconstructed)

Derivation of evidence_strength (best-effort, in priority order):
  1. old supporting_evidence_quality ("strong"/"moderate"/"weak"/"absent") maps
     directly — it was already the evidence-quality axis.
  2. else fall back to support_level: high→strong, medium→moderate, low→weak.
  3. else "moderate".

Node colors in v2 were keyed on support_level; they are re-keyed on the derived
evidence_strength so the visuals stay consistent. The summary counters
(high_support_nodes / low_support_nodes) are recomputed from evidence_strength.

Idempotent — safe to re-run; artifacts already at v3 are skipped.
"""

import json
from pathlib import Path

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"

_QUALITY_TO_STRENGTH = {
    "strong": "strong",
    "moderate": "moderate",
    "weak": "weak",
    "absent": "absent",
}
_SUPPORT_TO_STRENGTH = {"high": "strong", "medium": "moderate", "low": "weak"}

_EVIDENCE_COLOR = {
    "strong": "#22c55e",
    "moderate": "#eab308",
    "weak": "#f97316",
    "absent": "#ef4444",
}


def _derive_strength(ev: dict) -> str:
    quality = ev.get("supporting_evidence_quality")
    if quality in _QUALITY_TO_STRENGTH:
        return _QUALITY_TO_STRENGTH[quality]
    support = ev.get("support_level")
    if support in _SUPPORT_TO_STRENGTH:
        return _SUPPORT_TO_STRENGTH[support]
    return "moderate"


def _migrate_evaluation(ev: dict) -> dict:
    strength = _derive_strength(ev)
    new_ev = {
        "node_id": ev.get("node_id", ""),
        "evidence_strength": strength,
        "claim_evidence_calibration": "calibrated",
        "strengths": ev.get("strengths", []),
        "weaknesses": ev.get("weaknesses", []),
        "alternative_interpretations": ev.get("alternative_interpretations", []),
        "required_assumptions": ev.get("required_assumptions", []),
        "notes": ev.get("notes", ""),
        "literature_citations": ev.get("literature_citations", []),
        "novelty_score": ev.get("novelty_score"),
        "groundedness_score": ev.get("groundedness_score"),
    }
    return new_ev


def migrate_dag(dag: dict) -> tuple[dict, bool]:
    """Return (migrated_dag, was_changed). Idempotent."""
    if dag.get("schema_version", 0) >= 3:
        return dag, False

    high = 0
    low = 0
    for node in dag.get("dag", {}).get("nodes", []):
        ev = node.get("evaluation")
        if ev is not None:
            new_ev = _migrate_evaluation(ev)
            node["evaluation"] = new_ev
            strength = new_ev["evidence_strength"]
        else:
            strength = "moderate"
        # Re-key node color on the derived evidence strength.
        if "visual" in node:
            node["visual"]["color"] = _EVIDENCE_COLOR.get(strength, "#ef4444")
        if strength == "strong":
            high += 1
        elif strength in ("weak", "absent"):
            low += 1

    if "summary" in dag:
        dag["summary"]["high_support_nodes"] = high
        dag["summary"]["low_support_nodes"] = low

    dag["schema_version"] = 3
    return dag, True


def main() -> None:
    paper_dirs = [d for d in OUTPUTS_DIR.iterdir() if d.is_dir() and (d / "dag.json").exists()]
    migrated = 0
    for paper_dir in sorted(paper_dirs):
        dag_path = paper_dir / "dag.json"
        dag = json.loads(dag_path.read_text())
        dag, changed = migrate_dag(dag)
        if changed:
            dag_path.write_text(json.dumps(dag, indent=2))
            migrated += 1
            print(f"migrated   {paper_dir.name}")
        else:
            print(f"up-to-date {paper_dir.name}")
    print(f"\ndone. {migrated} artifact(s) migrated to schema_version 3.")


if __name__ == "__main__":
    main()
