"""eLife article XML reader and JATS parser.

Reads from a local clone of https://github.com/elifesciences/elife-article-xml
by default (expected at ../elife-article-xml relative to the project root).
Falls back to fetching from GitHub if no local clone is present.
"""

from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from lxml import etree

# Default local clone location: sibling directory of paper2tree
_PROJECT_ROOT = Path(__file__).parent.parent
LOCAL_REPO_DEFAULT = _PROJECT_ROOT.parent / "elife-article-xml"

GITHUB_RAW = "https://raw.githubusercontent.com/elifesciences/elife-article-xml/HEAD"
GITHUB_API = "https://api.github.com/repos/elifesciences/elife-article-xml"

_LIFE_SCIENCES = {
    "cell biology",
    "developmental biology",
    "ecology",
    "evolutionary biology",
    "genetics and genomics",
    "plant biology",
    "physics of living systems",
    "structural biology and molecular biophysics",
    "chromosomes and gene expression",
    "computational and systems biology",
}
_BIOMEDICAL = {
    "biochemistry and chemical biology",
    "epidemiology and global health",
    "immunology and inflammation",
    "medicine",
    "microbiology and infectious disease",
    "neuroscience",
    "stem cells and regenerative medicine",
}


@dataclass
class ELifePaper:
    article_id: str  # numeric string, e.g. "12345"
    filename: str  # source filename, e.g. "elife-12345-v3.xml"
    doi: str
    title: str
    authors: list[str]
    year: int
    abstract: str
    subject_areas: list[str]
    category: str  # "life_sciences" | "biomedical" | "other"
    article_text: str  # body text stripped of figures/tables
    human_review: str  # decision-letter + referee-reports concatenated
    elife_assessment: str | None = None
    word_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.word_count = len(self.article_text.split())


# ── Local repo access ──────────────────────────────────────────────────────────


def list_articles_local(repo_path: Path) -> list[str]:
    """Return all XML filenames from the local articles/ directory."""
    articles_dir = repo_path / "articles"
    return [p.name for p in articles_dir.glob("*.xml")]


def read_article_local(repo_path: Path, filename: str) -> str:
    """Read an article XML file from the local clone."""
    return (repo_path / "articles" / filename).read_text(encoding="utf-8")


# ── GitHub fallback ────────────────────────────────────────────────────────────


def _api_headers(token: str | None) -> dict[str, str]:
    h = {"Accept": "application/vnd.github.v3+json"}
    if token:
        h["Authorization"] = f"token {token}"
    return h


def _get_with_retry(
    url: str, headers: dict, params: dict | None = None, max_retries: int = 3
) -> httpx.Response:
    for attempt in range(max_retries):
        try:
            resp = httpx.get(
                url, headers=headers, params=params, timeout=60.0, follow_redirects=True
            )
            if resp.status_code in (429, 503):
                time.sleep(2 ** (attempt + 2))
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError:
            if attempt == max_retries - 1:
                raise
            time.sleep(2**attempt)
    raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts")


def list_articles_github(token: str | None = None) -> list[str]:
    """Return all article XML filenames via the GitHub git-trees API."""
    headers = _api_headers(token)
    resp = _get_with_retry(
        f"{GITHUB_API}/git/trees/HEAD",
        headers=headers,
        params={"recursive": "1"},
    )
    data = resp.json()
    if data.get("truncated"):
        print("  WARNING: GitHub tree response truncated — article list may be incomplete")
    return [
        item["path"][len("articles/") :]
        for item in data.get("tree", [])
        if item["path"].startswith("articles/") and item["path"].endswith(".xml")
    ]


def read_article_github(filename: str) -> str:
    """Fetch an article XML file from GitHub raw CDN."""
    resp = _get_with_retry(
        f"{GITHUB_RAW}/articles/{filename}",
        headers={"Accept": "application/xml"},
    )
    return resp.text


# ── Version deduplication ──────────────────────────────────────────────────────


def _latest_versions(filenames: list[str]) -> list[str]:
    """For each article ID keep only the highest-version filename."""
    pattern = re.compile(r"^elife-(\d+)-v(\d+)\.xml$")
    best: dict[str, tuple[int, str]] = {}
    for fn in filenames:
        m = pattern.match(fn)
        if not m:
            continue
        art_id, version = m.group(1), int(m.group(2))
        if art_id not in best or version > best[art_id][0]:
            best[art_id] = (version, fn)
    return [v[1] for v in best.values()]


# ── JATS XML parsing ───────────────────────────────────────────────────────────


def _text_of(elements: list, sep: str = "\n\n") -> str:
    parts = []
    for el in elements:
        t = "".join(el.itertext()).strip()
        if t:
            parts.append(t)
    return sep.join(parts)


def _extract_body_text(root: etree._Element) -> str:
    body = root.find("body")
    if body is None:
        return ""
    return _text_of(body.findall(".//p"))


def _extract_sub_article(root: etree._Element, article_type: str) -> str:
    parts = []
    for sa in root.findall(f"sub-article[@article-type='{article_type}']"):
        body = sa.find("body")
        if body is None:
            continue
        parts.append(_text_of(body.findall(".//p")))
    return "\n\n".join(p for p in parts if p)


