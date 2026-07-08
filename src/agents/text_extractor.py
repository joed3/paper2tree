"""Text Extractor — extracts and structures text from a downloaded paper.

Uses pdfplumber (+ pymupdf fallback) for PDF parsing, BeautifulSoup for HTML,
then calls Claude to structure the raw text into title/authors/abstract/sections.
"""

from pathlib import Path

import pdfplumber

from .. import llm
from ..prompts import load_prompt
from ..schemas.paper import ExtractedPaper, ExtractedPaperStructure, FetchResult

_MAX_TEXT_CHARS = 80_000  # ~60K tokens; fits comfortably in 200K context


def extract_text(fetch_result: FetchResult) -> ExtractedPaper:
    """Extract and structure paper text. Synchronous — wrap in asyncio.to_thread() if needed."""
    raw_path = Path(fetch_result.raw_path)

    if fetch_result.content_type == "pdf":
        raw_text = _extract_pdf(raw_path)
    else:
        raw_text = _extract_html(raw_path)

    structure = _structure_with_claude(raw_text)

    return ExtractedPaper(
        **structure.model_dump(),
        full_text=raw_text,
        word_count=len(raw_text.split()),
    )


def _extract_pdf(path: Path) -> str:
    """Extract text from a PDF file using pdfplumber, with pymupdf fallback."""
    try:
        with pdfplumber.open(str(path)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n\n".join(pages).strip()
        if len(text) > 200:
            return text
    except Exception:
        pass

    # Fallback: pymupdf
    try:
        import fitz  # pymupdf

        doc = fitz.open(str(path))
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n\n".join(pages).strip()
    except Exception as e:
        raise RuntimeError(f"Failed to extract text from PDF {path}: {e}") from e


def _extract_html(path: Path) -> str:
    """Extract readable text from an HTML file."""
    try:
        import markdownify
        from bs4 import BeautifulSoup

        html = path.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html, "lxml")

        # Remove navigation/boilerplate
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        # Prefer article/main content if available
        content = soup.find("article") or soup.find("main") or soup.body or soup
        return markdownify.markdownify(str(content), heading_style="ATX").strip()
    except Exception as e:
        raise RuntimeError(f"Failed to extract text from HTML {path}: {e}") from e


def _structure_with_claude(raw_text: str) -> ExtractedPaperStructure:
    """Call Claude to parse title/authors/abstract/sections from raw extracted text."""
    truncated = raw_text[:_MAX_TEXT_CHARS]
    template = load_prompt("text_extractor")
    prompt = template.substitute(raw_text=truncated)

    return llm.parse_structured(prompt, ExtractedPaperStructure, max_tokens=16384)
