"""Generate self-contained HTML exports from a paper review artifact.

The viewer template (frontend/dist-export/export.html) is produced once by
``npm run build:export`` and committed to the repository.  At export time this
module reads that template and replaces the data placeholder with the actual
paper JSON — no build tooling is required at runtime.
"""

import json
import re
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).parent.parent / "frontend" / "dist-export" / "export.html"
_PLACEHOLDER = "window.__PAPER_DATA__ = null;"


def generate_export_html(paper_data: dict) -> str:
    """Return a self-contained HTML string for the given paper review data.

    Args:
        paper_data: The parsed contents of a ``dag.json`` artifact.

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

    # Compact JSON — no whitespace needed inside the script tag
    data_json = json.dumps(paper_data, ensure_ascii=False, separators=(",", ":"))
    html = template.replace(_PLACEHOLDER, f"window.__PAPER_DATA__ = {data_json};", 1)

    # Update the <title> tag with the actual paper title
    title = paper_data.get("paper", {}).get("title", "paper2tree export")
    safe_title = title.replace("<", "&lt;").replace(">", "&gt;")
    html = re.sub(
        r"<title>[^<]*</title>", f"<title>paper2tree — {safe_title}</title>", html, count=1
    )

    return html


def safe_filename(paper_data: dict) -> str:
    """Return a safe filename (no extension) derived from the paper title."""
    title = paper_data.get("paper", {}).get("title", "export")
    # Keep alphanumeric, spaces, hyphens; collapse whitespace; truncate
    clean = re.sub(r"[^\w\s-]", "", title).strip()
    clean = re.sub(r"\s+", "_", clean)[:80]
    return f"paper2tree_{clean}" if clean else "paper2tree_export"
