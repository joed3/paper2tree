"""Disk-persisted job store for asynchronous paper reviews.

Each job is a single JSON file at <jobs_dir>/<job_id>.json so state survives
process restarts. Used by the MCP server (src/mcp_server.py); the FastAPI
server keeps its own in-memory store.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def default_jobs_dir() -> Path:
    """Resolve the jobs directory (PAPER2TREE_JOBS_DIR overrides the default)."""
    env = os.environ.get("PAPER2TREE_JOBS_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".paper2tree" / "jobs"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """CRUD for job JSON files. All methods are synchronous and atomic per call."""

    def __init__(self, jobs_dir: Path | None = None):
        self.jobs_dir = jobs_dir or default_jobs_dir()
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def create(self, source: str) -> dict:
        """Create a new queued job for the given source (URL or file path)."""
        job = {
            "job_id": uuid.uuid4().hex[:8],
            "status": "queued",
            "step": "Queued…",
            "source": source,
            "paper_id": None,
            "title": None,
            "html_path": None,
            "dag_path": None,
            "summary": None,
            "final_review": None,
            "error": None,
            "started_at": _now(),
            "completed_at": None,
        }
        self._write(job)
        return job

    def load(self, job_id: str) -> dict | None:
        """Return the job dict, or None if unknown."""
        path = self._path(job_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def update(self, job_id: str, **fields) -> dict:
        """Merge fields into the job and persist. Raises KeyError if unknown."""
        job = self.load(job_id)
        if job is None:
            raise KeyError(f"Unknown job_id: {job_id}")
        job.update(fields)
        self._write(job)
        return job

    def mark_stale_running_jobs(self) -> int:
        """Fail any job left in queued/running state by a previous process.

        Called at server startup so agents polling an orphaned job get a
        terminal status instead of waiting forever. Returns the count marked.
        """
        count = 0
        for path in self.jobs_dir.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if job.get("status") in ("queued", "running"):
                job["status"] = "error"
                job["error"] = "Server restarted while job was in progress. Resubmit the paper."
                job["completed_at"] = _now()
                path.write_text(json.dumps(job, indent=2), encoding="utf-8")
                count += 1
        return count

    def _write(self, job: dict) -> None:
        self._path(job["job_id"]).write_text(json.dumps(job, indent=2), encoding="utf-8")
