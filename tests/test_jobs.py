"""Tests for the disk-persisted job store (src/jobs.py)."""

import json

import pytest

from src.jobs import JobStore, default_jobs_dir


@pytest.fixture
def store(tmp_path):
    return JobStore(jobs_dir=tmp_path)


# ── create ─────────────────────────────────────────────────────────────────────


def test_create_returns_queued_job(store: JobStore):
    job = store.create("https://arxiv.org/abs/1706.03762")
    assert job["status"] == "queued"
    assert job["source"] == "https://arxiv.org/abs/1706.03762"
    assert len(job["job_id"]) == 8
    assert job["paper_id"] is None
    assert job["error"] is None


def test_create_persists_to_disk(store: JobStore, tmp_path):
    job = store.create("some-source")
    path = tmp_path / f"{job['job_id']}.json"
    assert path.exists()
    assert json.loads(path.read_text())["source"] == "some-source"


# ── load / update ──────────────────────────────────────────────────────────────


def test_load_round_trip(store: JobStore):
    job = store.create("x")
    loaded = store.load(job["job_id"])
    assert loaded == job


def test_load_unknown_returns_none(store: JobStore):
    assert store.load("nope1234") is None


def test_update_merges_fields(store: JobStore):
    job = store.create("x")
    updated = store.update(job["job_id"], status="running", step="[2/7] …")
    assert updated["status"] == "running"
    assert updated["step"] == "[2/7] …"
    # persisted
    assert store.load(job["job_id"])["status"] == "running"


def test_update_unknown_raises(store: JobStore):
    with pytest.raises(KeyError):
        store.update("nope1234", status="done")


# ── stale job handling ─────────────────────────────────────────────────────────


def test_mark_stale_running_jobs(store: JobStore):
    running = store.create("a")
    store.update(running["job_id"], status="running")
    queued = store.create("b")
    done = store.create("c")
    store.update(done["job_id"], status="done")

    marked = store.mark_stale_running_jobs()

    assert marked == 2
    assert store.load(running["job_id"])["status"] == "error"
    assert store.load(queued["job_id"])["status"] == "error"
    assert store.load(done["job_id"])["status"] == "done"


def test_mark_stale_skips_corrupt_files(store: JobStore, tmp_path):
    (tmp_path / "corrupt.json").write_text("{not json")
    assert store.mark_stale_running_jobs() == 0


# ── default dir resolution ─────────────────────────────────────────────────────


def test_default_jobs_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER2TREE_JOBS_DIR", str(tmp_path / "custom"))
    assert default_jobs_dir() == tmp_path / "custom"


def test_default_jobs_dir_global(monkeypatch):
    monkeypatch.delenv("PAPER2TREE_JOBS_DIR", raising=False)
    assert default_jobs_dir().parts[-2:] == (".paper2tree", "jobs")
