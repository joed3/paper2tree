# Paper2Tree: Multi-Agent Scientific Paper Review System

## Overview

Paper2Tree is a multi-agent pipeline that ingests a scientific paper from a URL, extracts its main text, and constructs a hierarchical directed acyclic graph (DAG) of the paper's claims. Each node in the DAG is independently assessed for validity, strengths, and weaknesses. The final output is a JSON structure designed for interactive visualization in a React front-end.

The system is designed to process papers **incrementally over time**: each paper's results are stored in its own folder under `outputs/`, and a central index file (`outputs/index.json`) tracks all processed papers. The React frontend reads from this index to populate a searchable paper browser, allowing the user to switch between any previously processed paper.

The system is implemented in **Python** using the **Claude Agent SDK** (`claude-agent-sdk`) for orchestration and the **Anthropic Python SDK** (`anthropic`) for direct LLM calls within specialized agents. The primary model throughout is `claude-opus-4-6` with adaptive thinking enabled (`thinking: {type: "adaptive"}`).

---

## System Architecture

```
                         ┌─────────────────────┐
          URL ──────────▶│  Orchestrator Agent │
                         │  (Agent SDK)        │
                         └────────┬────────────┘
                                  │ spawns sub-agents via Agent tool
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
           ┌────────────┐ ┌────────────┐ ┌────────────────┐
           │   Paper    │ │   Text     │ │    Claim       │
           │  Fetcher   │ │ Extractor  │ │   Extractor    │
           │   Agent    │ │   Agent    │ │     Agent      │
           └────────────┘ └────────────┘ └────────────────┘
                                                  │
                                                  ▼
                                         ┌────────────────┐
                                         │  DAG Builder   │
                                         │     Agent      │
                                         └───────┬────────┘
                                                 │ spawns one evaluator per root/primary claim
                              ┌──────────────────┼──────────────────┐
                              ▼                  ▼                  ▼
                    ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
                    │   Claim      │   │   Claim      │   │   Claim      │
                    │  Evaluator   │   │  Evaluator   │   │  Evaluator   │
                    │  Agent (1)   │   │  Agent (2)   │   │  Agent (N)   │
                    └──────────────┘   └──────────────┘   └──────────────┘
                                                 │
                                                 ▼
                                        ┌────────────────┐
                                        │    Output      │
                                        │   Formatter    │
                                        │    Agent       │
                                        └───────┬────────┘
                                                │
                                                ▼
                                          DAG JSON file
                                      (React-compatible)
```

---

## Agents

### 1. Orchestrator Agent

**Role:** Top-level coordinator. Drives the pipeline end-to-end, passes intermediate results between sub-agents, and handles retries and failures.

**Implementation:** Built with the **Claude Agent SDK** using `ClaudeSDKClient` (for fine-grained lifecycle control) or `query()` (for simpler invocations). Uses the built-in `Agent` tool to spawn sub-agents, `WebFetch` to delegate downloads, and `Bash` to invoke processing scripts.

**Responsibilities:**
- Accept a paper URL as input
- Derive a deterministic `paper_id` from the URL (see Paper ID Strategy below)
- Check `outputs/index.json` to skip already-processed papers (unless `--force` flag is set)
- Spawn and sequence the Paper Fetcher → Text Extractor → Claim Extractor → DAG Builder → Claim Evaluators → Output Formatter pipeline
- Aggregate results from parallel Claim Evaluator agents
- Write results to `outputs/<paper_id>/dag.json`
- Update `outputs/index.json` with the new paper's metadata entry

**Key Options:**
```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

options = ClaudeAgentOptions(
    allowed_tools=["Agent", "WebFetch", "Bash", "Read", "Write"],
    model="claude-opus-4-6",
    max_turns=50,
    system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
    agents={
        "paper-fetcher": ...,
        "text-extractor": ...,
        "claim-extractor": ...,
        "dag-builder": ...,
        "claim-evaluator": ...,
        "output-formatter": ...,
    }
)
```

---

### 2. Paper Fetcher Agent

**Role:** Downloads the paper content from the given URL. Handles multiple source types: direct PDF links, HTML landing pages, arXiv abstract/PDF URLs, DOI redirects, and PubMed links.

**Implementation:** Agent SDK sub-agent with `WebFetch` and `Bash` tools. For PDF files, saves raw bytes to a temp file. For HTML pages (e.g., journal landing pages), extracts the PDF download link or falls back to page HTML.

**Tools:** `WebFetch`, `Bash`, `Write`

**Sub-agent definition:**
```python
AgentDefinition(
    description="Downloads a scientific paper from a URL. Handles PDFs, HTML, arXiv, DOIs.",
    prompt=PAPER_FETCHER_PROMPT,
    tools=["WebFetch", "Bash", "Write"]
)
```

**Outputs:**
- `raw_content_path`: path to downloaded PDF or HTML file
- `content_type`: `"pdf"` | `"html"` | `"text"`
- `source_url`: resolved final URL after redirects
- `detected_format`: detected MIME type

**Special cases handled:**
- `arxiv.org/abs/XXXX` → fetch `arxiv.org/pdf/XXXX`
- DOI redirects via `doi.org`
- HTML-only pages (open-access HTML renderings)
- Paywalled pages (return partial content with a warning)

---

### 3. Text Extractor Agent

**Role:** Extracts clean, structured main text from raw downloaded content. Removes boilerplate (headers, footers, reference lists, acknowledgements), preserves section structure, and returns the core scientific content.

**Implementation:** Agent SDK sub-agent. Uses `Bash` to run Python PDF parsing libraries (`pdfplumber` or `pymupdf`) for PDF files, or `BeautifulSoup` for HTML. For complex PDFs, also uses an Anthropic API call (direct `anthropic` SDK) to clean up OCR artifacts or reconstruct garbled text.

**Tools:** `Bash`, `Read`, `Write`

**Sub-agent definition:**
```python
AgentDefinition(
    description="Extracts clean text from a downloaded paper (PDF or HTML).",
    prompt=TEXT_EXTRACTOR_PROMPT,
    tools=["Bash", "Read", "Write"]
)
```

**Outputs (structured JSON):**
```json
{
  "title": "...",
  "authors": ["..."],
  "abstract": "...",
  "sections": [
    {"heading": "Introduction", "text": "..."},
    {"heading": "Methods", "text": "..."},
    ...
  ],
  "full_text": "...",
  "word_count": 8420
}
```

**Libraries used (installed via Bash/pip):**
- `pdfplumber` — PDF text extraction with layout awareness
- `pymupdf` (`fitz`) — fallback for complex PDFs
- `beautifulsoup4` + `lxml` — HTML parsing
- `markdownify` — HTML → Markdown conversion for cleaner LLM input

---

### 4. Claim Extractor Agent

**Role:** Reads the extracted paper text and identifies the hierarchical claim structure. Determines the single root claim (thesis), primary supporting claims, and sub-claims. Also identifies the logical dependencies between claims.

**Implementation:** Direct **Anthropic SDK** call (not a Claude Code agent, since no file/web tools are needed). Uses `claude-opus-4-6` with adaptive thinking and **structured outputs** (Pydantic schema) to guarantee a well-formed claim graph.

```python
import anthropic
from pydantic import BaseModel

class Claim(BaseModel):
    id: str                      # e.g. "c1", "c1.1", "c1.2.3"
    text: str                    # the claim as a concise statement
    type: str                    # "root" | "primary" | "supporting" | "evidence"
    parent_id: str | None        # None for root
    section_source: str          # which paper section this comes from
    verbatim_quote: str          # short supporting quote from the paper

class ClaimGraph(BaseModel):
    claims: list[Claim]
    edges: list[tuple[str, str]] # (parent_id, child_id) directed edges

client = anthropic.Anthropic()
response = client.messages.parse(
    model="claude-opus-4-6",
    max_tokens=8192,
    thinking={"type": "adaptive"},
    output_config={"format": ...},  # derived from ClaimGraph
    messages=[{"role": "user", "content": CLAIM_EXTRACTION_PROMPT + paper_text}],
    output_format=ClaimGraph,
)
claim_graph = response.parsed_output
```

**Prompt strategy:**
1. First pass: identify the root claim (main thesis/contribution)
2. Second pass: identify 3–7 primary claims that directly support the root
3. Third pass: for each primary claim, identify supporting sub-claims and evidence nodes
4. Validate DAG structure (no cycles, all nodes reachable from root)

**Outputs:** `ClaimGraph` Pydantic object serialized to JSON

---

### 5. DAG Builder Agent

**Role:** Takes the raw `ClaimGraph` from the Claim Extractor and constructs a validated, enriched DAG. Resolves ambiguities, deduplicates near-identical claims, assigns depth levels, and ensures the graph is a proper DAG (no cycles).

**Implementation:** Direct Anthropic SDK call with structured outputs. After LLM enrichment, runs a pure-Python topological sort to validate DAG structure and assign depth/level metadata to each node.

**Responsibilities:**
- Merge near-duplicate claims (using embedding similarity or LLM judgment)
- Assign claim types: `root` | `primary` | `supporting` | `evidence`
- Assign node depth (root = 0)
- Validate: every node is reachable from root; no cycles exist
- Label edge relationship types: `"supports"` | `"requires"` | `"contradicts"` | `"qualifies"`
- Flag nodes whose claims are implicit/inferred vs. explicitly stated

**Outputs:** Enriched `DAGGraph` structure (see Output Format section)

---

### 6. Claim Evaluator Agents (parallel)

**Role:** Independently assess each claim node for scientific validity, logical soundness, empirical support, strengths, and weaknesses. One evaluator agent is spawned per **root or primary** claim; supporting/evidence nodes are evaluated in batch by each evaluator.

**Implementation:** Parallel direct Anthropic SDK calls. The Orchestrator spawns N evaluators concurrently using `asyncio.gather`. Each evaluator receives:
- The full paper text (for context)
- Its assigned claim subtree (the primary claim + all its descendants)

**Concurrency pattern:**
```python
import asyncio
import anthropic

async_client = anthropic.AsyncAnthropic()

async def evaluate_claim_subtree(claim_node, paper_text):
    response = await async_client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{
            "role": "user",
            "content": EVALUATOR_PROMPT.format(
                claim=claim_node.text,
                subtree=...,
                paper_text=paper_text
            )
        }],
        output_config={"format": ClaimEvaluation.model_json_schema()}
    )
    return response

evaluations = await asyncio.gather(*[
    evaluate_claim_subtree(node, paper_text)
    for node in primary_claim_nodes
])
```

**Per-node evaluation schema:**
```python
class ClaimEvaluation(BaseModel):
    node_id: str
    validity_score: float          # 0.0 – 1.0
    confidence_level: str          # "high" | "medium" | "low"
    is_well_supported: bool
    strengths: list[str]           # what the paper does well for this claim
    weaknesses: list[str]          # gaps, limitations, unsupported assertions
    alternative_interpretations: list[str]
    required_assumptions: list[str]
    supporting_evidence_quality: str  # "strong" | "moderate" | "weak" | "absent"
    notes: str                     # free-form evaluator commentary
```

---

### 7. Output Formatter Agent

**Role:** Merges the evaluated DAG into the final React-compatible JSON format. Computes summary statistics, assigns visual metadata (colors by validity score, node sizes by depth), writes the per-paper output file, and updates the global paper index.

**Implementation:** Lightweight Python function (no LLM call needed). Optionally a thin Agent SDK agent if summary text generation is desired.

**Outputs:**
- `outputs/<paper_id>/dag.json` — full DAG result for this paper (see format below)
- `outputs/index.json` — updated with this paper's index entry (upserted, not overwritten)

---

## JSON Output Format (React-Compatible)

The final output follows a node-link graph format consumable by React libraries such as **React Flow**, **D3.js force-directed**, or **Cytoscape.js**. Each paper is stored as `outputs/<paper_id>/dag.json`.

```json
{
  "paper": {
    "paper_id": "attention-is-all-you-need-a1b2c3d4",
    "title": "Attention Is All You Need",
    "authors": ["Vaswani et al."],
    "url": "https://arxiv.org/abs/1706.03762",
    "abstract": "...",
    "word_count": 8420,
    "processed_at": "2026-03-19T14:32:00Z"
  },
  "dag": {
    "nodes": [
      {
        "id": "c1",
        "label": "Transformers outperform RNNs on seq2seq tasks",
        "claim": "The Transformer architecture, based solely on attention mechanisms, achieves state-of-the-art results on machine translation tasks while requiring significantly less training time than recurrent or convolutional models.",
        "type": "root",
        "depth": 0,
        "section_source": "Abstract",
        "verbatim_quote": "The Transformer, a model architecture eschewing recurrence...",
        "is_explicit": true,
        "evaluation": {
          "validity_score": 0.91,
          "confidence_level": "high",
          "is_well_supported": true,
          "strengths": [
            "Comprehensive benchmarks on WMT 2014 EN-DE and EN-FR",
            "BLEU scores exceed all prior models"
          ],
          "weaknesses": [
            "Limited to translation tasks at time of publication",
            "Quadratic attention complexity not addressed"
          ],
          "alternative_interpretations": [
            "Gains may be partly attributable to larger model capacity, not architecture"
          ],
          "required_assumptions": [
            "Parallel computation is available at training time"
          ],
          "supporting_evidence_quality": "strong",
          "notes": "Well-executed empirical study with strong reproducibility."
        },
        "visual": {
          "color": "#22c55e",
          "size": 48,
          "border_width": 3
        }
      }
    ],
    "edges": [
      {
        "id": "e1",
        "source": "c1",
        "target": "c1.1",
        "relationship": "requires",
        "label": "requires"
      }
    ]
  },
  "summary": {
    "total_nodes": 14,
    "total_edges": 13,
    "max_depth": 3,
    "mean_validity_score": 0.78,
    "high_confidence_nodes": 6,
    "low_confidence_nodes": 2,
    "overall_assessment": "The paper presents a well-supported central claim with strong empirical evidence. Key weaknesses are the limited task scope and scalability concerns that became apparent in later literature."
  }
}
```

**Visual encoding conventions (for React):**
| Field | Encoding |
|---|---|
| `validity_score` ≥ 0.8 | Green (`#22c55e`) |
| `validity_score` 0.5–0.8 | Yellow (`#eab308`) |
| `validity_score` < 0.5 | Red (`#ef4444`) |
| Node `depth` 0 (root) | Largest size (48px) |
| Node `depth` 1 (primary) | Medium size (32px) |
| Node `depth` 2+ (supporting/evidence) | Small size (20px) |
| Edge `relationship: "contradicts"` | Dashed red line |
| Edge `relationship: "supports"` | Solid line |

---

## Paper Index (`outputs/index.json`)

A single index file tracks all processed papers. The frontend loads this on startup to populate the paper browser. The Output Formatter upserts into it after each successful run.

