# paper2tree Evaluation Plan

## Overview

This document outlines a programme for evaluating the paper2tree multi-agent review
system. The goal is to assess whether the hierarchical claim-decomposition pipeline
produces higher-quality scientific reviews than simpler single-agent approaches, and
whether it can surface genuine methodological problems in published research.

Evaluation proceeds in **two stages**. The pilot study (§0) validates the core
methodology and calibrates costs on a small sample before committing to the full
evaluations (§1–§3). All full evaluations are gated on pilot completion.

### System under evaluation

The full paper2tree pipeline:

```
paper (PDF / URL)
  → Paper Fetcher
  → Text Extractor
  → Claim Extractor        (ClaimGraph Pydantic output)
  → DAG Builder            (validated, topologically sorted)
  → Claim Evaluators       (parallel, one per primary claim)
  → Output Formatter       (dag.json, schema_version 2)
  → Final Reviewer Agent   (NEW — see §0.2)
```

The **Final Reviewer Agent** is a new pipeline step that takes the original paper text
and the completed DAG as input and produces a prose review in the register and format
of the target corpus. It is the primary output compared against human reviews.
The structured DAG output (support distributions, claim-level evaluations) is the
primary signal used in §2 (retraction prediction).

### Baseline

For all evaluations: a **single-agent reviewer** prompt to `claude-opus-4-7` with no
intermediate decomposition step:

> *"You are a peer reviewer for a scientific journal. Please write a detailed review of
> the following paper, covering: summary, strengths, weaknesses, requested revisions,
> and an overall recommendation."*

This baseline tests whether the added complexity of the DAG pipeline produces
measurably better reviews.

---

## §0 — Pilot Study

### Objective

Before committing to full-scale evaluation, validate the end-to-end methodology on a
small sample: implement the two new components (Final Reviewer Agent and single-agent
baseline), confirm the eLife XML data pipeline works correctly, run both systems on
10 papers, and assess whether the planned metrics are informative enough to justify
the full evaluation.

### §0.1 — Components to implement first

Both components must be implemented and manually validated before data collection
begins. Neither requires schema changes to `dag.json`.

#### Final Reviewer Agent

A new agent added as the last step of the paper2tree pipeline, invoked after
`Output Formatter`. It receives:

- The full extracted paper text (from Text Extractor)
- The completed `dag.json` (all claims, evaluations, overall assessment)

It produces a prose review structured to match eLife's open peer review format:

```
**eLife review format**
1. Summary paragraph — what the paper claims and its significance
2. Strengths — what the evidence supports well (grounded in high-support DAG nodes)
3. Weaknesses / essential revisions — concerns requiring author response
   (grounded in low-support nodes, flagged weaknesses, required assumptions)
4. Minor comments — presentation, clarity, supplementary issues
5. Recommendation — Accept / Major revisions / Minor revisions / Reject
```

The agent prompt explicitly instructs it to use the DAG evaluation as its primary
grounding, citing specific claim evaluations where relevant. For the pilot the model
is `claude-opus-4-7` with `thinking: {type: "enabled", budget_tokens: 8000}`.

#### Single-agent baseline reviewer

A standalone script (no DAG, no pipeline) that takes the same extracted paper text and
produces an eLife-format review using the same model and thinking budget. This isolates
the value of the intermediate decomposition step.

### §0.2 — eLife data pipeline

#### Source

**Repository**: `https://github.com/elifesciences/elife-article-xml`

The repo contains ~16,000 articles as JATS XML files under `articles/`. Critically,
each file contains both the paper and its peer review materials as nested
`<sub-article>` elements — no separate download or join step is required.

**Data format notes** (from inspection of the repo schema):
- Papers follow JATS DTD: `<front>` (metadata) + `<body>` (article text) + `<back>` (references)
- Peer review content is in `<sub-article>` children with `@article-type` values:
  - `decision-letter` — editorial decision + consolidated reviewer feedback
  - `referee-report` — individual reviewer reports (used under new eLife model from 2022)
  - `editor-report` — eLife Assessment (significance + evidence strength summary)
  - `author-comment` — author response to reviewers
- Metadata in `<article-meta>`: DOI, publication date, article type, authors, keywords

#### Sampling procedure

1. Clone or sparse-checkout the `articles/` directory.
2. Parse each XML file; keep only articles where:
   - `<article>@article-type` is `research-article`
   - At least one `<sub-article @article-type="decision-letter">` or
     `<sub-article @article-type="referee-report">` is present
   - Publication year is 2018 or later (open review fully adopted; richer review text)
