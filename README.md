# Paper2Tree

A multi-agent system for scientific paper review. Given a paper URL, Paper2Tree downloads the paper, extracts its main text, and constructs a **directed acyclic graph (DAG)** of the paper's claims — from the root thesis down through primary arguments, supporting claims, and evidence nodes. Each claim is independently assessed for validity, strengths, and weaknesses. Results are stored as JSON and designed for interactive visualization in a React front-end.

## How it works

The pipeline runs seven agents in sequence:

```
URL
 │
 ▼ Paper Fetcher      (Claude Agent SDK)      Downloads PDF or HTML; handles arXiv, DOIs
 │
 ▼ Text Extractor     (Anthropic SDK)         Parses raw text; structures title/abstract/sections
 │
 ▼ Claim Extractor    (Anthropic SDK)         Identifies hierarchical claim structure with adaptive thinking
 │
 ▼ DAG Builder        (Pure Python)           Validates graph, computes depths, detects cycles
 │
 ▼ Claim Evaluator    (Anthropic SDK, async)  Assesses validity, strengths, weaknesses per claim
 │
 ▼ Output Formatter   (Pure Python)           Assembles JSON; updates paper index
 │
 ▼ outputs/<paper_id>/dag.json
```

Each paper's results live in their own folder under `outputs/`. A central `outputs/index.json` tracks all processed papers so the front-end can display a searchable library.