```json
{
  "version": 1,
  "papers": [
    {
      "paper_id": "attention-is-all-you-need-a1b2c3d4",
      "title": "Attention Is All You Need",
      "authors": ["Vaswani et al."],
      "url": "https://arxiv.org/abs/1706.03762",
      "abstract_short": "We propose a new simple network architecture, the Transformer...",
      "processed_at": "2026-03-19T14:32:00Z",
      "mean_validity_score": 0.78,
      "total_claims": 14,
      "result_path": "attention-is-all-you-need-a1b2c3d4/dag.json"
    },
    {
      "paper_id": "bert-pre-training-deep-b9f1e2a3",
      "title": "BERT: Pre-training of Deep Bidirectional Transformers",
      "authors": ["Devlin et al."],
      "url": "https://arxiv.org/abs/1810.04805",
      "abstract_short": "We introduce BERT, which stands for Bidirectional Encoder...",
      "processed_at": "2026-03-20T09:15:00Z",
      "mean_validity_score": 0.84,
      "total_claims": 11,
      "result_path": "bert-pre-training-deep-b9f1e2a3/dag.json"
    }
  ]
}
```

The frontend fetches `index.json` once on load, then lazily fetches a specific paper's `dag.json` only when the user selects it.

---

## Paper ID Strategy

Each paper needs a stable, filesystem-safe, human-readable identifier. The `paper_id` is generated by the Orchestrator before processing begins:

```python
import re
import hashlib

def make_paper_id(title: str, url: str) -> str:
    # Slugify title: lowercase, keep alphanumeric and spaces, replace spaces with hyphens
    slug = re.sub(r"[^a-z0-9\s]", "", title.lower())
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = slug[:50].rstrip("-")           # max 50 chars, no trailing hyphen
    # Append 8-char hash of the URL for uniqueness
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
    return f"{slug}-{url_hash}"

# e.g. "attention-is-all-you-need-a1b2c3d4"
```

Special cases:
- If `title` is not yet known (before text extraction), use a hash of the URL as a temporary ID, then rename the folder once the title is extracted
- arXiv papers also store the arXiv ID (e.g. `1706.03762`) in the paper metadata for reference

---

## Technology Stack

### Python Dependencies

```
# Core AI
anthropic>=0.40.0          # Anthropic Python SDK (direct LLM calls)
claude-agent-sdk>=0.1.0    # Claude Agent SDK (orchestration)
pydantic>=2.0              # Structured output schemas

# Paper ingestion
httpx>=0.27               # Async HTTP for downloads
pdfplumber>=0.11          # PDF text extraction
pymupdf>=1.24             # Fallback PDF extraction (fitz)
beautifulsoup4>=4.12       # HTML parsing
lxml>=5.0                  # HTML parser backend
markdownify>=0.13          # HTML → Markdown

# Utilities
anyio>=4.0                 # Async runtime for Agent SDK
tenacity>=8.0              # Retry logic for API calls
python-dotenv>=1.0         # API key management
```

### Frontend Visualization (React)

Recommended libraries for consuming the JSON output:
- **React Flow** (`reactflow`) — purpose-built for node-link graphs with interactive pan/zoom
- **D3.js** — for custom force-directed or hierarchical tree layouts
- **Cytoscape.js** (`react-cytoscapejs`) — powerful graph analysis and styling

**Paper browser libraries:**
- **cmdk** — command-palette style search (fast fuzzy search over paper titles/authors)
- or a plain `<select>` dropdown sorted by `processed_at` (simpler, always works)

---

## File Structure

```
paper2tree/
├── PROJECT_PLAN.md
├── pyproject.toml              # or requirements.txt
├── .env                        # ANTHROPIC_API_KEY
│
├── src/
│   ├── __init__.py
│   ├── main.py                 # CLI entry point (see CLI Interface section)
│   │
│   ├── orchestrator.py         # Orchestrator Agent (Agent SDK)
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── paper_fetcher.py    # Agent SDK sub-agent definition + prompts
│   │   ├── text_extractor.py   # Agent SDK sub-agent definition + prompts
│   │   ├── claim_extractor.py  # Direct Anthropic SDK call + Pydantic schema
│   │   ├── dag_builder.py      # Direct Anthropic SDK call + graph validation
│   │   ├── claim_evaluator.py  # Async Anthropic SDK calls (parallel)
│   │   └── output_formatter.py # Pure Python JSON assembly + index upsert
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── claim.py            # Claim, ClaimGraph Pydantic models
│   │   ├── evaluation.py       # ClaimEvaluation Pydantic model
│   │   ├── output.py           # Final DAG JSON schema (PaperDAG)
│   │   └── index.py            # PaperIndex, PaperIndexEntry Pydantic models
│   │
│   ├── prompts/
│   │   ├── orchestrator.txt
│   │   ├── paper_fetcher.txt
│   │   ├── text_extractor.txt
│   │   ├── claim_extractor.txt
│   │   ├── dag_builder.txt
│   │   └── claim_evaluator.txt
│   │
│   └── utils/
│       ├── paper_id.py         # make_paper_id() — slug + URL hash
│       ├── pdf.py              # PDF parsing helpers
│       ├── html.py             # HTML parsing helpers
│       └── graph.py            # DAG validation (topological sort, cycle detection)
│
├── outputs/                    # All processed paper results
│   ├── index.json              # Global paper index (read by frontend on load)
│   ├── attention-is-all-you-need-a1b2c3d4/
│   │   ├── dag.json            # Full DAG result
│   │   └── raw/                # Intermediate files (PDF, extracted text)
│   │       ├── paper.pdf
│   │       └── extracted.json
│   └── bert-pre-training-deep-b9f1e2a3/
│       ├── dag.json
│       └── raw/
│           ├── paper.pdf
│           └── extracted.json
│
└── frontend/                   # React visualization app
    ├── package.json
    ├── src/
    │   ├── App.tsx
    │   ├── api/
    │   │   └── papers.ts       # fetch index.json + individual dag.json files
    │   ├── components/
    │   │   ├── PaperBrowser.tsx # Search/dropdown to select a paper
    │   │   ├── DAGViewer.tsx    # React Flow graph component
    │   │   ├── NodeCard.tsx     # Claim node detail panel (slide-out)
    │   │   └── EvalBadge.tsx    # Validity score badge
    │   ├── hooks/
    │   │   ├── usePaperIndex.ts # Loads + caches index.json
    │   │   └── usePaper.ts      # Lazily loads a single paper's dag.json
    │   └── types/
    │       └── dag.ts           # TypeScript types matching JSON schema
    └── public/
```

---

## Pipeline Data Flow

```
URL
 │
 ▼
[Paper Fetcher]
  → raw_content_path, content_type
 │
 ▼
[Text Extractor]
  → ExtractedPaper { title, authors, abstract, sections[], full_text }
 │
 ▼
[Claim Extractor]
  → ClaimGraph { claims[], edges[] }         (Pydantic, structured output)
 │
 ▼
[DAG Builder]
  → EnrichedDAG { nodes[], edges[] }         (validated, depth-assigned)
 │
 ├──► [Claim Evaluator 1] ──► ClaimEvaluation[]
 ├──► [Claim Evaluator 2] ──► ClaimEvaluation[]   (parallel)
 └──► [Claim Evaluator N] ──► ClaimEvaluation[]
 │
 ▼  (gather all evaluations)
[Output Formatter]
  → paper2tree_output.json
```

---

## Agent SDK vs. Direct API Usage

| Component | Implementation | Reason |
|---|---|---|
| Orchestrator | **Agent SDK** (`ClaudeSDKClient`) | Needs lifecycle control, Agent tool to spawn sub-agents |
| Paper Fetcher | **Agent SDK** sub-agent | Needs `WebFetch` + `Bash` for downloading |
| Text Extractor | **Agent SDK** sub-agent | Needs `Bash` to run parsing scripts |
| Claim Extractor | **Direct Anthropic SDK** | Pure LLM task; structured output via Pydantic |
| DAG Builder | **Direct Anthropic SDK** | Pure LLM + Python graph validation; no file I/O |
| Claim Evaluators | **Direct Anthropic SDK** (async) | Pure LLM tasks, parallelized with `asyncio.gather` |
| Output Formatter | **Pure Python** | Deterministic JSON assembly; no LLM needed |

---

## Model Configuration

All LLM calls use:
- **Model:** `claude-opus-4-6`
- **Thinking:** `{"type": "adaptive"}` (especially important for Claim Extractor and Evaluators)
- **Streaming:** enabled for long-running extractions (Text Extractor, Claim Extractor) via `.stream()` + `.get_final_message()`
- **Structured outputs:** Pydantic schemas passed via `output_format=` to `client.messages.parse()` for all schema-critical steps (Claim Extractor, DAG Builder, Claim Evaluators)

---

## CLI Interface

`src/main.py` exposes three commands:

```bash
# Process a single paper and store results
python -m src.main process <url> [--force]
# --force re-processes even if paper_id already exists in index.json

# Process multiple papers from a text file (one URL per line)
python -m src.main batch <urls.txt> [--force] [--concurrency 3]

# List all processed papers
python -m src.main list [--sort-by title|date|score]
```

The `batch` command runs multiple papers sequentially by default, or concurrently up to `--concurrency N` (limited by API rate limits). Each paper's pipeline is independent; a failure on one paper does not abort the batch.

---

## Frontend: Paper Browser

The frontend loads `index.json` once on startup, then renders a paper browser at the top of the page. Two UI options (choose one):

**Option A — Searchable dropdown (recommended for simplicity):**
- A `<select>` or `combobox` listing all papers sorted by `processed_at` (newest first)
- Inline search input that filters by title or author
- Selecting a paper triggers a fetch of `<paper_id>/dag.json` and re-renders the DAG viewer

**Option B — Command palette (`cmdk`):**
- A `⌘K` shortcut opens a command palette
- Full fuzzy search across all paper titles, authors, and abstracts
- More polished UX, slightly more implementation work

**Data flow:**
```
App load
  → GET /outputs/index.json
  → populate PaperBrowser with index entries
  → user selects a paper
  → GET /outputs/<paper_id>/dag.json   (lazy, cached)
  → render DAGViewer
  → user clicks a node
  → render NodeCard detail panel (slide-out or modal)
```

**`PaperBrowser` component props:**
```typescript
interface PaperBrowserProps {
  papers: PaperIndexEntry[];           // from index.json
  selectedId: string | null;
  onSelect: (paperId: string) => void;
  isLoading: boolean;
}
```

**`usePaperIndex` hook:**
```typescript
// Fetches and caches index.json; re-validates on window focus
function usePaperIndex(): { papers: PaperIndexEntry[]; loading: boolean; error: Error | null }
```

**`usePaper` hook:**
```typescript
// Lazily fetches a single paper's dag.json; cached by paper_id
function usePaper(paperId: string | null): { paper: PaperDAG | null; loading: boolean }
```

---

## Error Handling Strategy

| Failure Mode | Strategy |
|---|---|
| Download fails (paywalled, 404) | Orchestrator returns user-facing error with suggestions (try arXiv, Semantic Scholar) |
| PDF parsing fails | Text Extractor falls back: pdfplumber → pymupdf → raw text extraction |
| Claim extraction produces cycle | DAG Builder detects cycle via DFS, prompts Claim Extractor to revise |
| Evaluator API timeout | `tenacity` retry with exponential backoff; partial results allowed |
| Output schema validation failure | Re-prompt the LLM with the validation error message (max 3 retries) |

---

## Key Design Decisions

1. **Separation of Agent SDK and direct API calls:** The Agent SDK is used only where built-in tools (file I/O, web fetch, bash) are genuinely needed. Pure reasoning tasks (claim extraction, evaluation) use the Anthropic SDK directly for maximum control over structured outputs and parallelism.

2. **Parallel evaluation:** Claim Evaluator agents run concurrently (one per primary claim subtree) via `asyncio.gather`. This is the most expensive step; parallelism reduces total latency from O(N) to O(1) w.r.t. number of primary claims.

3. **Adaptive thinking for reasoning-heavy steps:** The Claim Extractor and Evaluators use `thinking: {type: "adaptive"}` to allow the model to reason through complex logical dependencies without a fixed budget.

4. **Structured outputs throughout:** Every inter-agent handoff uses Pydantic-validated structured outputs to prevent cascading failures from malformed data.

5. **DAG validation in Python (not LLM):** Cycle detection and topological sort are handled deterministically in Python (not delegated to the LLM), ensuring correctness guarantees.

6. **React-agnostic JSON schema:** The output format is intentionally compatible with multiple React graph libraries (React Flow, D3, Cytoscape) via a standard node-link representation, so the frontend is swappable.

7. **Per-paper folders with a flat index:** Each paper lives in `outputs/<paper_id>/` with a self-contained `dag.json`. The `index.json` at the root is a lightweight catalog (title, authors, score, path) that the frontend loads eagerly. Full DAG data is fetched lazily only when the user selects a paper, keeping initial load fast even with hundreds of papers.

8. **Idempotent re-processing:** The `--force` flag allows re-processing a paper without manual cleanup. Without it, the Orchestrator short-circuits if `paper_id` already exists in the index, making the `batch` command safe to re-run after failures.

9. **Intermediate artifact preservation:** Raw downloads and extracted text are kept in `outputs/<paper_id>/raw/`. This allows individual pipeline stages to be re-run in isolation (e.g., re-running only the Claim Extractor with an improved prompt) without re-downloading the paper.

---

## Knowledge Base & Literature Retrieval

> **Status:** Planned — targets v1.1.0 (additive/backwards-compatible; all new evaluation fields are optional)

### Overview

The knowledge base (KB) is a persistent vector store of published scientific literature. During claim evaluation, each claim is queried against the KB to retrieve the most semantically similar passages. The Claim Evaluators receive these passages as additional context and use them to assess two new dimensions:

- **Novelty** — is this claim genuinely new, or has it been established, extended, or contradicted by prior work?
- **Grounding** — is this claim consistent with what the broader literature says?

Matched passages are surfaced as structured citations in the evaluation output and displayed in the frontend's node detail panel.

---

### Updated System Architecture

```
                         ┌─────────────────────┐
          URL ──────────▶│  Orchestrator Agent │
                         │  (Agent SDK)        │
                         └────────┬────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
           ┌────────────┐ ┌────────────┐ ┌────────────────┐
           │   Paper    │ │   Text     │ │    Claim       │
           │  Fetcher   │ │ Extractor  │ │   Extractor    │
           └────────────┘ └────────────┘ └────────────────┘
                                                  │
                                                  ▼
                                         ┌────────────────┐
                                         │  DAG Builder   │
                                         └───────┬────────┘
                                                 │
                                                 ▼
                                  ┌──────────────────────────┐
                                  │   Literature Retriever   │◀──── Knowledge Base
                                  │  (per-claim KB queries)  │      (Qdrant + Voyage AI)
                                  └──────────────┬───────────┘
                                                 │ claim + retrieved passages
                              ┌──────────────────┼──────────────────┐
                              ▼                  ▼                  ▼
                    ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
                    │   Claim      │   │   Claim      │   │   Claim      │
                    │  Evaluator   │   │  Evaluator   │   │  Evaluator   │
                    │  Agent (1)   │   │  Agent (2)   │   │  Agent (N)   │
                    └──────────────┘   └──────────────┘   └──────────────┘
                                                 │
                                                 ▼
                                        ┌────────────────┐
                                        │    Output      │
                                        │   Formatter    │
                                        └───────┬────────┘
                                                │
                                                ▼
                                          DAG JSON file
```

