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
