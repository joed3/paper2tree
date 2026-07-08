"""Generate self-contained HTML exports from a paper review artifact.

The viewer template (frontend/dist-export/export.html) is produced once by
``npm run build:export`` and committed to the repository.  At export time this
module reads that template and replaces the data placeholder with the actual
paper JSON — no build tooling is required at runtime.
"""

import base64
import json
import re
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).parent.parent / "frontend" / "dist-export" / "export.html"
_PLACEHOLDER = "window.__PAPER_DATA__ = null;"


def _find_pdf(paper_dir: Path) -> Path | None:
    """Return paper.pdf if present, else the first other PDF in raw/, else None."""
    canonical = paper_dir / "raw" / "paper.pdf"
    if canonical.exists():
        return canonical
    others = list((paper_dir / "raw").glob("*.pdf"))
    return others[0] if others else None


def generate_export_html(paper_data: dict, pdf_path: Path | None = None) -> str:
    """Return a self-contained HTML string for the given paper review data.

    Args:
        paper_data: The parsed contents of a ``dag.json`` artifact.
        pdf_path:   Optional path to the paper PDF. When supplied the PDF is
                    base64-encoded and embedded as ``pdf_data_url`` inside the
                    injected data so the export works without a server.

    Returns:
        Complete HTML ready to be saved or served as a file.

    Raises:
        FileNotFoundError: If the viewer template has not been built yet.
        ValueError: If the template is missing the expected data placeholder.
    """
    if not _TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Export viewer template not found at {_TEMPLATE_PATH}. "
            "Run `npm run build:export` inside the frontend/ directory to build it."
        )

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    if _PLACEHOLDER not in template:
        raise ValueError(
            f"Export template is missing the expected placeholder: {_PLACEHOLDER!r}. "
            "Rebuild the template with `npm run build:export`."
        )

    # Augment paper data with an embedded PDF data URL when a PDF is available.
    # pdf_data_url is not part of the dag.json schema — it exists only in the export.
    export_data = dict(paper_data)
    if pdf_path is not None and pdf_path.exists():
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
        export_data["pdf_data_url"] = f"data:application/pdf;base64,{b64}"

    # Compact JSON — no whitespace needed inside the script tag
    data_json = json.dumps(export_data, ensure_ascii=False, separators=(",", ":"))
    html = template.replace(_PLACEHOLDER, f"window.__PAPER_DATA__ = {data_json};", 1)

    # Update the <title> tag with the actual paper title
    title = paper_data.get("paper", {}).get("title", "paper2tree export")
    safe_title = title.replace("<", "&lt;").replace(">", "&gt;")
    html = re.sub(
        r"<title>[^<]*</title>", f"<title>paper2tree — {safe_title}</title>", html, count=1
    )

    return html


def ensure_export_html(paper_id: str, outputs_dir: Path, force: bool = False) -> Path:
    """Generate outputs_dir/<paper_id>.html from the paper's dag.json if missing.

    Returns the path to the HTML file (existing or newly written).

    Raises:
        FileNotFoundError: If dag.json or the viewer template is missing.
    """
    html_path = outputs_dir / f"{paper_id}.html"
    if html_path.exists() and not force:
        return html_path

    paper_dir = outputs_dir / paper_id
    dag_path = paper_dir / "dag.json"
    if not dag_path.exists():
        raise FileNotFoundError(f"No dag.json found for paper_id={paper_id} at {dag_path}")

    paper_data = json.loads(dag_path.read_text(encoding="utf-8"))
    html = generate_export_html(paper_data, pdf_path=_find_pdf(paper_dir))
    html_path.write_text(html, encoding="utf-8")
    return html_path


def safe_filename(paper_data: dict) -> str:
    """Return a safe filename (no extension) derived from the paper title."""
    title = paper_data.get("paper", {}).get("title", "export")
    # Keep alphanumeric, spaces, hyphens; collapse whitespace; truncate
    clean = re.sub(r"[^\w\s-]", "", title).strip()
    clean = re.sub(r"\s+", "_", clean)[:80]
    return f"paper2tree_{clean}" if clean else "paper2tree_export"