---

### Knowledge Base Components

#### `src/kb/store.py` — Vector Store

Wraps **Qdrant** as the vector database. Qdrant runs locally via Docker (`qdrant/qdrant`) or connects to Qdrant Cloud for production. Each stored unit is a **passage** (a chunked excerpt from a paper), not a full paper.

```python
class KBPassage(BaseModel):
    passage_id: str          # "<paper_id>-<chunk_index>"
    paper_id: str            # source paper identifier
    title: str
    authors: list[str]
    year: int | None
    url: str
    doi: str | None
    section: str             # e.g. "Abstract", "Methods"
    text: str                # the passage text (300–600 tokens)
    embedding: list[float]   # generated by embedder

class VectorStore:
    def __init__(self, collection: str = "literature", url: str = "http://localhost:6333"): ...
    def upsert(self, passages: list[KBPassage]) -> None: ...
    def search(self, query_text: str, top_k: int = 8) -> list[KBSearchResult]: ...
    def count(self) -> int: ...
    def paper_exists(self, paper_id: str) -> bool: ...
```

**Why Qdrant:** runs locally without a separate server process (in-memory mode for tests), supports filtering by metadata (year, field, paper_id), and has a clean Python client. Chroma is an acceptable alternative for purely local setups.

#### `src/kb/embedder.py` — Embedding Generation

Uses **Voyage AI** (`voyage-3-large` or `voyage-3`) for embedding generation. Voyage AI is Anthropic-acquired and purpose-built for scientific and long-document retrieval, with a 32K-token context window.

```python
import voyageai

class Embedder:
    def __init__(self, model: str = "voyage-3-large"):
        self.client = voyageai.Client()   # reads VOYAGE_API_KEY from env
        self.model = model

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        """Batch embed up to 128 texts. input_type: 'document' for KB, 'query' for retrieval."""
        result = self.client.embed(texts, model=self.model, input_type=input_type)
        return result.embeddings
```

The distinction between `input_type="document"` (KB ingestion) and `input_type="query"` (claim retrieval) is important — Voyage AI's asymmetric embedding is optimized for this pattern.

#### `src/kb/ingestion.py` — Paper Ingestion Pipeline

Chunks a paper into passages and stores them in the vector store. Called by the `kb add` CLI command and optionally as a post-processing step after `process`.

```python
CHUNK_SIZE = 450        # target tokens per passage
CHUNK_OVERLAP = 50      # overlap between adjacent passages

def chunk_paper(extracted: ExtractedPaper) -> list[str]:
    """Split paper sections into overlapping fixed-size chunks."""
    ...

def ingest_paper(
    extracted: ExtractedPaper,
    paper_id: str,
    url: str,
    store: VectorStore,
    embedder: Embedder,
    *,
    skip_if_exists: bool = True,
) -> int:
    """Chunk, embed, and upsert a paper into the KB. Returns number of passages added."""
    if skip_if_exists and store.paper_exists(paper_id):
        return 0
    chunks = chunk_paper(extracted)
    embeddings = embedder.embed(chunks, input_type="document")
    passages = [
        KBPassage(passage_id=f"{paper_id}-{i}", paper_id=paper_id, text=chunk, embedding=emb, ...)
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
    ]
    store.upsert(passages)
    return len(passages)
```

**Chunking strategy:** Split at section boundaries first, then apply a sliding window within sections. Always include the paper title and section heading at the start of each chunk so the embedding captures both local and global context.

#### `src/kb/retriever.py` — Claim Retrieval

Queries the KB for each claim and returns ranked, deduplicated passages. This runs as a batch before the Claim Evaluators so retrieval can be parallelized independently.

```python
class RetrievedPassage(BaseModel):
    passage_id: str
    paper_id: str
    title: str
    authors: list[str]
    year: int | None
    url: str
    section: str
    text: str
    score: float             # cosine similarity

class LiteratureRetriever:
    def __init__(self, store: VectorStore, embedder: Embedder, top_k: int = 6): ...

    async def retrieve_for_claim(self, claim_text: str) -> list[RetrievedPassage]:
        """Embed the claim as a query and return top-K passages, excluding same-paper results."""
        ...

    async def retrieve_for_claims(
        self, claims: list[str], current_paper_id: str
    ) -> dict[str, list[RetrievedPassage]]:
        """Parallel retrieval for all claims. Filters out passages from the paper under review."""
        query_embeddings = self.embedder.embed(claims, input_type="query")
        results = await asyncio.gather(*[
            self.store.search_by_embedding(emb, top_k=self.top_k, exclude_paper=current_paper_id)
            for emb in query_embeddings
        ])
        return {claim: passages for claim, passages in zip(claims, results)}
```

Passages from the paper currently under review are excluded to avoid circular grounding.

---

### Pipeline Integration

The Literature Retriever runs as a new step between DAG Builder and Claim Evaluators:

```
[DAG Builder]
  → EnrichedDAG { nodes[], edges[] }
 │
 ▼
[Literature Retriever]        ← queries KB for every claim in parallel
  → retrieved: dict[claim_id, list[RetrievedPassage]]
 │
 ├──► [Claim Evaluator 1]  receives: claim subtree + retrieved passages for those claims
 ├──► [Claim Evaluator 2]
 └──► [Claim Evaluator N]
 │
 ▼
[Output Formatter]
```

If the KB is empty or unavailable, the retriever returns empty lists and the evaluators proceed without literature context (graceful degradation — no pipeline failure).

The retrieved passages are formatted into the evaluator prompt as a "Prior Literature" section:

```
PRIOR LITERATURE (retrieved from knowledge base — use to assess novelty and grounding):

[1] Smith et al. (2023) — "Attention mechanisms in protein folding" (Methods)
    "We demonstrate that cross-attention between sequence and structure embeddings..."
    Similarity: 0.87

[2] Jones & Lee (2022) — "Transformer architectures for biological sequences" (Abstract)
    "Our model achieves state-of-the-art results on..."
    Similarity: 0.81
```

---

### Updated Evaluation Schema

New optional fields are added to `ClaimEvaluation` (backwards-compatible; default to `None`/`[]` for papers processed without a KB):

```python
class LiteratureCitation(BaseModel):
    passage_id: str
    paper_id: str
    title: str
    authors: list[str]
    year: int | None
    url: str
    passage: str                      # the matched text excerpt
    relationship: Literal[           # evaluator's judgment of the relationship
        "supports",                   # prior work corroborates this claim
        "contradicts",                # prior work conflicts with this claim
        "precedes",                   # this claim extends or builds on prior work
        "unrelated",                  # retrieved but evaluator judged not relevant
    ]
    relevance_note: str               # 1–2 sentence explanation from the evaluator

class ClaimEvaluation(BaseModel):
    node_id: str
    support_level: Literal["high", "medium", "low"]
    confidence_level: Literal["high", "medium", "low"]
    is_well_supported: bool
    strengths: list[str]
    weaknesses: list[str]
    alternative_interpretations: list[str]
    required_assumptions: list[str]
    supporting_evidence_quality: Literal["strong", "moderate", "weak", "absent"]
    notes: str
    # New fields (v1.1.0 — optional for backwards compatibility):
    novelty_assessment: Literal[
        "novel",          # no closely related prior work found
        "incremental",    # extends or refines prior work
        "established",    # well-established in prior literature
        "contradicted",   # conflicts with prior literature
    ] | None = None
    novelty_notes: str | None = None
    grounding_in_literature: Literal[
        "well-grounded",       # consistent with and supported by prior work
        "partially-grounded",  # some prior support; some gaps or inconsistencies
        "ungrounded",          # no relevant prior work found in KB
        "contradicted",        # conflicts with retrieved prior work
    ] | None = None
    literature_citations: list[LiteratureCitation] = []
```

---

### KB CLI Commands

Three new subcommands added to `src/main.py`:

```bash
# Add a single paper to the KB (downloads, extracts, chunks, embeds, stores)
paper2tree kb add <url> [--force]

# Bulk-add all papers already in outputs/ to the KB (seeds KB from existing results)
paper2tree kb sync

# Show KB statistics
paper2tree kb stats
# → Collection: literature | Passages: 12,847 | Papers: 341
```

The `process` command gains a `--kb` flag that automatically ingests the processed paper into the KB after evaluation:

```bash
paper2tree process <url> --kb
```

`kb sync` is the practical starting point: it ingests all papers already in `outputs/` using their saved `raw/extracted.json`, populating the KB without re-downloading anything.

---

### Frontend Changes

The `NodeCard` component gains a **Prior Literature** section below the evaluation fields, visible only when `literature_citations` is non-empty. Each citation shows:

- Paper title, authors, year (linked to the source URL)
- The matched passage excerpt
- A relationship badge (`supports` / `contradicts` / `precedes`)
- The evaluator's relevance note

The `ClaimNode` canvas card gains a small `novelty_assessment` indicator alongside the existing `support_level` display.

New TypeScript types added to `dag.ts`:

```typescript
export interface LiteratureCitation {
  passage_id: string
  paper_id: string
  title: string
  authors: string[]
  year: number | null
  url: string
  passage: string
  relationship: 'supports' | 'contradicts' | 'precedes' | 'unrelated'
  relevance_note: string
}
// ClaimEvaluation gains:
  novelty_assessment: 'novel' | 'incremental' | 'established' | 'contradicted' | null
  novelty_notes: string | null
  grounding_in_literature: 'well-grounded' | 'partially-grounded' | 'ungrounded' | 'contradicted' | null
  literature_citations: LiteratureCitation[]
```

---

### New File Structure

```
src/
├── kb/
│   ├── __init__.py
│   ├── store.py           # VectorStore wrapping Qdrant
│   ├── embedder.py        # Voyage AI embedding generation
│   ├── ingestion.py       # Chunking + ingest pipeline
│   ├── retriever.py       # LiteratureRetriever (per-claim query)
│   └── schemas.py         # KBPassage, RetrievedPassage Pydantic models
│
└── agents/
    └── literature_retriever.py   # Thin orchestration wrapper around retriever.py
```

```
kb/                         # persistent KB data (gitignored)
└── qdrant/                 # Qdrant storage directory (or remote URL in .env)
```

New environment variables (`.env`):

```
VOYAGE_API_KEY=...
QDRANT_URL=http://localhost:6333    # or Qdrant Cloud URL
QDRANT_COLLECTION=literature        # default collection name
KB_TOP_K=6                          # passages retrieved per claim
```

---

### Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Vector DB | **Qdrant** | Runs locally or in cloud; metadata filtering; fast ANN search; Python client |
| Embeddings | **Voyage AI** (`voyage-3-large`) | Anthropic-acquired; best-in-class for scientific retrieval; asymmetric query/doc embedding |
| Chunking | Sliding window (450 tok / 50 overlap) | Balances passage coherence with retrieval granularity |
| Retrieval | Pre-evaluation batch query | All claims queried in parallel before evaluators start; no per-evaluator latency |
| Degradation | Graceful (empty citations) | Pipeline never fails due to KB unavailability; older artifacts remain valid |

---

### Versioning

These changes target **v1.1.0** — all new `ClaimEvaluation` fields are optional with sensible defaults, so existing `dag.json` artifacts at `schema_version: 1` remain valid without migration. Papers evaluated without a KB simply show no citations. A migration script is only required if `literature_citations` ever becomes a required field (which would be a v2.0.0 breaking change).

---

## Lightweight Alternative: Live Literature Search via MCP

> **Status:** Planned — simpler alternative to the full KB approach; can be implemented independently

### Overview

Instead of building and maintaining a persistent vector database, this approach searches for relevant literature **at claim evaluation time** using MCP-connected APIs (bioRxiv, PubMed). For each claim being evaluated, the system generates targeted search queries, retrieves the top matching abstracts, and injects them as context into the claim evaluator prompt — the same `literature_citations` fields are populated, so the output schema and frontend are unchanged.

This requires no new infrastructure: no Qdrant server, no embedding model, no ingestion pipeline. The only addition is a `LiveRetriever` module that calls external APIs in parallel alongside the existing evaluator flow.

---

### Available MCP Sources

**bioRxiv / medRxiv** — already available in this project via the `plugin:biorxiv:bioRxiv` MCP server. Provides `search_preprints`, `get_preprint`, and `search_published_preprints` tools. Best for life-science and computational biology preprints.

**PubMed / NCBI** — NCBI publishes an official MCP server (`ncbi-mcp`) covering PubMed (36M citations) and PMC full text. Alternatively, the NCBI E-utilities REST API can be called directly without MCP (no extra server process). Requires a free API key and `NCBI_EMAIL` for the polite pool (10 requests/second). Best for peer-reviewed biomedical literature.

For CS/ML-heavy papers, **Semantic Scholar** (`api.semanticscholar.org`) fills the gap that bioRxiv and PubMed leave — it covers arXiv papers and has a simple keyword/query endpoint that requires no MCP setup, just HTTP.

---

### Pipeline Integration

The `LiveRetriever` slots into the same position as the KB `LiteratureRetriever`: between DAG Builder and the parallel Claim Evaluators.

```
[DAG Builder]
  → EnrichedDAG
 │
 ▼
[LiveRetriever]          ← generates queries, calls APIs, deduplicates
  → retrieved: dict[claim_id, list[RetrievedPassage]]   (same schema as KB approach)
 │
 ├──► [Claim Evaluator 1]  receives claim + retrieved passages as context
 ├──► [Claim Evaluator 2]
 └──► [Claim Evaluator N]
```

The retrieved passages are formatted into the evaluator prompt identically to the KB approach (the "Prior Literature" block), so no prompt changes are needed beyond enabling the feature.

---

### Implementation

#### `src/kb/live_retriever.py`

