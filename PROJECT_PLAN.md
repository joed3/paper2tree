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