3. This eligible pool is expected to be ~8,000–12,000 articles.
4. **Draw 10 papers using a seeded random sample** (seed fixed for reproducibility).
   Stratify: 5 life sciences, 5 biomedical, based on eLife subject area tags
   in `<subj-group @subj-group-type="heading">`.

#### XML parsing

For each sampled article, extract:

| Field | XPath |
|-------|-------|
| DOI | `//article-meta/article-id[@pub-id-type="doi"]` |
| Title | `//article-meta/title-group/article-title` |
| Publication date | `//article-meta/pub-date[@date-type="pub"]` |
| Subject area | `//subj-group[@subj-group-type="heading"]/subject` |
| Article body text | `//body//p` (strip figures, tables, equations; keep captions) |
| Decision letter body | `//sub-article[@article-type="decision-letter"]//body//p` |
| Individual referee reports | `//sub-article[@article-type="referee-report"]//body//p` (one per reviewer) |
| eLife Assessment | `//sub-article[@article-type="editor-report"]//body//p` |

The **human review gold standard** for each paper is the concatenation of the
`decision-letter` and any `referee-report` bodies. The eLife Assessment is extracted
separately as a structured strength signal (it uses controlled vocabulary:
"landmark / fundamental / important / valuable / useful" for significance;
"exceptional / compelling / convincing / solid / incomplete / inadequate" for evidence).

### §0.3 — Pilot evaluation procedure

For each of the 10 sampled papers:

1. Run the full paper2tree pipeline → `dag.json`
2. Run the Final Reviewer Agent on `dag.json` + paper text → `paper2tree_review.txt`
3. Run the single-agent baseline on paper text alone → `baseline_review.txt`
4. Record wall-clock time and API cost for each

Compute the following metrics for each paper, then report mean ± SD across the 10:

| Metric | Implementation |
|--------|---------------|
| **BERTScore F1** | `paper2tree_review` vs. human review; `baseline_review` vs. human review. Use `microsoft/deberta-xlarge-mnli` via the `bert-score` Python package. |
| **ROUGE-L** | Same pairings as above via `rouge-score` package. |
| **Embedding cosine similarity** | Encode both reviews with `text-embedding-3-large`; compute cosine similarity. |
| **eLife Assessment alignment** | Compare the generated recommendation (Accept / Revisions / Reject) against the eLife Assessment significance/evidence rating. Not a strict match; use a coarse 3-point ordinal scale. |

**Qualitative review**: For each paper, read the paper2tree review, baseline review,
and human review side-by-side and record one paragraph of notes on: which system
captures concerns the other misses; whether the DAG grounding is visible in the
paper2tree review; and any obvious failure modes.

**Self-consistency check**: Select 3 of the 10 pilot papers (choose the three with the
longest article bodies, as longer papers are more likely to show run-to-run variation).
Run the full paper2tree pipeline — including the Final Reviewer Agent — on each of these
three papers a second time, independently (no caching; fresh API calls). For each paper
compute BERTScore F1 between the two generated reviews (run 1 vs. run 2). Report the
mean and range of these three within-paper BERTScore values. A mean ≥ 0.85 is taken as
evidence that the pipeline is stable enough for the full evaluation; below this threshold
indicates that stochastic variation in the Claim Extractor or Final Reviewer Agent is too
large to interpret differences between systems as meaningful signal.

### §0.4 — Pilot success criteria

The pilot should answer four questions before proceeding to full evaluation:

| Question | Proceed if… |
|----------|-------------|
| Are the metrics discriminating? | paper2tree and baseline produce *different* scores (not identical within noise) on ≥ 2 metrics |
| Is the Final Reviewer Agent functional? | ≥ 8/10 reviews are coherent, eLife-formatted, and reference DAG-grounded concerns |
| Are costs acceptable? | Full pipeline cost per paper is < $20 (extrapolated: 200-paper §1 run < $4,000) |
| Is self-consistency acceptable? | Mean within-paper BERTScore across the 3 re-run papers is ≥ 0.85 (see self-consistency check above) |

If any criterion is not met, iterate on the relevant component before proceeding.
The pilot adds at most one additional iteration cycle before full evaluation begins.

### §0.5 — Pilot outputs

The pilot produces four concrete artefacts:

1. `eval/pilot/` directory with `dag.json`, `paper2tree_review.txt`,
   `baseline_review.txt`, and `human_review.txt` for each of the 10 papers.
