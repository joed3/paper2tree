"""LiveRetriever — queries PubMed and Semantic Scholar at claim evaluation time.

Uses Claude Haiku to generate targeted search queries for each claim, then
fetches and ranks relevant passages. Caches results within a single run to
avoid redundant API calls for similar claims.
"""

import asyncio
import re
import xml.etree.ElementTree as ET

import httpx

from .. import llm
from .schemas import RetrievedPassage

_PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"

_MAX_RESULTS_PER_SOURCE = 5
_MAX_PASSAGES_PER_CLAIM = 8
_HTTP_TIMEOUT = 15.0


# ── Standalone parsing helpers (for testability) ───────────────────────────────


def _parse_pubmed_xml(xml_text: str) -> list[RetrievedPassage]:
    """Parse PubMed efetch XML into RetrievedPassage objects."""
    passages: list[RetrievedPassage] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return passages

    for article in root.findall(".//PubmedArticle"):
        try:
            # Title
            title_el = article.find(".//ArticleTitle")
            title = (title_el.text or "").strip() if title_el is not None else ""
            if not title:
                continue

            # Authors
            authors: list[str] = []
            for author in article.findall(".//Author"):
                last = author.findtext("LastName", "")
                fore = author.findtext("ForeName", "")
                name = f"{fore} {last}".strip()
                if name:
                    authors.append(name)

            # Year
            year_el = article.find(".//PubDate/Year")
            year_text = year_el.text if year_el is not None else None
            year = int(year_text) if year_text and year_text.isdigit() else None

            # Abstract
            abstract_parts: list[str] = []
            for abs_text in article.findall(".//AbstractText"):
                label = abs_text.get("Label")
                text = abs_text.text or ""
                if label:
                    abstract_parts.append(f"{label}: {text}")
                else:
                    abstract_parts.append(text)
            passage = " ".join(abstract_parts).strip()
            if not passage:
                continue

            # DOI
            doi: str | None = None
            for id_el in article.findall(".//ArticleId"):
                if id_el.get("IdType") == "doi":
                    doi = id_el.text
                    break

            # PMID for URL
            pmid_el = article.find(".//PMID")
            pmid = pmid_el.text if pmid_el is not None else None
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""

            passages.append(
                RetrievedPassage(
                    source="pubmed",
                    title=title,
                    authors=authors,
                    year=year,
                    url=url,
                    passage=passage,
                    doi=doi,
                )
            )
        except Exception:
            continue

    return passages


def _parse_semantic_scholar_response(data: dict) -> list[RetrievedPassage]:
    """Parse Semantic Scholar API response dict into RetrievedPassage objects."""
    passages: list[RetrievedPassage] = []
    for paper in data.get("data", []):
        try:
            title = (paper.get("title") or "").strip()
            if not title:
                continue

            abstract = (paper.get("abstract") or "").strip()
            if not abstract:
                continue

            authors = [a.get("name", "") for a in paper.get("authors", []) if a.get("name")]
            year = paper.get("year")
            url = paper.get("url") or ""
            doi = (paper.get("externalIds") or {}).get("DOI")

            passages.append(
                RetrievedPassage(
                    source="semantic_scholar",
                    title=title,
                    authors=authors,
                    year=year,
                    url=url,
                    passage=abstract,
                    doi=doi,
                )
            )
        except Exception:
            continue

    return passages


def _rank(passages: list[RetrievedPassage], claim_text: str) -> list[RetrievedPassage]:
    """Rank passages by lexical token overlap with the claim text."""
    claim_tokens = set(re.findall(r"\b\w+\b", claim_text.lower()))
    if not claim_tokens:
        return passages

    def score(p: RetrievedPassage) -> float:
        doc_tokens = set(re.findall(r"\b\w+\b", (p.title + " " + p.passage).lower()))
        return len(claim_tokens & doc_tokens) / len(claim_tokens)

    return sorted(passages, key=score, reverse=True)


# ── LiveRetriever ──────────────────────────────────────────────────────────────


