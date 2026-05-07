"""Locate verbatim quotes inside a PDF using PyMuPDF text search.

Uses a two-pass strategy:
  Pass 1 — exact quote (handles most cases)
  Pass 2 — first 60-character anchor prefix (handles long quotes that span line breaks)
"""

from pathlib import Path

from ..schemas.claim import ClaimGraph


def locate_in_pdf(
    pdf_path: str | Path,
    quote: str,
) -> tuple[int | None, list[list[float]] | None]:
    """Find the first occurrence of quote in the PDF.

    Returns (page_number_0indexed, [[x0,y0,x1,y1], …]) where each inner list is
    one matched line segment (PDF user units, 72 dpi origin top-left).
    Returns (None, None) if the quote cannot be found or the PDF cannot be opened.

    Multi-line quotes produce multiple rects — one per line — so the caller
    should render a highlight rect for each element, not just the first.
    """
    import fitz  # pymupdf

    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return None, None

    try:
        # Pass 1: exact match (search_for returns one Rect per matched line)
        for page_num, page in enumerate(doc):
            hits = page.search_for(quote)
            if hits:
                return page_num, [[r.x0, r.y0, r.x1, r.y1] for r in hits]

        # Pass 2: first 60-character anchor (handles quotes that wrap across lines)
        anchor = quote[:60].strip()
        if len(anchor) >= 20 and len(anchor) < len(quote):
            for page_num, page in enumerate(doc):
                hits = page.search_for(anchor)
                if hits:
                    return page_num, [[r.x0, r.y0, r.x1, r.y1] for r in hits]
    finally:
        doc.close()

    return None, None


def locate_claims(claim_graph: ClaimGraph, pdf_path: str | Path) -> None:
    """Mutate each Claim in claim_graph in-place, setting page_number and bbox.

    No-op if pdf_path does not exist. Silently leaves fields as None for
    quotes that cannot be located.
    """
    path = Path(pdf_path)
    if not path.exists():
        return

    for claim in claim_graph.claims:
        if not claim.verbatim_quote:
            continue
        claim.page_number, claim.bbox = locate_in_pdf(path, claim.verbatim_quote)
