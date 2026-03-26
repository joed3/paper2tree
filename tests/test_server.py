"""Tests for the FastAPI server routes.

Pipeline execution is mocked; these tests cover HTTP contract only
(status codes, response shapes, job lifecycle).
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.server import app, jobs


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_jobs():
    """Isolate each test with a clean job store."""
    jobs.clear()
    yield
    jobs.clear()


# ── POST /api/process ──────────────────────────────────────────────────────────


def test_process_url_returns_202(client: TestClient):
    with patch("src.server._run_url_job", new_callable=AsyncMock):
        resp = client.post("/api/process", json={"url": "https://arxiv.org/abs/1706.03762"})
    assert resp.status_code == 202


def test_process_url_returns_job_id(client: TestClient):
    with patch("src.server._run_url_job", new_callable=AsyncMock):
        resp = client.post("/api/process", json={"url": "https://arxiv.org/abs/1706.03762"})
    data = resp.json()
    assert "job_id" in data
    assert isinstance(data["job_id"], str)
    assert len(data["job_id"]) == 8


def test_process_url_job_stored(client: TestClient):
    with patch("src.server._run_url_job", new_callable=AsyncMock):
        resp = client.post("/api/process", json={"url": "https://arxiv.org/abs/1706.03762"})
    job_id = resp.json()["job_id"]
    assert job_id in jobs


def test_process_url_invalid_body_returns_422(client: TestClient):
    resp = client.post("/api/process", json={"not_url": "oops"})
    assert resp.status_code == 422


# ── GET /api/jobs ──────────────────────────────────────────────────────────────


def test_list_jobs_empty(client: TestClient):
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_jobs_returns_submitted_jobs(client: TestClient):
    with patch("src.server._run_url_job", new_callable=AsyncMock):
        client.post("/api/process", json={"url": "https://arxiv.org/abs/1706.03762"})
        client.post("/api/process", json={"url": "https://arxiv.org/abs/1810.04805"})
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_jobs_newest_first(client: TestClient):
    with patch("src.server._run_url_job", new_callable=AsyncMock):
        resp1 = client.post("/api/process", json={"url": "https://arxiv.org/abs/1706.03762"})
        resp2 = client.post("/api/process", json={"url": "https://arxiv.org/abs/1810.04805"})
    job_id_1 = resp1.json()["job_id"]
    job_id_2 = resp2.json()["job_id"]

    listed = client.get("/api/jobs").json()
    listed_ids = [j["job_id"] for j in listed]
    # Both IDs present
    assert job_id_1 in listed_ids
    assert job_id_2 in listed_ids


# ── GET /api/jobs/{job_id} ─────────────────────────────────────────────────────


def test_get_job_found(client: TestClient):
    with patch("src.server._run_url_job", new_callable=AsyncMock):
        post_resp = client.post("/api/process", json={"url": "https://arxiv.org/abs/1706.03762"})
    job_id = post_resp.json()["job_id"]

    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["status"] in ("queued", "running", "done", "error")
    assert "source" in data
    assert "created_at" in data


def test_get_job_not_found_returns_404(client: TestClient):
    resp = client.get("/api/jobs/doesnotexist")
    assert resp.status_code == 404


def test_job_initial_status_is_queued_or_running(client: TestClient):
    with patch("src.server._run_url_job", new_callable=AsyncMock):
        post_resp = client.post("/api/process", json={"url": "https://arxiv.org/abs/1706.03762"})
    job_id = post_resp.json()["job_id"]
    job = jobs[job_id]
    assert job["status"] in ("queued", "running")


# ── POST /api/upload ───────────────────────────────────────────────────────────


def test_upload_pdf_returns_202(client: TestClient):
    pdf_bytes = b"%PDF-1.4 fake content"
    with patch("src.server._run_file_job", new_callable=AsyncMock):
        resp = client.post(
            "/api/upload",
            files={"file": ("paper.pdf", pdf_bytes, "application/pdf")},
        )
    assert resp.status_code == 202


def test_upload_returns_job_id(client: TestClient):
    with patch("src.server._run_file_job", new_callable=AsyncMock):
        resp = client.post(
            "/api/upload",
            files={"file": ("paper.pdf", b"content", "application/pdf")},
        )
    assert "job_id" in resp.json()


def test_upload_job_uses_filename_as_source(client: TestClient):
    with patch("src.server._run_file_job", new_callable=AsyncMock):
        resp = client.post(
            "/api/upload",
            files={"file": ("my_paper.pdf", b"content", "application/pdf")},
        )
    job_id = resp.json()["job_id"]
    assert jobs[job_id]["source"] == "my_paper.pdf"
