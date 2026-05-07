"""
Migrate dag.json artifacts from schema_version 1 to 2 (project v1.4.x → v1.5.0).

What changes (all additive — no fields removed or renamed):
  PaperMeta    + has_local_pdf: bool
  DAGNode      + page_number: int | null
  DAGNode      + bbox: [[x0, y0, x1, y1], …] | null  (one rect per matched line)

The migration attempts to back-fill page_number and bbox for each node by
searching for its verbatim_quote in the paper's stored PDF using PyMuPDF.
Nodes whose quotes cannot be found (or papers without a local PDF) receive
null for both fields.

Also repairs v2 DAGs that were written with the old flat-list bbox format
([x0, y0, x1, y1] instead of [[x0, y0, x1, y1], …]).
"""

import json
from pathlib import Path

import fitz  # pymupdf

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"


# ── PDF search helper ──────────────────────────────────────────────────────────


def _locate(pdf_path: Path, quote: str) -> tuple[int | None, list[list[float]] | None]:
    """Two-pass search: exact quote, then 60-char anchor prefix.

    Returns all matched rects (one per line segment) rather than just the first.
    """
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return None, None

    try:
        for page_num, page in enumerate(doc):
            hits = page.search_for(quote)
            if hits:
                return page_num, [[r.x0, r.y0, r.x1, r.y1] for r in hits]

        anchor = quote[:60].strip()
        if len(anchor) >= 20 and len(anchor) < len(quote):
            for page_num, page in enumerate(doc):
                hits = page.search_for(anchor)
                if hits:
                    return page_num, [[r.x0, r.y0, r.x1, r.y1] for r in hits]
    finally:
        doc.close()

    return None, None


def _has_flat_bbox(dag: dict) -> bool:
    """Return True if any node's bbox is in the old flat [x0,y0,x1,y1] format."""
    for node in dag.get("dag", {}).get("nodes", []):
        bbox = node.get("bbox")
        if (
            bbox is not None
            and isinstance(bbox, list)
            and len(bbox) == 4
            and isinstance(bbox[0], (int, float))
        ):
            return True
    return False


# ── Per-DAG migration ──────────────────────────────────────────────────────────


def _find_pdf(paper_dir: Path) -> Path | None:
    """Return paper.pdf if it exists, else the first other PDF in raw/, else None."""
    canonical = paper_dir / "raw" / "paper.pdf"
    if canonical.exists():
        return canonical
    others = list((paper_dir / "raw").glob("*.pdf"))
    return others[0] if others else None


def migrate_dag(dag: dict, paper_dir: Path) -> tuple[dict, bool]:
    """Return (migrated_dag, was_changed). Idempotent — safe to re-run.

    Handles two cases:
      - schema_version < 2: full migration (add fields + locate coordinates)
      - schema_version == 2 with flat bbox: repair bbox to list-of-rects format
    """
    schema_version = dag.get("schema_version", 0)
    needs_full_migration = schema_version < 2
    needs_bbox_repair = schema_version >= 2 and _has_flat_bbox(dag)

    if not needs_full_migration and not needs_bbox_repair:
        return dag, False

    pdf_path = _find_pdf(paper_dir)
    has_local_pdf = pdf_path is not None

    if needs_full_migration:
        dag["paper"]["has_local_pdf"] = has_local_pdf

    # Back-fill / repair node coordinates
    located = 0
    for node in dag["dag"]["nodes"]:
        if needs_full_migration:
            node["page_number"] = None
            node["bbox"] = None
        if has_local_pdf and pdf_path is not None:
            quote = node.get("verbatim_quote", "")
            if quote:
                page_num, bbox = _locate(pdf_path, quote)
                node["page_number"] = page_num
                node["bbox"] = bbox
                if page_num is not None:
                    located += 1

    dag["schema_version"] = 2
    return dag, True


# ── Index rebuild ──────────────────────────────────────────────────────────────


def rebuild_index(outputs_dir: Path) -> None:
    entries = []
    for paper_dir in sorted(outputs_dir.iterdir()):
        if not paper_dir.is_dir():
            continue
        dag_path = paper_dir / "dag.json"
        if not dag_path.exists():
            continue
        try:
            dag = json.loads(dag_path.read_text())
        except Exception:
            continue
        paper = dag["paper"]
        summary = dag["summary"]
        abstract = paper["abstract"]
        if len(abstract) > 250:
            abstract = abstract[:250] + "…"
        entries.append(
            {
                "paper_id": paper["paper_id"],
                "title": paper["title"],
                "authors": paper["authors"],
                "url": paper["url"],
                "abstract_short": abstract,
                "processed_at": paper["processed_at"],
                "high_support_count": summary["high_support_nodes"],
                "total_claims": summary["total_nodes"],
                "result_path": f"{paper['paper_id']}/dag.json",
            }
        )
    entries.sort(key=lambda e: e["processed_at"], reverse=True)
    index_path = outputs_dir / "index.json"
    index_path.write_text(json.dumps({"version": 1, "papers": entries}, indent=2))
    print(f"  index.json → {len(entries)} papers")


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    paper_dirs = [d for d in OUTPUTS_DIR.iterdir() if d.is_dir() and (d / "dag.json").exists()]

    total_located = 0
    total_nodes = 0

    for paper_dir in sorted(paper_dirs):
        dag_path = paper_dir / "dag.json"
        dag = json.loads(dag_path.read_text())
        dag, changed = migrate_dag(dag, paper_dir)

        if changed:
            nodes_with_coords = sum(1 for n in dag["dag"]["nodes"] if n["page_number"] is not None)
            total_nodes_here = len(dag["dag"]["nodes"])
            total_located += nodes_with_coords
            total_nodes += total_nodes_here
            dag_path.write_text(json.dumps(dag, indent=2))
            has_pdf = dag["paper"]["has_local_pdf"]
            print(
                f"migrated   {paper_dir.name}"
                f"  pdf={'yes' if has_pdf else 'no'}"
                f"  coords={nodes_with_coords}/{total_nodes_here}"
            )
        else:
            print(f"up-to-date {paper_dir.name}")

    print()
    rebuild_index(OUTPUTS_DIR)
    print(f"\nCoordinates located: {total_located}/{total_nodes} nodes across all papers.")
    print("done.")


if __name__ == "__main__":
    main()
