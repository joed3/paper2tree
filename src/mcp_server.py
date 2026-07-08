"""MCP server — exposes the paper review pipeline to coding agents.

Any MCP-compatible agent (Claude Code, Codex, …) can submit a paper URL or
local file with `review_paper`, then poll `check_review_status` until the
interactive HTML review is ready.

Run directly:
    paper2tree-mcp

Register with Claude Code:
    claude mcp add paper2tree -- paper2tree-mcp
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .export_html import ensure_export_html
from .jobs import JobStore
from .orchestrator import get_outputs_dir, process_paper, process_paper_from_file

mcp = FastMCP("paper2tree")
store = JobStore()

# Keep references so tasks aren't garbage-collected mid-run
_running_tasks: dict[str, asyncio.Task] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run_job(job_id: str, source: str, live_search: bool, force: bool) -> None:
    """Background pipeline run; all state lands in the job file."""
    store.update(job_id, status="running", step="Starting pipeline …")

    def log(msg: str) -> None:
        stripped = msg.strip()
        if stripped:
            store.update(job_id, step=stripped)

    try:
        if source.startswith(("http://", "https://")):
            paper_id = await process_paper(source, force=force, live_search=live_search, log=log)
        else:
            file_path = Path(source).expanduser()
            paper_id = await process_paper_from_file(
                file_path, file_path.name, force=force, live_search=live_search, log=log
            )

        outputs_dir = get_outputs_dir()
        dag_path = outputs_dir / paper_id / "dag.json"
        data = json.loads(dag_path.read_text(encoding="utf-8"))

        # Covers cached papers processed before auto-export existed
        html_path = ensure_export_html(paper_id, outputs_dir)

        summary = data.get("summary", {})
        store.update(
            job_id,
            status="done",
            step="Complete",
            paper_id=paper_id,
            title=data.get("paper", {}).get("title"),
            html_path=str(html_path),
            dag_path=str(dag_path),
            summary={
                "total_claims": summary.get("total_nodes"),
                "high_support": summary.get("high_support_nodes"),
                "low_support": summary.get("low_support_nodes"),
                "max_depth": summary.get("max_depth"),
                "overall_assessment": summary.get("overall_assessment"),
            },
            final_review=data.get("final_review"),
            completed_at=_now(),
        )
    except Exception as exc:
        store.update(job_id, status="error", error=str(exc), completed_at=_now())
    finally:
        _running_tasks.pop(job_id, None)


@mcp.tool()
async def review_paper(source: str, live_search: bool = False, force: bool = False) -> dict:
    """Submit a scientific paper for a full claim-level review.

    Downloads/parses the paper, extracts its hierarchical claim structure as a
    DAG, evaluates every claim, writes a final prose review, and saves a
    self-contained interactive HTML viewer on the local machine.

    Returns immediately with a job_id — the pipeline takes 2–10 minutes.
    Poll check_review_status(job_id) every 30–60 seconds until the status is
    "done" or "error".

    Args:
        source: Paper URL (arXiv, bioRxiv, DOI, direct PDF link) or an
            absolute path to a local PDF/HTML file.
        live_search: Also search PubMed and Semantic Scholar for prior
            literature to ground the evaluation (adds ~30–90 s).
        force: Reprocess even if this paper was already reviewed.
    """
    if not source.startswith(("http://", "https://")):
        path = Path(source).expanduser()
        if not path.is_file():
            return {
                "error": f"source is neither a URL nor an existing file: {source}. "
                "Pass an http(s) URL or an absolute path to a local PDF/HTML file."
            }

    job = store.create(source)
    job_id = job["job_id"]
    task = asyncio.create_task(_run_job(job_id, source, live_search, force))
    _running_tasks[job_id] = task
    return {
        "job_id": job_id,
        "status": "queued",
        "message": (
            f"Review started for {source}. Poll check_review_status('{job_id}') "
            "every 30–60 seconds; typical runs take 2–10 minutes."
        ),
    }


@mcp.tool()
async def check_review_status(job_id: str) -> dict:
    """Check the progress of a paper review started with review_paper.

    While status is "queued" or "running", the step field shows the current
    pipeline stage. When status is "done", html_path points to the interactive
    HTML review (open it in a browser), and summary/final_review contain the
    assessment. When status is "error", the error field explains the failure.

    Args:
        job_id: The id returned by review_paper.
    """
    job = store.load(job_id)
    if job is None:
        return {"error": f"Unknown job_id: {job_id}"}
    return job


def main() -> None:
    store.mark_stale_running_jobs()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
