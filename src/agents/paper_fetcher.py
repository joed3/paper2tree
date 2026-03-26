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

2. Download the file using Bash:
   curl -L --max-time 120 -A "Mozilla/5.0" -o paper.pdf "<DOWNLOAD_URL>"
   (Replace <DOWNLOAD_URL> with the actual download URL from step 1.)

3. Verify the download:
   Run: ls -lh paper.pdf
   If the file is smaller than 5KB, it likely downloaded an HTML error page instead of a PDF.
   In that case, download as HTML instead:
   curl -L --max-time 120 -A "Mozilla/5.0" -o paper.html "<URL>"

4. Determine what was saved:
   - If paper.pdf exists and is > 5KB: content_type = "pdf", filename = "paper.pdf"
   - If paper.html exists: content_type = "html", filename = "paper.html"

5. Write manifest.json using Bash (NOT the Write tool — use echo/printf):
   For PDF:
   printf '%s' '{{"content_type": "pdf", "raw_path": "paper.pdf", "source_url": "<ACTUAL_URL_USED>"}}' > manifest.json
   For HTML:
   printf '%s' '{{"content_type": "html", "raw_path": "paper.html", "source_url": "<ACTUAL_URL_USED>"}}' > manifest.json

Replace <ACTUAL_URL_USED> with the URL you actually downloaded from (after any conversions in step 1).

IMPORTANT: Use Bash to write manifest.json (not the Write tool). The manifest must be valid JSON.
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

    return FetchResult(
        content_type=data["content_type"],
        raw_path=str(raw_path.resolve()),
        source_url=data["source_url"],
    )
