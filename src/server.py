"""FastAPI server — exposes the paper processing pipeline over HTTP.

Run from the project root:
    uvicorn src.server:app --reload --port 8000

Or via the installed script:
    paper2tree-server
"""

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# The web app writes and serves papers from the project-local outputs/ directory
# (unless the user explicitly points PAPER2TREE_OUTPUT_DIR elsewhere).
PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)
os.environ.setdefault("PAPER2TREE_OUTPUT_DIR", str(PROJECT_ROOT / "outputs"))

from .orchestrator import get_outputs_dir, process_paper, process_paper_from_file  # noqa: E402

OUTPUTS_DIR = get_outputs_dir()
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

app = FastAPI(title="paper2tree API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory job store ────────────────────────────────────────────────────────

jobs: dict[str, dict] = {}


def _new_job(source: str) -> dict:
    return {
        "job_id": uuid.uuid4().hex[:8],
        "status": "queued",
        "source": source,
        "step": "Queued…",
        "paper_id": None,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_logger(job_id: str):
    """Returns a log function that updates the job's step field."""

    def log(msg: str) -> None:
        jobs[job_id]["step"] = msg.strip()
        print(msg)

    return log


# ── Background task runners ────────────────────────────────────────────────────


async def _run_url_job(job_id: str, url: str, force: bool, live_search: bool) -> None:
    jobs[job_id]["status"] = "running"
    log = _make_logger(job_id)
    try:
        paper_id = await process_paper(url, force=force, live_search=live_search, log=log)
        jobs[job_id].update({"status": "done", "paper_id": paper_id})
    except Exception as exc:
        jobs[job_id].update({"status": "error", "error": str(exc)})


async def _run_file_job(
    job_id: str, tmp_path: Path, original_name: str, force: bool, live_search: bool
) -> None:
    jobs[job_id]["status"] = "running"
    log = _make_logger(job_id)
    try:
        paper_id = await process_paper_from_file(
            tmp_path, original_name, force=force, live_search=live_search, log=log
        )
        jobs[job_id].update({"status": "done", "paper_id": paper_id})
    except Exception as exc:
        jobs[job_id].update({"status": "error", "error": str(exc)})
    finally:
        tmp_path.unlink(missing_ok=True)


# ── API routes ─────────────────────────────────────────────────────────────────


class ProcessRequest(BaseModel):
    url: str
    force: bool = False
    live_search: bool = False


@app.post("/api/process", status_code=202)
async def process_url(body: ProcessRequest, background_tasks: BackgroundTasks):
    """Submit a paper URL for processing."""
    job = _new_job(body.url)
    job_id = job["job_id"]
    jobs[job_id] = job
    background_tasks.add_task(_run_url_job, job_id, body.url, body.force, body.live_search)
    return {"job_id": job_id}


@app.post("/api/upload", status_code=202)
async def upload_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    force: bool = False,
    live_search: bool = False,
):
    """Upload a paper file (PDF or HTML) for processing."""
    original_name = file.filename or "paper.pdf"
    suffix = Path(original_name).suffix or ".pdf"

    # Save to a temp file that persists until the job finishes
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    content = await file.read()
    tmp.write(content)
    tmp.close()
    tmp_path = Path(tmp.name)

    job = _new_job(original_name)
    job_id = job["job_id"]
    jobs[job_id] = job
    background_tasks.add_task(_run_file_job, job_id, tmp_path, original_name, force, live_search)
    return {"job_id": job_id}


@app.get("/api/jobs")
async def list_jobs():
    """List all submitted jobs, newest first."""
    return sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Get status of a single job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/api/papers/{paper_id}/export")
async def export_paper(paper_id: str):
    """Return a self-contained interactive HTML export of a paper review."""
    paper_dir = OUTPUTS_DIR / paper_id
    if not paper_dir.exists():
        raise HTTPException(status_code=404, detail="Paper not found")

    result_files = sorted(paper_dir.glob("dag*.json"))
    if not result_files:
        raise HTTPException(status_code=404, detail="No result file found for this paper")

    from .export_html import _find_pdf, generate_export_html, safe_filename

    try:
        data = json.loads(result_files[0].read_text(encoding="utf-8"))
        html = generate_export_html(data, pdf_path=_find_pdf(paper_dir))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}") from exc

    filename = safe_filename(data) + ".html"
    return Response(
        content=html.encode("utf-8"),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/api/papers/{paper_id}", status_code=204)
async def delete_paper(paper_id: str):
    """Delete a processed paper and all its artifacts."""
    paper_dir = OUTPUTS_DIR / paper_id
    if not paper_dir.exists():
        raise HTTPException(status_code=404, detail="Paper not found")

    shutil.rmtree(paper_dir)

    index_path = OUTPUTS_DIR / "index.json"
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text())
            data["papers"] = [p for p in data["papers"] if p["paper_id"] != paper_id]
            index_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass  # index corruption is non-fatal — paper dir is already deleted


# ── Static file serving ────────────────────────────────────────────────────────

# Always serve the outputs directory
OUTPUTS_DIR.mkdir(exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")

# Serve the built frontend if available (production mode)
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str = ""):
        # API and /outputs are handled above; everything else gets index.html
        index = FRONTEND_DIST / "index.html"
        return FileResponse(str(index))


# ── Entry point ────────────────────────────────────────────────────────────────


def main():
    uvicorn.run("src.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
