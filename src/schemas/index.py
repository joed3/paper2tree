from pydantic import BaseModel


class PaperIndexEntry(BaseModel):
    paper_id: str
    title: str
    authors: list[str]
    url: str
    abstract_short: str
    processed_at: str
    high_support_count: int
    total_claims: int
    result_path: str  # relative to outputs/: "<paper_id>/dag.json"


class PaperIndex(BaseModel):
    version: int = 1
    papers: list[PaperIndexEntry] = []
