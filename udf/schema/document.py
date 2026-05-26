"""DocumentSchema — pure document content model, independent of conversion infrastructure."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .blocks import Block
from .metadata import DocumentMetadata, PageBoundary


class DocumentSchema(BaseModel):
    """The format-agnostic document content definition.

    Fully describes document structure and content without any conversion
    infrastructure (verbatim, original_container, etc.).
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    blocks: list[Block] = []
    page_boundaries: list[PageBoundary] = []
