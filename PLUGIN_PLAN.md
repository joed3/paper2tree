# paper2tree Agent Plugin — Implementation Plan

## Goal

Wrap the existing paper2tree pipeline in a **Model Context Protocol (MCP) server** so that any MCP-compatible coding agent — including Claude Code and OpenAI Codex — can review a scientific paper by pointing to a URL or local file. The agent submits a job, polls until complete, and an interactive HTML review is saved locally for the user to open.

---

## Architecture Overview

```
User: "Review this paper: https://arxiv.org/abs/1706.03762"
         │
         ▼
Coding agent (Claude Code / Codex / etc.)
         │
         │  1. review_paper(input="https://...")  → { job_id: "a1b2c3" }
         │  2. check_review_status("a1b2c3")      → { status: "running", step: "[3/7] …" }
         │  3. check_review_status("a1b2c3")      → { status: "running", step: "[6/7] …" }
         │  4. check_review_status("a1b2c3")      → { status: "done", html_path: "…" }
         ▼
paper2tree MCP Server  (src/mcp_server.py)
         │  background asyncio task writing job state to disk
         ▼
src/orchestrator.py → fetch → extract → claims → DAG → evaluate → review → HTML
         │
         ▼  saves to ~/.paper2tree/outputs/
~/.paper2tree/outputs/<paper-id>/dag.json
~/.paper2tree/outputs/<paper-id>.html   ← new: auto-generated HTML export
         │
~/.paper2tree/jobs/<job-id>.json        ← job state, persisted across MCP restarts
         │
         ▼
Agent: "Done — open ~/.paper2tree/outputs/attention-is-all-you-need.html"
```

---

## Design Decisions (confirmed)

| Question | Decision |
|---|---|
| Output directory | User-global `~/.paper2tree/outputs/` always; `PAPER2TREE_OUTPUT_DIR` env var overrides |
| Blocking vs. async | Non-blocking: `review_paper` returns a `job_id` immediately; agent polls with `check_review_status` |
| Batch support | Deferred to v2 — one paper at a time for now |
| Auto-open browser | No — too disruptive in headless/CI contexts |

## Plan Review Adjustments (pre-implementation)

Reviewing the plan against the code surfaced four changes:

1. **Keep `process_paper`'s return type stable** (`paper_id`, not a tuple). The HTML path is
   deterministic — `get_outputs_dir()/<paper_id>.html` — so callers derive it. A new
   `ensure_export_html(paper_id, outputs_dir)` helper in `src/export_html.py` generates the file
   if missing; the pipeline calls it at the end, and the MCP server calls it again on completion
   to backfill HTML for papers cached before this feature existed (the early-return path skips
   the pipeline tail).
2. **`src/server.py` pins `PAPER2TREE_OUTPUT_DIR` to `PROJECT_ROOT/outputs` at startup**
   (via `os.environ.setdefault`). Otherwise the web app would write to the global dir while
   serving static files from the project dir. Web-app behavior is unchanged; CLI and MCP use
   the global default.
3. **CLI gains local-file routing.** The README already documents
   `python -m src.main process /path/to/paper.pdf`, but `process` only handles URLs today.
   The URL-vs-file routing needed for the MCP tool is added to the CLI too.
