"""Tests for the v2→v3 dag.json migration (scoring-model change)."""

from migrations.migrate_v2_to_v3 import migrate_dag
from src.schemas.evaluation import ClaimEvaluation
from src.schemas.output import PaperDAG


def _v2_dag() -> dict:
    """A minimal schema_version=2 artifact with the old evaluation fields."""
    return {
        "schema_version": 2,
        "paper": {
            "paper_id": "p1",
            "title": "T",
            "authors": ["A"],
            "url": "https://x",
            "abstract": "abs",
            "word_count": 10,
            "processed_at": "2026-01-01T00:00:00Z",
            "has_local_pdf": False,
        },
        "dag": {
            "nodes": [
                {
                    "id": "c1",
                    "label": "root",
                    "claim": "root claim",
                    "type": "root",
                    "depth": 0,
                    "section_source": "Abstract",
                    "verbatim_quote": "q",
                    "evaluation": {
                        "node_id": "c1",
                        "support_level": "low",
                        "confidence_level": "high",
                        "is_well_supported": False,
                        "strengths": ["s"],
                        "weaknesses": ["w"],
                        "alternative_interpretations": [],
                        "required_assumptions": [],
                        "supporting_evidence_quality": "absent",
                        "notes": "n",
                    },
                    "visual": {"color": "#ef4444", "size": 48, "border_width": 3},
                    "page_number": None,
                    "bbox": None,
                }
            ],
            "edges": [],
        },
        "summary": {
            "total_nodes": 1,
            "total_edges": 0,
            "max_depth": 0,
            "high_support_nodes": 0,
            "low_support_nodes": 1,
            "overall_assessment": "old",
        },
    }


def test_migration_bumps_schema_version():
    dag, changed = migrate_dag(_v2_dag())
    assert changed
    assert dag["schema_version"] == 3


def test_migration_derives_evidence_strength_from_quality():
    # supporting_evidence_quality="absent" takes priority → "absent"
    dag, _ = migrate_dag(_v2_dag())
    ev = dag["dag"]["nodes"][0]["evaluation"]
    assert ev["evidence_strength"] == "absent"
    assert ev["claim_evidence_calibration"] == "calibrated"


def test_migration_removes_old_fields():
    dag, _ = migrate_dag(_v2_dag())
    ev = dag["dag"]["nodes"][0]["evaluation"]
    for gone in (
        "support_level",
        "confidence_level",
        "is_well_supported",
        "supporting_evidence_quality",
    ):
        assert gone not in ev


def test_migrated_evaluation_validates_as_v3_schema():
    dag, _ = migrate_dag(_v2_dag())
    ev = dag["dag"]["nodes"][0]["evaluation"]
    # Must validate under the new ClaimEvaluation model.
    ClaimEvaluation.model_validate(ev)


def test_migrated_dag_validates_as_paperdag():
    dag, _ = migrate_dag(_v2_dag())
    PaperDAG.model_validate(dag)


def test_migration_falls_back_to_support_level():
    v2 = _v2_dag()
    del v2["dag"]["nodes"][0]["evaluation"]["supporting_evidence_quality"]
    v2["dag"]["nodes"][0]["evaluation"]["support_level"] = "high"
    dag, _ = migrate_dag(v2)
    assert dag["dag"]["nodes"][0]["evaluation"]["evidence_strength"] == "strong"


def test_migration_recomputes_summary_counts():
    dag, _ = migrate_dag(_v2_dag())
    # single node, absent → low band
    assert dag["summary"]["high_support_nodes"] == 0
    assert dag["summary"]["low_support_nodes"] == 1


def test_migration_idempotent():
    dag, _ = migrate_dag(_v2_dag())
    dag2, changed = migrate_dag(dag)
    assert not changed


def test_migration_rekeys_node_color():
    dag, _ = migrate_dag(_v2_dag())
    # absent → red
    assert dag["dag"]["nodes"][0]["visual"]["color"] == "#ef4444"
