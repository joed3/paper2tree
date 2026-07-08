"""Tests for the MCP server tools (src/mcp_server.py).

Pipeline execution is mocked; these tests cover input routing, the job
lifecycle, and result assembly from dag.json.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import src.mcp_server as mcp_server
from src.jobs import JobStore

FAKE_DAG = {
    "paper": {"title": "Test Paper", "authors": ["A"], "abstract": "x"},
    "summary": {
        "total_nodes": 5,
        "high_support_nodes": 3,
        "low_support_nodes": 1,
        "max_depth": 2,
        "overall_assessment": "Mixed support.",
    },
    "final_review": "A fine paper.",
    "dag": {"nodes": [], "edges": []},
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = JobStore(jobs_dir=tmp_path / "jobs")
    monkeypatch.setattr(mcp_server, "store", s)
    return s


@pytest.fixture
def outputs_dir(tmp_path, monkeypatch):
    out = tmp_path / "outputs"
    out.mkdir()
    monkeypatch.setenv("PAPER2TREE_OUTPUT_DIR", str(out))
    return out


def _write_fake_paper(outputs_dir: Path, paper_id: str) -> None:
    paper_dir = outputs_dir / paper_id
    paper_dir.mkdir(parents=True)
    (paper_dir / "dag.json").write_text(json.dumps(FAKE_DAG))
    (outputs_dir / f"{paper_id}.html").write_text("<html>fake</html>")


# ── review_paper input routing ─────────────────────────────────────────────────


def test_review_paper_rejects_bad_source(store: JobStore):
    result = asyncio.run(mcp_server.review_paper("not-a-url-or-file"))
    assert "error" in result
    assert "job_id" not in result


def test_review_paper_url_returns_job_id(store: JobStore):
    with patch.object(mcp_server, "_run_job", new_callable=AsyncMock):
        result = asyncio.run(mcp_server.review_paper("https://arxiv.org/abs/1706.03762"))
    assert result["status"] == "queued"
    assert len(result["job_id"]) == 8
    assert store.load(result["job_id"]) is not None


def test_review_paper_accepts_existing_file(store: JobStore, tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with patch.object(mcp_server, "_run_job", new_callable=AsyncMock):
        result = asyncio.run(mcp_server.review_paper(str(pdf)))
    assert result["status"] == "queued"


# ── _run_job lifecycle ─────────────────────────────────────────────────────────


def test_run_job_success_populates_result(store: JobStore, outputs_dir):
    _write_fake_paper(outputs_dir, "test-paper-12345678")
    job = store.create("https://example.com/paper")

    with patch.object(
        mcp_server, "process_paper", new_callable=AsyncMock, return_value="test-paper-12345678"
    ):
        asyncio.run(mcp_server._run_job(job["job_id"], "https://example.com/paper", False, False))

    done = store.load(job["job_id"])
    assert done["status"] == "done"
    assert done["paper_id"] == "test-paper-12345678"
    assert done["title"] == "Test Paper"
    assert done["html_path"].endswith("test-paper-12345678.html")
    assert done["summary"]["total_claims"] == 5
    assert done["summary"]["high_support"] == 3
    assert done["final_review"] == "A fine paper."
    assert done["completed_at"] is not None


def test_run_job_routes_file_source(store: JobStore, outputs_dir, tmp_path):
    _write_fake_paper(outputs_dir, "file-paper-12345678")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    job = store.create(str(pdf))

    with patch.object(
        mcp_server,
        "process_paper_from_file",
        new_callable=AsyncMock,
        return_value="file-paper-12345678",
    ) as mock_file:
        asyncio.run(mcp_server._run_job(job["job_id"], str(pdf), False, False))

    mock_file.assert_awaited_once()
    assert store.load(job["job_id"])["status"] == "done"


def test_run_job_failure_sets_error(store: JobStore, outputs_dir):
    job = store.create("https://example.com/paper")

    with patch.object(
        mcp_server, "process_paper", new_callable=AsyncMock, side_effect=RuntimeError("boom")
    ):
        asyncio.run(mcp_server._run_job(job["job_id"], "https://example.com/paper", False, False))

    failed = store.load(job["job_id"])
    assert failed["status"] == "error"
    assert "boom" in failed["error"]
    assert failed["completed_at"] is not None


# ── check_review_status ────────────────────────────────────────────────────────


def test_check_status_unknown_job(store: JobStore):
    result = asyncio.run(mcp_server.check_review_status("nope1234"))
    assert "error" in result


def test_check_status_returns_job_state(store: JobStore):
    job = store.create("x")
    store.update(job["job_id"], status="running", step="[3/7] Extracting …")
    result = asyncio.run(mcp_server.check_review_status(job["job_id"]))
    assert result["status"] == "running"
    assert result["step"] == "[3/7] Extracting …"
