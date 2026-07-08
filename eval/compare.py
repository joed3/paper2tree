"""Paired comparison of pilot runs — the v1.7-vs-v2 referee (see §14 of the v2 critique).

Answers the two pre-registered questions:

  1. Does the DAG beat the single-prompt baseline?  (paired p2t vs. baseline,
     within a single run's metrics.csv)
  2. Did v2.0 improve over v1.7?                     (paired p2t-v2 vs. p2t-v1.7,
     matched by article_id across two metrics.csv files)

Because the per-paper deltas are small, this uses a *paired* test rather than
comparing means: the Wilcoxon signed-rank test when SciPy is available, otherwise
a paired bootstrap 95% CI on the mean difference. Per-paper pairing is what gives
the sensitivity to detect a small but consistent effect.

Usage:
    # DAG vs. baseline, within the v2 run:
    python -m eval.compare --v2 eval/pilot_v2/metrics.csv

    # Also compare v2 against the frozen v1.7 control:
    python -m eval.compare --v2 eval/pilot_v2/metrics.csv --v1 eval/pilot_v17/metrics.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

METRICS = [
    "bertscore_f1",
    "rouge_l",
    "cosine_similarity",
    "concern_recall",
    "concern_precision",
    "concern_f1",
]


def _load(csv_path: Path) -> dict[str, dict[str, float]]:
    """Return {article_id: {column: value}} for numeric columns."""
    rows: dict[str, dict[str, float]] = {}
    with csv_path.open() as f:
        for row in csv.DictReader(f):
            aid = row.get("article_id", "")
            parsed: dict[str, float] = {}
            for k, v in row.items():
                try:
                    parsed[k] = float(v)
                except (TypeError, ValueError):
                    continue
            rows[aid] = parsed
    return rows


def _paired_test(diffs: list[float]) -> dict:
    """Paired significance on the per-paper differences (a - b)."""
    n = len(diffs)
    mean_diff = statistics.mean(diffs) if diffs else 0.0
    result: dict = {"n": n, "mean_diff": round(mean_diff, 4)}

    try:
        from scipy.stats import wilcoxon  # type: ignore

        if n >= 1 and any(d != 0 for d in diffs):
            stat, p = wilcoxon(diffs)
            result["test"] = "wilcoxon"
            result["p_value"] = round(float(p), 4)
        else:
            result["test"] = "wilcoxon"
            result["p_value"] = None
    except Exception:
        # Bootstrap 95% CI on the mean difference (no SciPy needed).
        import random

        random.seed(0)
        if n >= 2:
            means = []
            for _ in range(5000):
                sample = [random.choice(diffs) for _ in range(n)]
                means.append(statistics.mean(sample))
            means.sort()
            lo = means[int(0.025 * len(means))]
            hi = means[int(0.975 * len(means))]
            result["test"] = "bootstrap_ci95"
            result["ci95"] = [round(lo, 4), round(hi, 4)]
            result["significant"] = lo > 0 or hi < 0
        else:
            result["test"] = "bootstrap_ci95"
            result["ci95"] = None
    return result


def _compare(a_rows, b_rows, a_prefix: str, b_prefix: str, label: str) -> dict:
    """Pair a_prefix<metric> against b_prefix<metric> over shared article_ids."""
    shared = sorted(set(a_rows) & set(b_rows))
    out: dict = {"comparison": label, "n_papers": len(shared), "metrics": {}}
    for m in METRICS:
        a_col, b_col = f"{a_prefix}{m}", f"{b_prefix}{m}"
        diffs = [
            a_rows[aid][a_col] - b_rows[aid][b_col]
            for aid in shared
            if a_col in a_rows[aid] and b_col in b_rows[aid]
        ]
        if diffs:
            out["metrics"][m] = _paired_test(diffs)
    return out


def _print(report: dict) -> None:
    print(f"\n=== {report['comparison']}  (n={report['n_papers']} paired papers) ===")
    print(f"  {'metric':<20} {'mean Δ':>9}  significance")
    for m, r in report["metrics"].items():
        if r.get("test") == "wilcoxon":
            sig = f"p={r['p_value']}" if r.get("p_value") is not None else "p=n/a"
        else:
            ci = r.get("ci95")
            sig = f"95%CI={ci} {'*' if r.get('significant') else ''}" if ci else "ci=n/a"
        print(f"  {m:<20} {r['mean_diff']:>+9.4f}  {sig}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Paired comparison of pilot runs")
    ap.add_argument("--v2", required=True, help="metrics.csv for the v2.0 run")
    ap.add_argument("--v1", default=None, help="metrics.csv for the frozen v1.7 control")
    ap.add_argument("--out", default=None, help="write JSON report here")
    args = ap.parse_args()

    v2_rows = _load(Path(args.v2))
    reports = [
        _compare(v2_rows, v2_rows, "p2t_", "baseline_", "v2.0: DAG vs. single-prompt baseline")
    ]

    if args.v1:
        v1_rows = _load(Path(args.v1))
        reports.append(
            _compare(v2_rows, v1_rows, "p2t_", "p2t_", "DAG: v2.0 vs. v1.7 (paired by paper)")
        )

    for r in reports:
        _print(r)

    print(
        "\nNote: positive mean Δ favors the first arm (p2t over baseline; v2.0 over v1.7). "
        "A '*' or p<0.05 marks a statistically detectable paired difference."
    )

    if args.out:
        Path(args.out).write_text(json.dumps(reports, indent=2))
        print(f"\nJSON report → {args.out}")


if __name__ == "__main__":
    main()