```python
class LiveRetriever:
    """
    Searches bioRxiv and PubMed at evaluation time.
    No persistent storage — results are scoped to a single paper review run.
    """

    def __init__(
        self,
        top_k: int = 6,
        sources: list[str] = ("biorxiv", "pubmed"),
    ):
        self.top_k = top_k
        self.sources = sources
        self._cache: dict[str, list[RetrievedPassage]] = {}  # query → results, within-run only

    async def retrieve_for_claims(
        self,
        claims: list[str],
        current_paper_title: str,
    ) -> dict[str, list[RetrievedPassage]]:
        """Parallel retrieval for all claims. Returns claim_text → passages."""
        results = await asyncio.gather(*[
            self._retrieve_one(claim, current_paper_title) for claim in claims
        ])
        return dict(zip(claims, results))

    async def _retrieve_one(self, claim: str, paper_title: str) -> list[RetrievedPassage]:
        queries = await self._generate_queries(claim, paper_title)
        passages: list[RetrievedPassage] = []
        for q in queries:
            if q in self._cache:
                passages.extend(self._cache[q])
                continue
            fetched = await asyncio.gather(
                self._search_biorxiv(q) if "biorxiv" in self.sources else asyncio.sleep(0),  # type: ignore
                self._search_pubmed(q)  if "pubmed"  in self.sources else asyncio.sleep(0),  # type: ignore
            )
            hits = [p for batch in fetched if isinstance(batch, list) for p in batch]
            self._cache[q] = hits
            passages.extend(hits)
        return self._rank(passages, claim)[: self.top_k]

    async def _generate_queries(self, claim: str, paper_title: str) -> list[str]:
        """Use a cheap LLM call to turn a claim into 2 focused search queries."""
        response = await async_client.messages.create(
            model="claude-haiku-4-5-20251001",   # fast + cheap for query gen
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": (
                    f"Paper context: {paper_title}\n\n"
                    f"Claim: {claim}\n\n"
                    "Write 2 short PubMed/bioRxiv search queries (one per line, "
                    "no numbering) that would find prior literature relevant to "
                    "evaluating this claim. Be specific; avoid generic terms."
                ),
            }],
        )
        raw = response.content[0].text.strip()
        return [q.strip() for q in raw.splitlines() if q.strip()][:2]

    async def _search_biorxiv(self, query: str) -> list[RetrievedPassage]:
        # Calls the bioRxiv MCP search_preprints tool or REST API directly
        ...

    async def _search_pubmed(self, query: str) -> list[RetrievedPassage]:
        # Calls NCBI E-utilities: esearch → efetch for abstracts
        ...

    def _rank(self, passages: list[RetrievedPassage], claim: str) -> list[RetrievedPassage]:
        """
        Simple lexical ranking: score each passage by token overlap with the claim.
        Good enough for keyword-matched results; can be upgraded to embedding rerank
        without changing the interface.
        """
        claim_tokens = set(claim.lower().split())
        def score(p: RetrievedPassage) -> float:
            tokens = set((p.title + " " + p.passage).lower().split())
            return len(claim_tokens & tokens) / max(len(claim_tokens), 1)
        return sorted(passages, key=score, reverse=True)
```

#### Query generation strategy

The query generator uses `claude-haiku-4-5` (fast, cheap) rather than Opus to keep per-claim overhead low. For a 50-claim paper with 2 queries per claim, this is 100 lightweight API calls — typically under 5 seconds total in parallel and negligible cost (< $0.01).

Queries are generated once per claim subtree, not once per node, since sub-claims in the same subtree often share relevant literature.

#### Within-run caching

Repeated queries within a single paper review (e.g. two claims that generate the same search string) are served from an in-memory dict. This avoids redundant API calls without requiring any persistent storage.

#### Enabling live retrieval

A new `--live-search` flag on the `process` command activates the `LiveRetriever` in place of KB-based retrieval:

```bash
paper2tree process <url> --live-search
paper2tree process <url> --live-search --sources biorxiv,pubmed,semantic_scholar
```

Without either `--kb` or `--live-search`, the evaluators run without literature context (current default behaviour — no regression).

---

### Pros and Cons

| | Live Search (this approach) | Vector KB (full approach) |
|---|---|---|
| **Setup** | Zero — just API keys | Significant — Qdrant, Voyage AI, ingestion pipeline |
| **Freshness** | Always current; finds papers published yesterday | Stale until re-ingested; requires scheduled updates |
| **Coverage** | Bounded by API search quality and source scope | As broad as what was ingested (can be very broad) |
| **Search quality** | Keyword/BM25 — misses conceptually related papers that don't share terminology | Semantic vector search — finds thematically related work even with different wording |
| **Latency** | Adds ~5–15s per paper (parallelised API calls) | Near-zero — local vector search |
| **Cost** | ~$0.01–0.05 per paper in query-gen LLM calls; API calls are free | Upfront ingestion cost (embedding millions of papers); near-zero at retrieval time |
| **Rate limits** | Yes — PubMed 10 req/s, bioRxiv is reasonable; must be respected | None — queries local Qdrant |
| **Infrastructure** | None | Qdrant server + persistent storage (GBs to TBs) |
| **Offline support** | No | Yes |
| **Cross-paper reuse** | No — each review is independent | Yes — ingested papers benefit all future reviews |
| **Domain flexibility** | Limited by which APIs cover the field (gaps in CS/ML) | Covers any ingested source |
| **Implementation effort** | Low — 1 new module, no new services | High — 5+ new modules, new services, CLI commands |

### When to use each

**Use live search when:**
- You want literature grounding without any infrastructure setup
- The papers under review are in fields well-covered by PubMed and bioRxiv (biomedical, life sciences, computational biology)
- You review papers occasionally (low volume — the per-paper API overhead is acceptable)
- Freshness matters more than exhaustive coverage

**Use the vector KB when:**
- You review papers at high volume and per-paper latency compounds
- You work in fields not well-served by PubMed/bioRxiv (e.g. pure CS/ML — better served by arXiv/Semantic Scholar in the KB)
- You need semantic retrieval (vector similarity catches related work that keyword search misses)
- You want cross-paper knowledge accumulation (the KB grows and improves with each ingested paper)

### Recommended migration path

Start with live search (ship fast, no infrastructure), then migrate to the vector KB once the retrieval quality ceiling of keyword search becomes a bottleneck. Because both approaches populate the same `literature_citations` schema and the retriever interface is identical (`retrieve_for_claims(claims, paper_title) → dict[claim_id, passages]`), switching from `LiveRetriever` to `LiteratureRetriever` (KB-backed) is a one-line change in the orchestrator.

---

## Bulk KB Ingestion at Scale

> **Status:** Planned — no version target yet (depends on KB feature shipping first)

### Overview

The KB becomes genuinely useful for novelty and grounding assessment when it contains a large, representative slice of the published literature in the relevant field. This section covers how to populate the KB at scale from multiple upstream sources and keep it current over time.

**Practical scale targets:**

| KB size | Papers | Embedding cost (abstracts) | Qdrant vector storage | Use case |
|---------|--------|---------------------------|----------------------|----------|
| Small | 50K | ~$2 | ~3 GB | Single sub-field, fast to build |
| Medium | 500K | ~$15 | ~30 GB | Broad field (e.g. all of ML) |
| Large | 5M | ~$150 | ~300 GB | Multi-domain (CS + bio + medicine) |
| Very large | 50M+ | ~$1,500+ | ~3 TB+ | General literature — not recommended |

**Field-filtering is more important than raw size.** A focused 200K-paper KB in the right domain retrieves better than a noisy 10M-paper general KB. Always filter by field/category at ingestion time.

---

### Two-Tier Ingestion Strategy

Abstracts and full text serve different retrieval purposes. A two-tier approach controls cost while preserving quality:

**Tier 1 — Abstract KB (default):**
- One embedding per paper (the abstract, ~250 tokens)
- ~$0.03 per 1,000 papers in embedding costs
- Fast to build; sufficient for novelty detection ("has this been done before?")
- All sources can contribute to this tier

**Tier 2 — Full-Text KB (optional, on-demand):**
- 10–20 chunks per paper (~450 tokens each with 50-token overlap)
- ~$0.60 per 1,000 papers in embedding costs
- Required for grounding assessment against specific methods or results
- Enable selectively for high-priority papers or fields

The `--tier` flag on `kb ingest` commands controls which tier is populated. Both tiers live in the same Qdrant collection, distinguished by a `tier` metadata field on each passage.

---

### Source Connectors

Each source is implemented as a `SourceConnector` subclass with a common interface:

```python
# src/kb/sources/base.py
from abc import ABC, abstractmethod
from collections.abc import Iterator

class PaperRecord(BaseModel):
    source: str                   # "arxiv" | "biorxiv" | "pubmed" | "openalex" | ...
    source_id: str                # arXiv ID, PMID, DOI, OpenAlex ID, etc.
    doi: str | None
    title: str
    authors: list[str]
    year: int | None
    abstract: str
    full_text_url: str | None     # URL to fetch full text if needed
    pdf_url: str | None
    field_tags: list[str]         # source-specific field/category tags

class SourceConnector(ABC):
    @abstractmethod
    def fetch(
        self,
        *,
        since: date | None = None,
        fields: list[str] | None = None,
        query: str | None = None,
        limit: int | None = None,
    ) -> Iterator[PaperRecord]:
        """Yield PaperRecords lazily (do not buffer everything in memory)."""
        ...

    @property
    @abstractmethod
    def source_name(self) -> str: ...
```

#### arXiv (`src/kb/sources/arxiv.py`)

arXiv exposes two interfaces:

- **OAI-PMH API** (`export.arxiv.org/oai2`) — the standard for bulk harvest; yields metadata (no full text) for all papers or a date range. Use for incremental updates.
- **arXiv API** (`api.arxiv.org`) — search by category, keyword, date; returns metadata + abstract. Rate limit: 1 request/3 seconds (use `arxiv` Python package which handles this).
- **S3 bulk data** (`arxiv` bucket on AWS) — monthly snapshots of all PDFs and source LaTeX. Requires AWS account; best for one-time large-scale ingest.

Recommended category filters for common domains:

| Domain | arXiv categories |
|--------|-----------------|
| Machine learning | `cs.LG`, `cs.AI`, `stat.ML` |
| NLP | `cs.CL` |
| Computer vision | `cs.CV` |
| Computational biology | `q-bio.QM`, `q-bio.GN`, `cs.LG` |
| Neuroscience | `q-bio.NC` |
| Drug discovery | `q-bio.BM`, `q-bio.MN` |

```python
class ArxivConnector(SourceConnector):
    """Uses the arxiv Python package; handles rate limiting automatically."""
    source_name = "arxiv"

    def fetch(self, *, since=None, fields=None, query=None, limit=None):
        import arxiv
        search = arxiv.Search(
            query=" OR ".join(f"cat:{c}" for c in (fields or [])),
            max_results=limit,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        for result in search.results():
            if since and result.published.date() < since:
                break
            yield PaperRecord(
                source="arxiv",
                source_id=result.entry_id.split("/")[-1],
                doi=result.doi,
                title=result.title,
                authors=[str(a) for a in result.authors],
                year=result.published.year,
                abstract=result.summary,
                pdf_url=result.pdf_url,
                full_text_url=result.pdf_url,
                field_tags=result.categories,
            )
```

#### bioRxiv / medRxiv (`src/kb/sources/biorxiv.py`)

Uses the official bioRxiv content API (`api.biorxiv.org`), which returns preprint metadata and abstracts by date range and category. Full text requires fetching the PDF (same pipeline as the paper fetcher agent).

The existing MCP server (`plugin:biorxiv:bioRxiv`) wraps this API and can be used for interactive queries and exploration. For bulk ingestion, call the REST API directly to avoid MCP overhead.

Supported categories include: `neuroscience`, `bioinformatics`, `genomics`, `cell-biology`, `immunology`, `biochemistry`, `pharmacology-and-toxicology`, and ~30 others.

```python
class BiorxivConnector(SourceConnector):
    source_name = "biorxiv"
    BASE = "https://api.biorxiv.org/details/biorxiv"

    def fetch(self, *, since=None, fields=None, query=None, limit=None):
        # API pages results in batches of 100 by date range
        cursor = 0
        while True:
            url = f"{self.BASE}/{since or '2013-01-01'}/{date.today()}/{cursor}"
            data = httpx.get(url).json()
            for item in data["collection"]:
                if fields and item["category"] not in fields:
                    continue
                yield PaperRecord(
                    source="biorxiv",
                    source_id=item["doi"],
                    doi=item["doi"],
                    title=item["title"],
                    authors=item["authors"].split("; "),
                    year=int(item["date"][:4]),
                    abstract=item["abstract"],
                    pdf_url=f"https://www.biorxiv.org/content/{item['doi']}.full.pdf",
                    field_tags=[item["category"]],
                )
            if len(data["collection"]) < 100:
                break
            cursor += 100
```

#### PubMed / PubMed Central (`src/kb/sources/pubmed.py`)

Two separate data sources under the NCBI umbrella:

- **PubMed** (36M papers): metadata + abstracts via E-utilities API (`eutils.ncbi.nlm.nih.gov`). Free; 10 requests/second with API key (register at NCBI). Use `pymed` package or direct `requests`.
- **PubMed Central Open Access** (4.5M papers): full-text XML available via FTP bulk download (`ftp.ncbi.nlm.nih.gov/pub/pmc/oa_bulk/`). No rate limit for FTP; update packages released weekly.

For most use cases, PubMed abstracts are sufficient. For biomedical full-text, use the PMC FTP dump rather than per-paper API calls.

```python
class PubMedConnector(SourceConnector):
    source_name = "pubmed"

    def fetch(self, *, since=None, fields=None, query=None, limit=None):
        from pymed import PubMed
        pubmed = PubMed(tool="paper2tree", email=os.environ["NCBI_EMAIL"])
        date_filter = f' AND ("{since}"[Date - Publication] : "3000"[Date - Publication])' if since else ""
        results = pubmed.query((query or "") + date_filter, max_results=limit or 10_000)
        for article in results:
            yield PaperRecord(
                source="pubmed",
                source_id=article.pubmed_id,
                doi=article.doi,
                title=article.title,
                authors=[f"{a['lastname']} {a['firstname']}" for a in (article.authors or [])],
                year=article.publication_date.year if article.publication_date else None,
                abstract=article.abstract or "",
                full_text_url=None,   # use PMC FTP for full text
                field_tags=article.mesh_terms or [],
            )
```

#### OpenAlex (`src/kb/sources/openalex.py`)

OpenAlex is the best source for **broad, field-filtered, large-scale ingestion**. It is completely free (no API key needed, though polite pool registration is recommended), covers 250M+ works, and exposes both a paginated REST API and a full snapshot download.

- **API** (`api.openalex.org/works`): filter by `concepts.id`, `publication_year`, `open_access.is_oa`, etc. Cursor-based pagination; 100K requests/day on polite pool.
- **Snapshot** (S3): Parquet files partitioned by entity type (~300GB uncompressed). Best for initial large-scale load; updated monthly.

```python
class OpenAlexConnector(SourceConnector):
    source_name = "openalex"
    BASE = "https://api.openalex.org/works"

    def fetch(self, *, since=None, fields=None, query=None, limit=None):
        # fields = list of OpenAlex concept IDs or display names
        params = {
            "filter": self._build_filter(since, fields),
            "per-page": 200,
            "cursor": "*",
            "mailto": os.environ.get("OPENALEX_EMAIL", ""),
        }
        fetched = 0
        while True:
            data = httpx.get(self.BASE, params=params).json()
            for work in data["results"]:
                if limit and fetched >= limit:
                    return
                abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))
                if not abstract:
                    continue
                yield PaperRecord(
                    source="openalex",
                    source_id=work["id"],
                    doi=work.get("doi"),
                    title=work["title"],
                    authors=[a["author"]["display_name"] for a in work.get("authorships", [])],
                    year=work.get("publication_year"),
                    abstract=abstract,
                    pdf_url=work.get("open_access", {}).get("oa_url"),
                    field_tags=[c["display_name"] for c in work.get("concepts", [])],
                )
                fetched += 1
            cursor = data["meta"].get("next_cursor")
            if not cursor:
                break
            params["cursor"] = cursor
```

