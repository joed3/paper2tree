# Paper2Tree v1 — Review & Critique

*A step-back evaluation of the system's scientific judgment, its scoring model, and where the highest-leverage improvements are. Focused first on scientific taste; infrastructure notes are at the end.*

---

## 1. What the system does today

The pipeline is: fetch → extract text → **extract a claim DAG** → build/validate the DAG → **evaluate every claim** → synthesize a prose review (eLife format) → render an interactive tree in the frontend. Each claim node carries an evaluation with several ordinal scores, strength/weakness bullets, and optional literature citations.

Two things are worth separating, because they have very different health:

- **The interactive artifact** (a paper decomposed into a navigable claim tree, each node inspectable, linked back to the PDF). This is genuinely novel and is the product's real differentiator.
- **The scientific judgment** (the scores, the decomposition logic, the synthesized review). This is where the leverage — and most of the problems — live.

---

## 2. What's strong

- **The core metaphor is right.** Representing a paper as a hierarchy of claims from thesis → primary → supporting → evidence is a genuinely good lens on scientific argument, and the interactive frontend makes it legible in a way a prose review never can. This is the thing to protect.
- **Clean separation of deterministic vs. LLM work.** DAG validation, topological sort, ID generation, and output assembly are pure Python. Structured Pydantic hand-offs between stages are the right call and prevent cascading garbage.
- **PDF grounding.** Locating claims back to page/bbox coordinates is a real trust feature — it lets a reader verify the machine, which is exactly what a skeptical scientist wants.
- **You built an evaluation harness at all.** The eLife pilot (10 papers, human reviews as reference, a baseline arm) is the single most valuable thing in the repo. Most projects at this stage have no ground truth. It is already telling you something important — see below.

---

## 3. The central problem: the DAG does not yet earn its keep

The pilot results (`eval/pilot/metrics_summary.json`, n=10) are the most important finding in this review. Comparing the full DAG pipeline (`p2t`) against a single-prompt baseline reviewer:

| Metric | Paper2Tree | Baseline (single prompt) | Winner |
|---|---|---|---|
| BERTScore F1 | 0.834 | 0.836 | baseline |
| ROUGE-L | 0.136 | 0.144 | baseline |
| Cosine sim | 0.683 | 0.661 | p2t |
| Concern recall | 0.439 | 0.436 | tie |
| Concern precision | 0.605 | 0.602 | tie |
| Concern F1 | 0.508 | 0.506 | tie |

**Every difference is inside the noise.** The elaborate multi-agent DAG decomposition produces a final review that is statistically indistinguishable from — and on two of six metrics slightly worse than — a single well-prompted Opus call. The whole apparatus of extraction, enrichment, per-claim evaluation, and synthesis is currently paying for itself only in the interactive artifact, not in review quality.

Two honest caveats before drawing conclusions:
1. **The metrics are weak proxies.** Similarity-to-one-human-review (BERTScore/ROUGE/cosine) rewards surface overlap, not correctness of judgment. A review can be *better* than the human's and score lower. So "no lift" on these metrics is not proof of "no value."
2. **The artifact isn't being measured at all.** The pilot scores prose. The DAG's real value proposition — navigable, node-level, PDF-grounded critique — is invisible to every metric here.

But the conclusion still stands, and it is the strategic crux of the whole project:

> **If the DAG structure is going to justify its cost, it has to change the *judgment*, not just the *presentation*. Right now it changes only the presentation.** The evaluation is structurally flat (see §5), so the tree is decorative at judgment time. That is why the pipeline and the baseline converge.

This is the highest-leverage realization in the review. Everything below either (a) makes the structure load-bearing so the DAG actually reasons better, or (b) trims the parts that add complexity without judgment.

---

## 4. The scoring system — simplify it hard

You flagged this specifically, and you're right: scoring is opaque and distributed. Today each `ClaimEvaluation` carries **up to six** partly-overlapping judgments:

| Field | Type | What it's really measuring |
|---|---|---|
| `support_level` | high/med/low | Is the claim backed by evidence? |
| `is_well_supported` | bool | **Same thing, binarized.** |
| `supporting_evidence_quality` | strong/moderate/weak/absent | **Same thing again, from the evidence side.** |
| `confidence_level` | high/med/low | Model's self-reported meta-confidence |
| `novelty_score` | high/med/low \| null | Only when literature search is on |
| `groundedness_score` | high/med/low \| null | Only when literature search is on |