class LiveRetriever:
    """Retrieves relevant literature passages for a set of claims.

    Uses PubMed and Semantic Scholar as sources. Queries are generated via
    Claude Haiku for each claim. Results are cached by (claim_id) within a run.
    """

    def __init__(self, ncbi_email: str = "paper2tree@example.com") -> None:
        self._ncbi_email = ncbi_email
        self._cache: dict[str, list[RetrievedPassage]] = {}

    def retrieve_for_claims(
        self,
        enriched: list,  # list[EnrichedClaim] — avoid circular import
        paper_title: str,
    ) -> dict[str, list[RetrievedPassage]]:
        """Retrieve passages for all claims. Returns dict keyed by claim_id."""
        return asyncio.run(self._retrieve_all(enriched, paper_title))

    async def _retrieve_all(
        self,
        enriched: list,
        paper_title: str,
    ) -> dict[str, list[RetrievedPassage]]:
        tasks = [self._retrieve_one(ec.claim.id, ec.claim.text, paper_title) for ec in enriched]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {ec.claim.id: (r if isinstance(r, list) else []) for ec, r in zip(enriched, results)}

    async def _retrieve_one(
        self,
        claim_id: str,
        claim_text: str,
        paper_title: str,
    ) -> list[RetrievedPassage]:
        if claim_id in self._cache:
            return self._cache[claim_id]

        queries = self._generate_queries(claim_text, paper_title)

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            fetch_tasks = []
            for query in queries:
                fetch_tasks.append(self._search_pubmed(client, query))
                fetch_tasks.append(self._search_semantic_scholar(client, query))
            all_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        passages: list[RetrievedPassage] = []
        seen_titles: set[str] = set()
        for result in all_results:
            if isinstance(result, list):
                for p in result:
                    key = p.title.lower().strip()
                    if key not in seen_titles:
                        seen_titles.add(key)
                        passages.append(p)

        ranked = _rank(passages, claim_text)
        top = ranked[:_MAX_PASSAGES_PER_CLAIM]
        self._cache[claim_id] = top
        return top

    def _generate_queries(self, claim_text: str, paper_title: str) -> list[str]:
        """Generate 2 search queries via Claude Haiku."""
        prompt = (
            f"Paper title: {paper_title}\n\n"
            f"Claim: {claim_text}\n\n"
            "Generate exactly 2 short PubMed/academic search queries (one per line) "
            "to find prior literature relevant to evaluating this claim. "
            "Queries should be specific and use key technical terms. "
            "Output ONLY the 2 queries, nothing else."
        )
        try:
            text = llm.complete(prompt, model="claude-haiku-4-5-20251001", max_tokens=128)
            queries = [line.strip() for line in text.strip().splitlines() if line.strip()]
            return queries[:2] if queries else [claim_text[:200]]
        except Exception:
            return [claim_text[:200]]

    async def _search_pubmed(self, client: httpx.AsyncClient, query: str) -> list[RetrievedPassage]:
        """Search PubMed via esearch → efetch."""
        try:
            esearch_resp = await client.get(
                _PUBMED_ESEARCH,
                params={
                    "db": "pubmed",
                    "term": query,
                    "retmax": _MAX_RESULTS_PER_SOURCE,
                    "retmode": "json",
                    "email": self._ncbi_email,
                },
            )
            esearch_resp.raise_for_status()
            ids = esearch_resp.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []

            efetch_resp = await client.get(
                _PUBMED_EFETCH,
                params={
                    "db": "pubmed",
                    "id": ",".join(ids),
                    "rettype": "abstract",
                    "retmode": "xml",
                    "email": self._ncbi_email,
                },
            )
            efetch_resp.raise_for_status()
            return _parse_pubmed_xml(efetch_resp.text)
        except Exception:
            return []

    async def _search_semantic_scholar(
        self, client: httpx.AsyncClient, query: str
    ) -> list[RetrievedPassage]:
        """Search Semantic Scholar Graph API."""
        try:
            resp = await client.get(
                _S2_SEARCH,
                params={
                    "query": query,
                    "limit": _MAX_RESULTS_PER_SOURCE,
                    "fields": "title,authors,year,abstract,url,externalIds",
                },
            )
            resp.raise_for_status()
            return _parse_semantic_scholar_response(resp.json())
        except Exception:
            return []