4. **Job store lives in its own module** (`src/jobs.py`) instead of inline in the MCP server —
   independently testable, and the server file stays thin. Tool input parameter is named
   `source` (not `input`, which shadows a Python builtin and matches the server's job field).

---

## Components to Build / Modify

### 1. Configurable Output Directory
**File:** `src/orchestrator.py`

Currently `OUTPUTS_DIR = Path("outputs")` is relative to the process CWD — broken when called from any directory.

Changes:
- Replace the bare constant with `get_outputs_dir() -> Path`:
  1. If `PAPER2TREE_OUTPUT_DIR` env var is set, use that.
  2. Otherwise `~/.paper2tree/outputs/`.
- All internal callers (`process_paper`, `process_paper_from_file`, `write_outputs`) call `get_outputs_dir()` instead of the bare `OUTPUTS_DIR`.
- The FastAPI server (`src/server.py`) and CLI (`src/main.py`) keep working unchanged because they already import from the orchestrator.

### 2. Auto-generate HTML Export in the Pipeline
**Files:** `src/orchestrator.py`, `src/export_html.py`

Currently HTML is generated on-demand via the server endpoint. For agent use, write it automatically at the end of every run.

Changes to `_run_pipeline()`:
- After `write_outputs()`, call `generate_export_html()` and write `<paper_id>.html` into `outputs_dir/` (sibling of the `<paper_id>/` folder, easy to locate).
- Return `(paper_id, html_path: Path | None)` tuple instead of just `paper_id`.
- If the export template (`frontend/dist-export/export.html`) is missing, log a warning and set `html_path = None` — do not fail the run.
- CLI (`src/main.py`) prints the HTML path when present. Add `--no-html` flag to suppress generation if desired.

### 3. Disk-Persisted Job State
**Directory:** `~/.paper2tree/jobs/`

Each job is a JSON file at `~/.paper2tree/jobs/<job_id>.json`. This survives MCP server process restarts.

Schema:
```json
{
  "job_id": "a1b2c3d4",
  "status": "queued | running | done | error",
  "step": "[3/7] Extracting claim structure … Found 28 claims",
  "input": "https://arxiv.org/abs/1706.03762",
  "paper_id": null,
  "title": null,
  "html_path": null,
  "dag_path": null,
  "summary": null,
  "final_review": null,
  "error": null,
  "started_at": "2024-01-01T00:00:00Z",
  "completed_at": null
}
```

`summary` is populated on completion:
```json
{
  "total_claims": 28,
  "high_support": 21,
  "low_support": 3,
  "max_depth": 4,
  "overall_assessment": "The paper presents 28 claims with strong overall support…"
}
```

Stale detection: on server startup, any job still in `"running"` status is reset to `"error"` with `error = "Server restarted while job was in progress"`. This prevents the agent from polling forever on an orphaned job.

### 4. MCP Server
**New file:** `src/mcp_server.py`

Uses the `mcp` Python SDK, stdio transport — the standard for Claude Code and Codex integrations.

#### Tool 1: `review_paper`

Starts the pipeline in a background asyncio task and returns immediately.

```
Input:
  input        string   (required) Paper URL (arXiv, bioRxiv, DOI, direct PDF)
                        or absolute path to a local PDF/HTML file
  live_search  bool     (optional, default false) search PubMed + Semantic Scholar
  force        bool     (optional, default false) reprocess if already cached

Output (immediate):
  job_id   string   — pass to check_review_status to poll progress
  status   string   — always "queued" on success
  message  string   — human-readable confirmation
```

Input routing:
- Starts with `http://` or `https://` → `process_paper(url, ...)`
- Path to an existing local file → `process_paper_from_file(path, ...)`
- Anything else → error with a clear message

#### Tool 2: `check_review_status`

Reads the job file and returns current state. The agent should call this every 30–60 seconds until `status` is `"done"` or `"error"`.

```
Input:
  job_id   string   (required)

Output:
  job_id        string
  status        string   queued | running | done | error
  step          string   latest pipeline step message
  paper_id      string?  set when done
  title         string?  set when done
  html_path     string?  absolute path to open in browser; set when done
  dag_path      string?  absolute path to dag.json; set when done
  summary       object?  set when done
  final_review  string?  set when done
  error         string?  set on error
  started_at    string
  completed_at  string?
```

#### Server structure
```python
jobs_dir = Path.home() / ".paper2tree" / "jobs"
running_tasks: dict[str, asyncio.Task] = {}

@mcp.tool()
async def review_paper(input: str, live_search: bool = False, force: bool = False) -> dict: ...

@mcp.tool()
async def check_review_status(job_id: str) -> dict: ...

def main():
    mcp.run(transport="stdio")
```

### 5. Package Entry Point
**File:** `pyproject.toml`

```toml
[project.scripts]
paper2tree-mcp = "src.mcp_server:main"   # add alongside existing entries

[project.dependencies]
# add:
mcp>=1.0
```

---

## File-by-File Change Summary

| File | Type | Change |
|---|---|---|
| `src/orchestrator.py` | Modify | `get_outputs_dir()` helper; auto HTML export in `_run_pipeline()`; return `(paper_id, html_path)` |
| `src/main.py` | Modify | Print HTML path; `--no-html` flag |
| `src/mcp_server.py` | **New** | MCP server with `review_paper` + `check_review_status` tools |
| `pyproject.toml` | Modify | `mcp>=1.0` dependency; `paper2tree-mcp` script entry point |

No changes to frontend, agents, schemas, or prompts.

---

## Installation & Agent Registration

### Prerequisites
```bash
pip install -e ".[dev]"   # or: pip install paper2tree
```
Set `ANTHROPIC_API_KEY` in the environment (same key the pipeline already uses).

### Claude Code
```bash
claude mcp add paper2tree -- paper2tree-mcp
```

Or manually in `.claude/settings.json` or `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "paper2tree": {
      "command": "paper2tree-mcp"
    }
  }
}
```

### OpenAI Codex / other MCP-compatible agents
```json
{
  "mcpServers": {
    "paper2tree": {
      "command": "paper2tree-mcp"
    }
  }
}
```

The stdio transport is the universal default — any agent supporting MCP can use this configuration.

---

## Example Agent Interaction

```
User: "Critically review this paper: https://arxiv.org/abs/2303.08774"

Agent: I'll submit this paper for analysis.
[calls review_paper(input="https://arxiv.org/abs/2303.08774")]
→ { job_id: "f3a9b1c2", status: "queued" }

Agent: Job started (ID: f3a9b1c2). Checking progress…
[calls check_review_status("f3a9b1c2")]   # ~30s later
→ { status: "running", step: "[2/7] Extracting and structuring text … Title: 'Sparks of AGI…'" }

[calls check_review_status("f3a9b1c2")]   # ~90s later
→ { status: "running", step: "[5/7] Evaluating 31 claims …" }

[calls check_review_status("f3a9b1c2")]   # ~3 min later
→ {
    status: "done",
    title: "Sparks of Artificial General Intelligence…",
    html_path: "/Users/you/.paper2tree/outputs/sparks-of-artificial-ge-f7c291a3.html",
    summary: { total_claims: 31, high_support: 22, low_support: 3, max_depth: 3 },
    final_review: "This paper presents a comprehensive empirical study…"
  }

Agent: Review complete! Open the interactive claim graph here:
  ~/.paper2tree/outputs/sparks-of-artificial-ge-f7c291a3.html

Summary: 31 claims analyzed — 22 high support, 3 low support, max depth 3.

[pastes final_review]
```

---

## Implementation Order

1. **Output dir refactor** (`src/orchestrator.py`) — everything downstream depends on this.
2. **Auto HTML export** (`src/orchestrator.py`, `src/export_html.py`) — every run now produces the file the agent reports back.
3. **Job state module** (part of `src/mcp_server.py`) — disk-persisted job files in `~/.paper2tree/jobs/`.
4. **MCP server tools** (`src/mcp_server.py`) — wire `review_paper` and `check_review_status` to the orchestrator.
5. **Entry point + deps** (`pyproject.toml`) — `mcp>=1.0`, `paper2tree-mcp` script.
6. **Smoke test** — register locally with Claude Code, submit one arXiv URL, poll to completion, verify HTML opens.
