# paper2tree Evaluation Plan

## Overview

This document outlines a programme for evaluating the paper2tree multi-agent review
system. The goal is to assess whether the hierarchical claim-decomposition pipeline
produces higher-quality scientific reviews than simpler single-agent approaches, and
whether it can surface genuine methodological problems in published research.

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
  → Final Reviewer Agent   (NEW — see §1)
```

The **Final Reviewer Agent** is a new pipeline step (not yet implemented) that takes
the original paper text and the completed DAG as input and produces a prose review in
the register and format of the target corpus. It is the primary output evaluated in
§1. The structured DAG output (support distributions, claim-level evaluations) is the
primary signal evaluated in §2.

### Baseline

For all evaluations: a **single-agent reviewer** prompt to `claude-opus-4-7` with no
intermediate decomposition step:

> *"You are a peer reviewer for a scientific journal. Please write a detailed review of
> the following paper, covering: summary, strengths, weaknesses, requested revisions,
> and an overall recommendation."*

This baseline tests whether the added complexity of the DAG pipeline produces
measurably better reviews.

---

## §1 — Human Review Alignment

### Objective

Measure how closely the paper2tree final review matches the consensus of human peer
reviewers on the same paper, relative to the single-agent baseline.

### Rationale for the Final Reviewer Agent approach

Human reviews are prose; the raw paper2tree output is a structured claim DAG. Rather
than bridge this mismatch with fragile structural assumptions, the Final Reviewer Agent
synthesises the DAG into a prose review that can be compared directly text-to-text.
This also creates a clean ablation: if the DAG-grounded review outperforms the
single-agent review, that is direct evidence the decomposition step adds value.

### Data sources

#### eLife (primary)

- **Access**: eLife publishes full peer review histories under CC-BY since 2012 —
  decision letters, individual reviewer reports, and author responses are publicly
  available via the eLife API and bulk XML dumps.
- **Corpus size**: ~20,000 reviewed articles (accepted and rejected via the
  new eLife model from 2022).
- **Format**: Structured decision letter + individual reviewer reports; eLife reviews
  typically include an explicit summary, essential revisions, and optional comments.
- **Advantage**: High-quality open reviews from professional scientists; consistent
  format; includes both published (accepted) and revised papers.

#### ICLR / NeurIPS via OpenReview (secondary)

- **Access**: OpenReview public API; reviews, meta-reviews, and final decisions are
  available for all ICLR submissions from 2017 onwards.
- **Corpus size**: ~3,000–6,000 submissions per year; NeurIPS 2021+ also available.
- **Format**: Structured ratings (soundness 1–4, presentation 1–4, contribution 1–4,
  overall 1–10, confidence 1–5) plus written sections (summary, strengths, weaknesses,
  questions, limitations).
- **Advantage**: Numerical scores enable quantitative alignment metrics; multiple
  reviewers per paper provide a consensus signal; accept/reject ground truth available.

### Methodology

#### Step 1 — Paper sample

Draw a stratified random sample of papers from each corpus:

| Corpus | Sample size | Stratification |
|--------|-------------|----------------|
| eLife  | 200         | 50% life sciences, 50% biomedical; balanced across years 2018–2024 |
| ICLR   | 200         | 50% accepted, 50% rejected; balanced across years 2020–2024 |

For each paper, collect all associated human reviews and compute a **consensus review**
(aggregate scores, pooled strengths/weaknesses, majority recommendation).

#### Step 2 — Generate reviews

For each paper in the sample, generate three reviews:

1. **paper2tree review** — run the full pipeline; the Final Reviewer Agent is prompted
   with corpus-specific instructions to match the target format (eLife register for eLife
   papers; ICLR structured format with numerical scores for ICLR papers).
2. **Single-agent baseline** — same model (`claude-opus-4-7`), same paper, no DAG.
3. **Human consensus** — gold standard.

#### Step 3 — Evaluation metrics

**Automatic metrics (per paper, averaged across corpus):**

| Metric | What it measures |
|--------|-----------------|
| BERTScore F1 (DeBERTa-XL) | Semantic similarity of generated vs. human review text |
| ROUGE-L | Lexical overlap with human review |
| Embedding cosine similarity (text-embedding-3-large) | High-level alignment of review content |
| Score correlation (ICLR only) | Spearman ρ between generated numerical scores and human consensus scores |
| Aspect recall (LLM-judged) | Fraction of key human reviewer concerns surfaced in generated review |

**Aspect recall protocol**: For each human review, use Claude to extract a list of
distinct substantive concerns (e.g., "the evaluation lacks a baseline on dataset X",
"the theoretical bound in Theorem 2 appears loose"). Then prompt Claude to judge
whether each concern is addressed in the generated review. Report recall@k for the top
3 and top 5 concerns.

**Human preference study (optional, higher cost):**

Recruit domain scientists (e.g., via Prolific with field-specific screening) to
blind-compare paper2tree reviews against single-agent reviews on:

- Accuracy of concern identification
- Depth of analysis
- Usefulness to an author
- Overall quality

Report preference rate and Cohen's κ for inter-rater agreement.

#### Step 4 — Analysis

- Primary comparison: paper2tree vs. baseline on each metric (paired t-test or
  Wilcoxon signed-rank; p < 0.05 with Bonferroni correction for multiple metrics).
- Secondary: break down by field (life science vs. biomedical for eLife; ML subfields
  for ICLR), paper length, and accept/reject decision.
- Ablation: compare "DAG-grounded prose review" against "single-agent review" to
  isolate the value of the decomposition step.

### Limitations

- Text similarity does not distinguish between a review that correctly identifies a
  flaw and one that agrees with a flawed paper. High similarity to a glowing human
  review of a weak paper would look like success. The retraction evaluation (§2)
  partially addresses this.
- Human reviews are written after careful reading over days; paper2tree processes a
  paper in minutes. Some discrepancy is expected and may not indicate system failure.
- The Final Reviewer Agent introduces its own generation variance. Poor prompt design
  could depress scores independent of DAG quality. Prompt should be iterated before
  the main evaluation run.
- eLife and ICLR represent a narrow slice of scientific publishing (high-profile
  biomedical and ML). Generalisability to other fields is untested.

---

## §2 — Retraction Prediction

### Objective

Assess whether the paper2tree structured output can distinguish flawed published papers
(subsequently retracted for methodological reasons) from matched non-retracted papers
in the same journals and time periods, relative to the single-agent baseline.

### Rationale

Retracted papers represent a curated set of cases where post-publication scrutiny
identified problems serious enough to warrant formal correction. If paper2tree's
claim-level evaluation machinery genuinely assesses scientific rigour, it should assign
lower support scores and flag more weaknesses in these papers than in controls — and
should do so more reliably than a single-agent reviewer.

### Data source

**Retraction Watch Database** (available at retractionwatch.com; bulk CSV):

- ~50,000 entries as of 2025, covering retractions across all fields.
- Fields include: DOI, journal, publisher, retraction date, reason codes (multiple
  possible), country, open access status.

**Reason code filter** — include only retractions citing causes that a pre-publication
review system could plausibly detect from paper content:

| Include | Exclude |
|---------|---------|
| Unreliable Results | Authorship dispute |
| Error in Data | Plagiarism of text |
| Concerns/Issues About Data | Duplicate publication of same data (if exact copy) |
| Falsification/Fabrication of Data | Ethical violations (human subjects, consent) |
| Error in Methods | Post-publication update/correction (not retraction) |
| Contamination of Cell Lines / Reagents | Legal reasons |

After filtering, perform the full analysis on the filtered set **and** report a
stratified breakdown by reason code (see §2.3).

### Methodology

#### Step 1 — Corpus construction

1. Download the Retraction Watch CSV; apply the reason code filter above.
2. Resolve DOIs to obtain full-text PDFs (via Unpaywall API, PubMed Central, or
   publisher open-access routes).
3. Discard papers where full text is not obtainable (~30–40% of retractions are
   paywalled).
4. **Target: 300 retracted papers** across at least 3 fields (biomedical, life
   sciences, social/behavioural science).

**Matched controls**: For each retracted paper, identify 2 matched controls from the
same journal with publication year within ±2 years, chosen randomly from papers that
have not been retracted or issued a correction. Match on journal rather than subfield
to avoid introducing selection bias.

Final corpus: ~300 retracted + ~600 controls = ~900 papers.

#### Step 2 — Generate structured evaluations

For each paper, run:

1. **paper2tree pipeline** → `dag.json` (structured features below)
2. **Single-agent baseline** → prose review

Extract the following feature vector from each `dag.json`:

| Feature | Source |
|---------|--------|
| `frac_low_support` | `low_support_nodes / total_nodes` |
| `frac_high_support` | `high_support_nodes / total_nodes` |
| `mean_weakness_count` | average `len(evaluation.weaknesses)` across all evaluated nodes |
| `mean_assumption_count` | average `len(evaluation.required_assumptions)` |
| `evidence_quality_dist` | distribution over `supporting_evidence_quality` (strong/moderate/weak/absent) |
| `frac_low_groundedness` | fraction of nodes with `groundedness_score == "low"` |
| `frac_low_novelty` | fraction of nodes with `novelty_score == "low"` |
| `overall_assessment_sentiment` | embedding of `summary.overall_assessment` projected onto a positive–negative axis (calibrated on held-out set) |

From the single-agent review, extract an equivalent signal (overall sentiment + count
of flagged weaknesses) using the same LLM-judging approach described in §1.

#### Step 3 — Classification and evaluation

**Binary classification task**: retracted (positive) vs. control (negative).

1. Train a logistic regression classifier on the paper2tree feature vector using 5-fold
   cross-validation (train on 4 folds, evaluate on 1; report mean ± SD).
2. Train the same classifier on single-agent features.
3. Primary metric: **AUROC** (area under the ROC curve). Secondary: precision at top
   decile (P@10%) — relevant to a triage use case where a journal processes many
   submissions.

**Stratified analysis by retraction reason**: Report AUROC separately for each reason
code group (e.g., "Unreliable Results", "Error in Methods"). This tests which failure
modes paper2tree is sensitive to.

**Null model**: A classifier that uses only journal impact factor and publication year
as features, to control for field-level base rates.

#### Step 4 — Analysis

- Report AUROC for: paper2tree, single-agent baseline, null model.
- Significance testing: DeLong's method for comparing two AUROC values (paired, same
  papers).
- Feature importance: logistic regression coefficients and permutation importance to
  identify which paper2tree signals are most predictive.
- Qualitative case study: manually inspect 10–20 retracted papers where paper2tree
  achieved high predicted probability, to characterise what the system is detecting.

### Limitations

- Retraction is a noisy proxy for paper quality: many methodologically weak papers are
  never retracted, and some retractions are procedural. This biases the analysis toward
  cases where flaws were severe and eventually caught.
- The system reviews the paper *as published*, with the same information available to
  the original reviewers. Papers that passed peer review may be genuinely hard to
  distinguish from good papers.
- Fabricated data (e.g., manipulated images) is unlikely to be detectable from text
  alone, regardless of pipeline sophistication.
- Full-text availability bias: open-access papers are over-represented in the retracted
  corpus after filtering for obtainable PDFs. If OA papers differ systematically in
  quality from paywalled papers, this could distort results.
- The feature vector is hand-crafted from the current schema. A richer embedding of
  the full DAG (e.g., graph neural network on the claim graph) might yield better
  discrimination but requires more data to train reliably.

---

## §3 — Proposed Additional Evaluations

### §3.1 — Intra-system reliability (self-consistency)

**Question**: Does the pipeline produce consistent reviews of the same paper across
multiple runs?

**Method**: Run paper2tree 5× on the same paper; measure variance in `frac_low_support`,
`overall_assessment` embedding distance, and key concern recall across runs.

**Value**: Establishes a noise floor before interpreting results from §1 and §2. If
self-consistency is low, improving pipeline variance should take priority over
improving mean accuracy.

**Cost**: Low — requires only ~20 papers × 5 runs each.

### §3.2 — Replication alignment

**Question**: For papers with known replication outcomes (successful or failed), does
paper2tree's support signal predict replication success?

**Data**: The Reproducibility Project: Cancer Biology (37 papers with replication
attempts), the Many Labs projects (social psychology), and the Open Science
Collaboration replication dataset.

**Method**: Correlate `frac_high_support` with replication outcome (binary:
replicated / not replicated) and effect size ratio. Compare Spearman ρ against
single-agent baseline.

**Value**: The most direct test of whether claim-level evaluation reflects actual
scientific rigour. Higher signal quality than retraction (which is sparse and noisy).

**Limitation**: Existing replication corpora are small (~100–200 papers each) and
concentrated in social/behavioural sciences and cancer biology.

### §3.3 — Cross-domain consistency

**Question**: Does performance degrade on fields outside ML and biomedical science?

**Method**: Run §1 on a sample of reviews from disciplines with public peer review
histories: *PLOS ONE* (broad science), *Humanities and Social Sciences
Communications*, and *F1000Research*. Report BERTScore and aspect recall across fields.

**Value**: Identifies scope limitations before deployment or publication.

### §3.4 — DAG structural validity (expert annotation study)

**Question**: Does the claim hierarchy produced by paper2tree reflect how domain
experts decompose the same paper's argument structure?

**Method**: Recruit 3 domain scientists per paper for a small sample (n = 20 papers).
Ask each to identify the paper's main claim and its 3–5 primary supporting claims.
Compare against the paper2tree DAG using Jaccard similarity on extracted claim sets
(LLM-judged semantic matching).

**Value**: Validates the core mechanism rather than just the downstream output.
Essential if the evaluation is intended for publication.

**Cost**: High — requires expert recruitment and annotation time.

---

## §4 — Implementation Roadmap

| Priority | Evaluation | Blocker | Estimated API cost |
|----------|------------|---------|-------------------|
| P0 | Final Reviewer Agent (component) | Nothing — implement first | — |
| P0 | §3.1 Self-consistency (20 papers) | Final Reviewer Agent | ~$200 |
| P1 | §1 ICLR alignment (200 papers) | Final Reviewer Agent | ~$2,000–4,000 |
| P1 | §2 Retraction prediction (900 papers) | PDF access pipeline | ~$5,000–9,000 |
| P2 | §1 eLife alignment (200 papers) | Final Reviewer Agent | ~$2,000–4,000 |
| P2 | §3.2 Replication alignment | Replication datasets | ~$500 |
| P3 | §3.3 Cross-domain consistency | eLife infra | ~$1,000 |
| P3 | §3.4 Expert annotation study | Recruitment | ~$500 + expert time |

API cost estimates assume `claude-opus-4-7` at current pricing for a ~40-node paper.
Costs can be reduced ~3–5× by using `claude-haiku-4-5` for the Claim Evaluators during
evaluation runs, accepting some accuracy penalty.

---

## §5 — Open Questions

The following design decisions should be resolved before beginning data collection:

1. **Final Reviewer Agent format**: Should the agent produce a generic review, or
   should it be prompted to match the specific format of the target corpus (ICLR,
   eLife)? Format-matching will improve text similarity scores but may not reflect
   real-world deployability.

2. **Human review aggregation**: For papers with multiple human reviewers, should the
   comparison target be (a) each individual reviewer independently, (b) the
   meta-reviewer/action editor's decision letter, or (c) a pooled synthetic consensus?
   Each choice changes what "alignment" means.

3. **Retraction control matching**: Should controls be matched on journal + year only,
   or also on article type (original research vs. review), open-access status, or
   citation count? Tighter matching reduces confounds but shrinks the available pool.

4. **Evaluation scope**: Is the primary audience for this evaluation internal
   (iterating the pipeline) or external (publication)? This affects the required level
   of statistical rigour and the importance of the expert annotation study (§3.4).

5. **Evaluation model**: Should the evaluation use the same model as the pipeline
   (`claude-opus-4-7`) or a different model to avoid circularity in LLM-as-judge steps?
