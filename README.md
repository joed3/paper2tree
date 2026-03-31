# paper2tree

A multi-agent AI system that turns a scientific paper into an interactive, evaluable claim tree. Give it a URL — it downloads the paper, extracts the argument structure as a directed acyclic graph (DAG), evaluates each claim for strength and support, and presents everything in a shareable interactive viewer.

---

## How it works

Seven agents run in sequence:

```
URL or PDF
 │
 ▼  Paper Fetcher      Downloads PDF or HTML; handles arXiv, DOIs, open-access pages
 │
 ▼  Text Extractor     Parses raw text; structures title, abstract, and sections
 │
 ▼  Claim Extractor    Identifies the hierarchical claim structure using adaptive thinking
 │
 ▼  DAG Builder        Validates the graph, computes depths, detects cycles
 │
 ▼  Claim Evaluator    Assesses validity, strengths, and weaknesses per claim
 │
 ▼  Output Formatter   Assembles dag.json and updates the paper index
 │
 ▼  outputs/<paper_id>/dag.json
```

Each paper's results live in their own folder under `outputs/`. A central `outputs/index.json` tracks all processed papers so the frontend can display a browsable library.

---

## Requirements & Installation

**Python backend:**

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- The [Claude Code CLI](https://claude.ai/code) installed and authenticated (used by the Paper Fetcher agent)

```bash
git clone https://github.com/yourname/paper2tree
cd paper2tree

pip install -e .

cp .env.example .env
# Edit .env and add: ANTHROPIC_API_KEY=sk-ant-...
```

**Frontend** (only needed to browse results or submit papers from the UI):

- Node.js 18+

```bash
cd frontend
npm install
```

---

## Paper2Tree in Action

<!-- Replace this block with a screen recording or GIF of the UI -->
> 🎬 **Demo video** — add a screen recording here showing the DAG viewer in action.
> Tip: drag an `.mp4` into the GitHub editor to embed it automatically.

The frontend gives you a fully interactive claim tree for every processed paper:

- **Moveable canvas** — pan, zoom, and drag nodes freely; supporting/evidence nodes collapse by default to keep the view clean
- **Expand subtrees** — click `+N` on any node to reveal its children; a minimap always shows the full tree
- **Node detail panel** — click any node to see the full claim, verbatim quote, evaluator assessment (strengths, weaknesses, alternative interpretations), and cited prior literature when live search was used
- **Export** — download a self-contained HTML file (~135 KB gzip) you can share with anyone; the full interactive viewer works offline with no server required

**Start the frontend:**

```bash
# Terminal 1 — API server
uvicorn src.server:app --reload --port 8000

# Terminal 2 — frontend dev server
cd frontend && npm run dev
```

Then open [http://localhost:5173](http://localhost:5173). Click **+** in the sidebar to paste a URL or upload a PDF. Progress updates in real time; the paper loads automatically when the pipeline completes.

---

## Processing papers from the CLI

For scripting or server-less use, the CLI processes papers directly without the frontend.

**Single paper:**
```bash
python -m src.main process https://arxiv.org/abs/1706.03762
```

**Local PDF:**
```bash
python -m src.main process /path/to/paper.pdf
```

**Example output:**
```
[1/6] Fetching paper from https://arxiv.org/abs/1706.03762 …
      Downloaded: pdf → paper.pdf
[2/6] Extracting and structuring text …
      Title: 'Attention Is All You Need'
      Word count: 8,421
[3/6] Extracting claim structure …
      Found 14 claims
[4/6] Building and validating DAG …
      14 nodes, max depth 3
[5/6] Evaluating 14 claims …
      Evaluated 14 claims
[6/6] Writing output …

✓ Done — paper_id: attention-is-all-you-need-a7468c68
  Output: outputs/attention-is-all-you-need-a7468c68/dag.json
  Claims: 14 nodes, high support: 9/14
```

Results are saved to `outputs/<paper_id>/dag.json`. Re-running the same URL is a no-op unless you pass `--force`.

---

<details>
<summary><strong>Advanced CLI options</strong> — batch processing, live literature search, listing and inspecting papers</summary>

### Live literature search

Pass `--live-search` to enrich evaluations with prior-literature context retrieved at runtime from PubMed and Semantic Scholar. For each claim, Claude Haiku generates targeted search queries; the retriever fetches results, deduplicates by title, and ranks by lexical overlap. The evaluator cites retrieved papers inline in its strengths, weaknesses, and interpretations.

```bash
python -m src.main process https://arxiv.org/abs/1706.03762 --live-search
```

No additional API key is required. Optionally set `NCBI_EMAIL` in `.env` to identify your requests to NCBI (recommended for high-volume use). Live search adds roughly 30–90 seconds depending on claim count and network latency.

### Batch processing

Create a text file with one URL per line (`#` lines are comments):

```
# Foundational transformer papers
https://arxiv.org/abs/1706.03762
https://arxiv.org/abs/1810.04805
https://arxiv.org/abs/2005.14165
```

```bash
python -m src.main batch papers.txt

# Process up to 3 papers concurrently
python -m src.main batch papers.txt --concurrency 3

# Reprocess all, even previously cached ones
python -m src.main batch papers.txt --force
```

### List processed papers

```bash
python -m src.main list

# Sort options: date (default), title, score
python -m src.main list --sort-by score
```

```
           Processed Papers (3 total)
 ┌─────────────────────────────────────────────┬──────────────────┬────────┬───────┬────────────┐
 │ Title                                       │ Authors          │ Claims │ High  │ Date       │
 ├─────────────────────────────────────────────┼──────────────────┼────────┼───────┼────────────┤
 │ Attention Is All You Need                   │ Vaswani, Shazeer │     14 │   9   │ 2026-03-19 │
 │ BERT: Pre-training of Deep Bidirectional... │ Devlin, Chang    │     11 │   8   │ 2026-03-19 │
 │ Language Models are Few-Shot Learners       │ Brown, Mann      │     16 │  10   │ 2026-03-18 │
 └─────────────────────────────────────────────┴──────────────────┴────────┴───────┴────────────┘
```

### Inspect a paper

```bash
python -m src.main show attention-is-all-you-need-a7468c68
```

Prints the abstract, summary statistics, and a tree of all claims with their support levels.

### Force reprocess

```bash
python -m src.main process https://arxiv.org/abs/1706.03762 --force
```

</details>

<details>
<summary><strong>Output format</strong> — dag.json schema reference</summary>

Each processed paper produces a folder:

```
outputs/
├── index.json                                   # global paper index
└── attention-is-all-you-need-a7468c68/
    ├── dag.json                                  # full DAG result
    └── raw/
        ├── paper.pdf                             # downloaded file
        └── manifest.json                         # fetcher metadata
```

`dag.json` follows a node-link format compatible with React Flow, D3.js, and Cytoscape.js:

```json
{
  "schema_version": 1,
  "paper": {
    "paper_id": "attention-is-all-you-need-a7468c68",
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "url": "https://arxiv.org/abs/1706.03762",
    "abstract": "...",
    "word_count": 8421,
    "processed_at": "2026-03-19T14:32:00Z"
  },
  "dag": {
    "nodes": [
      {
        "id": "c1",
        "label": "Transformers achieve state-of-the-art on seq2seq tasks…",
        "claim": "The Transformer architecture, relying solely on attention...",
        "type": "root",
        "depth": 0,
        "section_source": "Abstract",
        "verbatim_quote": "The Transformer, a model architecture eschewing recurrence...",
        "evaluation": {
          "support_level": "high",
          "strengths": ["Comprehensive benchmarks on WMT 2014", "..."],
          "weaknesses": ["Limited to translation at time of writing", "..."],
          "supporting_evidence_quality": "strong",
          "notes": "..."
        },
        "visual": { "color": "#22c55e", "size": 48, "border_width": 3 }
      }
    ],
    "edges": [
      { "id": "e_c1_c1.1", "source": "c1", "target": "c1.1", "relationship": "supports" }
    ]
  },
  "summary": {
    "total_nodes": 14,
    "total_edges": 13,
    "max_depth": 3,
    "high_support_nodes": 9,
    "low_support_nodes": 1,
    "overall_assessment": "The paper presents 14 claims with strong overall support..."
  }
}
```

**Visual encoding:**

| Support level | Node color |
|---|---|
| `high` | Green `#22c55e` |
| `medium` | Yellow `#eab308` |
| `low` | Red `#ef4444` |

Node size decreases with depth: root (48px) → primary (36px) → supporting (24px) → evidence (20px). Edge style: solid gray for `supports`/`requires`, dashed yellow for `qualifies`, dashed red for `contradicts`.

</details>

<details>
<summary><strong>Frontend details</strong> — component overview, static PNG export</summary>

### Component overview

| Area | Description |
|---|---|
| **Left sidebar** | Searchable list of all processed papers and in-progress jobs. Shows support badge and claim count per paper; pulsing indicator and step text for running jobs. |
| **DAG canvas** | Interactive React Flow graph with dagre left-to-right layout. Scroll to pan, Ctrl+scroll or pinch to zoom, drag individual nodes. Supporting/evidence nodes collapsed by default; click `+N` on any node to expand its subtree. |
| **Full-graph inset** | Portrait minimap (top-left corner) always showing the complete claim tree. Collapsed nodes appear dimmed. |
| **Top bar** | Title, authors, source link, summary stats, and **Export** button. |
| **Node detail panel** | Full claim text, verbatim quote, section source, and complete evaluation — support level, strengths, weaknesses, alternative interpretations, required assumptions, evaluator notes, and cited prior literature. |
| **Assessment banner** | Pipeline's overall assessment shown at the bottom of the canvas. |

### HTML export

Click **Export** in the top bar to download a self-contained HTML file (~420 KB, ~135 KB gzip) that embeds the full interactive viewer and paper data. Recipients need no server, no account, and no Node.js — just a browser.

To rebuild the export viewer template after changing frontend components:

```bash
cd frontend && npm run build:export
```

### Static PNG (no frontend required)

```bash
pip install -e ".[viz]"
python visualize.py outputs/<paper_id>/dag.json
```

The PNG is saved as `visualization.png` alongside the `dag.json`.

</details>

<details>
<summary><strong>Project structure</strong></summary>

```
paper2tree/
├── src/
│   ├── agents/
│   │   ├── paper_fetcher.py     # Claude Agent SDK — downloads paper via WebFetch + Bash
│   │   ├── text_extractor.py    # pdfplumber/BeautifulSoup + Claude (structures raw text)
│   │   ├── claim_extractor.py   # Claude with adaptive thinking → ClaimGraph JSON
│   │   ├── dag_builder.py       # Pure Python — validates DAG, computes depths
│   │   ├── claim_evaluator.py   # Async Claude — evaluates all claims in one call
│   │   └── output_formatter.py  # Pure Python — assembles dag.json + index.json
│   ├── schemas/                 # Pydantic models for inter-agent data contracts
│   │   ├── paper.py             # FetchResult, ExtractedPaper
│   │   ├── claim.py             # Claim, ClaimGraph
│   │   ├── evaluation.py        # ClaimEvaluation, LiteratureCitation
│   │   ├── output.py            # DAGNode, DAGEdge, PaperDAG
│   │   └── index.py             # PaperIndexEntry, PaperIndex
│   ├── kb/                      # Knowledge-base retrieval (live literature search)
│   │   ├── schemas.py           # RetrievedPassage Pydantic model
│   │   └── live_retriever.py    # LiveRetriever: PubMed + Semantic Scholar, Haiku queries
│   ├── prompts/                 # Prompt templates (.txt, loaded via string.Template)
│   ├── utils/
│   │   ├── paper_id.py          # make_paper_id(title, url) → "slug-urlhash"
│   │   └── graph.py             # BFS DAG builder, cycle detection, subtree utilities
│   ├── export_html.py           # Self-contained HTML export generator
│   ├── orchestrator.py          # Async pipeline coordinator
│   ├── server.py                # FastAPI server (job submission, status, export)
│   └── main.py                  # CLI (click + rich)
├── frontend/                    # React visualization app (Node.js 18+)
│   ├── src/
│   │   ├── App.tsx              # Root layout (sidebar + DAG canvas + node panel)
│   │   ├── ExportApp.tsx        # Stripped-down viewer for HTML export
│   │   ├── components/          # DAGViewer, ClaimNode, NodeCard, PaperBrowser, …
│   │   ├── hooks/               # usePaperIndex, usePaper, useJobs
│   │   ├── api/                 # papers.ts, jobs.ts
│   │   └── types/dag.ts         # TypeScript types mirroring the JSON schema
│   ├── dist-export/export.html  # Pre-built self-contained viewer template
│   ├── vite.export.config.ts    # Singlefile build config for HTML export
│   └── package.json
├── migrations/                  # Schema migration scripts (v0→v1, …)
├── outputs/                     # Generated results (gitignored)
├── visualize.py                 # Static PNG generator (matplotlib + networkx)
├── pyproject.toml
├── CHANGELOG.md
└── .env.example
```

</details>

<details>
<summary><strong>Development</strong> — linting, pre-commit hooks, schema migrations</summary>

### Linting and formatting

```bash
# Python — check and auto-fix
ruff check src/ --fix
ruff format src/

# Frontend — check
cd frontend && npm run lint
```

### Pre-commit hooks

```bash
pip install -e ".[dev]"
pre-commit install
```

On every `git commit` the hooks run `ruff` (Python) and `eslint` (TypeScript/TSX) on staged files, strip trailing whitespace, and ensure files end with a newline.

```bash
# Run manually against the entire repo
pre-commit run --all-files
```

### Schema migrations

When `dag.json` changes in a breaking way (major version bump), a migration script is added to `migrations/`. See `migrations/README.md` for conventions.

```bash
# Upgrade all outputs/ artifacts from schema v0 to v1
python migrations/migrate_v0_to_v1.py
```

</details>

<details>
<summary><strong>Design notes</strong></summary>

- **Adaptive thinking and structured output are mutually exclusive** in the current Claude API. The Claim Extractor uses adaptive thinking (for reasoning quality) and parses the JSON response manually with Pydantic retry logic. Other agents use `messages.stream()` with manual Pydantic parsing plus an explicit `stop_reason == "max_tokens"` guard to catch truncated responses before attempting a parse.

- **Per-paper folders with a flat index** keep individual results self-contained. `index.json` is a lightweight catalog (title, score, path) loaded eagerly by the frontend; full DAG data is fetched lazily per paper.

- **Idempotent by default.** Re-running `process` on the same URL is a no-op unless `--force` is passed. The `batch` command is safe to re-run after partial failures.

- **Intermediate artifacts** (downloaded PDF, extracted text manifest) are preserved in `outputs/<paper_id>/raw/`. This allows individual pipeline stages to be re-run in isolation without re-downloading.

- **HTML export is build-time, not runtime.** The viewer template is built once with `vite-plugin-singlefile` and committed to `frontend/dist-export/`. The server injects paper data via a string replace — no Node.js required at runtime.

</details>
