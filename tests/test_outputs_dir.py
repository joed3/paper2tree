"""Tests for output directory resolution and the ensure_export_html helper."""

import json
from pathlib import Path

import pytest

from src.export_html import ensure_export_html
from src.orchestrator import get_outputs_dir

# ── get_outputs_dir ────────────────────────────────────────────────────────────


def test_env_var_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER2TREE_OUTPUT_DIR", str(tmp_path / "custom"))
    assert get_outputs_dir() == tmp_path / "custom"


def test_default_is_user_global(monkeypatch):
    monkeypatch.delenv("PAPER2TREE_OUTPUT_DIR", raising=False)
    assert get_outputs_dir() == Path.home() / ".paper2tree" / "outputs"


def test_env_var_expands_tilde(monkeypatch):
    monkeypatch.setenv("PAPER2TREE_OUTPUT_DIR", "~/somewhere")
    assert get_outputs_dir() == Path.home() / "somewhere"


# ── ensure_export_html ─────────────────────────────────────────────────────────
# Uses the real committed viewer template (frontend/dist-export/export.html).

FAKE_DAG = {
    "paper": {"title": "Export Test Paper", "authors": ["A"], "abstract": "x"},
    "summary": {"total_nodes": 1},
    "dag": {"nodes": [], "edges": []},
}


@pytest.fixture
def paper_outputs(tmp_path):
    paper_dir = tmp_path / "export-test-12345678"
    paper_dir.mkdir()
    (paper_dir / "dag.json").write_text(json.dumps(FAKE_DAG))
    return tmp_path


def test_generates_html_from_dag(paper_outputs):
    html_path = ensure_export_html("export-test-12345678", paper_outputs)
    assert html_path == paper_outputs / "export-test-12345678.html"
    content = html_path.read_text()
    assert "Export Test Paper" in content
    assert "window.__PAPER_DATA__ = null;" not in content


def test_existing_html_not_regenerated(paper_outputs):
    html_path = paper_outputs / "export-test-12345678.html"
    html_path.write_text("preexisting")
    result = ensure_export_html("export-test-12345678", paper_outputs)
    assert result == html_path
    assert html_path.read_text() == "preexisting"


def test_force_regenerates(paper_outputs):
    html_path = paper_outputs / "export-test-12345678.html"
    html_path.write_text("preexisting")
    ensure_export_html("export-test-12345678", paper_outputs, force=True)
    assert html_path.read_text() != "preexisting"


def test_missing_dag_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ensure_export_html("does-not-exist", tmp_path)
