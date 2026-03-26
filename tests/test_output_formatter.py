"""Tests for output_formatter helpers, format_output, write_outputs, and _upsert_index."""

import json
from pathlib import Path

from src.agents.output_formatter import (
    _node_size,
    _overall_assessment,
    _support_color,
    _upsert_index,
    format_output,
    write_outputs,
)
from src.schemas.claim import ClaimGraph
from src.schemas.output import SCHEMA_VERSION
from src.utils.graph import build_dag
from tests.conftest import make_claim, make_evaluation, make_extracted_paper

# ── _support_color ─────────────────────────────────────────────────────────────


def test_support_color_high():
    assert _support_color("high") == "#22c55e"


def test_support_color_medium():
    assert _support_color("medium") == "#eab308"


def test_support_color_low():
    assert _support_color("low") == "#ef4444"


def test_support_color_unknown_defaults_to_red():
    # Any unknown value falls through to the red default
    assert _support_color("unknown") == "#ef4444"


# ── _node_size ─────────────────────────────────────────────────────────────────


def test_node_size_depth_zero():
    assert _node_size(0) == 48


def test_node_size_depth_one():
    assert _node_size(1) == 36


def test_node_size_depth_two():
    assert _node_size(2) == 24


def test_node_size_depth_three():
    assert _node_size(3) == 20  # 48-36=12; clamped to min 20


def test_node_size_deep_clamped_to_minimum():
    assert _node_size(10) == 20


# ── _overall_assessment ────────────────────────────────────────────────────────


def test_overall_assessment_strong():
    # 7/10 = 70% high → "strong"
    text = _overall_assessment(high=7, low=1, n_claims=10)
    assert "strong" in text
    assert "10 claims" in text


def test_overall_assessment_weak():
    # 1/10 high, 6/10 low → "weak"
    text = _overall_assessment(high=1, low=6, n_claims=10)
    assert "weak" in text


def test_overall_assessment_mixed():
    # 4/10 high, 3/10 low → "mixed"
    text = _overall_assessment(high=4, low=3, n_claims=10)
    assert "mixed" in text


def test_overall_assessment_includes_counts():
    text = _overall_assessment(high=3, low=2, n_claims=8)
    assert "3 high" in text
    assert "2 low" in text


# ── format_output ──────────────────────────────────────────────────────────────


def _make_pipeline_outputs(claim_configs: list[dict]):
    """Helper: build enriched list + evaluations from simple config."""
    claims = [make_claim(**cfg) for cfg in claim_configs]
    graph = ClaimGraph(claims=claims)
    enriched = build_dag(graph)
    evaluations = {e.claim.id: make_evaluation(e.claim.id) for e in enriched}
    return enriched, evaluations


def test_format_output_node_count():
    enriched, evals = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None},
            {"id": "c1.1", "type": "primary", "parent_id": "c1"},
            {"id": "c1.1.1", "type": "supporting", "parent_id": "c1.1"},
        ]
    )
    dag = format_output("paper-abc", "https://example.com", make_extracted_paper(), enriched, evals)
    assert dag.summary.total_nodes == 3
    assert len(dag.dag.nodes) == 3


def test_format_output_edge_count():
    """Root has no parent → only 2 edges for a 3-node chain."""
    enriched, evals = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None},
            {"id": "c1.1", "type": "primary", "parent_id": "c1"},
            {"id": "c1.1.1", "type": "supporting", "parent_id": "c1.1"},
        ]
    )
    dag = format_output("paper-abc", "https://example.com", make_extracted_paper(), enriched, evals)
    assert dag.summary.total_edges == 2
    assert len(dag.dag.edges) == 2


def test_format_output_root_has_no_edge():
    enriched, evals = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None},
            {"id": "c1.1", "type": "primary", "parent_id": "c1"},
        ]
    )
    dag = format_output("paper-abc", "https://example.com", make_extracted_paper(), enriched, evals)
    edge_targets = {e.target for e in dag.dag.edges}
    assert "c1" not in edge_targets


def test_format_output_label_truncated():
    long_text = "A" * 100
    enriched, evals = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None, "text": long_text},
        ]
    )
    dag = format_output("paper-abc", "https://example.com", make_extracted_paper(), enriched, evals)
    node = dag.dag.nodes[0]
    assert len(node.label) == 81  # 80 chars + "…"
    assert node.label.endswith("…")
    assert node.claim == long_text  # full text preserved


def test_format_output_label_not_truncated_when_short():
    short_text = "Short claim."
    enriched, evals = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None, "text": short_text},
        ]
    )
    dag = format_output("paper-abc", "https://example.com", make_extracted_paper(), enriched, evals)
    assert dag.dag.nodes[0].label == short_text


def test_format_output_support_counts():
    enriched, _ = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None},
            {"id": "c1.1", "type": "primary", "parent_id": "c1"},
            {"id": "c1.2", "type": "primary", "parent_id": "c1"},
        ]
    )
    evals = {
        "c1": make_evaluation("c1", support_level="high"),
        "c1.1": make_evaluation("c1.1", support_level="low"),
        "c1.2": make_evaluation("c1.2", support_level="medium"),
    }
    dag = format_output("paper-abc", "https://example.com", make_extracted_paper(), enriched, evals)
    assert dag.summary.high_support_nodes == 1
    assert dag.summary.low_support_nodes == 1


