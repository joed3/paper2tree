"""
Pilot evaluation for paper2tree vs. single-agent reviewer.

Samples 10 eLife papers, runs both review systems, computes metrics,
and writes results to --output-dir (default: eval/pilot/).

Usage:
    python -m eval.pilot_study [OPTIONS]

Options:
    --n N               Papers to sample (default: 10)
    --seed SEED         Random seed (default: 42)
    --output-dir DIR    Output directory (default: eval/pilot)
    --github-token TOK  GitHub API token (or set GITHUB_TOKEN env var)
    --force             Re-run all steps even if outputs exist
    --self-consistency  Add self-consistency check on 3 longest papers
    --skip-pipeline     Skip pipeline; use existing dag.json files only
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from eval.elife_parser import (
    LOCAL_REPO_DEFAULT,
    ELifePaper,
    parse_article,
    read_article_github,
    read_article_local,
    sample_eligible_papers,
)
from eval.metrics import compute_metrics
from src.agents.baseline_reviewer import generate_baseline_review
from src.agents.claim_evaluator import evaluate_claims
from src.agents.claim_extractor import extract_claims
from src.agents.final_reviewer import generate_review
from src.agents.output_formatter import format_output
from src.schemas.output import PaperDAG
from src.schemas.paper import ExtractedPaper
from src.utils.graph import build_dag

# ── Pipeline helper ────────────────────────────────────────────────────────────


async def build_paper_dag(paper: ELifePaper, log=print) -> PaperDAG:
    """Run the paper2tree pipeline on an eLife paper (text only, no PDF fetch)."""
    log("    [3/6] Extracting claims…")
    claim_graph = await asyncio.to_thread(extract_claims, paper.article_text)
    log(f"    [4/6] Building DAG ({len(claim_graph.claims)} claims)…")
    enriched = build_dag(claim_graph)
    log(f"    [5/6] Evaluating {len(enriched)} claims…")
    evaluations = await evaluate_claims(enriched, paper.article_text)
    log("    [6/6] Formatting output…")

    extracted = ExtractedPaper(
        title=paper.title,
        authors=paper.authors,
        abstract=paper.abstract,
        sections=[],
        full_text=paper.article_text,
        word_count=paper.word_count,
    )
    paper_id = f"elife_{paper.article_id}"
    url = f"https://doi.org/{paper.doi}" if paper.doi else f"elife:{paper.article_id}"

    return format_output(paper_id, url, extracted, enriched, evaluations, has_local_pdf=False)


# ── Per-paper processing ───────────────────────────────────────────────────────


async def process_paper(
    paper: ELifePaper,
    paper_dir: Path,
    force: bool,
    skip_pipeline: bool,
    log=print,
) -> bool:
    """Process a single paper. Returns True on success."""
    paper_dir.mkdir(parents=True, exist_ok=True)

    # ── Human review ──────────────────────────────────────────────────────────
    human_path = paper_dir / "human_review.txt"
    if not human_path.exists():
        human_path.write_text(paper.human_review)

    if paper.elife_assessment:
        (paper_dir / "elife_assessment.txt").write_text(paper.elife_assessment)

    # ── Write metadata ────────────────────────────────────────────────────────
    meta_path = paper_dir / "metadata.json"
    if not meta_path.exists():
        meta_path.write_text(
            json.dumps(
                {
                    "article_id": paper.article_id,
                    "filename": paper.filename,
                    "doi": paper.doi,
                    "title": paper.title,
                    "authors": paper.authors,
                    "year": paper.year,
                    "subject_areas": paper.subject_areas,
                    "category": paper.category,
                    "word_count": paper.word_count,
                },
                indent=2,
            )
        )

    # ── Build DAG ─────────────────────────────────────────────────────────────
    dag_path = paper_dir / "dag.json"
    if skip_pipeline and not dag_path.exists():
        log(f"  SKIP {paper.article_id}: --skip-pipeline but no dag.json found")
        return False

    if not skip_pipeline and (force or not dag_path.exists()):
        log(f"  [pipeline] {paper.title[:60]}…")
        t0 = time.time()
        try:
            dag = await build_paper_dag(paper, log=log)
        except Exception as e:
            log(f"  ERROR building DAG for {paper.article_id}: {e}")
            return False
        dag_path.write_text(dag.model_dump_json(indent=2))
        log(f"    DAG written ({len(dag.dag.nodes)} nodes, {time.time()-t0:.0f}s)")

    # Load DAG
    try:
        dag = PaperDAG.model_validate_json(dag_path.read_text())
    except Exception as e:
        log(f"  ERROR loading dag.json for {paper.article_id}: {e}")
        return False

    # ── Final reviewer (DAG-grounded) ─────────────────────────────────────────
    p2t_path = paper_dir / "paper2tree_review.txt"
    if force or not p2t_path.exists():
        log(f"  [final_reviewer] {paper.article_id}…")
        t0 = time.time()
        try:
            review = await asyncio.to_thread(
                generate_review, paper.article_text, dag, "final_reviewer_elife_dag_only"
            )
        except Exception as e:
            log(f"  ERROR in final reviewer for {paper.article_id}: {e}")
            return False
        p2t_path.write_text(review)
        log(f"    paper2tree review written ({len(review.split())} words, {time.time()-t0:.0f}s)")

    # ── Baseline reviewer ─────────────────────────────────────────────────────
    baseline_path = paper_dir / "baseline_review.txt"
    if force or not baseline_path.exists():
        log(f"  [baseline_reviewer] {paper.article_id}…")
        t0 = time.time()
        try:
            review = await asyncio.to_thread(
                generate_baseline_review, paper.article_text, "baseline_reviewer_elife"
            )
        except Exception as e:
            log(f"  ERROR in baseline reviewer for {paper.article_id}: {e}")
            return False
        baseline_path.write_text(review)
        log(f"    baseline review written ({len(review.split())} words, {time.time()-t0:.0f}s)")

    return True


# ── Metrics computation ────────────────────────────────────────────────────────


def compute_all_metrics(output_dir: Path, log=print) -> list[dict]:
    """Compute metrics for all completed papers in output_dir."""
    rows: list[dict] = []

    for paper_dir in sorted(output_dir.iterdir()):
        if not paper_dir.is_dir():
            continue

        # Check required files exist
        required = ["human_review.txt", "paper2tree_review.txt", "baseline_review.txt"]
        if not all((paper_dir / f).exists() for f in required):
            log(f"  SKIP {paper_dir.name}: missing files")
            continue

        human = (paper_dir / "human_review.txt").read_text()
        p2t = (paper_dir / "paper2tree_review.txt").read_text()
        baseline = (paper_dir / "baseline_review.txt").read_text()
        assessment = (
            (paper_dir / "elife_assessment.txt").read_text()
            if (paper_dir / "elife_assessment.txt").exists()
            else None
        )

        meta: dict = {}
        meta_path = paper_dir / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())

        log(f"  Computing metrics for {paper_dir.name}…")
        p2t_metrics = compute_metrics(p2t, human, elife_assessment=assessment)
        baseline_metrics = compute_metrics(baseline, human, elife_assessment=assessment)

        rows.append(
            {
                "article_id": meta.get("article_id", paper_dir.name),
                "title": meta.get("title", "")[:80],
                "year": meta.get("year", ""),
                "category": meta.get("category", ""),
                "word_count_article": meta.get("word_count", ""),
                "word_count_human_review": len(human.split()),
                "word_count_p2t_review": len(p2t.split()),
                "word_count_baseline_review": len(baseline.split()),
                "p2t_bertscore_f1": p2t_metrics["bertscore_f1"],
                "baseline_bertscore_f1": baseline_metrics["bertscore_f1"],
                "p2t_rouge_l": p2t_metrics["rouge_l"],
                "baseline_rouge_l": baseline_metrics["rouge_l"],
                "p2t_cosine_similarity": p2t_metrics["cosine_similarity"],
                "baseline_cosine_similarity": baseline_metrics["cosine_similarity"],
                "p2t_recommendation": p2t_metrics["recommendation"],
                "baseline_recommendation": baseline_metrics["recommendation"],
                "p2t_assessment_alignment": p2t_metrics["assessment_alignment"],
                "baseline_assessment_alignment": baseline_metrics["assessment_alignment"],
                "p2t_concern_recall": p2t_metrics["concern_recall"],
                "baseline_concern_recall": baseline_metrics["concern_recall"],
                "p2t_concern_precision": p2t_metrics["concern_precision"],
                "baseline_concern_precision": baseline_metrics["concern_precision"],
                "p2t_concern_f1": p2t_metrics["concern_f1"],
                "baseline_concern_f1": baseline_metrics["concern_f1"],
            }
        )

    return rows


def write_metrics_csv(rows: list[dict], output_dir: Path, log=print) -> None:
    if not rows:
        log("  No completed papers to compute metrics for")
        return

    csv_path = output_dir / "metrics.csv"
    fieldnames = list(rows[0].keys())
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Summary stats
    import statistics

    numeric = [
        "p2t_bertscore_f1",
        "baseline_bertscore_f1",
        "p2t_rouge_l",
        "baseline_rouge_l",
        "p2t_cosine_similarity",
        "baseline_cosine_similarity",
        "p2t_concern_recall",
        "baseline_concern_recall",
        "p2t_concern_precision",
        "baseline_concern_precision",
        "p2t_concern_f1",
        "baseline_concern_f1",
    ]
    summary_rows = []
    for col in numeric:
        vals = [r[col] for r in rows if r[col] is not None]
        if vals:
            summary_rows.append(
                {
                    "metric": col,
                    "mean": round(statistics.mean(vals), 4),
                    "stdev": round(statistics.stdev(vals), 4) if len(vals) > 1 else None,
                    "min": round(min(vals), 4),
                    "max": round(max(vals), 4),
                    "n": len(vals),
                }
            )

    summary_path = output_dir / "metrics_summary.json"
    summary_path.write_text(json.dumps(summary_rows, indent=2))
    log(f"  metrics.csv written ({len(rows)} papers)")
    log("  metrics_summary.json written")

    # Print summary table
    log("\n  ┌─────────────────────────────────────────────┬────────┬────────┐")
    log("  │ Metric                                      │  Mean  │ StDev  │")
    log("  ├─────────────────────────────────────────────┼────────┼────────┤")
    for s in summary_rows:
        log(f"  │ {s['metric']:<43} │ {s['mean']:.4f} │ {str(s['stdev'] or 'N/A'):<6} │")
    log("  └─────────────────────────────────────────────┴────────┴────────┘")


def write_qualitative_notes(rows: list[dict], output_dir: Path) -> None:
    """Write a template qualitative_notes.md for manual side-by-side reading."""
    lines = [
        "# Pilot Study — Qualitative Notes",
        "",
        "For each paper, read `paper2tree_review.txt`, `baseline_review.txt`, and "
        "`human_review.txt` side-by-side and fill in the observations below.",
        "",
    ]
    for row in rows:
        aid = row["article_id"]
        lines += [
            f"## {aid} — {row['title']}",
            "",
            f"**paper2tree BERTScore F1**: {row['p2t_bertscore_f1']:.4f}  "
            f"**baseline**: {row['baseline_bertscore_f1']:.4f}",
            "",
            "**Observations**:",
            "",
            "- Which system captures concerns the other misses:",
            "  _[fill in]_",
            "",
            "- Is the DAG grounding visible in the paper2tree review:",
            "  _[fill in]_",
            "",
            "- Obvious failure modes:",
            "  _[fill in]_",
            "",
            "---",
            "",
        ]
    (output_dir / "qualitative_notes.md").write_text("\n".join(lines))


# ── Self-consistency check ─────────────────────────────────────────────────────


async def run_self_consistency_check(
    papers: list[ELifePaper],
    output_dir: Path,
    log=print,
) -> None:
    """Re-run pipeline on 3 longest papers; compute within-paper BERTScore."""
    from eval.metrics import bertscore_f1

    sorted_papers = sorted(papers, key=lambda p: p.word_count, reverse=True)
    check_papers = sorted_papers[:3]
    log(f"\n[Self-consistency] Re-running {len(check_papers)} papers…")

    sc_results = []
    for paper in check_papers:
        paper_dir = output_dir / paper.article_id
        run2_dir = paper_dir / "run2"
        run2_dir.mkdir(exist_ok=True)

        log(f"  Re-running {paper.article_id} (word_count={paper.word_count:,})…")
        try:
            dag2 = await build_paper_dag(paper, log=log)
            (run2_dir / "dag.json").write_text(dag2.model_dump_json(indent=2))
            review2 = await asyncio.to_thread(generate_review, paper.article_text, dag2)
            (run2_dir / "paper2tree_review.txt").write_text(review2)
        except Exception as e:
            log(f"  ERROR on run2 for {paper.article_id}: {e}")
            continue

        # Compare run1 vs run2
        run1_path = paper_dir / "paper2tree_review.txt"
        if not run1_path.exists():
            log(f"  SKIP: no run1 review for {paper.article_id}")
            continue
        review1 = run1_path.read_text()
        score = bertscore_f1(review2, review1)
        sc_results.append({"article_id": paper.article_id, "bertscore_f1_run1_vs_run2": score})
        log(f"    BERTScore F1 (run1 vs run2): {score:.4f}")

    if sc_results:
        import statistics

        scores = [r["bertscore_f1_run1_vs_run2"] for r in sc_results]
        mean_score = statistics.mean(scores)
        passed = mean_score >= 0.85
        log(
            f"\n  Self-consistency mean BERTScore F1: {mean_score:.4f} "
            f"({'PASS ✓' if passed else 'FAIL ✗'} — threshold 0.85)"
        )

        sc_path = output_dir / "self_consistency.json"
        sc_path.write_text(
            json.dumps(
                {
                    "results": sc_results,
                    "mean_bertscore_f1": mean_score,
                    "threshold": 0.85,
                    "passed": passed,
                },
                indent=2,
            )
        )
        log("  self_consistency.json written")


# ── Figures ───────────────────────────────────────────────────────────────────


def generate_figures(output_dir: Path, log=print) -> None:
    """Generate performance plots from metrics.csv into output_dir/figures/."""
    try:
        import pandas as pd
        from plotnine import (
            aes,
            element_blank,
            element_line,
            element_rect,
            element_text,
            geom_abline,
            geom_bar,
            geom_col,
            geom_errorbar,
            geom_point,
            ggplot,
            labs,
            position_dodge,
            scale_fill_manual,
            theme,
            ylim,
        )
    except ImportError as exc:
        log(f"  SKIP figures: {exc} — run: pip install -e '.[eval]'")
        return

    csv_path = output_dir / "metrics.csv"
    if not csv_path.exists():
        log(f"  SKIP figures: {csv_path} not found")
        return

    df = pd.read_csv(csv_path)
    if df.empty:
        log("  SKIP figures: metrics.csv is empty")
        return

    figures_dir = output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)

    # ── Colour palette ──────────────────────────────────────────────────────
    BG = "#0f172a"
    PANEL = "#1e293b"
    TEXT = "#e2e8f0"
    GRID = "#334155"
    P2T_COLOR = "#818cf8"
    BASE_COLOR = "#64748b"

    def dark_theme():
        return theme(
            plot_background=element_rect(fill=BG, color=BG),
            panel_background=element_rect(fill=PANEL),
            panel_grid_major=element_line(color=GRID, size=0.4),
            panel_grid_minor=element_blank(),
            panel_border=element_blank(),
            axis_line=element_line(color=TEXT, size=0.4),
            axis_text=element_text(color=TEXT, size=9),
            axis_title=element_text(color=TEXT, size=10),
            plot_title=element_text(color=TEXT, size=12, face="bold"),
            legend_background=element_rect(fill=BG, color=BG),
            legend_key=element_rect(fill=PANEL, color=PANEL),
            legend_text=element_text(color=TEXT, size=9),
            legend_title=element_text(color=TEXT, size=10),
            strip_background=element_rect(fill=GRID),
            strip_text=element_text(color=TEXT, size=9),
        )

    SYSTEM_COLORS = {"paper2tree": P2T_COLOR, "baseline": BASE_COLOR}

    # ── Figure 1: Mean metric comparison (grouped bar + error bars) ─────────
    metric_map = {
        "BERTScore F1": ("p2t_bertscore_f1", "baseline_bertscore_f1"),
        "ROUGE-L": ("p2t_rouge_l", "baseline_rouge_l"),
        "Cosine Sim.": ("p2t_cosine_similarity", "baseline_cosine_similarity"),
    }
    rows = []
    for label, (p2t_col, base_col) in metric_map.items():
        for val in df[p2t_col].dropna():
            rows.append({"metric": label, "system": "paper2tree", "value": float(val)})
        for val in df[base_col].dropna():
            rows.append({"metric": label, "system": "baseline", "value": float(val)})
    long_df = pd.DataFrame(rows)

    summary = (
        long_df.groupby(["metric", "system"])["value"].agg(mean="mean", std="std").reset_index()
    )
    summary["ymin"] = (summary["mean"] - summary["std"]).clip(lower=0)
    summary["ymax"] = summary["mean"] + summary["std"]

    fig1 = (
        ggplot(summary, aes(x="metric", y="mean", fill="system"))
        + geom_col(position=position_dodge(0.75), width=0.65)
        + geom_errorbar(
            aes(ymin="ymin", ymax="ymax"),
            position=position_dodge(0.75),
            width=0.2,
            color=TEXT,
            size=0.5,
        )
        + scale_fill_manual(values=SYSTEM_COLORS)
        + ylim(0, 1)
        + labs(title="Mean Metrics: paper2tree vs Baseline", x="", y="Score", fill="")
        + dark_theme()
    )
    fig1.save(
        str(figures_dir / "metric_comparison.png"), dpi=150, width=7, height=4.5, verbose=False
    )
    log("  metric_comparison.png")

    # ── Figure 2: Per-paper BERTScore F1 scatter ────────────────────────────
    scatter_df = df[["p2t_bertscore_f1", "baseline_bertscore_f1"]].dropna()
    if not scatter_df.empty:
        fig2 = (
            ggplot(scatter_df, aes(x="baseline_bertscore_f1", y="p2t_bertscore_f1"))
            + geom_abline(slope=1, intercept=0, color=GRID, linetype="dashed", size=0.8)
            + geom_point(color=P2T_COLOR, size=3, alpha=0.85)
            + labs(
                title="BERTScore F1 per Paper: paper2tree vs Baseline",
                x="Baseline",
                y="paper2tree",
            )
            + dark_theme()
        )
        fig2.save(
            str(figures_dir / "bertscore_scatter.png"), dpi=150, width=5, height=5, verbose=False
        )
        log("  bertscore_scatter.png")

    # ── Figure 3: Concern alignment (recall / precision / F1) ──────────────
    concern_map = {
        "Recall": ("p2t_concern_recall", "baseline_concern_recall"),
        "Precision": ("p2t_concern_precision", "baseline_concern_precision"),
        "F1": ("p2t_concern_f1", "baseline_concern_f1"),
    }
    concern_rows = []
    for label, (p2t_col, base_col) in concern_map.items():
        for val in df[p2t_col].dropna():
            concern_rows.append({"metric": label, "system": "paper2tree", "value": float(val)})
        for val in df[base_col].dropna():
            concern_rows.append({"metric": label, "system": "baseline", "value": float(val)})
    if concern_rows:
        concern_df = pd.DataFrame(concern_rows)
        concern_summary = (
            concern_df.groupby(["metric", "system"])["value"]
            .agg(mean="mean", std="std")
            .reset_index()
        )
        concern_summary["ymin"] = (concern_summary["mean"] - concern_summary["std"]).clip(lower=0)
        concern_summary["ymax"] = concern_summary["mean"] + concern_summary["std"]

        fig3 = (
            ggplot(concern_summary, aes(x="metric", y="mean", fill="system"))
            + geom_col(position=position_dodge(0.75), width=0.65)
            + geom_errorbar(
                aes(ymin="ymin", ymax="ymax"),
                position=position_dodge(0.75),
                width=0.2,
                color=TEXT,
                size=0.5,
            )
            + scale_fill_manual(values=SYSTEM_COLORS)
            + ylim(0, 1)
            + labs(
                title="Concern Alignment vs Human Review",
                x="",
                y="Score",
                fill="",
            )
            + dark_theme()
        )
        fig3.save(
            str(figures_dir / "concern_alignment.png"), dpi=150, width=7, height=4.5, verbose=False
        )
        log("  concern_alignment.png")

    # ── Figure 4: Recommendation distribution ──────────────────────────────
    REC_ORDER = ["Accept", "Minor Revisions", "Major Revisions", "Reject"]
    REC_COLORS = {
        "Accept": "#22c55e",
        "Minor Revisions": "#818cf8",
        "Major Revisions": "#f59e0b",
        "Reject": "#ef4444",
    }
    rec_rows = []
    for _, row in df.iterrows():
        if pd.notna(row.get("p2t_recommendation")):
            rec_rows.append({"system": "paper2tree", "recommendation": row["p2t_recommendation"]})
        if pd.notna(row.get("baseline_recommendation")):
            rec_rows.append(
                {"system": "baseline", "recommendation": row["baseline_recommendation"]}
            )
    if rec_rows:
        rec_df = pd.DataFrame(rec_rows)
        rec_df["recommendation"] = pd.Categorical(
            rec_df["recommendation"], categories=REC_ORDER, ordered=True
        )
        fig4 = (
            ggplot(rec_df, aes(x="system", fill="recommendation"))
            + geom_bar(position="fill", width=0.55)
            + scale_fill_manual(values=REC_COLORS, drop=False)
            + labs(title="Recommendation Distribution", x="", y="Proportion", fill="")
            + dark_theme()
        )
        fig4.save(
            str(figures_dir / "recommendation_dist.png"),
            dpi=150,
            width=5,
            height=4.5,
            verbose=False,
        )
        log("  recommendation_dist.png")


# ── Main ───────────────────────────────────────────────────────────────────────


async def main_async(args: argparse.Namespace) -> None:
    load_dotenv()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    log_path = output_dir / "run.log"
    log_lines: list[str] = []

    def log(msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        log_lines.append(line)

    if args.plots_only:
        log("--plots-only: generating figures from existing metrics.csv")
        generate_figures(output_dir, log=log)
        log_path.write_text("\n".join(log_lines))
        log(f"\nDone — figures in {output_dir}/figures/")
        return

    elife_repo = Path(args.elife_repo) if args.elife_repo else LOCAL_REPO_DEFAULT
    token = args.github_token or os.environ.get("GITHUB_TOKEN")

    log(f"paper2tree pilot study — {datetime.now(timezone.utc).isoformat()}")
    log(f"  n={args.n}  seed={args.seed}  output_dir={output_dir}")
    if (elife_repo / "articles").is_dir():
        log(f"  elife_repo={elife_repo} (local)")
    else:
        log(f"  elife_repo=GitHub (local clone not found at {elife_repo})")

    # ── Step 1: Sample papers ─────────────────────────────────────────────────
    papers_cache = output_dir / "sampled_papers.json"

    if not args.force and papers_cache.exists():
        log("Loading cached paper sample…")
        _cached = json.loads(papers_cache.read_text())
        papers: list[ELifePaper] = []
        for entry in _cached:
            paper_dir = output_dir / entry["article_id"]
            article_text_path = paper_dir / "article_text.txt"
            human_review_path = paper_dir / "human_review.txt"
            if not article_text_path.exists() or not human_review_path.exists():
                log(f"  Re-reading {entry['filename']} (cached text missing)…")
                try:
                    if (elife_repo / "articles").is_dir():
                        xml = read_article_local(elife_repo, entry["filename"])
                    else:
                        xml = read_article_github(entry["filename"])
                    p = parse_article(xml, entry["filename"])
                    if p:
                        paper_dir.mkdir(exist_ok=True)
                        article_text_path.write_text(p.article_text)
                        if not human_review_path.exists():
                            human_review_path.write_text(p.human_review)
                        papers.append(p)
                except Exception as e:
                    log(f"  ERROR reading {entry['filename']}: {e}")
            else:
                p = ELifePaper(
                    article_id=entry["article_id"],
                    filename=entry["filename"],
                    doi=entry.get("doi", ""),
                    title=entry.get("title", ""),
                    authors=entry.get("authors", []),
                    year=entry.get("year", 0),
                    abstract=entry.get("abstract", ""),
                    subject_areas=entry.get("subject_areas", []),
                    category=entry.get("category", "other"),
                    article_text=article_text_path.read_text(),
                    human_review=human_review_path.read_text(),
                    elife_assessment=(paper_dir / "elife_assessment.txt").read_text()
                    if (paper_dir / "elife_assessment.txt").exists()
                    else None,
                )
                papers.append(p)
    else:
        log("Sampling papers from eLife corpus…")
        papers = sample_eligible_papers(
            n=args.n, seed=args.seed, repo_path=elife_repo, token=token, log=log
        )
        # Cache metadata and article text
        papers_cache.write_text(
            json.dumps(
                [
                    {
                        "article_id": p.article_id,
                        "filename": p.filename,
                        "doi": p.doi,
                        "title": p.title,
                        "authors": p.authors,
                        "year": p.year,
                        "abstract": p.abstract,
                        "subject_areas": p.subject_areas,
                        "category": p.category,
                    }
                    for p in papers
                ],
                indent=2,
            )
        )
        for p in papers:
            paper_dir = output_dir / p.article_id
            paper_dir.mkdir(exist_ok=True)
            (paper_dir / "article_text.txt").write_text(p.article_text)

    log(f"Working with {len(papers)} papers")

    # ── Step 2: Process each paper ────────────────────────────────────────────
    for i, paper in enumerate(papers, 1):
        log(f"\n[{i}/{len(papers)}] {paper.article_id}: {paper.title[:70]}…")
        paper_dir = output_dir / paper.article_id
        ok = await process_paper(
            paper,
            paper_dir,
            force=args.force,
            skip_pipeline=args.skip_pipeline,
            log=log,
        )
        if ok:
            log(f"  Done: {paper.article_id}")
        else:
            log(f"  Failed: {paper.article_id}")

    # ── Step 3: Compute metrics ────────────────────────────────────────────────
    log("\nComputing metrics…")
    rows = compute_all_metrics(output_dir, log=log)
    write_metrics_csv(rows, output_dir, log=log)
    write_qualitative_notes(rows, output_dir)
    log("qualitative_notes.md written")

    # ── Step 4: Self-consistency check (optional) ─────────────────────────────
    if args.self_consistency:
        await run_self_consistency_check(papers, output_dir, log=log)

    # ── Step 5: Generate figures ───────────────────────────────────────────────
    log("\nGenerating figures…")
    generate_figures(output_dir, log=log)

    # ── Write run log ─────────────────────────────────────────────────────────
    log_path.write_text("\n".join(log_lines))
    log(f"\nDone — results in {output_dir}/")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="paper2tree pilot evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--n", type=int, default=10, help="Number of papers (default: 10)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--output-dir", default="eval/pilot", help="Output directory")
    parser.add_argument(
        "--elife-repo",
        default=None,
        help=f"Path to local elife-article-xml clone (default: {LOCAL_REPO_DEFAULT})",
    )
    parser.add_argument(
        "--github-token", default=None, help="GitHub API token (fallback if no local clone)"
    )
    parser.add_argument("--force", action="store_true", help="Re-run all steps")
    parser.add_argument(
        "--self-consistency", action="store_true", help="Run self-consistency check"
    )
    parser.add_argument("--skip-pipeline", action="store_true", help="Skip DAG generation")
    parser.add_argument(
        "--plots-only",
        action="store_true",
        help="Skip all pipeline steps; regenerate figures from existing metrics.csv",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
