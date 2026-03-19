"""Orchestrator — coordinates the full paper-processing pipeline.

Pipeline:
  fetch_paper → extract_text → extract_claims → build_dag → evaluate_claims → write_outputs
"""
import asyncio
import hashlib
import shutil
from pathlib import Path

from dotenv import load_dotenv

from .agents.claim_evaluator import evaluate_claims
from .agents.claim_extractor import extract_claims
from .agents.output_formatter import format_output, write_outputs
from .agents.paper_fetcher import fetch_paper
from .agents.text_extractor import extract_text
from .utils.graph import build_dag
from .utils.paper_id import make_paper_id

load_dotenv()

OUTPUTS_DIR = Path("outputs")


async def process_paper(url: str, force: bool = False) -> str:
    """Run the full pipeline for a single paper URL.

    Returns the paper_id on success.
    Raises on any unrecoverable error.
    """
    OUTPUTS_DIR.mkdir(exist_ok=True)

    # Temp directory based on URL hash (title unknown until after extraction)
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
    temp_dir = OUTPUTS_DIR / f"_tmp_{url_hash}"
    raw_dir = temp_dir / "raw"

    try:
        # ── Step 1: Fetch ─────────────────────────────────────────────────────
        print(f"[1/6] Fetching paper from {url} …")
        fetch_result = await fetch_paper(url, raw_dir)
        print(f"      Downloaded: {fetch_result.content_type} → {Path(fetch_result.raw_path).name}")

        # ── Step 2: Extract text ──────────────────────────────────────────────
        print("[2/6] Extracting and structuring text …")
        extracted = await asyncio.to_thread(extract_text, fetch_result)
        print(f"      Title: {extracted.title!r}")
        print(f"      Authors: {', '.join(extracted.authors[:3])}")
        print(f"      Word count: {extracted.word_count:,}")

        # ── Step 3: Determine paper_id and check for duplicates ───────────────
        paper_id = make_paper_id(extracted.title, url)
        paper_dir = OUTPUTS_DIR / paper_id
        output_path = paper_dir / "dag.json"

        if not force and output_path.exists():
            print(f"      Already processed (paper_id={paper_id}). Use --force to reprocess.")
            return paper_id

        # Move raw files from temp to final location
        paper_dir.mkdir(parents=True, exist_ok=True)
        final_raw_dir = paper_dir / "raw"
        if final_raw_dir.exists():
            shutil.rmtree(final_raw_dir)
        shutil.move(str(raw_dir), str(final_raw_dir))

        # Patch fetch_result to point to new location
        original_name = Path(fetch_result.raw_path).name
        fetch_result.raw_path = str((final_raw_dir / original_name).resolve())

        # ── Step 4: Extract claims ────────────────────────────────────────────
        print("[3/6] Extracting claim structure …")
        claim_graph = await asyncio.to_thread(extract_claims, extracted.full_text)
        print(f"      Found {len(claim_graph.claims)} claims")

        # ── Step 5: Build DAG ─────────────────────────────────────────────────
        print("[4/6] Building and validating DAG …")
        enriched = build_dag(claim_graph)
        max_depth = max(ec.depth for ec in enriched)
        print(f"      {len(enriched)} nodes, max depth {max_depth}")

        # ── Step 6: Evaluate claims ───────────────────────────────────────────
        print(f"[5/6] Evaluating {len(enriched)} claims …")
        evaluations = await evaluate_claims(enriched, extracted.full_text)
        print(f"      Evaluated {len(evaluations)} claims")

        # ── Step 7: Format and write output ───────────────────────────────────
        print("[6/6] Writing output …")
        paper_dag = format_output(paper_id, url, extracted, enriched, evaluations)
        write_outputs(paper_dag, paper_dir, OUTPUTS_DIR)

        print(f"\n✓ Done — paper_id: {paper_id}")
        print(f"  Output: {output_path}")
        print(f"  Claims: {paper_dag.summary.total_nodes} nodes, mean validity: {paper_dag.summary.mean_validity_score:.2f}")

        return paper_id

    except Exception:
        # Clean up temp directory on failure (leave final paper_dir if it was created)
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    finally:
        # Always clean up temp dir if it still exists
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
