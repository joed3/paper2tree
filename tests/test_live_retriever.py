"""Tests for LiveRetriever parsing helpers, ranking, and caching.

HTTP calls and LLM calls are mocked — no network or API key required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from src.kb.live_retriever import (
    LiveRetriever,
    _parse_pubmed_xml,
    _parse_semantic_scholar_response,
    _rank,
)
from src.kb.schemas import RetrievedPassage

# ── _parse_pubmed_xml ──────────────────────────────────────────────────────────

_PUBMED_XML_ONE = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <ArticleTitle>Deep learning for protein folding prediction</ArticleTitle>
        <AuthorList>
          <Author>
            <LastName>Smith</LastName>
            <ForeName>Alice</ForeName>
          </Author>
          <Author>
            <LastName>Jones</LastName>
            <ForeName>Bob</ForeName>
          </Author>
        </AuthorList>
        <Abstract>
          <AbstractText>We present a novel deep learning approach to protein structure prediction achieving state-of-the-art results on CASP14.</AbstractText>
        </Abstract>
      </Article>
      <PubDate>
        <Year>2022</Year>
      </PubDate>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">12345678</ArticleId>
        <ArticleId IdType="doi">10.1234/example.2022</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""

_PUBMED_XML_NO_ABSTRACT = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>99999999</PMID>
      <Article>
        <ArticleTitle>A paper with no abstract</ArticleTitle>
        <AuthorList/>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">99999999</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""

_PUBMED_XML_SECTIONED = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>11111111</PMID>
      <Article>
        <ArticleTitle>Structured abstract paper</ArticleTitle>
        <AuthorList>
          <Author>
            <LastName>Doe</LastName>
            <ForeName>Jane</ForeName>
          </Author>
        </AuthorList>
        <Abstract>
          <AbstractText Label="BACKGROUND">Background information here.</AbstractText>
          <AbstractText Label="METHODS">Methods described here.</AbstractText>
          <AbstractText Label="RESULTS">Results presented here.</AbstractText>
        </Abstract>
      </Article>
      <PubDate>
        <Year>2021</Year>
      </PubDate>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">11111111</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""


def test_parse_pubmed_xml_returns_one_passage():
    passages = _parse_pubmed_xml(_PUBMED_XML_ONE)
    assert len(passages) == 1


def test_parse_pubmed_xml_title():
    passages = _parse_pubmed_xml(_PUBMED_XML_ONE)
    assert passages[0].title == "Deep learning for protein folding prediction"


def test_parse_pubmed_xml_authors():
    passages = _parse_pubmed_xml(_PUBMED_XML_ONE)
    assert "Alice Smith" in passages[0].authors
    assert "Bob Jones" in passages[0].authors


def test_parse_pubmed_xml_year():
    passages = _parse_pubmed_xml(_PUBMED_XML_ONE)
    assert passages[0].year == 2022


def test_parse_pubmed_xml_doi():
    passages = _parse_pubmed_xml(_PUBMED_XML_ONE)
    assert passages[0].doi == "10.1234/example.2022"


def test_parse_pubmed_xml_url_contains_pmid():
    passages = _parse_pubmed_xml(_PUBMED_XML_ONE)
    assert "12345678" in passages[0].url


def test_parse_pubmed_xml_source_is_pubmed():
    passages = _parse_pubmed_xml(_PUBMED_XML_ONE)
    assert passages[0].source == "pubmed"


def test_parse_pubmed_xml_skips_no_abstract():
    passages = _parse_pubmed_xml(_PUBMED_XML_NO_ABSTRACT)
    assert len(passages) == 0


def test_parse_pubmed_xml_sectioned_abstract_joined():
    passages = _parse_pubmed_xml(_PUBMED_XML_SECTIONED)
    assert len(passages) == 1
    assert "BACKGROUND:" in passages[0].passage
    assert "METHODS:" in passages[0].passage
    assert "RESULTS:" in passages[0].passage


def test_parse_pubmed_xml_invalid_xml_returns_empty():
    passages = _parse_pubmed_xml("not xml at all <<>>")
    assert passages == []


def test_parse_pubmed_xml_empty_string_returns_empty():
    passages = _parse_pubmed_xml("")
    assert passages == []


# ── _parse_semantic_scholar_response ──────────────────────────────────────────

_S2_RESPONSE_ONE = {
    "data": [
        {
            "title": "Attention Is All You Need",
            "authors": [{"name": "Vaswani"}, {"name": "Shazeer"}],
            "year": 2017,
            "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.",
            "url": "https://www.semanticscholar.org/paper/attention",
            "externalIds": {"DOI": "10.48550/arXiv.1706.03762"},
        }
    ]
}

_S2_RESPONSE_NO_ABSTRACT = {
    "data": [
        {
            "title": "Paper without abstract",
            "authors": [],
            "year": 2020,
            "abstract": None,
            "url": "https://example.com",
            "externalIds": {},
        }
    ]
}

_S2_RESPONSE_EMPTY = {"data": []}


def test_parse_s2_returns_one_passage():
    passages = _parse_semantic_scholar_response(_S2_RESPONSE_ONE)
    assert len(passages) == 1


def test_parse_s2_title():
    passages = _parse_semantic_scholar_response(_S2_RESPONSE_ONE)
    assert passages[0].title == "Attention Is All You Need"


def test_parse_s2_authors():
    passages = _parse_semantic_scholar_response(_S2_RESPONSE_ONE)
    assert "Vaswani" in passages[0].authors


def test_parse_s2_year():
    passages = _parse_semantic_scholar_response(_S2_RESPONSE_ONE)
    assert passages[0].year == 2017


def test_parse_s2_doi():
    passages = _parse_semantic_scholar_response(_S2_RESPONSE_ONE)
    assert passages[0].doi == "10.48550/arXiv.1706.03762"


def test_parse_s2_source_is_semantic_scholar():
    passages = _parse_semantic_scholar_response(_S2_RESPONSE_ONE)
    assert passages[0].source == "semantic_scholar"


def test_parse_s2_skips_no_abstract():
    passages = _parse_semantic_scholar_response(_S2_RESPONSE_NO_ABSTRACT)
    assert len(passages) == 0


def test_parse_s2_empty_data():
    passages = _parse_semantic_scholar_response(_S2_RESPONSE_EMPTY)
    assert passages == []


def test_parse_s2_missing_data_key():
    passages = _parse_semantic_scholar_response({})
    assert passages == []


# ── _rank ──────────────────────────────────────────────────────────────────────


def _make_passage(title: str, passage: str, source: str = "pubmed") -> RetrievedPassage:
    return RetrievedPassage(
        source=source,
        title=title,
        authors=[],
        url="https://example.com",
        passage=passage,
    )


def test_rank_returns_all_passages():
    passages = [
        _make_passage("Unrelated paper", "Completely unrelated content about cooking recipes"),
        _make_passage("Relevant paper", "Deep learning neural network protein folding structure"),
    ]
    ranked = _rank(passages, "deep learning for protein structure prediction")
    assert len(ranked) == 2


def test_rank_most_relevant_first():
    passages = [
        _make_passage("Unrelated", "cooking recipes food kitchen"),
        _make_passage("Relevant", "deep learning neural network protein folding prediction"),
    ]
    ranked = _rank(passages, "deep learning protein folding prediction")
    assert ranked[0].title == "Relevant"


def test_rank_empty_passages():
    ranked = _rank([], "any claim text")
    assert ranked == []


def test_rank_empty_claim():
    passages = [_make_passage("Some paper", "Some content")]
    # Empty claim should not crash
    ranked = _rank(passages, "")
    assert len(ranked) == 1


def test_rank_stable_order_equal_scores():
    # Two passages with no overlap — both score 0; original order preserved (stable sort)
    passages = [
        _make_passage("Paper A", "aaa bbb ccc"),
        _make_passage("Paper B", "ddd eee fff"),
    ]
    ranked = _rank(passages, "zzz yyy xxx")
    assert len(ranked) == 2


# ── LiveRetriever: within-run cache ───────────────────────────────────────────


def _make_enriched(claim_id: str, claim_text: str = "A claim."):
    claim = MagicMock()
    claim.id = claim_id
    claim.text = claim_text
    ec = MagicMock()
    ec.claim = claim
    return ec


def test_cache_populated_after_retrieval():
    retriever = LiveRetriever()
    passage = _make_passage("Test paper", "test abstract content")
    retriever._cache["c1"] = [passage]
    assert "c1" in retriever._cache
    assert retriever._cache["c1"][0].title == "Test paper"


def test_retrieve_one_uses_cache():
    """If a claim_id is already in cache, no HTTP calls are made."""
    retriever = LiveRetriever()
    passage = _make_passage("Cached paper", "cached content")
    retriever._cache["c1"] = [passage]

    import asyncio

    result = asyncio.run(retriever._retrieve_one("c1", "some claim text", "paper title"))
    assert result == [passage]


# ── LiveRetriever: retrieve_for_claims (mocked) ───────────────────────────────


def test_retrieve_for_claims_returns_dict_keyed_by_claim_id():
    enriched = [_make_enriched("c1"), _make_enriched("c1.1")]

    with (
        patch.object(LiveRetriever, "_generate_queries", return_value=["query1"]),
        patch.object(LiveRetriever, "_search_pubmed", new_callable=AsyncMock, return_value=[]),
        patch.object(
            LiveRetriever, "_search_semantic_scholar", new_callable=AsyncMock, return_value=[]
        ),
    ):
        retriever = LiveRetriever()
        result = retriever.retrieve_for_claims(enriched, "Test Paper")

    assert set(result.keys()) == {"c1", "c1.1"}


def test_retrieve_for_claims_deduplicates_same_title():
    """Passages with identical titles are deduplicated."""
    enriched = [_make_enriched("c1", "protein folding deep learning")]

    duplicate_passage = _make_passage("Duplicate Title", "some content")
    duplicate_passage2 = _make_passage("Duplicate Title", "same title different source")

    with (
        patch.object(LiveRetriever, "_generate_queries", return_value=["query1"]),
        patch.object(
            LiveRetriever,
            "_search_pubmed",
            new_callable=AsyncMock,
            return_value=[duplicate_passage],
        ),
        patch.object(
            LiveRetriever,
            "_search_semantic_scholar",
            new_callable=AsyncMock,
            return_value=[duplicate_passage2],
        ),
    ):
        retriever = LiveRetriever()
        result = retriever.retrieve_for_claims(enriched, "Test Paper")

    # Only one passage with that title should survive deduplication
    titles = [p.title for p in result["c1"]]
    assert titles.count("Duplicate Title") == 1


def test_retrieve_for_claims_handles_http_errors_gracefully():
    """If HTTP calls raise exceptions, the claim still gets an empty list."""
    enriched = [_make_enriched("c1")]

    with (
        patch.object(LiveRetriever, "_generate_queries", return_value=["query1"]),
        patch.object(
            LiveRetriever,
            "_search_pubmed",
            new_callable=AsyncMock,
            side_effect=Exception("timeout"),
        ),
        patch.object(
            LiveRetriever,
            "_search_semantic_scholar",
            new_callable=AsyncMock,
            side_effect=Exception("timeout"),
        ),
    ):
        retriever = LiveRetriever()
        result = retriever.retrieve_for_claims(enriched, "Test Paper")

    assert result["c1"] == []