def test_format_output_schema_version():
    enriched, evals = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None},
        ]
    )
    dag = format_output("paper-abc", "https://example.com", make_extracted_paper(), enriched, evals)
    assert dag.schema_version == SCHEMA_VERSION


def test_format_output_missing_evaluation_uses_medium_color():
    enriched, _ = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None},
        ]
    )
    dag = format_output("paper-abc", "https://example.com", make_extracted_paper(), enriched, {})
    assert dag.dag.nodes[0].visual.color == _support_color("medium")


def test_format_output_root_border_wider():
    enriched, evals = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None},
            {"id": "c1.1", "type": "primary", "parent_id": "c1"},
        ]
    )
    dag = format_output("paper-abc", "https://example.com", make_extracted_paper(), enriched, evals)
    root_node = next(n for n in dag.dag.nodes if n.id == "c1")
    child_node = next(n for n in dag.dag.nodes if n.id == "c1.1")
    assert root_node.visual.border_width > child_node.visual.border_width


def test_format_output_edge_ids_unique():
    enriched, evals = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None},
            {"id": "c1.1", "type": "primary", "parent_id": "c1"},
            {"id": "c1.2", "type": "primary", "parent_id": "c1"},
        ]
    )
    dag = format_output("paper-abc", "https://example.com", make_extracted_paper(), enriched, evals)
    edge_ids = [e.id for e in dag.dag.edges]
    assert len(edge_ids) == len(set(edge_ids))


# ── write_outputs ──────────────────────────────────────────────────────────────


def _make_simple_dag():
    enriched, evals = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None, "text": "Root claim."},
        ]
    )
    return format_output(
        "paper-test-abc", "https://example.com", make_extracted_paper(), enriched, evals
    )


def test_write_outputs_creates_dag_json(tmp_path: Path):
    dag = _make_simple_dag()
    paper_dir = tmp_path / "paper-test-abc"
    write_outputs(dag, paper_dir, tmp_path)
    assert (paper_dir / "dag.json").exists()


def test_write_outputs_dag_json_is_valid_json(tmp_path: Path):
    dag = _make_simple_dag()
    paper_dir = tmp_path / "paper-test-abc"
    write_outputs(dag, paper_dir, tmp_path)
    data = json.loads((paper_dir / "dag.json").read_text())
    assert "schema_version" in data
    assert data["schema_version"] == SCHEMA_VERSION


def test_write_outputs_creates_index_json(tmp_path: Path):
    dag = _make_simple_dag()
    write_outputs(dag, tmp_path / "paper-test-abc", tmp_path)
    assert (tmp_path / "index.json").exists()


def test_write_outputs_index_contains_paper(tmp_path: Path):
    dag = _make_simple_dag()
    write_outputs(dag, tmp_path / "paper-test-abc", tmp_path)
    index = json.loads((tmp_path / "index.json").read_text())
    ids = [p["paper_id"] for p in index["papers"]]
    assert "paper-test-abc" in ids


# ── _upsert_index ──────────────────────────────────────────────────────────────


def test_upsert_creates_new_index(tmp_path: Path):
    dag = _make_simple_dag()
    index_path = tmp_path / "index.json"
    _upsert_index(index_path, dag)
    assert index_path.exists()
    data = json.loads(index_path.read_text())
    assert len(data["papers"]) == 1


def test_upsert_deduplicates_same_paper(tmp_path: Path):
    dag = _make_simple_dag()
    index_path = tmp_path / "index.json"
    _upsert_index(index_path, dag)
    _upsert_index(index_path, dag)  # second upsert same paper
    data = json.loads(index_path.read_text())
    assert len(data["papers"]) == 1


def test_upsert_appends_different_papers(tmp_path: Path):
    enriched1, evals1 = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None},
        ]
    )
    dag1 = format_output(
        "paper-aaa", "https://a.com", make_extracted_paper(title="Paper A"), enriched1, evals1
    )
    enriched2, evals2 = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None},
        ]
    )
    dag2 = format_output(
        "paper-bbb", "https://b.com", make_extracted_paper(title="Paper B"), enriched2, evals2
    )

    index_path = tmp_path / "index.json"
    _upsert_index(index_path, dag1)
    _upsert_index(index_path, dag2)
    data = json.loads(index_path.read_text())
    assert len(data["papers"]) == 2


def test_upsert_truncates_long_abstract(tmp_path: Path):
    long_abstract = "X" * 500
    enriched, evals = _make_pipeline_outputs(
        [
            {"id": "c1", "type": "root", "parent_id": None},
        ]
    )
    dag = format_output(
        "paper-long",
        "https://example.com",
        make_extracted_paper(abstract=long_abstract),
        enriched,
        evals,
    )
    index_path = tmp_path / "index.json"
    _upsert_index(index_path, dag)
    data = json.loads(index_path.read_text())
    abstract_short = data["papers"][0]["abstract_short"]
    assert len(abstract_short) <= 251  # 250 chars + "…"
    assert abstract_short.endswith("…")


def test_upsert_handles_corrupt_index(tmp_path: Path):
    index_path = tmp_path / "index.json"
    index_path.write_text('{"invalid": "old schema", "mean_validity_score": 0.7}')
    dag = _make_simple_dag()
    # Should not raise; should create a fresh index
    _upsert_index(index_path, dag)
    data = json.loads(index_path.read_text())
    assert len(data["papers"]) == 1
