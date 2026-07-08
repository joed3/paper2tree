"""Orchestrator — coordinates the full paper-processing pipeline.

Pipeline:
  fetch_paper → extract_text → extract_claims → build_dag → evaluate_claims
  → final_reviewer → write_outputs
"""

import asyncio
import hashlib
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

from .agents.claim_evaluator import evaluate_claims
from .agents.claim_extractor import extract_claims
from .agents.final_reviewer import generate_review
from .agents.output_formatter import format_output, write_outputs
from .agents.paper_fetcher import fetch_paper
from .agents.text_extractor import extract_text
from .export_html import ensure_export_html
from .kb.live_retriever import LiveRetriever
from .schemas.paper import FetchResult
from .utils.graph import build_dag
from .utils.paper_id import make_paper_id
from .utils.pdf_locate import locate_claims

load_dotenv()

LogFn = Callable[[str], None]


def get_outputs_dir() -> Path:
    """Resolve the outputs directory.

    PAPER2TREE_OUTPUT_DIR overrides; otherwise user-global ~/.paper2tree/outputs
    so the pipeline works regardless of the caller's working directory.
    """
    env = os.environ.get("PAPER2TREE_OUTPUT_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".paper2tree" / "outputs"


async def _run_pipeline(
    fetch_result: FetchResult,
    url: str,
    temp_dir: Path,
    force: bool,
    log: LogFn,
    live_search: bool = False,
    export_html: bool = True,
) -> str:
    """Steps 2–7 of the pipeline (after fetching). Shared by URL and file paths."""
    outputs_dir = get_outputs_dir()
    try:
        # ── Step 2: Extract text ──────────────────────────────────────────────
        log("[2/7] Extracting and structuring text …")
        extracted = await asyncio.to_thread(extract_text, fetch_result)
        log(f"      Title: {extracted.title!r}")
        log(f"      Authors: {', '.join(extracted.authors[:3])}")
        log(f"      Word count: {extracted.word_count:,}")

        # ── Step 3: Determine paper_id and check for duplicates ───────────────
        paper_id = make_paper_id(extracted.title, url)
        paper_dir = outputs_dir / paper_id
        output_path = paper_dir / "dag.json"

        if not force and output_path.exists():
            log(f"      Already processed (paper_id={paper_id}). Use --force to reprocess.")
            return paper_id

        # Move raw files from temp to final location
        paper_dir.mkdir(parents=True, exist_ok=True)
        final_raw_dir = paper_dir / "raw"
        if final_raw_dir.exists():
            shutil.rmtree(final_raw_dir)
        shutil.move(str(temp_dir / "raw"), str(final_raw_dir))

        # Patch fetch_result to point to new location
        original_name = Path(fetch_result.raw_path).name
        fetch_result.raw_path = str((final_raw_dir / original_name).resolve())
        if fetch_result.pdf_path is not None:
            pdf_name = Path(fetch_result.pdf_path).name
            fetch_result.pdf_path = str((final_raw_dir / pdf_name).resolve())

        # ── Step 4: Extract claims ────────────────────────────────────────────
        log("[3/7] Extracting claim structure …")
        claim_graph = await asyncio.to_thread(extract_claims, extracted.full_text)
        log(f"      Found {len(claim_graph.claims)} claims")

        # ── Step 4.5: Locate claims in PDF ───────────────────────────────────
        if fetch_result.pdf_path is not None:
            log("      Locating claims in PDF …")
            await asyncio.to_thread(locate_claims, claim_graph, fetch_result.pdf_path)
            located = sum(1 for c in claim_graph.claims if c.page_number is not None)
            log(f"      Located {located}/{len(claim_graph.claims)} claims with page coordinates")

        # ── Step 5: Build DAG ─────────────────────────────────────────────────
        log("[4/7] Building and validating DAG …")
        enriched = build_dag(claim_graph)
        max_depth = max(ec.depth for ec in enriched)
        log(f"      {len(enriched)} nodes, max depth {max_depth}")

        # ── Step 5.5: Live literature search (optional) ───────────────────────
        retrieved = None
        if live_search:
            log(f"[5/7] Searching prior literature for {len(enriched)} claims …")
            retriever = LiveRetriever()
            retrieved = await asyncio.to_thread(
                retriever.retrieve_for_claims, enriched, extracted.title
            )
            total_passages = sum(len(v) for v in retrieved.values())
            log(f"      Retrieved {total_passages} passages from PubMed + Semantic Scholar")

        # ── Step 6: Evaluate claims ───────────────────────────────────────────
        log(f"[{'6' if live_search else '5'}/7] Evaluating {len(enriched)} claims …")
        evaluations = await evaluate_claims(enriched, extracted.full_text, retrieved=retrieved)
        log(f"      Evaluated {len(evaluations)} claims")

        # ── Step 7: Format output ─────────────────────────────────────────────
        paper_dag = format_output(
            paper_id,
            url,
            extracted,
            enriched,
            evaluations,
            has_local_pdf=fetch_result.pdf_path is not None,
        )

        # ── Step 7: Generate final review ─────────────────────────────────────
        log("[6/7] Generating final review …")
        try:
            paper_dag.final_review = await asyncio.to_thread(
                generate_review, extracted.full_text, paper_dag
            )
            log("      Final review complete")
        except Exception as e:
            log(f"      WARNING: final review failed ({e}); continuing without it")

        # ── Step 8: Write output ───────────────────────────────────────────────
        log("[7/7] Writing output …")
        write_outputs(paper_dag, paper_dir, outputs_dir)

        if export_html:
            try:
                html_path = ensure_export_html(paper_id, outputs_dir, force=True)
                log(f"      Interactive HTML: {html_path}")
            except FileNotFoundError as e:
                log(f"      WARNING: HTML export skipped ({e})")

        log(f"\n✓ Done — paper_id: {paper_id}")
        log(f"  Output: {output_path}")
        log(
            f"  Claims: {paper_dag.summary.total_nodes} nodes, high support: {paper_dag.summary.high_support_nodes}/{paper_dag.summary.total_nodes}"
        )

        return paper_id

    except Exception:
        # Clean up temp directory on failure (leave final paper_dir if it was created)
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


async def process_paper(
    url: str,
    force: bool = False,
    live_search: bool = False,
    log: LogFn = print,
    export_html: bool = True,
) -> str:
    """Run the full pipeline for a single paper URL.

    Returns the paper_id on success.
    Raises on any unrecoverable error.
    """
    outputs_dir = get_outputs_dir()
    outputs_dir.mkdir(parents=True, exist_ok=True)

    url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
    temp_dir = outputs_dir / f"_tmp_{url_hash}"
    raw_dir = temp_dir / "raw"

    log(f"[1/7] Fetching paper from {url} …")
    fetch_result = await fetch_paper(url, raw_dir)
    log(f"      Downloaded: {fetch_result.content_type} → {Path(fetch_result.raw_path).name}")

    return await _run_pipeline(
        fetch_result, url, temp_dir, force, log, live_search=live_search, export_html=export_html
    )


async def process_paper_from_file(
    file_path: Path,
    original_name: str,
    force: bool = False,
    live_search: bool = False,
    log: LogFn = print,
    export_html: bool = True,
) -> str:
    """Run the pipeline for an already-downloaded local file (skips the fetch step).

    Returns the paper_id on success.
    Raises on any unrecoverable error.
    """
    outputs_dir = get_outputs_dir()
    outputs_dir.mkdir(parents=True, exist_ok=True)

    suffix = file_path.suffix.lower()
    content_type = "pdf" if suffix == ".pdf" else "html" if suffix in (".html", ".htm") else "text"
    pseudo_url = f"upload://{original_name}"

    file_hash = hashlib.sha256(original_name.encode()).hexdigest()[:8]
    temp_dir = outputs_dir / f"_tmp_{file_hash}"
    raw_dir = temp_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Normalise PDF filename so the viewer can always find it at paper.pdf
    saved_name = "paper.pdf" if content_type == "pdf" else original_name
    dest = raw_dir / saved_name
    shutil.copy2(file_path, dest)

    # Write a manifest so the rest of the pipeline has the expected structure
    manifest: dict = {
        "content_type": content_type,
        "raw_path": saved_name,
        "pdf_path": saved_name if content_type == "pdf" else None,
        "source_url": pseudo_url,
    }
    (raw_dir / "manifest.json").write_text(json.dumps(manifest))

    fetch_result = FetchResult(
        content_type=content_type,
        raw_path=str(dest.resolve()),
        source_url=pseudo_url,
        pdf_path=str(dest.resolve()) if content_type == "pdf" else None,
    )

    log(f"[1/7] Using uploaded file: {original_name}")
    return await _run_pipeline(
        fetch_result,
        pseudo_url,
        temp_dir,
        force,
        log,
        live_search=live_search,
        export_html=export_html,
    )
