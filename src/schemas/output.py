from pydantic import BaseModel


class VisualMeta(BaseModel):
    color: str
    size: int
    border_width: int


class DAGNode(BaseModel):
    id: str
    label: str  # truncated claim text for display
    claim: str  # full claim text
    type: str
    depth: int
    section_source: str
    verbatim_quote: str
    evaluation: dict | None = None
    visual: VisualMeta
    page_number: int | None = None
    bbox: list[list[float]] | None = None  # [[x0,y0,x1,y1], …] one rect per matched line


class DAGEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship: str
    label: str


class DAGData(BaseModel):
    nodes: list[DAGNode]
    edges: list[DAGEdge]


class PaperMeta(BaseModel):
    paper_id: str
    title: str
    authors: list[str]
    url: str
    abstract: str
    word_count: int
    processed_at: str
    has_local_pdf: bool = False


class DAGSummary(BaseModel):
    total_nodes: int
    total_edges: int
    max_depth: int
    high_support_nodes: int
    low_support_nodes: int
    overall_assessment: str


SCHEMA_VERSION = 2


class PaperDAG(BaseModel):
    schema_version: int = SCHEMA_VERSION
    paper: PaperMeta
    dag: DAGData
    summary: DAGSummary
    final_review: str | None = None  # eLife-format prose review; None for pre-v1.7 papers
