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

# Install dependencies
pip install -e .

# Set your API key
cp .env.example .env
# Edit .env and add: ANTHROPIC_API_KEY=sk-ant-...
```

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
```

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
  Claims: 14 nodes, mean validity: 0.87
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
 │ Title                                       │ Authors          │ Claims │ Score │ Date       │
 ├─────────────────────────────────────────────┼──────────────────┼────────┼───────┼────────────┤
 │ Attention Is All You Need                   │ Vaswani, Shazeer │     14 │  0.87 │ 2026-03-19 │
 │ BERT: Pre-training of Deep Bidirectional... │ Devlin, Chang    │     11 │  0.84 │ 2026-03-19 │
 │ Language Models are Few-Shot Learners       │ Brown, Mann      │     16 │  0.79 │ 2026-03-18 │
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
          "validity_score": 0.91,
          "confidence_level": "high",
          "strengths": ["Comprehensive benchmarks on WMT 2014", "..."],
          "weaknesses": ["Limited to translation at time of writing", "..."],
          "supporting_evidence_quality": "strong"
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
    "mean_validity_score": 0.87,
    "high_confidence_nodes": 9,
    "low_confidence_nodes": 1,
    "overall_assessment": "The paper presents 14 claims with strong overall support..."
  }
}
```

**Visual encoding conventions** (for React front-end):

| Validity score | Node color |
|---|---|
| ≥ 0.8 | Green `#22c55e` |
| 0.5 – 0.8 | Yellow `#eab308` |
| < 0.5 | Red `#ef4444` |

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
| **Left sidebar** | Searchable list of all processed papers, sorted newest-first. Shows validity badge and claim count for each. |
| **DAG canvas** | Interactive React Flow graph with dagre hierarchical layout. Pan, zoom, drag nodes. Minimap in the bottom-right corner. |
| **Top bar** | Paper title, authors, source link, and summary stats (mean validity, claim count, max depth, high-confidence ratio). |
| **Node detail panel** | Click any node to open a 360px slide-in panel with the full claim text, verbatim quote, section source, and the complete evaluation — strengths, weaknesses, alternative interpretations, required assumptions, evaluator notes. |
| **Assessment banner** | The pipeline's overall assessment of the paper shown at the bottom of the canvas. |

**Node visual encoding:**

| Color | Validity |
|---|---|
| Green | ≥ 0.7 |
| Yellow | 0.4 – 0.7 |
| Red | < 0.4 |

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
│   │   ├── evaluation.py        # ClaimEvaluation, SubtreeEvaluation
│   │   ├── output.py            # DAGNode, DAGEdge, PaperDAG
│   │   └── index.py             # PaperIndexEntry, PaperIndex
│   ├── prompts/                 # Prompt templates (.txt, loaded via string.Template)
│   │   ├── text_extractor.txt
│   │   ├── claim_extractor.txt
│   │   └── claim_evaluator.txt
│   ├── utils/
│   │   ├── paper_id.py          # make_paper_id(title, url) → "slug-urlhash"
│   │   └── graph.py             # BFS DAG builder, cycle detection, subtree utilities
│   ├── orchestrator.py          # Async pipeline coordinator
│   └── main.py                  # CLI (click + rich)
├── frontend/                    # React visualization app (Node.js)
│   ├── src/
│   │   ├── App.tsx              # Root layout (sidebar + DAG canvas + node panel)
│   │   ├── components/
│   │   │   ├── PaperBrowser.tsx # Searchable paper list
│   │   │   ├── DAGViewer.tsx    # React Flow canvas with dagre layout
│   │   │   ├── ClaimNode.tsx    # Custom node component
│   │   │   ├── NodeCard.tsx     # Claim detail slide-in panel
│   │   │   └── EvalBadge.tsx    # Validity score badge
│   │   ├── hooks/
│   │   │   ├── usePaperIndex.ts # Loads outputs/index.json
│   │   │   └── usePaper.ts      # Lazily loads a paper's dag.json (cached)
│   │   ├── api/papers.ts        # fetch wrappers for /outputs/*
│   │   └── types/dag.ts         # TypeScript types mirroring the JSON schema
│   └── package.json
├── outputs/                     # Generated results (gitignored)
├── visualize.py                 # Static PNG generator (matplotlib + networkx)
├── pyproject.toml
└── .env.example
```

## Design notes

- **Adaptive thinking and structured output are mutually exclusive** in the current Claude API. The Claim Extractor uses adaptive thinking (for reasoning quality) and parses the JSON response manually with Pydantic retry logic. Other agents that don't need deep reasoning use `messages.parse()` with a Pydantic schema for guaranteed structure.

- **Per-paper folders with a flat index** keep individual results self-contained. The `index.json` is a lightweight catalog (title, score, path) loaded eagerly by the front-end; full DAG data is fetched lazily per paper.

- **Idempotent by default.** Re-running `process` on the same URL is a no-op unless `--force` is passed. The `batch` command is safe to re-run after partial failures.

- **Intermediate artifacts** (downloaded PDF, extracted text manifest) are preserved in `outputs/<paper_id>/raw/`. This allows individual pipeline stages to be re-run in isolation without re-downloading.
