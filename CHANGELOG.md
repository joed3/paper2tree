# Changelog

All notable changes to paper2tree are documented here.

Version numbers follow [Semantic Versioning](https://semver.org/):
- **MAJOR** — breaking changes to the agent framework, data schema, or frontend
  (requires a migration script for existing artifacts)
- **MINOR** — additive, backwards-compatible changes (new fields, new agents,
  new UI features)
- **PATCH** — bug fixes and hotfixes that don't change any interface

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