Note: OpenAlex stores abstracts as inverted indices (word → list of positions); `_reconstruct_abstract` reverses this into plain text.

#### Semantic Scholar (`src/kb/sources/semantic_scholar.py`)

Good for **citation-enriched retrieval** — Semantic Scholar includes citation counts and influence scores which can be used to weight retrieved passages by impact. Free Academic Graph API; 100 requests/second with API key.

```python
class SemanticScholarConnector(SourceConnector):
    source_name = "semantic_scholar"

    def fetch(self, *, since=None, fields=None, query=None, limit=None):
        import semanticscholar as sch
        api = sch.SemanticScholar(api_key=os.environ.get("S2_API_KEY"))
        results = api.search_paper(
            query or " ".join(fields or []),
            fields=["title", "abstract", "authors", "year", "externalIds",
                    "openAccessPdf", "fieldsOfStudy", "citationCount"],
            limit=limit or 1000,
        )
        for paper in results:
            if not paper.abstract:
                continue
            yield PaperRecord(
                source="semantic_scholar",
                source_id=paper.paperId,
                doi=paper.externalIds.get("DOI") if paper.externalIds else None,
                title=paper.title,
                authors=[a["name"] for a in (paper.authors or [])],
                year=paper.year,
                abstract=paper.abstract,
                pdf_url=paper.openAccessPdf.get("url") if paper.openAccessPdf else None,
                field_tags=paper.fieldsOfStudy or [],
            )
```

---

### Deduplication Registry

With multiple sources, the same paper (e.g. a paper on both arXiv and PubMed) must not be embedded twice. A lightweight SQLite registry tracks every ingested paper by its canonical identifier:

```python
# src/kb/registry.py
class IngestionRegistry:
    """SQLite-backed registry for deduplication and ingestion state tracking."""

    def is_ingested(self, *, doi: str | None, source_id: str, source: str) -> bool:
        """Returns True if this paper has already been ingested (by DOI or source_id)."""
        ...

    def mark_ingested(self, record: PaperRecord, tier: int, n_passages: int) -> None:
        ...

    def cursor(self, source: str) -> date | None:
        """Returns the most recent ingestion date for this source (for incremental updates)."""
        ...

    def set_cursor(self, source: str, as_of: date) -> None:
        ...

    def stats(self) -> dict:
        """Returns per-source counts, total passages, last updated timestamps."""
        ...
```

**Deduplication priority:** DOI (globally canonical) → arXiv ID → PMID → title+year fuzzy match (last resort, ~95% precision, avoids embedding obvious duplicates without a DOI).

---

### Bulk Ingestion Pipeline

`src/kb/pipeline.py` orchestrates fetching → deduplication → embedding → storage for a single source run. It is designed to be resumable: if interrupted, restarting skips already-ingested papers via the registry.

```python
async def run_ingestion(
    connector: SourceConnector,
    store: VectorStore,
    embedder: Embedder,
    registry: IngestionRegistry,
    *,
    tier: int = 1,            # 1 = abstract only, 2 = full text
    batch_size: int = 64,     # papers per embedding batch (Voyage AI max: 128)
    rate_limit: float = 1.0,  # seconds between source API calls
) -> IngestionStats:
    batch: list[PaperRecord] = []

    async for record in connector.fetch(...):
        if registry.is_ingested(doi=record.doi, source_id=record.source_id, source=record.source):
            continue
        batch.append(record)

        if len(batch) >= batch_size:
            await _flush_batch(batch, store, embedder, registry, tier)
            batch.clear()

    if batch:
        await _flush_batch(batch, store, embedder, registry, tier)
```

`_flush_batch` sends all abstracts (or full-text chunks) to Voyage AI in a single batched embedding call, then upserts to Qdrant. Voyage AI supports up to 128 texts per call; for full-text with multiple chunks per paper, batch by chunk count not paper count.

---

### Incremental Updates

Each source connector records a **cursor** (the date of the most recently ingested paper) in the registry. The scheduler calls `kb update` on a cron schedule:

```bash
# One-off: catch up on papers since last run
paper2tree kb update --sources arxiv,biorxiv,pubmed

# Set up a daily cron (writes to system crontab or a cron file)
paper2tree kb schedule --interval daily --sources arxiv,biorxiv
```

The update command fetches only papers newer than the stored cursor, so daily runs typically process a few hundred to a few thousand papers rather than the full corpus.

---

### CLI Commands

```bash
# --- Initial bulk ingestion ---

# arXiv: ingest ML + computational biology papers from 2020 onwards (abstract tier)
paper2tree kb ingest arxiv \
  --categories cs.LG,cs.AI,cs.CL,q-bio.QM,q-bio.NC \
  --since 2020-01-01 --limit 200000 --tier 1

# bioRxiv: ingest neuroscience + bioinformatics preprints (last 3 years)
paper2tree kb ingest biorxiv \
  --categories neuroscience,bioinformatics,genomics \
  --since 2022-01-01 --tier 1

# OpenAlex: broad field sweep with open-access filter (good starting point)
paper2tree kb ingest openalex \
  --field "machine learning" --open-access-only \
  --since 2018-01-01 --limit 500000 --tier 1

# PubMed: biomedical literature by MeSH query
paper2tree kb ingest pubmed \
  --query "deep learning AND (drug discovery OR protein structure)" \
  --since 2019-01-01 --tier 1

# Semantic Scholar: by field of study, sorted by citation count
paper2tree kb ingest semantic-scholar \
  --field "Biology" --min-citations 10 \
  --limit 100000 --tier 1

# --- Upgrade specific papers to full-text tier ---
paper2tree kb upgrade --source arxiv --categories cs.LG --since 2023-01-01 --tier 2

# --- Incremental updates (run daily via cron) ---
paper2tree kb update --sources arxiv,biorxiv,pubmed

# --- Inspect the KB ---
paper2tree kb stats
# Collection: literature
# Total passages: 4,821,340 (tier-1: 4,780,000 | tier-2: 41,340)
# Papers: 482,134  |  Sources: arxiv (210k), openalex (180k), biorxiv (55k), pubmed (37k)
# Last updated: 2026-03-25 (arxiv), 2026-03-24 (biorxiv), 2026-03-20 (pubmed)
# Qdrant collection size: 28.4 GB
```

---

### Recommended Ingestion Sequence

For a new deployment, this order minimises API calls and cost:

1. **Start with OpenAlex** (no auth, no rate-limit friction, broad coverage): ingest 200K–500K papers in the target field. This alone is often enough for a good KB.
2. **Add arXiv** for recent preprints in CS/ML/quant-bio (PDF access enables tier-2 later).
3. **Add bioRxiv** via the existing API if the domain includes life sciences.
4. **Add PubMed** for biomedical literature via E-utilities; use the PMC FTP dump for full-text if needed.
5. **Run `kb sync`** to also ingest any papers already processed by paper2tree itself (leverages already-downloaded PDFs and extracted text at zero additional fetch cost).
6. **Enable daily `kb update`** on arXiv and bioRxiv to stay current.

---

### New File Structure

```
src/kb/
├── sources/
│   ├── __init__.py
│   ├── base.py              # SourceConnector ABC + PaperRecord schema
│   ├── arxiv.py
│   ├── biorxiv.py
│   ├── pubmed.py
│   ├── openalex.py
│   └── semantic_scholar.py
├── pipeline.py              # run_ingestion() — fetch → dedup → embed → store
├── registry.py              # SQLite deduplication + cursor tracking
├── scheduler.py             # incremental update scheduling
├── store.py                 # VectorStore (Qdrant)
├── embedder.py              # Voyage AI
├── ingestion.py             # single-paper chunking (used by kb sync and process --kb)
├── retriever.py             # per-claim query at evaluation time
└── schemas.py               # KBPassage, RetrievedPassage, IngestionStats

kb/                          # gitignored runtime data
├── registry.db              # SQLite deduplication registry
└── qdrant/                  # local Qdrant storage (or use QDRANT_URL for remote)
```

New dependencies:

```
# Add to pyproject.toml
voyageai>=0.3              # embeddings
qdrant-client>=1.9         # vector store
arxiv>=2.1                 # arXiv connector
pymed>=0.8                 # PubMed connector
semanticscholar>=0.8       # Semantic Scholar connector
httpx>=0.27                # OpenAlex + bioRxiv connectors (already present)
```

New environment variables:

```
VOYAGE_API_KEY=...
QDRANT_URL=http://localhost:6333    # or Qdrant Cloud URL
QDRANT_COLLECTION=literature
NCBI_EMAIL=you@example.com          # required by NCBI E-utilities
S2_API_KEY=...                      # optional; increases Semantic Scholar rate limit
OPENALEX_EMAIL=you@example.com      # polite pool registration (optional but recommended)
KB_TOP_K=6                          # passages retrieved per claim at evaluation time
```

---

## Hosting for General Users

This section outlines what it would take to turn paper2tree from a local developer tool into a publicly hosted web application.

---

### API Key Model: Bring Your Own Key (BYOK)

The most important architectural decision for a hosted paper2tree is **who pays for the Claude API calls**.

The recommended model is **BYOK**: users supply their own Anthropic API key, which is stored encrypted in the database and injected into their pipeline jobs at runtime. The service operator only pays for infrastructure.

**Why BYOK is the right choice here:**

- **Cost**: each paper costs $0.50–2.00 in Claude Opus API calls. At any meaningful scale, subsidising this for users makes the service uneconomical without a paid tier.
- **Trust**: power users (researchers, academics) already have Anthropic accounts and are comfortable with BYOK — it's standard practice for AI tooling.
- **Simplicity**: no billing infrastructure, no per-paper metering, no credit system to build and maintain.
- **Control**: users can choose their own Claude model and spending limits via their Anthropic console.

The trade-off is a higher barrier to first use (users must have an Anthropic API key). This is acceptable for the target audience of researchers.

---

### Key Challenges vs. Local Use

| Concern | Local | Public web |
|---|---|---|
| **Auth** | None needed | Must identify users to scope their papers and store their API key |
| **API costs** | You pay, you control | User pays via their own key — service has no Claude cost |
| **Key storage** | `.env` file | Encrypted at rest; injected per-job; never logged |
| **Job queuing** | In-memory, single user | Concurrent jobs across many users; need a real queue |
| **Storage** | Local `outputs/` folder | Persistent, per-user S3 storage |
| **Pipeline runtime** | ~2–5 min, you wait | Must survive server restarts mid-job |
| **Scaling** | Single process | Workers must scale independently of the API server |

---

### Recommended Architecture

```
Browser
  │
  ▼
CDN / Static Hosting          ← React frontend (Vite build, served via S3 + CloudFront)
  │
  ▼
API Server (FastAPI on ECS)   ← auth, job submission, status, key management
  │
  ├── RDS Postgres            ← users, jobs, encrypted API keys
  ├── S3                      ← per-user outputs/ (dag.json, index.json, raw PDFs)
  │
  ▼
SQS Queue
  │
  ▼
Worker Pool (ECS Fargate)     ← runs the pipeline with the user's API key
  │
  └── Anthropic API           ← billed to the user's own account
```

Workers receive the user's (decrypted) API key as part of the job payload and instantiate the Anthropic client with it, rather than reading from the environment.

Staying within the AWS ecosystem simplifies IAM permissions, secrets management, networking, and billing — everything is in one place.

---

### Component Recommendations

#### Frontend — S3 + CloudFront
Build the React app with `npm run build` and deploy the `dist/` folder to an S3 bucket configured for static website hosting, fronted by a CloudFront distribution.

- CloudFront handles global CDN, HTTPS (via ACM), and custom domains
- API requests (`/api/*`) are forwarded to the API server via a CloudFront origin group — no CORS configuration needed
- GitHub Actions can deploy automatically: `aws s3 sync dist/ s3://your-bucket --delete` on every push to `main`

#### API Server — ECS Fargate
Run the FastAPI server as a Docker container on ECS Fargate behind an Application Load Balancer.

- Fargate is serverless containers: no EC2 instances to manage
- Auto-scaling based on CPU/request count
- ALB handles HTTPS termination, health checks, and rolling deploys
- For early-stage traffic, a single `t4g.small`-equivalent task (~$12/mo) is sufficient

Alternatively, **AWS App Runner** offers a simpler managed alternative to ECS for the API server — deploy directly from a container image with zero infrastructure config.

#### Pipeline Workers — ECS Fargate (separate task definition)
Workers are the same container image as the API server but run the pipeline instead of handling HTTP. They are triggered by SQS messages rather than HTTP requests.

- Each worker task runs one job to completion then exits — clean isolation, no shared state
- Fargate scales the number of running tasks based on SQS queue depth (via an Application Auto Scaling policy)
- 2 vCPU / 4 GB memory is sufficient for the pipeline (PDF parsing + API calls)
- Spot Fargate tasks reduce cost by ~70% for workloads that can tolerate occasional interruption — pipeline jobs can be retried safely

#### Job Queue — SQS
SQS is the natural choice when the rest of the stack is on AWS.

- Standard queues with a 10-minute visibility timeout (covers the ~5-minute pipeline runtime)
- Dead-letter queue (DLQ) for jobs that fail after 3 attempts
- Long polling in workers keeps cost near zero when the queue is empty
- Replaces the current in-memory `jobs` dict — job status is stored in RDS Postgres and updated by workers as they progress

#### Storage — S3
`outputs/` moves to S3, scoped per user:

```
s3://paper2tree-outputs/
  {user_id}/
    index.json
    {paper_id}/
      dag.json
      raw/
        paper.pdf
        manifest.json
```

