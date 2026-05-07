"""Paper Fetcher Agent — downloads a paper from a URL using the Claude Agent SDK.

The agent runs with cwd=raw_dir so all Bash/Write paths resolve there.
After the agent finishes it must have written manifest.json to raw_dir.
"""

import json
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from ..schemas.paper import FetchResult


def _build_prompt(url: str) -> str:
    return f"""Download the scientific paper from the following URL and save it to disk.

URL: {url}

STEPS — follow in order:

1. Detect the URL type:
   - If the URL contains "arxiv.org/abs/", convert it to the PDF URL:
     replace "/abs/" with "/pdf/" and add ".pdf" suffix if missing.
     Example: https://arxiv.org/abs/1706.03762 → https://arxiv.org/pdf/1706.03762.pdf
   - If the URL already ends with ".pdf", use it directly.
   - For DOI URLs (doi.org/...) or journal pages, try to find and use the direct PDF link.
   - For bioRxiv/medRxiv URLs, the PDF is at: <base_url>.full.pdf

2. Download the file using Bash:
   curl -L --max-time 120 -A "Mozilla/5.0" -o paper.pdf "<DOWNLOAD_URL>"
   (Replace <DOWNLOAD_URL> with the actual download URL from step 1.)

3. Verify the primary download:
   Run: ls -lh paper.pdf
   Check whether the file starts with the PDF magic bytes: python3 -c "f=open('paper.pdf','rb');print(f.read(4));f.close()"
   If the file is smaller than 5KB OR does not start with b'%PDF', it downloaded an HTML page instead.
   In that case:
   a) Rename the bad file: mv paper.pdf paper.html
   b) Attempt PDF recovery: scan paper.html for a PDF link using one of these methods:
      - grep -o 'content="[^"]*\\.pdf[^"]*"' paper.html | head -3
      - grep -o 'href="[^"]*\\.pdf[^"]*"' paper.html | head -3
      - grep -o '"citation_pdf_url"[^>]*content="[^"]*"' paper.html | head -3
      - For biorxiv.org pages: construct https://www.biorxiv.org/content/<DOI>.full.pdf
      - For PubMed/PMC pages: look for links ending in /pdf or .pdf
   c) If a PDF URL is found, download it:
      curl -L --max-time 120 -A "Mozilla/5.0" -o paper.pdf "<PDF_URL>"
      Then verify: ls -lh paper.pdf && python3 -c "f=open('paper.pdf','rb');print(f.read(4));f.close()"

4. Determine what was saved and write manifest.json:

   Case A — Primary PDF download succeeded (paper.pdf > 5KB and starts with %PDF):
   printf '%s' '{{"content_type": "pdf", "raw_path": "paper.pdf", "pdf_path": "paper.pdf", "source_url": "<ACTUAL_URL>"}}' > manifest.json

   Case B — HTML was downloaded AND a secondary PDF was found (both paper.html and paper.pdf exist and paper.pdf > 5KB):
   printf '%s' '{{"content_type": "html", "raw_path": "paper.html", "pdf_path": "paper.pdf", "source_url": "<ACTUAL_URL>"}}' > manifest.json

   Case C — Only HTML was downloaded (no PDF found):
   printf '%s' '{{"content_type": "html", "raw_path": "paper.html", "pdf_path": null, "source_url": "<ACTUAL_URL>"}}' > manifest.json

Replace <ACTUAL_URL> with the URL you actually downloaded from (after any conversions in step 1).

IMPORTANT: Use Bash printf to write manifest.json (not the Write tool). The manifest must be valid JSON.
"""


async def fetch_paper(url: str, raw_dir: Path) -> FetchResult:
    """Download a paper to raw_dir using the Agent SDK.

    The agent writes paper.pdf (or paper.html) and manifest.json into raw_dir.
    Returns a FetchResult with absolute paths.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)

    prompt = _build_prompt(url)

    last_result: ResultMessage | None = None
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            allowed_tools=["Bash", "Write", "WebFetch"],
            permission_mode="acceptEdits",
            cwd=str(raw_dir.resolve()),
            max_turns=20,
        ),
    ):
        if isinstance(message, ResultMessage):
            last_result = message

    manifest_path = raw_dir / "manifest.json"
    if not manifest_path.exists():
        agent_output = last_result.result if last_result else "no output"
        raise RuntimeError(
            f"Paper fetcher did not write manifest.json.\nAgent output: {agent_output}"
        )

    data = json.loads(manifest_path.read_text())

    # Resolve the relative raw_path to absolute
    raw_path = raw_dir / data["raw_path"]
    if not raw_path.exists():
        raise RuntimeError(f"Paper fetcher wrote manifest but file not found: {raw_path}")

    # Resolve optional pdf_path
    pdf_path_rel = data.get("pdf_path")
    pdf_path_abs: str | None = None
    if pdf_path_rel:
        pdf_candidate = raw_dir / pdf_path_rel
        if pdf_candidate.exists():
            pdf_path_abs = str(pdf_candidate.resolve())

    return FetchResult(
        content_type=data["content_type"],
        raw_path=str(raw_path.resolve()),
        source_url=data["source_url"],
        pdf_path=pdf_path_abs,
    )