2. `eval/pilot/metrics.csv` with all per-paper metric values.
3. `eval/pilot/qualitative_notes.md` with the side-by-side reading notes.
4. An updated cost estimate for the full §1 and §2 runs, replacing the rough figures
   in §4.

### §0.6 — Implementation

#### File structure

```
eval/
  __init__.py
  elife_parser.py        # GitHub fetch + JATS XML parsing + seeded sampling
  metrics.py             # BERTScore, ROUGE-L, cosine similarity, assessment alignment
  pilot_study.py         # Main re-runnable orchestrator (entry point)

src/agents/
  final_reviewer.py      # New: DAG-grounded eLife-format review
  baseline_reviewer.py   # New: single-agent eLife-format review (no DAG)

src/prompts/
  final_reviewer.txt     # Prompt template for the DAG-grounded reviewer
  baseline_reviewer.txt  # Prompt template for the single-agent reviewer
```

#### How to run

```bash
# Install eval extras first
pip install -e ".[eval]"

# Run the full pilot (sampling, pipeline, reviews, metrics)
python -m eval.pilot_study \
  --n 10 \
  --seed 42 \
  --output-dir eval/pilot \
  --github-token $GITHUB_TOKEN   # optional; raises API rate limit from 60→5000 req/hr

# Re-run with updated metric logic, keeping existing DAGs and reviews
python -m eval.pilot_study --skip-pipeline

# Force full re-run from scratch
python -m eval.pilot_study --force

# Also run self-consistency check (re-runs 3 longest papers, adds ~$120)
python -m eval.pilot_study --self-consistency
```

#### New optional dependencies (eval extras)

Add to `pyproject.toml`:
```toml
[project.optional-dependencies]
eval = [
    "bert-score>=0.3",
    "rouge-score>=0.1",
    "sentence-transformers>=3.0",
]
```
`lxml` and `httpx` are already main dependencies.

#### Resume / idempotency

Each paper's outputs are written to `eval/pilot/<article_id>/` as they complete.
Re-running without `--force` skips any file that already exists:
`dag.json`, `paper2tree_review.txt`, `baseline_review.txt`, `human_review.txt`.
Metrics are always recomputed from the existing text files.

#### Pipeline integration

eLife papers arrive as JATS-extracted text (no PDF). The pilot bypasses
`paper_fetcher` and `text_extractor`, calling the pipeline internals directly:

```
article_text (str)
  → extract_claims(article_text)    → ClaimGraph
  → build_dag(claim_graph)          → list[EnrichedClaim]
  → evaluate_claims(enriched, text) → dict[str, ClaimEvaluation]
  → format_output(...)              → PaperDAG  →  dag.json
  → generate_review(text, dag)      → paper2tree_review.txt
  → generate_baseline_review(text)  → baseline_review.txt
```

---

## §1 — Human Review Alignment (full study)

*Gated on §0 pilot completion and all four success criteria being met.*

### Objective

Measure how closely the paper2tree final review matches the consensus of human peer
reviewers on the same paper, relative to the single-agent baseline, at scale.

### Rationale for the Final Reviewer Agent approach

Human reviews are prose; the raw paper2tree output is a structured claim DAG. Rather
than bridge this mismatch with fragile structural assumptions, the Final Reviewer Agent
synthesises the DAG into prose that can be compared directly text-to-text.
This also creates a clean ablation: if the DAG-grounded review outperforms the
single-agent review, that is direct evidence the decomposition step adds value.

### Data sources

#### eLife (primary — same pipeline as §0)

- **Corpus size**: ~8,000–12,000 articles with open peer review in the eligible pool.
- **Sample for §1**: 200 papers (stratified: 50% life sciences, 50% biomedical;
  balanced across years 2018–2024).
- **Human gold standard**: decision-letter + referee-report bodies, as in §0.

#### ICLR / NeurIPS via OpenReview (secondary)

- **Access**: OpenReview public API.
- **Corpus size**: ~3,000–6,000 ICLR submissions per year from 2017 onwards.
- **Sample for §1**: 200 papers (50% accepted, 50% rejected; 2020–2024).
- **Format**: Structured ratings (soundness 1–4, presentation 1–4, contribution 1–4,
  overall 1–10, confidence 1–5) plus written sections.
- **Advantage**: Numerical scores enable quantitative alignment metrics; multiple
  reviewers per paper provide a consensus signal.

### Methodology

#### Step 1 — Paper sample