## Requirements

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- The [Claude Code CLI](https://claude.ai/code) installed and authenticated (required by the Agent SDK for the Paper Fetcher step)

## Installation

```bash
git clone https://github.com/yourname/paper2tree
cd paper2tree

# Install runtime dependencies
pip install -e .

# Set your API key
cp .env.example .env
# Edit .env and add: ANTHROPIC_API_KEY=sk-ant-...
```

**For development** (linting + pre-commit hooks):

```bash
pip install -e ".[dev]"
pre-commit install
```

This registers git hooks that run `ruff` (Python lint + format) and `eslint` (TypeScript) automatically on every commit.

The main dependencies installed are:

| Package | Purpose |
|---|---|
| `anthropic` | LLM calls for text extraction, claim extraction, evaluation |
| `claude-agent-sdk` | Agent SDK for the paper fetcher (WebFetch + Bash tools) |
| `pdfplumber` / `pymupdf` | PDF text extraction |
| `beautifulsoup4` / `markdownify` | HTML paper parsing |
| `pydantic` | Structured output schemas between agents |
| `tenacity` | Retry logic for LLM calls |
| `click` / `rich` | CLI and terminal output |

## Usage

All commands are run from the project root.

### Process a single paper

```bash
python -m src.main process <url>
```

Accepts arXiv abstract pages, direct PDF links, DOI URLs, and open-access HTML pages.

```bash
# arXiv paper (abstract page — automatically fetches the PDF)
python -m src.main process https://arxiv.org/abs/1706.03762

# Direct PDF link
python -m src.main process https://proceedings.mlr.press/v97/chen19a/chen19a.pdf

# Force reprocess a paper that was already cached
python -m src.main process https://arxiv.org/abs/1706.03762 --force

# Enable live literature search (queries PubMed + Semantic Scholar during evaluation)
python -m src.main process https://arxiv.org/abs/1706.03762 --live-search
```

#### Live literature search

Pass `--live-search` to enrich claim evaluations with prior-literature context retrieved at runtime from PubMed and Semantic Scholar. For each claim, Claude Haiku generates two targeted search queries, the retriever fetches up to five results per source, deduplicates by title, and ranks by lexical overlap with the claim text. The evaluator uses this context to populate a `literature_citations` field on each `ClaimEvaluation`.

```bash
python -m src.main process https://arxiv.org/abs/2303.08774 --live-search
```

No additional API key is required — PubMed and Semantic Scholar are queried over public APIs. Set `NCBI_EMAIL` in your `.env` to identify your requests to NCBI (recommended for high-volume use):

```
NCBI_EMAIL=you@example.com
```

The live search step adds roughly 30–90 seconds depending on the number of claims and network latency. Results are cached within a single run — repeated claims share retrieved passages.

**Example output:**

```
[1/6] Fetching paper from https://arxiv.org/abs/1706.03762 …
      Downloaded: pdf → paper.pdf
[2/6] Extracting and structuring text …
      Title: 'Attention Is All You Need'
      Authors: Ashish Vaswani, Noam Shazeer, Niki Parmar
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

### Process multiple papers

Create a text file with one URL per line (lines starting with `#` are comments):

```
# Foundational transformer papers
https://arxiv.org/abs/1706.03762
https://arxiv.org/abs/1810.04805
https://arxiv.org/abs/2005.14165

# Vision
https://arxiv.org/abs/2010.11929
```

Then run:

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
python -m src.main list --sort-by title
```

**Example output:**

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
python -m src.main show <paper_id>
```

```bash
python -m src.main show attention-is-all-you-need-a7468c68
```

Prints the paper's abstract, summary statistics, and a tree of all claims with their validity scores.

## Output format

Each processed paper produces a `dag.json` file:

```
outputs/
├── index.json                                   # global paper index
└── attention-is-all-you-need-a7468c68/
    ├── dag.json                                  # full DAG result
    └── raw/
        ├── paper.pdf                             # downloaded file
        └── manifest.json                         # fetcher metadata
```

The `dag.json` follows a node-link format compatible with React Flow, D3.js, and Cytoscape.js:

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

**Visual encoding conventions** (for React front-end):

| Support level | Node color |
|---|---|
| `high` | Green `#22c55e` |
| `medium` | Yellow `#eab308` |
| `low` | Red `#ef4444` |

Node size decreases with depth: root (48px) → primary (36px) → supporting (24px) → evidence (20px).

## Frontend

A React app that lets you browse all processed papers and explore their claim DAGs interactively.

### Starting the frontend

**Browsing existing results** (no API server needed):
```bash
cd frontend
npm install
npm run dev
```
Then open [http://localhost:5173](http://localhost:5173). The Vite dev server serves `outputs/` directly.

**Submitting new papers from the UI** also requires the API server:
```bash
# Terminal 1 — API server (from project root)
pip install -e .
uvicorn src.server:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

Click the **+** button in the sidebar (or "Add your first paper" on an empty state) to open the submission dialog. You can paste a URL or drag-and-drop / select a local PDF or HTML file. A progress indicator tracks each pipeline step in real time and the paper auto-loads in the DAG viewer once processing completes.

### What you get

| Area | Description |
|---|---|
| **Left sidebar** | Searchable list of all processed papers and in-progress jobs. Shows support badge and claim count per paper; pulsing indicator and step text for running jobs. |
| **DAG canvas** | Interactive React Flow graph with dagre left-to-right layout. Scroll to pan, Ctrl+scroll or pinch to zoom, drag individual nodes. Supporting/evidence nodes collapsed by default; click `+N` on any node to expand its subtree. |
| **Full-graph inset** | Portrait minimap (top-left corner) always showing the complete claim tree regardless of collapse state. Collapsed nodes appear dimmed. |
| **Top bar** | Paper title, authors, source link, and summary stats (support badge, claim count, max depth, high-support ratio). |
| **Node detail panel** | Click any node to open a slide-in panel with the full claim text, verbatim quote, section source, and the complete evaluation — support level, strengths, weaknesses, alternative interpretations, required assumptions, evaluator notes, and (when `--live-search` was used) cited prior literature with relevance notes. |
| **Assessment banner** | The pipeline's overall assessment of the paper shown at the bottom of the canvas. |

**Node visual encoding:**

| Color | Support level |
|---|---|
| Green | `high` |
| Yellow | `medium` |
| Red | `low` |

Node size decreases with depth (root → primary → supporting → evidence). Edge style indicates relationship: solid gray for `supports`/`requires`, dashed yellow for `qualifies`, dashed red for `contradicts`.

### Frontend requirements

- Node.js 18+

The frontend dependencies (`react`, `reactflow`, `dagre`, `tailwindcss`) are installed via `npm install` and are separate from the Python environment.

### Generating a static visualization

If you just want a quick PNG without running the frontend:

```bash
# Install visualization dependencies (one-time)
pip install -e ".[viz]"

# Generate PNG for the first paper in outputs/
python visualize.py

# Generate PNG for a specific paper
python visualize.py outputs/<paper_id>/dag.json

# Custom output path
python visualize.py outputs/<paper_id>/dag.json my_graph.png
```

The PNG is saved alongside the `dag.json` as `visualization.png`.

## Project structure

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
│   │   ├── evaluation.py        # ClaimEvaluation (support_level: high/medium/low), LiteratureCitation
│   │   ├── output.py            # DAGNode, DAGEdge, PaperDAG (schema_version)
│   │   └── index.py             # PaperIndexEntry, PaperIndex
│   ├── kb/                      # Knowledge-base retrieval (live literature search)
│   │   ├── schemas.py           # RetrievedPassage Pydantic model
│   │   └── live_retriever.py    # LiveRetriever: PubMed + Semantic Scholar, Haiku queries, LRU cache
│   ├── prompts/                 # Prompt templates (.txt, loaded via string.Template)
│   │   ├── text_extractor.txt
│   │   ├── claim_extractor.txt
│   │   └── claim_evaluator.txt
│   ├── utils/
│   │   ├── paper_id.py          # make_paper_id(title, url) → "slug-urlhash"
│   │   └── graph.py             # BFS DAG builder, cycle detection, subtree utilities
│   ├── orchestrator.py          # Async pipeline coordinator
│   ├── server.py                # FastAPI server (job submission + status polling)
│   └── main.py                  # CLI (click + rich)
├── frontend/                    # React visualization app (Node.js)
│   ├── src/
│   │   ├── App.tsx              # Root layout (sidebar + DAG canvas + node panel)
│   │   ├── components/
│   │   │   ├── PaperBrowser.tsx # Paper list + in-progress job entries
│   │   │   ├── DAGViewer.tsx    # React Flow canvas (LR dagre, collapse/expand, inset)
│   │   │   ├── ClaimNode.tsx    # Custom node component with expand toggle
│   │   │   ├── ExpandContext.ts # React context for collapse/expand state
│   │   │   ├── NodeCard.tsx     # Claim detail slide-in panel
│   │   │   ├── EvalBadge.tsx    # Support level badge (high/medium/low)
│   │   │   ├── AddPaperDialog.tsx  # URL/file submission dialog
│   │   │   └── JobProgressView.tsx # Pipeline step progress for in-flight jobs
│   │   ├── hooks/
│   │   │   ├── usePaperIndex.ts # Loads outputs/index.json
│   │   │   ├── usePaper.ts      # Lazily loads a paper's dag.json (cached)
│   │   │   └── useJobs.ts       # Job polling + localStorage persistence
│   │   ├── api/
│   │   │   ├── papers.ts        # fetch wrappers for /outputs/*
│   │   │   └── jobs.ts          # fetch wrappers for /api/jobs
│   │   └── types/dag.ts         # TypeScript types mirroring the JSON schema
│   ├── eslint.config.js         # ESLint 9 flat config (typescript-eslint + react-hooks)
│   └── package.json
├── migrations/                  # Schema migration scripts
│   ├── migrate_v0_to_v1.py      # validity_score → support_level (schema_version 0→1)
│   └── README.md
├── outputs/                     # Generated results (gitignored)
├── visualize.py                 # Static PNG generator (matplotlib + networkx)
├── pyproject.toml               # Source of truth for version + ruff config
├── .pre-commit-config.yaml      # ruff (Python) + ESLint (TypeScript) hooks
├── CHANGELOG.md
└── .env.example
```

## Development

### Linting and formatting

Python is linted and formatted with [ruff](https://docs.astral.sh/ruff/). TypeScript/React uses [ESLint 9](https://eslint.org/) with `typescript-eslint` and `eslint-plugin-react-hooks`.

```bash
# Python — check and auto-fix
ruff check src/ --fix
ruff format src/

# Frontend — check
cd frontend && npm run lint
```

### Pre-commit hooks

Install once after cloning:

```bash
pip install -e ".[dev]"
pre-commit install
```

On every `git commit`, the hooks will:

1. Strip trailing whitespace and ensure files end with a newline
2. Run `ruff check --fix` and `ruff format` on staged Python files
3. Run `eslint src` on staged TypeScript/TSX files

To run all hooks against the entire repo manually:

```bash
pre-commit run --all-files
```

### Schema migrations

When the `dag.json` output schema changes in a breaking way (major version bump), a migration script is added to `migrations/`. See `migrations/README.md` for the conventions and history.

```bash
# Upgrade all outputs/ artifacts from schema v0 to v1
python migrations/migrate_v0_to_v1.py
```

## Design notes

- **Adaptive thinking and structured output are mutually exclusive** in the current Claude API. The Claim Extractor uses adaptive thinking (for reasoning quality) and parses the JSON response manually with Pydantic retry logic. Other agents that don't need deep reasoning use `messages.parse()` with a Pydantic schema for guaranteed structure.

- **Per-paper folders with a flat index** keep individual results self-contained. The `index.json` is a lightweight catalog (title, score, path) loaded eagerly by the front-end; full DAG data is fetched lazily per paper.

- **Idempotent by default.** Re-running `process` on the same URL is a no-op unless `--force` is passed. The `batch` command is safe to re-run after partial failures.

- **Intermediate artifacts** (downloaded PDF, extracted text manifest) are preserved in `outputs/<paper_id>/raw/`. This allows individual pipeline stages to be re-run in isolation without re-downloading.