- The API server writes to S3 using the AWS SDK (`boto3`) via an IAM role — no long-lived credentials in the codebase
- The frontend fetches outputs via pre-signed URLs (time-limited, scoped to the requesting user's prefix) generated by the API server
- S3 lifecycle rules can expire raw PDFs after 30 days to control storage costs

#### Database — RDS Postgres
Persist:
- User accounts (id, email, created_at)
- Encrypted API keys (see below)
- Job records with status, step, paper_id, error (replaces in-memory store)
- Per-user paper index metadata (mirrors index.json for fast queries)

RDS `db.t4g.micro` (~$15/mo) is sufficient for early-stage traffic. Aurora Serverless v2 is a cost-efficient upgrade path when traffic grows.

#### Auth — Clerk or AWS Cognito
Both integrate with FastAPI JWT verification middleware.

- **Clerk**: drop-in React sign-in components, easiest DX, free up to 10K MAU
- **AWS Cognito**: stays entirely within the AWS ecosystem; free up to 50K MAU; more configuration required

Clerk is recommended for speed of development; Cognito if AWS-only infrastructure is a hard requirement.

#### Secrets — AWS Secrets Manager
Store the Fernet encryption key (or KMS key ARN) and other service secrets. ECS tasks access them via IAM role at runtime — no secrets in environment variables or container images.

---

### Storing User API Keys Securely

The Anthropic API key must be:
1. Encrypted at rest in RDS (not stored in plaintext)
2. Decrypted only at job dispatch time, in memory, never logged
3. Transmitted only over TLS
4. Deletable by the user at any time

**Recommended: envelope encryption with AWS KMS**

```
User submits API key via HTTPS
  → API server calls KMS GenerateDataKey
  → Encrypts key with the data key
  → Stores ciphertext in RDS (api_key_enc column)
  → Data key is discarded from memory

Job dispatched:
  → API server calls KMS Decrypt
  → Passes plaintext key to ECS worker via SQS message (itself encrypted in transit by SQS)
  → Worker sets ANTHROPIC_API_KEY in memory, runs pipeline
  → Key is never written to disk or logs
```

KMS costs ~$1/mo for the key plus $0.03 per 10,000 API calls — negligible. IAM policies ensure only the API server and worker tasks can use the key.

For a simpler starting point: **Fernet symmetric encryption** (Python `cryptography` package) with the secret stored in AWS Secrets Manager. Adequate for early-stage; migrate to KMS before significant user growth.

---

### Changes Required in the Codebase

#### 1. Persist job state to RDS/Redis
Replace the in-memory `jobs: dict` in `server.py` with async Postgres writes:

```python
# src/job_store.py
async def set_job(job: dict) -> None:
    await db.execute("INSERT INTO jobs ... ON CONFLICT (job_id) DO UPDATE SET ...")

async def get_job(job_id: str) -> dict | None:
    return await db.fetchone("SELECT * FROM jobs WHERE job_id = $1", job_id)
```

#### 2. Write outputs to S3
Add an `S3Store` adapter that matches the current `Path`-based interface:

```python
# src/storage.py
import boto3

class S3Store:
    def __init__(self, bucket: str, prefix: str):  # prefix = user_id
        self._s3 = boto3.client("s3")
        self._bucket = bucket
        self._prefix = prefix

    def write(self, key: str, content: str) -> None:
        self._s3.put_object(Bucket=self._bucket, Key=f"{self._prefix}/{key}", Body=content)

    def read(self, key: str) -> str:
        obj = self._s3.get_object(Bucket=self._bucket, Key=f"{self._prefix}/{key}")
        return obj["Body"].read().decode()

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket, Key=f"{self._prefix}/{key}")
            return True
        except self._s3.exceptions.ClientError:
            return False
```

`write_outputs()` and `_upsert_index()` receive an `S3Store` instance instead of `outputs_dir: Path`.

#### 3. Inject user API key into workers
Make the Anthropic client a passed dependency rather than a module-level singleton:

```python
# Before (current)
_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

# After
def make_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)
```

This also makes agents easier to test (no environment variable dependency).

#### 4. Add key management endpoints

```
POST /api/keys          — encrypt and store the user's Anthropic API key
DELETE /api/keys        — delete stored key
GET /api/keys/status    — returns {has_key: bool} without exposing the key
```

#### 5. Rate limit infrastructure usage
Even with BYOK, the service bears infrastructure cost per job. Add a daily job cap per user (e.g. 20 papers/day) enforced in the API server before enqueueing.

---

### Deployment Topology: Recommended Starting Point

```
GitHub Actions
  └── builds Docker image → ECR
  └── deploys frontend → S3 + CloudFront invalidation

CloudFront (frontend CDN)
  └── origin: S3 static site
  └── /api/* forwarded → ALB

ALB
  └── ECS Fargate (API server tasks, auto-scaled)
        └── RDS Postgres
        └── SQS (job queue)
        └── S3 (outputs bucket, via IAM role)
        └── AWS Secrets Manager (encryption key)

SQS
  └── ECS Fargate (worker tasks, scaled by queue depth)
        └── S3 (writes results)
        └── Anthropic API (user's own key)
```

**Estimated monthly AWS cost at low traffic (< 100 papers/day):**

| Component | Cost |
|---|---|
| CloudFront + S3 (frontend) | ~$1/mo |
| ECS Fargate (API server, 1 task) | ~$12/mo |
| ECS Fargate (workers, ~3 min/paper × 100/day) | ~$30/mo |
| RDS Postgres (`db.t4g.micro`) | ~$15/mo |
| SQS | < $1/mo |
| S3 (outputs storage, ~10 GB) | ~$0.25/mo |
| KMS | ~$1/mo |
| ALB | ~$18/mo |
| Anthropic API | **$0 — billed directly to each user** |
| **Total at 100 papers/day** | **~$80/mo** |

Using Fargate Spot for workers reduces the worker line to ~$9/mo. The ALB is the largest fixed cost; it can be replaced with an AWS App Runner service (~$5/mo) to cut the bill further at low traffic.

---

### What to Build First

1. **Stage 1 — Single container on App Runner with local BYOK** (days): Deploy the existing FastAPI server + React build as a single Docker image on AWS App Runner. Users paste their API key into a UI field; it's stored in the browser's `localStorage` and sent as a request header. No server-side key storage, no auth, no S3 — `outputs/` uses an EFS volume attached to the container. Good for demos and small groups of trusted users.

2. **Stage 2 — Add auth, server-side key storage, and S3** (weeks): Add Clerk for sign-in, RDS for user records and job state, encrypted server-side key storage via Secrets Manager or KMS, and S3 for per-user output storage. Users enter their key once; it's used automatically.

3. **Stage 3 — Decouple workers with SQS + ECS** (weeks): Move pipeline execution to separate Fargate worker tasks triggered by SQS. The API server becomes stateless. Concurrent users are handled cleanly; jobs survive server restarts.

---

## Standalone Local Package

This section covers distributing paper2tree as a self-contained application that any user can run on their own machine with a single command, without needing to know Python, Node.js, or how to configure a dev environment.

---

### Is It Possible?

Yes. The standard approach for this kind of full-stack tool is **Docker Compose**: the user installs Docker, clones the repo (or downloads a release archive), drops their API key into a `.env` file, and runs `docker compose up`. Everything else — Python dependencies, Node build, environment wiring — is handled inside the container.

Docker Compose can work **with or without Claude Code**, depending on which variant you choose:

- **With Claude Code** (full-featured, larger image ~1.2 GB): installs the Claude Code CLI in the runtime container and authenticates it via `ANTHROPIC_API_KEY`. This keeps the agent-based paper fetcher as-is.
- **Without Claude Code** (lighter image ~900 MB): replaces the paper fetcher with direct `httpx` calls, removing the `claude-agent-sdk` dependency entirely. Simpler to maintain; sufficient for arXiv and most open-access papers.

The rest of this section covers the full-featured variant (keeping Claude Code). The `httpx` fallback is described at the end.

---

### Approach 1: Docker Compose (Recommended)

Docker Compose is the right default. It handles the full dependency stack in one file, works identically on macOS, Windows (WSL2), and Linux, and requires no knowledge of Python or Node from the user.

**User experience:**

```bash
# 1. Install Docker Desktop (one-time, from docker.com)
# 2. Clone or download the repo
git clone https://github.com/yourname/paper2tree && cd paper2tree

# 3. Set API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 4. Start
docker compose up

# Open http://localhost:8000
```

That's the entire install flow. The same `ANTHROPIC_API_KEY` authenticates both direct Anthropic SDK calls (claim extractor, evaluator) and the Claude Code CLI used by the paper fetcher.

**`Dockerfile`** (multi-stage: build frontend, then Python + Node runtime):

```dockerfile
# Stage 1: build the React frontend
FROM node:24-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python + Node.js runtime (Node required for Claude Code CLI)
FROM python:3.11-slim
WORKDIR /app

# Install Node.js LTS into the Python image
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI (authenticates via ANTHROPIC_API_KEY at runtime)
RUN npm install -g @anthropic-ai/claude-code

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e "."

# Copy source and the built frontend assets
COPY src/ ./src/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Point Claude Code at a writable config dir inside the container
ENV CLAUDE_CONFIG_DIR=/tmp/claude-config

# Persist outputs to a named volume
VOLUME ["/app/outputs"]

EXPOSE 8000
CMD ["paper2tree-server"]
```

**`docker-compose.yml`**:

```yaml
services:
  paper2tree:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    volumes:
      - outputs:/app/outputs
    restart: unless-stopped

volumes:
  outputs:
```

The `outputs` named volume persists all processed papers across container restarts. Users can also bind-mount a host directory (`./outputs:/app/outputs`) if they want direct filesystem access to their results.

**`.env.example`** (committed to the repo as a template):

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
NCBI_EMAIL=you@example.com
```

---

### Claude Code Authentication in Containers

The Claude Code CLI (`@anthropic-ai/claude-code`) supports two authentication modes, and **both work inside a Docker container**:

#### Option A: API key (recommended — works out of the box)

When `ANTHROPIC_API_KEY` is set in the environment, Claude Code authenticates using the key directly, bypassing the interactive browser-based OAuth flow. No extra setup is needed — the same key passed to `docker compose up` via `.env` covers both the Anthropic SDK and the Claude Code CLI.

`CLAUDE_CONFIG_DIR=/tmp/claude-config` in the Dockerfile gives Claude Code a writable scratch directory for its session state. This is the only container-specific requirement.

#### Option B: Mounted host credentials (for Claude Pro / Max / OAuth users)

Users who access Claude Code through a Claude.ai subscription (Pro or Max) authenticate via OAuth rather than an API key. Both tiers work identically for this purpose — the relevant distinction is **subscription (OAuth)** vs. **API key**, not Pro vs. Max.

These users can mount their host-side credentials into the container:

```yaml
# docker-compose.yml — add to the volumes block
volumes:
  - outputs:/app/outputs
  - ${HOME}/.claude:/root/.claude:ro   # mount host Claude Code auth
```

The `:ro` flag mounts the credentials read-only, so the container cannot modify the host's auth state. The user authenticates once on their host machine (`claude auth login`), then reuses those credentials across container runs. No `.env` changes are needed — the mounted `~/.claude` directory contains all the tokens Claude Code needs.

Note: subscription users (Pro/Max) do not have an `ANTHROPIC_API_KEY` that works with the Claude Code CLI — their access is tied to the OAuth session, not a key. They should use the mount approach, not Option A.

#### Security considerations for Option B

Mounting `~/.claude` carries meaningfully more risk than using an API key, and the plan should be explicit about this:

**Why OAuth tokens are more sensitive than API keys:**
- An API key has a defined, limited scope and can be independently revoked without affecting your account or other sessions.
- The `~/.claude` OAuth tokens are tied to your full Claude.ai session. If exfiltrated from inside the container, an attacker gains something closer to account-level access. Revoking them means invalidating your entire session, not just a single key.
- The `:ro` mount prevents the container from *modifying* credentials, but a compromised container (e.g. via a vulnerability in a Python dependency or the Claude Code CLI itself) can still *read* and exfiltrate them.

**Threat model:**
| Scenario | Risk level |
|---|---|
| Personal laptop, container not exposed to the network | Low — attack surface is limited to the local machine |
| Shared team machine or cloud VM | Meaningful — other users or processes on the host could access the socket or volume |
| Container with inbound network exposure (e.g. port-forwarded to the internet) | High — a vulnerability in any dependency could expose the tokens to a remote attacker |

**Recommendation:** Use Option B only for personal local deployments on a machine you control. For any shared or networked environment, prefer Option A (API key) if at all possible. Pro/Max users on shared machines should consider purchasing a separate pay-per-use API key specifically for Docker use — this gives a revocable, scoped credential with no account-level blast radius.

If Option B is used, apply additional isolation:
```yaml
# docker-compose.yml — restrict network access to Anthropic endpoints only
services:
  paper2tree:
    # ... other config ...
    dns: ["8.8.8.8"]
    # Consider adding network policies if your Docker setup supports it
```

#### Why this matters vs. the old assumption

The earlier version of this plan stated that Claude Code's authentication "requires an interactive browser flow that doesn't work headlessly in a container." That was an overstatement — it applies only to the OAuth path when no API key is set. API key auth has never required a browser and works natively in headless/container environments.

---

### Optional: Lighter Image Without Claude Code

If image size is a concern (~300 MB saving) or the paper fetcher is being rewritten for other reasons, the `claude-agent-sdk` dependency can be removed by replacing the fetcher with direct `httpx` calls. The Agent SDK is doing very little in the fetcher — it's essentially a managed HTTP download. A direct implementation handles the same cases (arXiv URL conversion, PDF vs. HTML fallback, size validation):

```python
# src/agents/paper_fetcher.py — standalone-compatible version
import re
import httpx
from pathlib import Path
from ..schemas.paper import FetchResult

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; paper2tree/1.0)"}
_MIN_PDF_BYTES = 5_000

def _resolve_url(url: str) -> str:
    """Convert arXiv abstract pages to direct PDF URLs."""
    if m := re.match(r"https?://arxiv\.org/abs/(.+)", url):
        return f"https://arxiv.org/pdf/{m.group(1)}.pdf"
    return url

async def fetch_paper(url: str, raw_dir: Path) -> FetchResult:
    raw_dir.mkdir(parents=True, exist_ok=True)
    download_url = _resolve_url(url)

    async with httpx.AsyncClient(follow_redirects=True, timeout=120, headers=_HEADERS) as client:
        response = await client.get(download_url)
        response.raise_for_status()

    content_type = "pdf"
    filename = "paper.pdf"

    if len(response.content) < _MIN_PDF_BYTES or b"%PDF" not in response.content[:1024]:
        # Likely an HTML error page — try fetching as HTML instead
        async with httpx.AsyncClient(follow_redirects=True, timeout=120, headers=_HEADERS) as client:
            response = await client.get(url)
        content_type = "html"
        filename = "paper.html"

    out_path = raw_dir / filename
    out_path.write_bytes(response.content)

    manifest = {"content_type": content_type, "raw_path": filename, "source_url": str(response.url)}
    (raw_dir / "manifest.json").write_text(json.dumps(manifest))

    return FetchResult(content_type=content_type, raw_path=str(out_path), source_url=str(response.url))
```

With this change, the Node.js runtime layer can be removed from the Dockerfile entirely (the frontend build stage still uses Node, but it's discarded after). The trade-off is losing the agent's ability to handle edge-case URL patterns (paywalled journals, DOI redirects requiring JavaScript). For arXiv and most open-access papers, direct HTTP is sufficient.

The two approaches can coexist with a build-time or runtime flag:

```yaml
# docker-compose.yml — select fetcher variant at build time
services:
  paper2tree:
    build:
      context: .
      args:
        INCLUDE_CLAUDE_CODE: "true"   # set to "false" for the lighter image