Three of these six (`support_level`, `is_well_supported`, `supporting_evidence_quality`) are three encodings of one underlying quantity: *how well does the evidence back this claim?* The LLM is being asked to split one judgment into three fields, which produces internal inconsistency (e.g. `support_level: high` with `supporting_evidence_quality: moderate`) and gives the reader three numbers that should never disagree but sometimes do. Only `support_level` actually drives anything — it sets the node color. The other two are shown in the card and do nothing.

**Recommendation — collapse to two orthogonal axes plus a calibration flag:**

1. **`evidence_strength`** (strong / moderate / weak / absent) — the single "how good is the evidence" axis. Absorbs `support_level`, `is_well_supported`, and `supporting_evidence_quality`. Drives node color.
2. **`claim_evidence_calibration`** (overclaimed / calibrated / underclaimed) — *does the strength of the claim match the strength of the evidence?* This is the judgment human reviewers actually make and the system currently does not surface at all. A weakly-supported modest claim and a weakly-supported sweeping claim are very different problems, and only this axis distinguishes them.

**Cut `confidence_level`.** LLM self-reported confidence is poorly calibrated and, in the UI, it just sits next to the support badge as a second number the reader has to reconcile. It adds noise, not signal. If you want uncertainty, express it *in the evidence axis* (that's what "absent" and "weak" are for) or in the notes.

**Make `novelty` and `groundedness` first-class or drop them.** Right now they only exist when live search is on (off by default), rely on keyword search quality (§9), and are visually bolted on. Either commit to them as a real dimension (and evaluate whether the retrieved literature is any good) or remove the half-feature. Half-wired scores erode trust in the whole panel.

Net: **from six scores to two**, both of which map to a decision a reviewer actually makes. That is the simplification you asked for, and it also *improves* judgment by forcing the overclaiming question into the open.

---

## 5. The missing thesis: compositional evaluation

This is the feature that would make the DAG earn its keep, and its absence is why §3 happened.

Today, `evaluate_claims` sends **the whole paper + a flat list of all claims** in one call and scores each claim independently. The tree that was so carefully built is not used during evaluation. Concretely:

- A parent claim is not evaluated *in light of whether its own children hold up*. In a real argument, "our method is state-of-the-art" (parent) is supported *if and only if* the benchmark sub-claims (children) survive scrutiny. The system never checks that the child evidence actually composes into the parent.
- There is no propagation. A root thesis resting on three sub-claims, one of which is `weak`, should inherit doubt. Instead every node is judged in isolation against the full text.

**Recommendation:** evaluate **bottom-up**. Score leaves/evidence nodes first (against the paper), then evaluate each parent *conditioned on the evaluations of its children* — asking specifically "given that child A is strong, child B is weak, does the parent claim follow?" This is the compositional reasoning a DAG uniquely enables and a single prompt cannot do. It is also the most likely thing to open a real quality gap over the baseline, because it lets the system catch *inferential* gaps ("the evidence is fine but it doesn't support the conclusion drawn"), which flat evaluation and single-prompt review both miss.

Secondary but related: the edges are currently **all hardcoded `"supports"`** in the formatter, rather than the `requires` / `contradicts` / `qualifies` typing sketched in the project plan.

**Decision (per project owner): keep the simple `supports`-only structure for now.** Typed edges were tried and found too confusing to work with, and they are *not* a prerequisite for compositional evaluation — bottom-up propagation works fine over a uniform `supports` tree (a parent is judged on how well its supporting children held up). The typed-edge idea is explicitly parked, not on the roadmap. If a future version wants to surface contradictions, the cleaner path is a dedicated "internal contradiction" flag in the evaluation output (the evaluator already notes these in `notes`) rather than reintroducing a full edge-type taxonomy.

---

## 6. Evaluate the things reviewers actually judge

"Support level" is a vague scalar that flattens several distinct scientific concerns into one axis. Real peer review distinguishes failure modes, and different **claim types need different rubrics**:

- An **empirical/measurement** claim → statistical validity, sample size, error bars, reproducibility.
- A **causal** claim → confounds, alternative explanations, whether the design supports causal inference at all.
- A **methodological** choice → justification, ablations, baselines.
- A **generalization** → scope of evidence vs. scope of claim (this is the calibration axis from §4).

The current single prompt asks one skeptical persona to score everything the same way. Tagging each claim with a type (you already classify root/primary/supporting/evidence — this is an *orthogonal* axis) and routing to a type-appropriate rubric is a high-leverage way to inject genuine scientific taste. It's also cheap: it's mostly prompt engineering plus one enum field.

**Also worth fixing:** the evaluator persona is hardcoded to "You are Reviewer 2: thorough, demanding, and unwilling to give the benefit of the doubt." That bakes a **negativity bias** into every score with no calibration. Reviewer-2 theatrics are fun but they systematically distort the support distribution downward, which is exactly the kind of miscalibration that would show up as poor alignment to balanced human assessments. Prefer an explicitly *calibrated* stance ("rigorous and fair; distinguish fatal flaws from minor gaps") over an adversarial one.

---

## 7. Aggregation is naive

`overall_assessment` is a templated string from the raw count of high/low-support claims, and the summary treats every node equally. A paper whose **root thesis is unsupported** but which has twenty well-supported trivial leaf claims will score "strong overall." That is backwards.

**Recommendation:** weight aggregation by **claim centrality** — the root and primary claims should dominate the overall verdict; evidence-level leaves should barely move it. A depth-weighted or root-path-weighted score would make the summary reflect *whether the paper's actual thesis holds*, which is the only question that matters at the top level. This is a small change with a large effect on whether the top-line verdict is trustworthy.

---

## 8. Foundation risk: the extraction is unvalidated

Everything downstream is conditioned on the claim graph being a faithful decomposition of the paper. Yet there is **no evaluation of extraction quality**: are these the right claims? Is the hierarchy correct? Did it miss the paper's actual central contribution? A beautiful evaluation of the wrong claims is worse than useless because it looks authoritative.

**Recommendation:** add an extraction-quality check to the eval harness — even a small human-rated set ("did it capture the true thesis? are the primary claims the real ones? is the tree faithful?"). This is unglamorous but it's the base of the whole stack, and right now it's untested. If extraction is noisy, no amount of evaluation cleverness recovers.

---

## 9. Features to remove or defer

- **`confidence_level`** — cut (§4).
- **`is_well_supported` and `supporting_evidence_quality` as separate fields** — merge into one evidence axis (§4).
- **Live literature search, as currently built** — it's off by default, uses lexical/keyword ranking (`_rank` is token-overlap), and powers two half-wired scores. Either invest in it properly (semantic retrieval, quality-checked passages) or defer it. As-is it adds surface area and a trust liability for little judgment gain. The keyword ranker in particular will surface superficially-matching but conceptually-irrelevant papers, which is worse than no literature.
- **The full vector-KB plan (Qdrant + Voyage) in PROJECT_PLAN.md** — this is a large infra commitment that the pilot gives you no evidence to justify yet. Don't build it until compositional evaluation (§5) shows the core judgment works. Grounding a weak judgment in more literature doesn't fix the judgment.

Do **not** remove: the DAG artifact, PDF grounding, the eval harness, the baseline arm.

---

## 10. What to change, and how it was prioritized

Sections 4–8 each argue for one change. The lens for ranking them is **(leverage on scientific quality) ÷ (effort)**, further weighted by the two strategic answers in §11 (co-equal artifact + review; user is a scientist triaging papers). Rather than repeat a ranking here, the resolved priority lives in **§11 ("Revised top three")** and the executable sequence — which orders by build dependency, not importance — lives in **§13**.

One decision principle that ties them together: after the highest-leverage changes land, **re-run the pilot (§14) and let it referee the premise.** If the DAG still doesn't beat the single-prompt baseline, that is a signal to stop adding judgment features and lean on the DAG-as-navigation artifact instead — not to build more.

---

## 11. Direction (resolved)

Answers to the strategic questions, and what each implies:

- **Deliverable: the artifact and the review are co-equal.** So node-level judgment quality has to improve *and* stay legible in the tree — a change to scoring or evaluation is only "done" when it reads clearly on a node card, not just in the JSON. This raises the bar on the §4 simplification: fewer, meaningful scores per node is now a product requirement, not just cleanup. And §3's "no lift over baseline" *is* a live concern, because the review is half the product.

- **User: a scientist triaging papers to decide what's worth reading.** This is the most consequential answer. It sets the whole calibration target:
  - **Optimize for recall of real flaws and fast navigation to them.** The triaging reader's worst outcome is being told a paper is fine when its thesis is actually unsupported. So the top-line verdict must be dominated by the *central* claims (this makes §7 centrality-weighting a priority, not a nicety) and the UI should route the reader straight to the weakest load-bearing nodes.
  - **But recall of flaws is not the same as the adversarial Reviewer-2 persona (§6).** A triaging reader needs *true* flaws surfaced, not a uniformly harsh take that cries wolf on every node — that destroys the signal they're triaging on. Keep the persona calibrated; use the `claim_evidence_calibration` axis and centrality weighting to make severity legible instead of cranking negativity.
  - Implication for the frontend: a "why should I (not) read this" summary that leads with the most central weak claims would serve this user better than the current templated count-based `overall_assessment`.

- **Cost/latency: worth it for better judgment.** Green light on compositional bottom-up evaluation (§5) even though it serializes parent-after-children. This is now the flagship judgment change. Note you don't lose all parallelism — siblings at the same level still evaluate concurrently; only the depth dimension serializes. Concretely: evaluate by depth, deepest first, all nodes at a given depth in parallel, passing children's evaluations up as context to their parents.

### Revised top three, given the above
1. **Compositional bottom-up evaluation** (§5) — now the flagship, explicitly funded on latency. Most likely to open a real gap over baseline and to catch inferential/overclaiming failures the triaging reader cares about most.
2. **Simplify scoring to two axes** (§4) — required for co-equal artifact legibility; adds the overclaiming judgment the triaging reader needs.
3. **Centrality-weighted aggregation + a "worth reading?" summary** (§7) — directly serves the triage use case; ensures the verdict tracks whether the *thesis* holds, not leaf trivia.

Then: type-specific rubrics + de-biased persona (§6), validate extraction (§8), and re-run the pilot to check whether the gap over baseline finally opens.

### Still worth confirming later (not blocking)
- **Domain scope** (biomedical vs. general science) — determines whether type-specific rubrics (§6) encode wet-lab/statistical norms vs. ML/CS norms, and whether PubMed is the right literature source if you revisit grounding. The current pilot is all eLife/biomedical, so defaulting there is safe for now.

---

## 12. Cross-check against the open GitHub issues

I reviewed the nine open issues. Several are direct, independent confirmation of this critique — worth pulling into the plan; others are out of scope for a judgment-quality release.

**Fold into this plan (they *are* this plan):**

- **#2 "add model for node scores"** — *"scores for each node should be determined in part by the nodes below — right now, they are just determined for the claim itself."* This is **exactly §5 (compositional evaluation)**, independently arrived at. It's the strongest signal that compositional scoring is the right flagship. This work closes #2.
- **#1 "add a summary review / top-level view"** — the summary review now exists (`final_review`), but the issue's second half — *"this final reviewer could also recalibrate claim-level scores based on dependent nodes"* — is again §5/§7. The centrality-weighted "worth reading?" summary (§7, §11) is the top-level triage view this issue wants. Partially done; the recalibration part is folded into this plan.
- **#3 "scope follow-ups and suggestions"** — *"not every suggested follow-up is reasonable… break down into minor and major… don't discourage authors by being overly prescriptive."* This maps onto the **de-biased persona (§6)** and directly serves the triaging reader (§11): flaws should be **severity-ranked (major vs. minor), not a flat wall of demands.** Add explicit major/minor scoping to the review synthesis as part of the §6 work.

**Fold into §8 (foundation reliability), not judgment, but do it in this cycle:**

- **#7 "Opus refuses structured extraction for some arXiv papers"** — deterministic `stop_reason='refusal'` on the text extractor kills whole papers before any judgment happens. A broken foundation invalidates every downstream score. Cheap fix (Sonnet fallback on refusal) and it protects the eval pipeline from silent sample dropouts. Include it.
- **#6 "Frontend JSON parse error when no papers exist"** — minor empty-state bug; fix opportunistically, not gating.

**Explicitly defer (out of scope for a judgment release):**

- **#8 "chat with claim nodes"** — a genuinely good artifact feature (fits the co-equal-artifact goal and the triaging reader who wants to interrogate a node), but it's additive UX, not judgment quality. Park until the core judgment gap over baseline is proven. Note it as the natural *next* release after this one.
- **#5 "MCP / CLI tool"** and **#9 "Claude plugin"** — already shipped in 1.7.0 per the CHANGELOG; appear stale. Close or update.
- **#4 "better name"** — cosmetic; ignore for now.

---

## 13. Implementation plan

Target release: **v2.0.0** (MAJOR). This release *removes* three `ClaimEvaluation` fields (`confidence_level`, `is_well_supported`, `supporting_evidence_quality`) and changes the semantics of the scores (flat → compositional). Under the project's own versioning rule — MAJOR = "breaking changes to the data schema… requires a migration script for existing artifacts" — that is unambiguously a major bump, not a minor one. We therefore bump `SCHEMA_VERSION` to 3 and ship a real migration rather than carrying the removed fields as optional deadweight. Work in a feature branch, one PR per phase so each is reviewable and independently revertible.

### Implementation status — *comparison-ready; feature development paused here*

Work is on branch **`v2-compositional-evaluation`**. Per the directive to stop adding features once a v1.7-vs-v2 comparison is possible, everything needed to run that comparison is done; the remaining phases are intentionally **not** started.

| Phase | Status | Notes |
|---|---|---|
| 0 — Baseline lock-in | ⏳ **user action** | Run `eval/pilot_study.py` (n=20) on both code versions; `eval/compare.py` is ready to pair them. Requires API tokens — left to you (budget). |
| 1 — Simplify scoring | ✅ done | `evidence_strength` + `claim_evidence_calibration`; `confidence_level`/`is_well_supported`/`supporting_evidence_quality` removed. Schema, prompt, formatter, final reviewer, CLI, frontend, tests all updated. |
| 2 — Compositional evaluation | ✅ done | `claim_evaluator` now evaluates depth-by-depth, deepest first, parents conditioned on children (evidential vs. inferential gaps). New tests assert ordering + child context. |
| 3 — Centrality-weighted aggregation | ✅ done | Weighted verdict + "worth reading?" framing; a weak thesis with strong leaves no longer reads "strong". Tests cover the old bug. |
| Migration v2→v3 | ✅ done | `migrations/migrate_v2_to_v3.py` + 9 tests; all 9 committed artifacts migrated and re-validated; `index.json` rebuilt. |
| Eval harness | ✅ done | `eval/compare.py` (paired Wilcoxon / bootstrap CI); pilot default raised to 20. |
| Docs + version | ✅ done | `pyproject` → 2.0.0; CHANGELOG 2.0.0 entry; README scoring section. |
| 4 — Type rubrics + de-biased persona | ⏸ **paused** | Persona already softened in Phase 1's prompt; full `claim_nature` rubric routing deferred until the comparison validates the approach. |
| 5 — Foundation reliability (#7) | ⏸ **paused** | Deferred. |

Full Python suite: **169 tests passing.** Next action is **Phase 0** — run the paired comparison (§14) and let it decide whether to resume Phase 4/5 or rethink.

### Phase 0 — Baseline lock-in (do this first, before touching any logic)
The pilot is the referee for the whole release. Freeze it so "before vs. after" is a fair comparison.
1. **Expand the sample to 20 papers.** 10 is underpowered to detect a small lift (the current p2t-vs-baseline deltas are ~0.002, far inside the stdev). 20 is a deliberate compromise between statistical power and token budget: it roughly doubles sensitivity over the current set while keeping the run affordable — enough to catch a real effect, though very small effects may still be missed. Draw the 10 new papers from the same eLife source (`eval/elife_parser.py`) so the reference reviews stay comparable.
2. **Lock the v1.7 control on all 20 papers.** Run the current pipeline (`eval/pilot_study.py`) — both the DAG (`p2t`) arm and the single-prompt baseline arm — across the full 20-paper set and snapshot the metrics as `eval/pilot/baseline_v1.7.json`. (Confirm the 10 original papers still reproduce `metrics_summary.json` along the way.) Every later comparison is against this 20-paper control.
3. Add per-paper result persistence so paired comparisons are possible (see §14).

### Phase 1 — Simplify scoring (§4)  → closes part of the scoring opacity
1. `src/schemas/evaluation.py`: replace `support_level`, `is_well_supported`, `supporting_evidence_quality` with a single `evidence_strength: Literal["strong","moderate","weak","absent"]`; add `claim_evidence_calibration: Literal["overclaimed","calibrated","underclaimed"]`; **remove `confidence_level`**. Leave `novelty_score`/`groundedness_score` untouched this release — they're tied to literature search, which stays out of scope (§9), so the §4 "make first-class or drop" decision is deferred with them, not resolved here.
2. `src/prompts/claim_evaluator.txt`: rewrite the criteria block for the two new axes; drop the confidence instruction; explain the calibration axis with an example.
3. `src/agents/output_formatter.py`: `_support_color` → `_evidence_color` keyed on `evidence_strength`; update `high_support_nodes`/`low_support_nodes` counting; update `_overall_assessment`.
4. `src/schemas/output.py` + `DAGSummary`: rename the summary counters to match (keep JSON keys stable where the frontend depends on them, or update both sides together).
5. Frontend: `EvalBadge`, `NodeCard.tsx`, `ClaimNode.tsx`, `types/dag.ts` — render `evidence_strength` + a new calibration chip (e.g. amber "overclaimed"); delete the confidence and evidence-quality lines.
6. **Migration:** bump `SCHEMA_VERSION` to 3 and add `migrations/migrate_v2_to_v3.py` (mirroring the existing `migrate_v1_to_v2.py`). The migration maps old artifacts forward: derive `evidence_strength` from the old `supporting_evidence_quality` (or map `support_level` if absent), set `claim_evidence_calibration` to `"calibrated"` as a neutral default (it's a new judgment we can't retro-infer), and drop `confidence_level`/`is_well_supported`. The frontend then only has to understand v3; no dual-path rendering. Old node colors were keyed on `support_level` → re-key on the migrated `evidence_strength`.
7. **Tests:** update `tests/test_schemas_claim.py`-style coverage for the new `ClaimEvaluation`; add a test asserting `_evidence_color` mapping; add a **migration test** — feed a real v2 artifact through `migrate_v2_to_v3.py` and assert the result validates as v3 with `evidence_strength` correctly derived and `confidence_level`/`is_well_supported` gone.

### Phase 2 — Compositional bottom-up evaluation (§5)  → closes #2, part of #1  → the flagship
1. `src/agents/claim_evaluator.py`: replace the single flat call with depth-ordered evaluation. Group `enriched` claims by `depth`; evaluate deepest depth first, all nodes at a depth concurrently (`asyncio.gather`), then pass each node's children's evaluations up as context when evaluating its parents. Preserve sibling parallelism; only depth serializes.
2. New prompt (or a branch in `claim_evaluator.txt`) for the "parent conditioned on children" case: include a "child claim evaluations" block and instruct the model to judge whether the children's evidence actually composes into the parent — flag **inferential gaps** (children hold but don't support the parent) distinctly from **evidential gaps** (children themselves weak).
3. Keep a `max_concurrency` cap so wide levels don't blow rate limits.
4. **Tests:** a synthetic 3-level DAG fixture; assert evaluation order is leaves-before-parents; assert a parent whose children are all `absent` cannot be scored `strong` (a soft invariant enforced in prompt + a sanity assertion in tests using a stubbed LLM via the existing `tests/test_llm.py` mocking pattern).

### Phase 3 — Centrality-weighted aggregation + triage summary (§7, §11)  → closes part of #1
1. `output_formatter.py`: weight the overall verdict by claim centrality (root/primary dominate; evidence leaves contribute little). Simplest defensible scheme: weight ∝ `1/(depth+1)` or an explicit `{root:4, primary:2, supporting:1, evidence:0.5}` map. Replace the templated count-based `_overall_assessment` with a weighted score → verdict band.
2. Add a short **"worth reading?"** framing to `overall_assessment` that leads with the most central weak claims (the triaging reader's core need).
3. **Tests:** a DAG with a weak root + many strong leaves must produce a non-"strong" overall verdict (the current bug); a DAG with strong root + weak leaves stays favorable.

### Phase 4 — Type-specific rubrics + de-biased persona (§6)  → closes #3
1. Add `claim_nature: Literal["empirical","causal","methodological","interpretive"]` to `Claim` (extractor assigns it) — orthogonal to the existing root/primary/supporting/evidence axis.
2. `claim_evaluator.txt`: branch the rubric on `claim_nature` (causal → confounds/alternatives; empirical → stats/repro; etc.).
3. Replace the "Reviewer 2, unwilling to give benefit of the doubt" persona with a **calibrated** one ("rigorous and fair; distinguish fatal flaws from minor gaps; do not manufacture concerns").
4. Review synthesis: **severity-scope** weaknesses into major vs. minor (closes #3) so the triaging reader isn't handed a flat wall of demands.
5. **Tests:** extraction test asserting `claim_nature` is populated and valid; a persona regression check that a deliberately-solid claim isn't scored `weak` (guards against negativity bias) using a canned strong-paper fixture.

### Phase 5 — Foundation reliability (§8, #7)
1. `src/agents/text_extractor.py`: on `stop_reason == 'refusal'`, fall back to Sonnet automatically; restructure the prompt (instructions first, content framed as data, drop raw `---` delimiters). Consider Sonnet as the default for extraction (cheaper, rarely refuses).
2. Add an **extraction-quality mini-eval** (§8): a small human-rated set scoring "captured the true thesis / correct primary claims / faithful tree." Even 5–10 hand-checked papers establishes a floor.
   - Note: this cycle keeps the *text-only* extraction backend. The larger structured + multimodal extraction upgrade is evaluated separately in §15 and deliberately deferred.
3. **Tests:** a refusal-path unit test (mock a `refusal` stop_reason, assert Sonnet fallback fires).

### Phase 6 — Docs, version, changelog (every phase contributes; finalize here)
1. **README.md** — update the scoring description (two axes, not six), the evaluation section (compositional), and remove references to `confidence_level`.
2. **PROJECT_PLAN.md** — reconcile the `ClaimEvaluation` schema block and the (now `supports`-only, typed-edges parked) DAG description with reality.
3. **CHANGELOG.md** — add a `## [2.0.0]` entry and call out the breaking change prominently: Added (calibration axis, compositional evaluation, type rubrics, extraction fallback), Changed (scoring collapsed to two axes, centrality-weighted verdict, calibrated persona, `SCHEMA_VERSION` 2→3), Removed (`confidence_level`, `is_well_supported`, `supporting_evidence_quality`). Document the `migrate_v2_to_v3.py` step and that existing artifacts must be migrated.
4. **`pyproject.toml`** — bump `version` to `2.0.0`.
5. Close/annotate issues #1, #2, #3, #7 with the PRs; update the stale #5/#9.

### Sequencing note
**Phase numbers reflect build dependencies, not importance** — the flagship by priority is Phase 2 (compositional evaluation, §11), but it can't land until Phase 1 ships the new schema it consumes. Phases 1, 3, and 5 are independent and can land in any order; Phase 2 and Phase 4 both depend on Phase 1. Land Phase 0 first, always.

---

## 14. Measuring whether it actually worked

The whole point of §3 is that we currently can't claim improvement. This release must be judged by the eval harness, not by inspection. Concrete protocol:

**Setup (Phase 0):**
- Freeze the **v1.7 control**: the current pipeline's reviews on the 20-paper sample, scored and saved as `baseline_v1.7.json`. Keep the **single-prompt baseline arm** — it's the "is the DAG worth it" referee.
- Persist per-paper results (not just aggregates) so we can run **paired** statistics.

**Primary success criteria (pre-registered, decide the thresholds *before* running):**
1. **Does the DAG finally beat the single-prompt baseline?** The core §3 question. Compare v2.0 p2t vs. baseline on the existing metrics (BERTScore F1, ROUGE-L, cosine, concern recall/precision/F1). Because deltas are tiny, use a **paired test** (Wilcoxon signed-rank across papers) and report the effect size + CI, not just means. Target: p2t significantly ≥ baseline on concern-F1 and cosine, no regression on the rest.
2. **Did v2.0 improve over v1.7?** Paired comparison p2t-v2.0 vs. p2t-v1.7 on the same papers. This isolates the value of *this release* from the DAG-vs-baseline question.

**New metrics to add (the current suite doesn't test what we changed):**
3. **Overclaiming detection** — hand-label a small set of claims known to be over/under/calibrated (or seed with a few deliberately-overclaimed papers) and measure agreement of the new `claim_evidence_calibration` axis. Without this, the new axis is unmeasured.
4. **Verdict correctness on the thesis** — because the triaging reader cares about the *central* claim: check whether the centrality-weighted overall verdict flips correctly on a constructed pair (a paper with strong leaves but a broken thesis should read unfavorable). This tests §7 directly; the existing similarity metrics won't catch it.
5. **eLife Assessment / recommendation alignment** — the harness already has `assessment_alignment` and `elife_assessment_ordinal`; make sure the new verdict feeds them and report whether alignment to the human eLife assessment improves.
6. **Extraction fidelity** (§8 mini-eval) — report the human-rated thesis-capture rate as a gate; if extraction is unreliable, judgment metrics are uninterpretable.

**Guardrails / cost tracking:**
7. **Latency & token cost per paper**, v1.7 vs v2.0 — compositional evaluation serializes by depth, so this *will* rise. Record it so the "worth it for judgment" trade (§11) is quantified, not assumed.
8. **No silent sample loss** — with the #7 fix, confirm all sample papers actually complete extraction; a dropped paper biases the comparison.

**Decision rule:**
- If criterion 1 holds (DAG now beats baseline) → the compositional bet paid off; ship and double down.
- If criterion 2 holds but 1 doesn't (better than v1.7 but still ≈ baseline) → the release improved the product but the DAG still isn't justified *by the prose review alone*; lean harder on the artifact half of the value prop (§11) and reconsider whether the review needs the DAG at all.
- If neither holds → stop and reconsider the premise before building more; the artifact remains the defensible value, and the judgment layer needs a rethink rather than more features.

Report all of this in `eval/pilot/v2.0_report.md` alongside the qualitative notes template that already exists.

---

## 15. Future direction: structured + multimodal extraction (evaluated, deferred)

**The idea (from a reviewer):** replace the current text-only PDF path with a structured extractor like **Docling** or **MinerU**, and add a **multimodal LLM** to understand figures. Verdict: **genuinely strong — probably the single highest-ceiling improvement available — but explicitly deferred to a dedicated release *after* v2.0, for a methodological reason, not because it's low-value.**

### Why it matters (and why it's a real gap, not a nicety)
Today extraction is `pdfplumber.extract_text()` → a flat text blob. Tables arrive as mangled inline text; **figures are absent entirely** (images aren't extracted, and the structuring LLM never sees one). Yet in experimental science — and the entire eLife pilot is experimental biology — **the evidence lives in the figures and tables**: blots, dose-response curves, microscopy, error bars, n's, significance markers, supplementary tables. The claim evaluator is currently asked "is this claim supported by the evidence?" while structurally blind to the primary evidence. That is a foundational ceiling on judgment quality that no amount of compositional-evaluation cleverness (§5) can lift. It is plausibly a *larger* lever than anything in v2.0.

### The proposal has two separable parts, with different risk profiles
1. **Structured text extraction** (Docling / MinerU): correct reading order, tables as structured data, figure/caption detection with bounding boxes, formula handling. **Moderate effort, clear win, low risk.** Captions and table cells are text and are evidence-dense; capturing them well would materially improve both claim extraction and evaluation on its own.
2. **Figure *understanding*** (multimodal LLM over the extracted figure crops): **higher ceiling, higher risk.** Vision models are known to confabulate on scientific figures — misreading axis scales, error bars, significance stars, and sample sizes. A wrong figure description fed into the scoring path could make judgment *worse*, not better. This part needs its **own validation** before it's trusted in the evaluator. Because Claude is natively multimodal, prefer passing figure crops **directly** to the claim evaluator over a lossy text-summary intermediate — fewer places to hallucinate, and the evaluator sees the actual pixels alongside the claim.

### Docling vs. MinerU (brief)
- **Docling** (IBM, open source): strong layout analysis, table structure, reading order; clean Python API and export formats; actively maintained. Best default for born-digital biomedical PDFs (which is most of the eLife corpus).
- **MinerU**: strong on formulas, complex layouts, and OCR of scanned documents. Prefer it for math-heavy or scanned/low-quality PDFs.
- **Recommendation:** prototype **Docling first** against the pilot PDFs; keep MinerU as the fallback for documents Docling handles poorly. Nicely, the existing PDF-grounding infrastructure (`locate_claims`, `page_number`/`bbox`) is already spatially aware, so figure objects (caption + image + bbox) extend it naturally rather than fighting it.

### Why defer it from v2.0 (the decisive reason)
- **Don't change extraction and judgment in the same release.** §14's entire design is a clean paired comparison that isolates the value of compositional evaluation. If the extraction backend *also* changes in v2.0, no metric movement can be attributed to either cause — the experiment is confounded and the release can't answer its own question. Hold extraction constant through v2.0.
- **It doesn't confound the v2.0 question anyway**, because both current arms (the DAG pipeline *and* the single-prompt baseline) are equally text-blind. Figure-blindness is a *separable* axis, so deferring it costs nothing in the v2.0 comparison.
- **Scope**: it's an ingestion overhaul with its own dependency, cost, and evaluation needs — a coherent release of its own, not a phase bolted onto an already-large v2.0.

### The one principled way to include part of it now
If you want better extraction *in* v2.0, the only clean way is to apply the new backend to **both arms** and **re-baseline before Phase 0 locks the control** — i.e. re-run the v1.7 pipeline on the new extraction too, so v1.7-control and v2.0 share identical ingestion. Any other path (upgrading only the DAG arm, or upgrading mid-release) breaks the comparison. My recommendation is still to hold the line and keep v2.0 focused, but this is the escape hatch if the figure gap feels too urgent to wait.

### Recommended plan
- **v2.0:** unchanged — text-only, focused on judgment logic.
- **Next release (v2.1 or a v3.0 track):** structured extraction (Docling) first, measured on the extraction mini-eval (§13 Phase 5) *plus* a new **figure-grounding metric** — does adding figure/table understanding raise concern-recall and catch evidence-level weaknesses the text-only version provably missed? Ship figure *understanding* only after it clears a hallucination check on a hand-labeled figure set. Given the co-equal-artifact goal, this also unlocks showing figure crops in the node card, which strengthens the artifact half of the product.
- Treat this as the **leading candidate for the release after v2.0**, especially if v2.0's eval shows the DAG still isn't clearly beating the baseline — because then "both arms are blind to the evidence" becomes the most likely explanation, and this is the fix.
