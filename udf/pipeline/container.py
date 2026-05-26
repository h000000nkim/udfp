"""Original container and conversion trace — seed patch support and provenance tracking."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class OriginalContainer(_Base):
    """Reference to the original file container for Seed Patch mode generation."""

    format: Literal["ole2", "zip", "none"]
    path: str
    checksum: str


class ConversionTrace(_Base):
    """Provenance record: when and how the document was parsed."""

    parsed_at: str
    parser_version: str
    checksum: str | None = None