| Corpus | N | Stratification |
|--------|---|----------------|
| eLife  | 200 | 50% life sciences, 50% biomedical; balanced 2018–2024 |
| ICLR   | 200 | 50% accepted, 50% rejected; balanced 2020–2024 |

#### Step 2 — Generate reviews

For each paper: (1) paper2tree review, (2) single-agent baseline, (3) human gold standard.
The Final Reviewer Agent is prompted to match the target corpus format (eLife register
for eLife; ICLR structured format with numerical scores for ICLR).

#### Step 3 — Evaluation metrics

| Metric | What it measures |
|--------|-----------------|
| BERTScore F1 (DeBERTa-XL) | Semantic similarity of generated vs. human review text |
| ROUGE-L | Lexical overlap with human review |
| Embedding cosine similarity (text-embedding-3-large) | High-level content alignment |
| Score correlation (ICLR only) | Spearman ρ between generated and human consensus scores |
| Aspect recall@3, @5 (LLM-judged) | Fraction of top human reviewer concerns surfaced |

**Aspect recall protocol**: Use Claude to extract distinct substantive concerns from
each human review, then judge whether each appears in the generated review.
Use `claude-haiku-4-5` (not `claude-opus-4-7`) for this step to avoid circularity
with the generation model — see §5, open question 5.

**Human preference study (optional):**
Recruit domain scientists via Prolific to blind-compare paper2tree vs. baseline
reviews. Report preference rate and Cohen's κ for inter-rater agreement.

#### Step 4 — Analysis

- Primary comparison: paper2tree vs. baseline on each metric (Wilcoxon signed-rank,
  Bonferroni correction for multiple metrics).
- Secondary breakdown by field, paper length, and accept/reject decision.
- Ablation: DAG-grounded review vs. single-agent review to isolate decomposition value.

### Limitations

- Text similarity does not distinguish a review that correctly identifies a flaw from
  one that agrees with a flawed paper. The retraction evaluation (§2) partially
  addresses this.
- Human reviews are written after careful reading over days; paper2tree processes in
  minutes. Some discrepancy is expected and may not indicate system failure.
- eLife and ICLR represent a narrow slice of scientific publishing.

---

## §2 — Retraction Prediction

*Gated on §0 pilot completion; can run in parallel with §1.*

### Objective

Assess whether the paper2tree structured output can distinguish flawed published papers
(subsequently retracted for methodological reasons) from matched non-retracted controls,
relative to the single-agent baseline.

### Data source

**Retraction Watch Database** (retractionwatch.com; bulk CSV; ~50,000 entries as of 2025).

**Reason code filter** — include only retractions citing causes detectable from text:

| Include | Exclude |
|---------|---------|
| Unreliable Results | Authorship dispute |
| Error in Data | Plagiarism of text |
| Concerns/Issues About Data | Duplicate publication (exact copy) |
| Falsification/Fabrication of Data | Ethical violations |
| Error in Methods | Post-publication corrections (not retractions) |
| Contamination of Cell Lines / Reagents | Legal reasons |

### Methodology

#### Step 1 — Corpus construction

1. Download Retraction Watch CSV; apply reason code filter.
2. Resolve DOIs → full-text PDFs (Unpaywall, PubMed Central, OA publisher routes).
3. **Target: 300 retracted papers** across ≥ 3 fields.
4. **Matched controls**: 2 controls per retracted paper from the same journal, ±2 years,
   no retractions or corrections. Final corpus: ~900 papers.

#### Step 2 — Feature extraction from `dag.json`

| Feature | Source |
|---------|--------|
| `frac_low_support` | `low_support_nodes / total_nodes` |
| `frac_high_support` | `high_support_nodes / total_nodes` |
| `mean_weakness_count` | avg `len(evaluation.weaknesses)` across nodes |
| `mean_assumption_count` | avg `len(evaluation.required_assumptions)` |
| `evidence_quality_dist` | distribution over `supporting_evidence_quality` |
| `frac_low_groundedness` | fraction of nodes with `groundedness_score == "low"` |
| `frac_low_novelty` | fraction of nodes with `novelty_score == "low"` |
| `overall_assessment_sentiment` | embedding of `summary.overall_assessment` on positive–negative axis |

#### Step 3 — Classification

Logistic regression, 5-fold cross-validation. Primary metric: **AUROC**.
Secondary: precision at top decile (P@10%). Stratify results by retraction reason code.
Compare against null model (journal impact factor + publication year only).

### Limitations

Retraction is a noisy proxy; many weak papers are never retracted.
Fabricated data is unlikely detectable from text alone.
Full-text availability bias toward open-access papers.