def parse_article(xml_content: str, filename: str) -> ELifePaper | None:
    """Parse a JATS XML string into an ELifePaper.

    Returns None if ineligible: not a research-article, year < 2018,
    no decision-letter or referee-report, or article body too short.
    """
    try:
        root = etree.fromstring(xml_content.encode())
    except etree.XMLSyntaxError:
        return None

    if root.get("article-type", "") != "research-article":
        return None

    # Publication year
    year_el = (
        root.find(".//pub-date[@date-type='pub']/year")
        or root.find(".//pub-date[@publication-type='epub']/year")
        or root.find(".//pub-date/year")
    )
    if year_el is None or not year_el.text:
        return None
    try:
        year = int(year_el.text)
    except ValueError:
        return None
    if year < 2018:
        return None

    has_review = (
        root.find("sub-article[@article-type='decision-letter']") is not None
        or root.find("sub-article[@article-type='referee-report']") is not None
    )
    if not has_review:
        return None

    doi_el = root.find(".//article-meta/article-id[@pub-id-type='doi']")
    doi = doi_el.text.strip() if doi_el is not None and doi_el.text else ""

    title_el = root.find(".//article-meta/title-group/article-title")
    title = "".join(title_el.itertext()).strip() if title_el is not None else filename

    authors: list[str] = []
    for contrib in root.findall(".//article-meta//contrib[@contrib-type='author']"):
        surname = contrib.findtext("name/surname", default="")
        given = contrib.findtext("name/given-names", default="")
        name = f"{given} {surname}".strip()
        if name:
            authors.append(name)

    abstract_el = root.find(".//article-meta/abstract")
    abstract = _text_of(abstract_el.findall(".//p")) if abstract_el is not None else ""

    subject_areas: list[str] = []
    for sg in root.findall(".//subj-group[@subj-group-type='heading']"):
        for subj in sg.findall("subject"):
            if subj.text:
                subject_areas.append(subj.text.strip())

    lower_areas = {s.lower() for s in subject_areas}
    if lower_areas & _BIOMEDICAL:
        category = "biomedical"
    elif lower_areas & _LIFE_SCIENCES:
        category = "life_sciences"
    else:
        category = "other"

    article_text = _extract_body_text(root)
    if len(article_text.split()) < 500:
        return None

    decision_letter = _extract_sub_article(root, "decision-letter")
    referee_reports = _extract_sub_article(root, "referee-report")
    human_review_parts = [p for p in [decision_letter, referee_reports] if p]
    if not human_review_parts:
        return None
    human_review = "\n\n---\n\n".join(human_review_parts)

    assessment = _extract_sub_article(root, "editor-report") or None

    m = re.match(r"elife-(\d+)-v\d+\.xml", filename)
    article_id = m.group(1) if m else filename.replace(".xml", "")

    return ELifePaper(
        article_id=article_id,
        filename=filename,
        doi=doi,
        title=title,
        authors=authors,
        year=year,
        abstract=abstract,
        subject_areas=subject_areas,
        category=category,
        article_text=article_text,
        human_review=human_review,
        elife_assessment=assessment,
    )


# ── Sampling ───────────────────────────────────────────────────────────────────


def sample_eligible_papers(
    n: int = 10,
    seed: int = 42,
    repo_path: Path | None = None,
    token: str | None = None,
    log=print,
) -> list[ELifePaper]:
    """Sample n eligible eLife papers with fixed-seed stratification.

    Reads from the local clone at repo_path when available; falls back to
    GitHub API + raw CDN. The sample is deterministic for a given seed.

    Stratification: up to n//2 life-sciences papers and up to n//2 biomedical
    papers; any shortfall in one bucket is filled from the other or from the
    uncategorised remainder.
    """
    if repo_path is None:
        repo_path = LOCAL_REPO_DEFAULT

    use_local = repo_path is not None and (repo_path / "articles").is_dir()

    if use_local:
        log(f"  Reading article list from local clone: {repo_path}/articles/")
        all_files = list_articles_local(repo_path)
    else:
        if token is None:
            token = os.environ.get("GITHUB_TOKEN")
        log("  Local clone not found — fetching article list from GitHub…")
        all_files = list_articles_github(token=token)

    latest = _latest_versions(all_files)
    log(f"  {len(latest):,} unique articles found")

    rng = random.Random(seed)
    rng.shuffle(latest)

    life_sciences: list[ELifePaper] = []
    biomedical: list[ELifePaper] = []
    other: list[ELifePaper] = []
    parsed = 0
    target_per_bucket = (n + 1) // 2

    for filename in latest:
        if len(life_sciences) >= target_per_bucket and len(biomedical) >= target_per_bucket:
            break

        try:
            if use_local:
                xml = read_article_local(repo_path, filename)
            else:
                log(f"  Fetching {filename}…")
                xml = read_article_github(filename)
                time.sleep(0.05)
        except Exception as e:
            log(f"    read error ({filename}): {e}")
            continue

        paper = parse_article(xml, filename)
        parsed += 1
        if paper is None:
            continue

        if paper.category == "life_sciences" and len(life_sciences) < target_per_bucket:
            life_sciences.append(paper)
            log(f"  + life_sciences  [{len(life_sciences)}/{target_per_bucket}]  {filename}")
        elif paper.category == "biomedical" and len(biomedical) < target_per_bucket:
            biomedical.append(paper)
            log(f"  + biomedical     [{len(biomedical)}/{target_per_bucket}]  {filename}")
        else:
            other.append(paper)

        if parsed % 500 == 0:
            log(f"  … scanned {parsed:,} files")

    pool = life_sciences + biomedical
    if len(pool) < n:
        pool.extend(other[: n - len(pool)])

    result = pool[:n]
    log(
        f"  Sampled {len(result)} papers "
        f"({sum(1 for p in result if p.category == 'life_sciences')} life_sciences, "
        f"{sum(1 for p in result if p.category == 'biomedical')} biomedical)"
    )
    return result