```

---

### Approach 2: `pip install` with Bundled Frontend

For users who already have Python 3.11+, a PyPI package is a lower-friction alternative to Docker:

```bash
pip install paper2tree
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
paper2tree-server
# Open http://localhost:8000
```

This requires shipping the pre-built frontend assets inside the Python wheel. The approach:

1. **Add a Hatch build hook** (`hatch_build.py`) that runs `npm ci && npm run build` in `frontend/` before the wheel is assembled, then copies `frontend/dist/` into `src/static/`
2. **Update `server.py`** to serve static files from `src/static/` when `frontend/dist/` is not present (i.e. when running from the installed package rather than the dev repo)
3. **Publish to PyPI** via GitHub Actions on every version tag

```python
# hatch_build.py
import subprocess
from pathlib import Path
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        frontend = Path("frontend")
        if not (frontend / "node_modules").exists():
            subprocess.run(["npm", "ci"], cwd=frontend, check=True)
        subprocess.run(["npm", "run", "build"], cwd=frontend, check=True)
        # Copy dist into the package so it's included in the wheel
        build_data["shared_data"] = {"frontend/dist": "src/static"}
```

The downside: this requires Node.js to be available on the machine building the wheel (i.e. on the user's machine for `pip install` from source, or on the CI runner for a PyPI release). For PyPI distribution, pre-building the frontend in CI and including the `dist/` folder in the sdist avoids this entirely.

---

### Approach 3: GitHub Releases with a Pre-Built Archive

For users who want zero build steps, publish a pre-built release archive on GitHub Releases:

```
paper2tree-v1.2.0-macos-arm64.tar.gz
  ├── paper2tree-server   ← single binary (via PyInstaller or Nuitka)
  └── frontend/dist/      ← pre-built React assets
```

**PyInstaller** can bundle the Python runtime + all dependencies into a single executable:

```bash
pyinstaller --onefile --name paper2tree-server src/server.py
```

The user downloads the archive, sets `ANTHROPIC_API_KEY` in their shell, and runs `./paper2tree-server`. No Python, no pip, no Node required.

This is the highest-friction approach to build (PyInstaller bundles are finicky, especially with pdfplumber/PyMuPDF native libraries) but the lowest-friction approach for end users who aren't comfortable with command-line tools at all.

---

### Recommended Rollout

| Approach | User requirement | Effort to implement | Best for |
|---|---|---|---|
| **Docker Compose** | Docker Desktop | Low (one Dockerfile + compose file) | Most users; cross-platform; recommended default |
| **`pip install`** | Python 3.11+ | Medium (build hook + PyPI publish) | Python-familiar users who prefer native install |
| **GitHub Release binary** | Nothing | High (PyInstaller packaging + CI) | Non-technical users; point-and-click install |

Start with Docker Compose. It requires the least codebase change, is the most reproducible, and is well understood by the technical audience (researchers, developers) who are the primary users. The `pip install` path is a good v2 addition once the Docker path is validated.

Replacing the paper fetcher with direct `httpx` is **optional** — it reduces image size and removes the Node.js runtime dependency, but it is no longer a prerequisite. The Claude Code CLI authenticates non-interactively via `ANTHROPIC_API_KEY` and works correctly inside containers.

---

### Required Codebase Changes Summary

| Change | Required? | Why |
|---|---|---|
| Add `Dockerfile` + `docker-compose.yml` (with Node.js + Claude Code) | **Yes** | Docker Compose launch; keeps full agent-based paper fetcher |
| Set `CLAUDE_CONFIG_DIR=/tmp/claude-config` in Dockerfile | **Yes** | Gives Claude Code a writable config dir inside the container |
| Add `NCBI_EMAIL` to `.env.example` | **Yes** | Documents live search configuration |
| Replace `paper_fetcher.py` with `httpx` implementation | Optional | Removes Node.js from image; saves ~300 MB; loses edge-case URL handling |
| Remove `claude-agent-sdk` from `pyproject.toml` | Optional (paired with above) | Only if switching to `httpx` fetcher |
| Update `server.py` static file path to support installed-package layout | Optional | `pip install` compatibility only |
| Add `hatch_build.py` build hook | Optional | Pre-builds frontend into the wheel (pip path) |
| Add GitHub Actions release workflow | Optional | Publishes to PyPI + GitHub Releases on version tags |

---

## PDF Panel — Claim Source Highlighting

> **Status:** Planned — targets v1.2.0

### Overview

When a user clicks a node in the claim DAG, a fourth panel appears to the right of the NodeCard showing the source PDF with the selected claim's `verbatim_quote` highlighted in place. Clicking a different node updates the highlight; clicking the same node again (or closing the panel) dismisses it.

The highlight uses one of two strategies, applied in order of preference:
1. **Coordinate-based:** the pipeline records the exact page number and bounding box of each claim's `verbatim_quote` using PyMuPDF during processing. The frontend uses these coordinates to draw a pixel-accurate highlight overlay over the rendered PDF canvas.
2. **Text-search fallback:** for DAGs processed before this feature shipped (schema v1), the frontend searches the rendered PDF text layer for the `verbatim_quote` string at load time and highlights the first match using the PDF.js `customTextRenderer` API.

The PDF is served from the local static path `/outputs/<paper_id>/raw/paper.pdf`, which is already mounted by the FastAPI server. If no local PDF exists (e.g. the paper was processed from an HTML source), the PDF panel shows a "No PDF available" message.

---

### Design Decisions Summary

| Decision | Choice | Reason |
|---|---|---|
| Highlight approach | Coordinate-based + text-search fallback | Precise for new papers; works on existing DAGs without re-processing |
| Panel layout | Fourth panel, far right of NodeCard | Preserves DAG and NodeCard visibility; additive to existing layout |
| PDF source | Local `/outputs/<paper_id>/raw/paper.pdf` only | Already served; no extra routes needed |
| PDF rendering library | `react-pdf` (wraps PDF.js) | MIT, widely used, exposes text layer for fallback search |
| Coordinate extraction | PyMuPDF `page.search_for()` | Already a project dependency; fastest, most accurate text search with bbox output |

---

### Schema Changes — v2

#### Python (`src/schemas/`)

**`src/schemas/claim.py`** — add two optional fields to `Claim`:

```python
class Claim(BaseModel):
    id: str
    text: str
    type: Literal["root", "primary", "supporting", "evidence"]
    parent_id: str | None = None
    section_source: str
    verbatim_quote: str
    # New in v2 (optional — None for non-PDF sources or when search fails):
    page_number: int | None = None        # 0-indexed page in the source PDF
    bbox: list[float] | None = None       # [x0, y0, x1, y1] in PDF user units (72dpi)
```

**`src/schemas/output.py`** — add `page_number` and `bbox` to `DAGNode`, bump `SCHEMA_VERSION`:

```python
SCHEMA_VERSION = 2

class DAGNode(BaseModel):
    id: str
    label: str
    claim: str
    type: str
    depth: int
    section_source: str
    verbatim_quote: str
    evaluation: dict | None = None
    visual: VisualMeta
    # New in v2:
    page_number: int | None = None
    bbox: list[float] | None = None       # [x0, y0, x1, y1] in PDF user units
```

#### TypeScript (`frontend/src/types/dag.ts`)

```typescript
export interface DAGNode {
  id: string
  label: string
  claim: string
  type: 'root' | 'primary' | 'supporting' | 'evidence'
  depth: number
  section_source: string
  verbatim_quote: string
  evaluation: ClaimEvaluation | null
  visual: VisualMeta
  // New in v2 — null for HTML-sourced papers or when location search failed:
  page_number: number | null
  bbox: [number, number, number, number] | null
}
```

Both fields are additive and optional (`null`-defaulted), so frontend code reading v1 DAGs (which will not have these keys) must treat absent fields as `null`. TypeScript optional chaining (`node.page_number ?? null`) handles this cleanly at runtime.

---

### Migration — v1 → v2

**`migrations/migrate_v1_to_v2.py`**

For each `outputs/<paper_id>/dag.json` with `schema_version: 1`:
1. Check if `outputs/<paper_id>/raw/paper.pdf` exists.
2. If yes: open the PDF with PyMuPDF, search for each node's `verbatim_quote` using `page.search_for()` across all pages (stopping at first match), and write `page_number` and `bbox` to the node.
3. If no PDF: set both fields to `null`.
4. Bump `schema_version` to `2`.
5. Write the updated `dag.json` in place.

```python
import fitz  # pymupdf
import json
from pathlib import Path

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"


def locate_quote(pdf_path: Path, quote: str) -> tuple[int | None, list[float] | None]:
    """Search all pages of a PDF for quote. Returns (page_number, [x0,y0,x1,y1]) or (None, None)."""
    try:
        doc = fitz.open(str(pdf_path))
        for page_num, page in enumerate(doc):
            hits = page.search_for(quote)
            if hits:
                r = hits[0]
                return page_num, [r.x0, r.y0, r.x1, r.y1]
        # If exact match fails, try searching with a shorter anchor (first 60 chars)
        anchor = quote[:60].strip()
        if len(anchor) < len(quote):
            for page_num, page in enumerate(doc):
                hits = page.search_for(anchor)
                if hits:
                    r = hits[0]
                    return page_num, [r.x0, r.y0, r.x1, r.y1]
        return None, None
    except Exception:
        return None, None


def migrate_dag(dag: dict, paper_dir: Path) -> tuple[dict, bool]:
    if dag.get("schema_version", 0) >= 2:
        return dag, False

    pdf_path = paper_dir / "raw" / "paper.pdf"
    has_pdf = pdf_path.exists()
    changed = False

    for node in dag["dag"]["nodes"]:
        node["page_number"] = None
        node["bbox"] = None
        if has_pdf:
            quote = node.get("verbatim_quote", "")
            if quote:
                page_num, bbox = locate_quote(pdf_path, quote)
                node["page_number"] = page_num
                node["bbox"] = bbox
        changed = True

    dag["schema_version"] = 2
    return dag, changed


def main() -> None:
    paper_dirs = [d for d in OUTPUTS_DIR.iterdir() if d.is_dir() and (d / "dag.json").exists()]
    for paper_dir in paper_dirs:
        dag_path = paper_dir / "dag.json"
        dag = json.loads(dag_path.read_text())
        dag, changed = migrate_dag(dag, paper_dir)
        if changed:
            dag_path.write_text(json.dumps(dag, indent=2))
            print(f"migrated   {paper_dir.name}")
        else:
            print(f"up-to-date {paper_dir.name}")
    print("done.")

if __name__ == "__main__":
    main()
```

---

### Backend Pipeline Changes

#### New: `src/utils/pdf_locate.py`

Pure utility wrapping PyMuPDF's `page.search_for()`. Does a two-pass search: exact quote first, then a 60-character anchor prefix as fallback for long quotes that may span line breaks in the PDF rendering.

```python
import fitz
from pathlib import Path


def locate_in_pdf(pdf_path: str | Path, quote: str) -> tuple[int | None, list[float] | None]:
    """
    Find the first occurrence of quote in the PDF.
    Returns (page_number_0indexed, [x0, y0, x1, y1]) or (None, None).
    Coordinates are in PDF user units (points at 72dpi).
    """
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return None, None

    # Pass 1: exact match
    for page_num, page in enumerate(doc):
        hits = page.search_for(quote)
        if hits:
            r = hits[0]
            doc.close()
            return page_num, [r.x0, r.y0, r.x1, r.y1]

    # Pass 2: first 60 chars as anchor (handles long quotes that wrap lines)
    anchor = quote[:60].strip()
    if len(anchor) >= 20 and len(anchor) < len(quote):
        for page_num, page in enumerate(doc):
            hits = page.search_for(anchor)
            if hits:
                r = hits[0]
                doc.close()
                return page_num, [r.x0, r.y0, r.x1, r.y1]

    doc.close()
    return None, None


def locate_claims(claim_graph, pdf_path: str | Path) -> None:
    """
    Mutate each Claim in claim_graph in-place, setting page_number and bbox.
    Only called for PDF-sourced papers; no-op if pdf_path does not exist.
    """
    path = Path(pdf_path)
    if not path.exists():
        return
    for claim in claim_graph.claims:
        claim.page_number, claim.bbox = locate_in_pdf(path, claim.verbatim_quote)
```

#### Modified: `src/orchestrator.py`

Add a new step 4.5 between claim extraction and DAG building:

```python
from .utils.pdf_locate import locate_claims

# ── Step 4: Extract claims ────────────────────────────────────────────
log("[3/6] Extracting claim structure …")
claim_graph = await asyncio.to_thread(extract_claims, extracted.full_text)
log(f"      Found {len(claim_graph.claims)} claims")

# ── Step 4.5: Locate claims in PDF ───────────────────────────────────
if fetch_result.content_type == "pdf":
    log("      Locating claims in PDF …")
    await asyncio.to_thread(locate_claims, claim_graph, fetch_result.raw_path)
    located = sum(1 for c in claim_graph.claims if c.page_number is not None)
    log(f"      Located {located}/{len(claim_graph.claims)} claims with coordinates")

# ── Step 5: Build DAG ─────────────────────────────────────────────────
```

The step numbering displayed in log messages does not change — the coordinate lookup is logged as part of step 3.

#### Modified: `src/utils/graph.py`

`build_dag` must propagate `page_number` and `bbox` from `Claim` to the enriched node objects. The exact change depends on the current `EnrichedClaim` type, but the principle is: copy these two fields from the source `Claim` when constructing each enriched node.

#### Modified: `src/agents/output_formatter.py`

When assembling `DAGNode` output objects, include `page_number` and `bbox` from the enriched claim:

```python
DAGNode(
    id=node.id,
    label=label,
    claim=node.text,
    type=node.type,
    depth=node.depth,
    section_source=node.section_source,
    verbatim_quote=node.verbatim_quote,
    evaluation=...,
    visual=...,
    page_number=node.page_number,   # new
    bbox=node.bbox,                  # new
)
```

---

### Frontend Changes

#### New dependency: `react-pdf`

```bash
npm install react-pdf
```

`react-pdf` v7+ ships with its own TypeScript types and bundles `pdfjs-dist` as a peer dependency. The PDF.js worker must be configured once at the app entry point.

**`frontend/src/main.tsx`** — add worker configuration:

```typescript
import { pdfjs } from 'react-pdf'
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()
```

**`frontend/vite.config.ts`** — ensure the worker file is correctly bundled. Add `optimizeDeps` exclusions for `pdfjs-dist` if needed (react-pdf v7 typically handles this automatically with Vite 5+).

#### New: `frontend/src/components/PDFPanel.tsx`

```typescript
interface PDFPanelProps {
  pdfUrl: string              // e.g. "/outputs/hyperagents-2a45007d/raw/paper.pdf"
  pageNumber: number | null   // 0-indexed (from DAGNode.page_number); null for text-search mode
  bbox: [number, number, number, number] | null  // PDF user units [x0, y0, x1, y1]
  verbatimQuote: string | null                   // fallback text-search target
  onClose: () => void
}
```

**Behaviour:**
- Renders the PDF using `react-pdf`'s `<Document>` and `<Page>` components.
- When `pageNumber` is known, scrolls directly to that page on mount and whenever `pageNumber` changes.
- When `bbox` is provided: renders a `<div>` overlay absolutely positioned over the page canvas using coordinates scaled from PDF units to screen pixels. The scale factor is `renderedPageWidth / page.originalWidth` (available via `onPageLoadSuccess`).
- When `bbox` is null but `verbatimQuote` is provided: enables the PDF.js text layer (`renderTextLayer`) and uses `customTextRenderer` to wrap matching text spans in a highlight `<span>`.
- Has a ×  close button in the top-right corner.
- Shows a loading spinner while the PDF loads.
- Shows "No PDF available" when `pdfUrl` is falsy.

**Coordinate overlay implementation detail:**

PDF.js provides page dimensions via the `page` object in `onPageLoadSuccess`. PyMuPDF returns bounding boxes in the same coordinate space (origin top-left, y increases downward in the rendered image). The overlay `<div>` is positioned as:

```typescript
const scale = renderedWidth / page.originalWidth
const style = {
  position: 'absolute' as const,
  left:   bbox[0] * scale,
  top:    bbox[1] * scale,
  width:  (bbox[2] - bbox[0]) * scale,
  height: (bbox[3] - bbox[1]) * scale,
  backgroundColor: 'rgba(250, 204, 21, 0.35)',   // yellow-400 at 35% opacity
  border: '1px solid rgba(250, 204, 21, 0.7)',
  pointerEvents: 'none' as const,
}
```

The page container must be `position: relative` to anchor the overlay.

**Text-search fallback implementation detail:**

`react-pdf`'s `customTextRenderer` receives each text item and its index. After the page text content is loaded, search for `verbatimQuote` in the concatenated text, identify which spans overlap the match range, and wrap them:

```typescript
<Page
  renderTextLayer
  customTextRenderer={({ str, itemIndex }) =>
    matchedIndices.has(itemIndex)
      ? `<mark class="pdf-highlight">${str}</mark>`
      : str
  }