---

## §3 — Proposed Additional Evaluations

*All gated on §1 completion; run sequentially in order of priority.*

### §3.1 — Intra-system reliability

Run paper2tree 5× on 20 papers; measure variance in `frac_low_support`,
`overall_assessment` embedding distance, and aspect recall. Establishes a noise floor
before interpreting §1 and §2 results. **Cost: ~$200.**

### §3.2 — Replication alignment

Correlate `frac_high_support` with replication outcomes from the Reproducibility
Project: Cancer Biology (37 papers) and the Open Science Collaboration dataset.
The most direct test of whether claim-level support predicts real-world reproducibility.
**Cost: ~$500.**

### §3.3 — Cross-domain consistency

Run §1 metrics on papers from *PLOS ONE*, *Humanities and Social Sciences
Communications*, and *F1000Research* (all have open reviews). Tests whether
performance holds outside high-profile biomedical and ML venues.
**Cost: ~$1,000.**

### §3.4 — DAG structural validity (expert annotation)

Recruit 3 domain scientists per paper (n = 20 papers) to identify the main claim
and 3–5 primary supporting claims. Compare against paper2tree DAG via LLM-judged
Jaccard similarity. Validates the core decomposition mechanism.
**Cost: ~$500 + expert time.**

---

## §4 — Implementation Roadmap

### Stage 1 — Pilot (implement and validate first)

| Step | Task | Depends on | Est. cost |
|------|------|------------|-----------|
| 1a | Implement Final Reviewer Agent | — | — |
| 1b | Implement single-agent baseline reviewer | — | — |
| 1c | Build eLife XML parser (clone repo, filter, sample 10) | — | — |
| 1d | Run pilot on 10 eLife papers | 1a, 1b, 1c | ~$200–400 |
| 1e | Compute pilot metrics; write qualitative notes | 1d | — |
| 1f | Assess pilot success criteria; iterate if needed | 1e | ~$100 per iteration |

**Gate**: All four pilot success criteria (§0.4) must pass before Stage 2 begins.

### Stage 2 — Full evaluations (post-pilot)

| Priority | Evaluation | Depends on | Est. cost |
|----------|------------|------------|-----------|
| P1 | §1 eLife alignment (200 papers) | Stage 1 gate | ~$2,000–4,000* |
| P1 | §2 Retraction prediction (900 papers) | Stage 1 gate | ~$5,000–9,000* |
| P2 | §1 ICLR alignment (200 papers) | §1 eLife complete | ~$2,000–4,000* |
| P2 | §3.1 Self-consistency | §1 eLife complete | ~$200 |
| P3 | §3.2 Replication alignment | §1 complete | ~$500 |
| P3 | §3.3 Cross-domain consistency | §1 complete | ~$1,000 |
| P3 | §3.4 Expert annotation study | §1 complete | ~$500 + expert time |

*Costs to be revised upward or downward after Stage 1 produces an empirical per-paper
cost figure.

API cost estimates assume `claude-opus-4-7` for generation and `claude-haiku-4-5`
for LLM-as-judge steps. Costs can be reduced ~3–5× by using `claude-haiku-4-5` for
Claim Evaluators during evaluation runs, accepting some accuracy penalty.

---

## §5 — Open Questions

Decisions to resolve before Stage 2 data collection begins. Some can be resolved
using pilot observations.

1. **Final Reviewer Agent format**: The pilot uses a fixed eLife format. For §1 ICLR
   the agent must produce numerical ratings. Decide whether a single prompt with
   format-switching or two separate prompts is cleaner.

2. **Human review aggregation**: For papers with multiple reviewers, compare against
   (a) each reviewer independently, (b) the decision letter only, or (c) a pooled
   synthetic consensus? The pilot uses the decision letter; revisit if it proves
   too compressed to capture individual concerns.

3. **Retraction control matching**: Journal + year only, or also match on article type,
   open-access status, or citation count? Tighter matching reduces confounds but
   shrinks the pool.

4. **Evaluation scope**: Internal (iteration guidance) or external (publication)?
   Determines whether §3.4 expert annotation is essential or optional.

5. **Evaluation model circularity**: The LLM-as-judge steps in §1 (aspect recall) use
   Claude. The pilot uses `claude-haiku-4-5` for judging vs. `claude-opus-4-7` for
   generation. Confirm whether this separation is sufficient, or whether a non-Anthropic
   judge model (e.g., GPT-4o) is needed for external credibility.
