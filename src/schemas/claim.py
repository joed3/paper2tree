from typing import Literal

from pydantic import BaseModel, model_validator


class Claim(BaseModel):
    id: str
    text: str
    type: Literal["root", "primary", "supporting", "evidence"]
    parent_id: str | None = None
    section_source: str
    verbatim_quote: str
    page_number: int | None = None  # 0-indexed page in source PDF; None for HTML sources
    bbox: list[list[float]] | None = None  # [[x0,y0,x1,y1], …] one rect per matched line


class ClaimGraph(BaseModel):
    claims: list[Claim]

    @model_validator(mode="after")
    def validate_structure(self) -> "ClaimGraph":
        if not self.claims:
            raise ValueError("ClaimGraph must have at least one claim")

        roots = [c for c in self.claims if c.parent_id is None]
        if not roots:
            raise ValueError("No root claim found (no claim with parent_id=None)")

        typed_roots = [c for c in self.claims if c.type == "root"]
        if len(typed_roots) > 1:
            raise ValueError(f"Expected exactly 1 root claim, got {len(typed_roots)}")

        # Check all parent_ids reference existing claim ids
        ids = {c.id for c in self.claims}
        for claim in self.claims:
            if claim.parent_id is not None and claim.parent_id not in ids:
                raise ValueError(
                    f"Claim {claim.id!r} references unknown parent_id {claim.parent_id!r}"
                )

        return self
