from pydantic import BaseModel


class VisualMeta(BaseModel):
    color: str
    size: int
    border_width: int


class DAGNode(BaseModel):
    id: str
    label: str          # truncated claim text for display
    claim: str          # full claim text
    type: str
    depth: int
    section_source: str
    verbatim_quote: str
    evaluation: dict | None = None
    visual: VisualMeta


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


class DAGSummary(BaseModel):
    total_nodes: int
    total_edges: int
    max_depth: int
    mean_validity_score: float
    high_confidence_nodes: int
    low_confidence_nodes: int
    overall_assessment: str


class PaperDAG(BaseModel):
    paper: PaperMeta
    dag: DAGData
    summary: DAGSummary