/>
```

The `pdf-highlight` class applies `background: rgba(250,204,21,0.35)` via Tailwind or a CSS rule in `index.css`.

**Width:** Fixed at 560px. The panel is not resizable in v1.2.0; a resize handle can be added in a future iteration.

#### Modified: `frontend/src/App.tsx`

**New state:**
```typescript
const [pdfPanelOpen, setPdfPanelOpen] = useState(false)
```

**Derived values:**
```typescript
// PDF is available if the paper was fetched from a URL or uploaded as a PDF
const pdfUrl = paper && !paper.paper.url.startsWith('upload://')
  ? `/outputs/${paper.paper.paper_id}/raw/paper.pdf`
  : (() => {
      // Uploaded PDFs are also stored locally — check manifest content_type
      // For simplicity in v1.2.0, check if the paper_id dir has raw/paper.pdf
      // by examining the url — if it starts with upload://, check the filename suffix
      const uploadedPdf = paper?.paper.url.startsWith('upload://') &&
        paper.paper.url.toLowerCase().endsWith('.pdf')
      return uploadedPdf
        ? `/outputs/${paper!.paper.paper_id}/raw/${paper!.paper.url.replace('upload://', '')}`
        : null
    })()

const showPDFPanel = pdfPanelOpen && !!selectedNode && !!pdfUrl
```

**Open/close triggers:**
- PDF panel opens automatically when a node is clicked and `pdfUrl` is non-null.
- A "View in PDF" button on `NodeCard` toggles the panel for cases where the user dismissed it but wants it back.
- PDF panel has its own close button.
- Switching to a different paper resets `pdfPanelOpen` to `false`.

**Layout update:**
```tsx
{/* right panels */}
{selectedNode && !selectedJobId && (
  <NodeCard
    node={selectedNode}
    onClose={() => setSelectedNodeId(null)}
    pdfAvailable={!!pdfUrl}
    pdfPanelOpen={showPDFPanel}
    onTogglePDF={() => setPdfPanelOpen((v) => !v)}
  />
)}
{showPDFPanel && selectedNode && pdfUrl && (
  <PDFPanel
    pdfUrl={pdfUrl}
    pageNumber={selectedNode.page_number}
    bbox={selectedNode.bbox}
    verbatimQuote={selectedNode.verbatim_quote}
    onClose={() => setPdfPanelOpen(false)}
  />
)}
```

#### Modified: `frontend/src/components/NodeCard.tsx`

Add a "View in PDF →" / "Hide PDF ←" toggle button in the header bar, visible only when `pdfAvailable` is true:

```tsx
{pdfAvailable && (
  <button
    onClick={onTogglePDF}
    className="text-[10px] font-mono text-slate-500 hover:text-slate-300 transition-colors px-2 py-0.5 rounded border border-slate-700 hover:border-slate-500"
  >
    {pdfPanelOpen ? '← hide pdf' : 'view in pdf →'}
  </button>
)}
```

`NodeCard` also gets two new props: `pdfAvailable: boolean` and `pdfPanelOpen: boolean` and `onTogglePDF: () => void`.

---

### Layout at a Glance

```
┌──────────┬────────────────────────────────┬────────────┬────────────────────┐
│  Paper   │                                │  NodeCard  │    PDF Panel       │
│ Browser  │        DAG Viewer (flex-1)     │  (360px)   │    (560px)         │
│ (220px)  │                                │            │  [highlighted PDF] │
│          │                                │            │                    │
└──────────┴────────────────────────────────┴────────────┴────────────────────┘
```

On a 1440px screen with both panels open: `1440 - 220 - 360 - 560 = 300px` for the DAG. This is workable but tight. The PDF panel is dismissed with its close button to reclaim DAG space. Future work could add a resize handle or collapsible panels.

---

### PDF Availability for URL-Sourced Papers

Not every URL produces a PDF. The fetcher agent already converts arXiv `/abs/` URLs to `/pdf/` URLs and downloads the result as `paper.pdf`, but journal landing pages, DOI redirects, and some preprint servers may fall back to HTML text extraction. The PDF panel must only be offered when a local PDF actually exists.

#### Problem with the current fetcher

The current fetcher falls back silently to HTML when the PDF is too small or the URL returns an HTML page. There is no secondary attempt to find an embedded PDF link, and `manifest.json` records only a single `raw_path` — there is no way to know after the fact whether a PDF was obtained separately.

The `FetchResult` schema has the same limitation: `content_type` tells you what the primary download was, but gives no information about a secondary PDF download.

#### Enhanced fetcher behaviour

The paper fetcher prompt is extended to add a **PDF recovery step** after an HTML fallback:

> After downloading as HTML, scan the downloaded page for links or meta-tags pointing to a PDF version of the paper. Common patterns:
> - `<a href="...pdf">`, `<meta name="citation_pdf_url" content="...">` (Google Scholar / most preprint servers)
> - bioRxiv/medRxiv: `https://www.biorxiv.org/content/<doi>.full.pdf`
> - PubMed Central: PMC full-text PDF link in the page HTML
> - Semantic Scholar: `openAccessPdf.url` field
>
> If a PDF URL is found, download it as `paper.pdf` and record `pdf_path: "paper.pdf"` in the manifest. If no PDF URL is found, record `pdf_path: null`.

This step runs only when `content_type == "html"` — it is a secondary download attempt, not a replacement for the primary text-based extraction (text extraction still uses the HTML for section structure).

#### `manifest.json` extension

```json
{
  "content_type": "html",
  "raw_path": "paper.html",
  "source_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC...",
  "pdf_path": "paper.pdf"
}
```

`pdf_path` is `null` (or absent) when no PDF was obtained. When `content_type == "pdf"`, `pdf_path` equals `raw_path` (`"paper.pdf"`).

#### `FetchResult` schema extension (`src/schemas/paper.py`)

```python
class FetchResult(BaseModel):
    content_type: str         # "pdf" | "html" | "text"
    raw_path: str             # absolute path to the primary downloaded file
    source_url: str           # final URL after redirects
    pdf_path: str | None = None  # absolute path to paper.pdf if obtained; else None
```

The orchestrator sets `pdf_path = raw_path` when `content_type == "pdf"`, and reads `pdf_path` from the manifest when `content_type == "html"`.

#### `PaperMeta` extension (`src/schemas/output.py` + `frontend/src/types/dag.ts`)

Add `has_local_pdf: bool` to the paper metadata stored in `dag.json`:

```python
class PaperMeta(BaseModel):
    paper_id: str
    title: str
    authors: list[str]
    url: str
    abstract: str
    word_count: int
    processed_at: str
    has_local_pdf: bool = False   # True when paper.pdf exists in outputs/<paper_id>/raw/
```

```typescript
export interface PaperMeta {
  paper_id: string
  title: string
  authors: string[]
  url: string
  abstract: string
  word_count: number
  processed_at: string
  has_local_pdf: boolean   // new in v2 — False for HTML-only or missing-PDF papers
}
```

`output_formatter.py` receives `has_local_pdf` from the orchestrator (which checks `fetch_result.pdf_path is not None`) and writes it into `PaperMeta`.

#### Orchestrator changes

The PDF locate step (step 4.5) is already gated on `fetch_result.content_type == "pdf"`. After the fetcher manifest extension, the gate should instead use `fetch_result.pdf_path is not None`:

```python
if fetch_result.pdf_path is not None:
    log("      Locating claims in PDF …")
    await asyncio.to_thread(locate_claims, claim_graph, fetch_result.pdf_path)
    ...
```

This correctly handles the case where the primary download was HTML but a secondary PDF was obtained.

#### Frontend `pdfUrl` derivation (updated)

Replace the heuristic with a metadata-driven check:

```typescript
// Clean: driven by has_local_pdf from PaperMeta
const pdfUrl = paper?.paper.has_local_pdf
  ? `/outputs/${paper.paper.paper_id}/raw/paper.pdf`
  : null
```

Note: uploaded PDFs store the file under the original filename (e.g. `raw/my-paper.pdf`), not always `raw/paper.pdf`. The `has_local_pdf` flag in combination with the upload URL (`upload://my-paper.pdf`) needs special handling in `output_formatter.py` to normalise the PDF to `paper.pdf` during the copy-to-final-dir step in the orchestrator, or to record the actual filename. The simplest fix: the orchestrator renames any uploaded PDF to `paper.pdf` during the `shutil.move` step, so the filename is always predictable.

#### Migration update

`migrate_v1_to_v2.py` must also set `has_local_pdf` for existing DAGs:

```python
pdf_path = paper_dir / "raw" / "paper.pdf"
dag["paper"]["has_local_pdf"] = pdf_path.exists()
```

This is added to the existing migration loop alongside the coordinate backfill.

---

### Server-Side Changes

None required. The PDF is already served by the existing `/outputs` static mount:

```python
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
```

`/outputs/<paper_id>/raw/paper.pdf` is accessible without any new endpoints.

---

### New and Modified Files Summary

| File | Status | Change |
|---|---|---|
| `src/schemas/paper.py` | Modified | Add `pdf_path: str \| None` to `FetchResult` |
| `src/schemas/claim.py` | Modified | Add `page_number: int \| None`, `bbox: list[float] \| None` |
| `src/schemas/output.py` | Modified | Add `page_number`, `bbox` to `DAGNode`; add `has_local_pdf` to `PaperMeta`; bump `SCHEMA_VERSION = 2` |
| `src/utils/pdf_locate.py` | **New** | `locate_in_pdf()` + `locate_claims()` using PyMuPDF |
| `src/utils/graph.py` | Modified | Propagate `page_number` and `bbox` through enriched nodes |
| `src/agents/paper_fetcher.py` | Modified | Extend prompt to attempt PDF recovery from HTML pages; extend manifest to record `pdf_path` |
| `src/agents/output_formatter.py` | Modified | Pass `page_number`, `bbox`, and `has_local_pdf` into output nodes and paper metadata |
| `src/orchestrator.py` | Modified | Read `pdf_path` from `FetchResult`; gate coordinate lookup on `pdf_path is not None`; pass `has_local_pdf` to formatter |
| `migrations/migrate_v1_to_v2.py` | **New** | Back-fills `page_number`/`bbox` for existing DAGs; sets `has_local_pdf`; bumps schema version |
| `frontend/src/types/dag.ts` | Modified | Add `page_number`, `bbox` to `DAGNode`; add `has_local_pdf` to `PaperMeta` |
| `frontend/src/components/PDFPanel.tsx` | **New** | PDF viewer with coordinate overlay + text-search fallback |
| `frontend/src/components/NodeCard.tsx` | Modified | Add "View in PDF" toggle button |
| `frontend/src/App.tsx` | Modified | PDF panel state + metadata-driven `pdfUrl` derivation |
| `frontend/src/main.tsx` | Modified | Configure PDF.js worker URL |
| `frontend/package.json` | Modified | Add `react-pdf` dependency |
| `frontend/vite.config.ts` | Modified | Bundle PDF.js worker correctly (if needed) |

---

### Dependencies

**Python** (`pyproject.toml`): no new dependencies — `pymupdf>=1.24` is already listed.

**Frontend** (`frontend/package.json`):

```json
"react-pdf": "^7.0.0"
```

`pdfjs-dist` is pulled in automatically as a peer dependency by `react-pdf`.

---

### Implementation Order

1. **Python schema + fetcher + utility** (no frontend)
   - Add `pdf_path: str | None` to `FetchResult` and extend `manifest.json` spec
   - Extend paper fetcher prompt with PDF recovery step for HTML pages; update manifest parsing in `fetch_paper()` to read `pdf_path`
   - Add `has_local_pdf` to `PaperMeta`; update `output_formatter.py` to receive and write it
   - Add `page_number`/`bbox` to `Claim` and `DAGNode` schemas
   - Write `src/utils/pdf_locate.py` and test against an existing output PDF
   - Wire locate step into orchestrator (gate on `fetch_result.pdf_path is not None`)
   - Update `graph.py` and `output_formatter.py` to propagate all new fields
   - Process one arXiv paper and one HTML-sourced paper; verify `has_local_pdf` and coordinates in both resulting `dag.json` files

2. **Migration script**
   - Write and run `migrations/migrate_v1_to_v2.py` against `outputs/`
   - Spot-check 2–3 DAGs to confirm `page_number`/`bbox` are populated correctly

3. **Frontend: types and react-pdf setup**
   - Update `dag.ts`
   - Install `react-pdf`, configure worker in `main.tsx`
   - Verify Vite build compiles without errors

4. **Frontend: `PDFPanel` component (coordinate path first)**
   - Implement basic PDF rendering with `react-pdf`
   - Add page scroll when `pageNumber` is set
   - Add bbox overlay div with highlight styling
   - Test against a paper with known coordinates

5. **Frontend: `PDFPanel` component (text-search fallback)**
   - Enable text layer
   - Implement `customTextRenderer` with quote matching
   - Test against a v1 DAG with no coordinates

6. **Frontend: `App.tsx` wiring**
   - Add PDF panel state and layout
   - Add "View in PDF" button to `NodeCard`
   - Test full user flow: click node → PDF opens → highlight visible → close → click different node → highlight updates
