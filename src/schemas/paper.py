from pydantic import BaseModel


class FetchResult(BaseModel):
    content_type: str  # "pdf" | "html" | "text"
    raw_path: str  # absolute path to downloaded file
    source_url: str  # final URL after redirects


class ExtractedSection(BaseModel):
    heading: str
    text: str


class ExtractedPaperStructure(BaseModel):
    """The structured metadata Claude extracts from raw text."""

    title: str
    authors: list[str]
    abstract: str
    sections: list[ExtractedSection]


class ExtractedPaper(BaseModel):
    """Full extracted paper including raw text."""

    title: str
    authors: list[str]
    abstract: str
    sections: list[ExtractedSection]
    full_text: str = ""
    word_count: int = 0
