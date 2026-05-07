# Changelog

All notable changes to paper2tree are documented here.

Version numbers follow [Semantic Versioning](https://semver.org/):
- **MAJOR** — breaking changes to the agent framework, data schema, or frontend
  (requires a migration script for existing artifacts)
- **MINOR** — additive, backwards-compatible changes (new fields, new agents,
  new UI features)
- **PATCH** — bug fixes and hotfixes that don't change any interface

---

## [1.6.0] — 2026-05-07

### Added
- **Continuous-scroll PDF viewer** — replaced the single-page + prev/next navigation with a full document vertical scroll. All pages render simultaneously; opening the panel automatically scrolls to the page containing the selected claim.
- **All-claims highlighting on scroll** — every node whose `page_number` and `bbox` are set is highlighted on its respective page as you scroll through the PDF. Selected claim renders with a bright yellow border; all other claims on the same page render with a subtle amber overlay.
- **Clickable claim highlights** — clicking any non-selected claim highlight in the PDF selects that node, instantly updating the NodeCard on the right. Allows navigating the full claim structure directly from the PDF.
- **DAG mini-map inset while PDF is open** — a compact SVG overview of the complete claim graph (the existing full-map inset from the DAG view) now appears as a floating panel in the bottom-left corner of the PDF area. The currently selected node is highlighted in white so the user can see their position in the argument structure at a glance. Clicking the inset closes the PDF and returns to the full DAG view.
- **PDF embedded in self-contained exports** — when a paper has a local PDF, the export now base64-encodes it and injects it as `pdf_data_url` in `window.__PAPER_DATA__`. The export viewer supports the full PDF panel (continuous scroll, all-claims highlights, clickable highlights, DAG inset) with no server required. The `pdfjs` worker is inlined as a blob URL via Vite's `?raw` import so the export works completely offline.

### Changed
- **PDF panel moved to center area** — the PDF viewer now occupies the main center slot (replacing the DAG), rather than appearing as a fourth column to the right. The NodeCard remains on the right. The close button is labelled "← DAG" instead of "×". The DAG is hidden but not unmounted while the PDF is open, preserving pan/zoom state.
- **Multi-line bbox** — `bbox` type corrected from a single flat `[x0, y0, x1, y1]` list to `[[x0, y0, x1, y1], …]` (one rect per matched line segment). Quotes spanning multiple lines now produce a separate highlight box per line. Type updated in `Claim`, `DAGNode`, and `DAGNode` TypeScript interface. Migration script updated to re-run coordinate search and repair existing v2 artifacts that held the old flat format (339/422 nodes re-located across 10 papers).
- `FullMapInset` and `buildFullLayout` are now exported from `DAGViewer.tsx` for standalone use in the PDF area.
- `tsconfig.json` gains `"types": ["vite/client"]` to support the `?raw` import suffix used by the worker blob approach.

### Fixed
- PDF coordinate highlights previously only covered the first line of multi-line quotes; all matched line segments are now rendered.

---

## [1.5.0] — 2026-05-07

### Added
- **PDF panel** — clicking any node in the DAG opens a fourth panel (560 px, far right) showing the source paper PDF with the selected claim's `verbatim_quote` highlighted in place. The panel persists across node selections and can be toggled with the "view in pdf →" button on the NodeCard or dismissed with its own close button.
- **Coordinate-based highlighting** — the pipeline now locates each claim's verbatim quote in the source PDF using PyMuPDF's `page.search_for()` (two-pass: exact quote, then 60-char anchor prefix). The bounding box is stored in `dag.json` and rendered as a precise yellow overlay on the target page.
- **Text-search fallback** — for nodes without stored coordinates (older DAGs or unlocatable quotes), the PDF.js text layer highlights words from the verbatim quote throughout the rendered page.
- **PDF recovery for HTML-sourced papers** — the paper fetcher agent now scans HTML landing pages for embedded PDF links (`<meta name="citation_pdf_url">`, `href="*.pdf"`, bioRxiv/PMC patterns) and attempts a secondary PDF download. A local PDF is stored alongside the HTML extraction, enabling the PDF panel for papers initially fetched as HTML.
- **`paper.has_local_pdf`** — new boolean field on `PaperMeta` in `dag.json`; drives whether the PDF panel is offered in the UI (no heuristics).
- **`node.page_number` / `node.bbox`** — new optional fields on `DAGNode` carrying the 0-indexed page number and `[x0, y0, x1, y1]` bounding box (PDF user units) for each claim's quote.
- **Frontend PDF viewer** — new `PDFPanel` component using `react-pdf` (PDF.js wrapper); single-page view with prev/next navigation and page counter.
- **`NodeCard` "View in PDF" toggle** — button in the NodeCard header opens/closes the PDF panel independently of node selection.
- Uploaded PDFs are now normalised to `paper.pdf` on disk for consistent URL resolution.

### Changed *(schema_version 1 → 2 — additive only, no fields removed)*
- `PaperMeta` gains `has_local_pdf: bool` (default `false`).
- `DAGNode` gains `page_number: int | null` and `bbox: [number, number, number, number][] | null` — list of per-line rects (both default `null`). *(The flat single-rect type shipped in 1.5.0 was corrected to list-of-rects in 1.6.0.)*
- `FetchResult` (internal) gains `pdf_path: str | None`.
- `SCHEMA_VERSION` constant in `src/schemas/output.py` bumped from `1` to `2`.

### Migration
Run `python migrations/migrate_v1_to_v2.py` to upgrade existing artifacts. The script back-fills `page_number` and `bbox` by searching stored PDFs, sets `has_local_pdf`, and bumps `schema_version` to 2. Unmigrated v1 DAGs continue to render correctly in the UI — the PDF panel simply does not appear.

---

## [1.4.0] — 2026-03-30

### Added
- **Interactive HTML export** — "Export" button in the top bar downloads a fully self-contained `.html` file (~420 KB, ~135 KB gzip) containing the complete interactive DAG viewer. Recipients can open it in any browser with no server, no dependencies, and no account required — full moveable canvas, expand/collapse nodes, node detail panel, prior literature citations, and overall assessment banner all work offline.
- `GET /api/papers/{paper_id}/export` server endpoint returns the export HTML with a `Content-Disposition: attachment` header so browsers trigger a download; filename is derived from the paper title.
- `src/export_html.py` — Python module that reads the pre-built viewer template (`frontend/dist-export/export.html`), injects the paper's `dag.json` data as `window.__PAPER_DATA__`, and updates the `<title>` tag with the paper title.
- `frontend/src/ExportApp.tsx` — stripped-down viewer-only React app (no paper browser, job tracking, or add-paper dialog) that reads paper data from `window.__PAPER_DATA__` on mount.
- `frontend/vite.export.config.ts` + `vite-plugin-singlefile` dev dependency — separate Vite build configuration that produces the single-file viewer template; run with `npm run build:export` from the `frontend/` directory.
- Pre-built viewer template committed to `frontend/dist-export/export.html` so the server can serve exports without requiring Node.js at runtime.

---

## [1.3.0] — 2026-03-26

### Added
- **Live literature search** — new `--live-search` flag on the CLI `process` command and `live_search` field on the server's `/api/process` and `/api/upload` endpoints. When enabled, the pipeline queries PubMed and Semantic Scholar for each claim before evaluation, providing prior-literature context to the evaluator.
- `src/kb/` module: `LiveRetriever` class that generates targeted search queries via Claude Haiku (`claude-haiku-4-5-20251001`), fetches results from PubMed E-utilities (esearch → efetch) and the Semantic Scholar Graph API, deduplicates by title, and ranks by lexical token overlap with the claim text. Results are cached within a single run.
- `LiteratureCitation` Pydantic model added to `src/schemas/evaluation.py`; `ClaimEvaluation` gains a new optional field `literature_citations: list[LiteratureCitation] = []`.
- Claim evaluator prompt updated to instruct the LLM to populate `literature_citations` when prior literature is available.
- Frontend `NodeCard` now renders a **Prior Literature** section showing cited papers with title (linked to source), authors, year, and relevance note — only displayed when citations are present.
- 17 new unit tests in `tests/test_live_retriever.py` covering XML parsing, Semantic Scholar response parsing, lexical ranking, deduplication, within-run caching, and mocked end-to-end retrieval.

## [1.2.0] — 2026-03-26

### Added
- Submitted papers now appear immediately as in-progress entries in the sidebar — no need to keep the dialog open
- New `JobProgressView` center panel: clicking an in-progress or failed entry shows the step-by-step progress bar (Fetch → Extract text → Extract claims → Build DAG → Evaluate claims → Write output), current step text, and full error detail on failure
- Jobs persist across page refreshes via `localStorage` (retained for 24 hours); active jobs resume polling automatically on reload
- Failed jobs show a dismiss button (×) in both the sidebar entry and the progress view
- When a job completes, the sidebar entry is automatically replaced by the paper entry and the center panel switches to the DAG view — no manual refresh needed
- `AddPaperDialog` closes immediately after submission; progress tracking is handled entirely in the sidebar

## [1.1.2] — 2026-03-26

### Fixed
- Full-graph inset moved to upper-left corner; resized from landscape (224×136) to portrait (156×220) to match the LR layout's orientation, where nodes stack vertically within each rank making the full tree taller than wide

## [1.1.1] — 2026-03-26

### Fixed
- DAG canvas now pans with scroll (any direction) instead of click-drag; Ctrl+scroll or pinch zooms as before; node dragging is unaffected

## [1.1.0] — 2026-03-26

### Added
- DAG viewer now collapses supporting and evidence nodes by default; only the root and primary claim nodes are shown on load
- Primary nodes (and any node with hidden children) display a `+N` badge in the header row — clicking it expands that node's subtree; clicking `−` collapses it again; the click is isolated from the node selection so the detail panel still opens normally
- Full-graph inset (bottom-right corner) replaces the ReactFlow minimap — it always renders the complete claim tree via a second dagre layout, with collapsed nodes dimmed, giving a bird's-eye view of the whole paper regardless of expansion state
- Expansion state resets automatically when switching to a different paper

## [1.0.1] — 2026-03-26

### Fixed
- DAG viewer now lays out left-to-right instead of top-to-bottom, reducing horizontal crowding on papers with many claims (`rankdir: LR` in dagre; node handles moved from top/bottom to left/right)

---

## [1.0.0] — 2026-03-25

### Added
- React/TypeScript frontend with interactive DAG viewer (ReactFlow)
- Node detail side panel (`NodeCard`) showing full evaluation breakdown:
  strengths, weaknesses, alternative interpretations, required assumptions,
  evaluator notes
- `EvalBadge` component showing support level (high / medium / low) with
  color coding
- Paper browser sidebar with search and paper index
- `AddPaperDialog` for submitting new papers from the UI
- `schema_version` field on all `dag.json` artifacts (currently `1`)
- `migrations/` folder with versioned migration scripts and a README

### Changed *(breaking — schema_version 0 → 1)*
- `ClaimEvaluation.validity_score` (float 0–1) replaced by
  `ClaimEvaluation.support_level` (`"high" | "medium" | "low"`)
- `DAGSummary.mean_validity_score` removed; replaced by
  `DAGSummary.high_support_nodes` and `DAGSummary.low_support_nodes`
- `DAGSummary.high_confidence_nodes` / `low_confidence_nodes` renamed to
  `high_support_nodes` / `low_support_nodes`
- `PaperIndexEntry.mean_validity_score` replaced by `high_support_count`
- Node visual colors now derived from `support_level` rather than a
  continuous validity score

### Migration
Run `python migrations/migrate_v0_to_v1.py` to upgrade existing artifacts.

---

## [0.0.0] — 2026-03-19

Initial prototype.

### Added
- CLI pipeline (`paper2tree <url>`) covering PDF download, claim extraction,
  DAG construction, claim evaluation, and JSON output
- Multi-agent architecture: orchestrator → claim extractor → claim evaluator →
  output formatter
- `outputs/<paper_id>/dag.json` artifact format (schema_version 0)
- `outputs/index.json` paper index
- `visualize.py` for quick static DAG rendering with matplotlib/networkx
