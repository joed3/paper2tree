from pydantic import BaseModel


class RetrievedPassage(BaseModel):
    source: str  # "pubmed" | "semantic_scholar"
    title: str
    authors: list[str]
    year: int | None = None
    url: str
    passage: str  # abstract or excerpt
    doi: str | None = None
