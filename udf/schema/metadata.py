"""Document metadata — whole-document properties (page layout, numbering, sections). Lengths in pt."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class PageMargins(_Base):
    """Page margin dimensions (top, bottom, left, right) in pt."""

    top: float
    bottom: float
    left: float
    right: float


class ColumnDef(_Base):
    """Multi-column layout definition (count, gap, widths)."""

    count: int = 1
    gap: float | None = None
    same_width: bool = True
    widths: list[float] = []
    separator: bool | None = None


class SectionDef(_Base):
    """A document section with its own page geometry, margins, and column layout."""

    page_width: float | None = None
    page_height: float | None = None
    margins: PageMargins | None = None
    header_margin: float | None = None
    footer_margin: float | None = None
    gutter: float | None = None
    columns: ColumnDef | None = None
    start_page_number: int | None = None
    orientation: Literal["portrait", "landscape"] | None = None
    break_type: Literal["next_page", "continuous", "even_page", "odd_page", "new_column"] | None = None
    page_number_format: Literal[
        "decimal", "roman_lower", "roman_upper",
        "alpha_lower", "alpha_upper", "hangul",
        "ganada", "circled_decimal",
    ] | None = None
    background_color: str | None = None
    background_image: str | None = None
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    line_numbering: bool | None = None


class DocumentMetadata(_Base):
    """Top-level document metadata: title, author, page layout, numbering config."""

    title: str | None = None
    author: str | None = None
    subject: str | None = None
    keywords: list[str] = []
    language: str | None = None
    page_size: str | None = None
    page_width: float | None = None
    page_height: float | None = None
    margins: PageMargins | None = None
    header_margin: float | None = None
    footer_margin: float | None = None
    gutter: float | None = None
    start_page_number: int | None = None
    start_footnote_number: int | None = None
    start_endnote_number: int | None = None
    start_picture_number: int | None = None
    start_table_number: int | None = None
    start_equation_number: int | None = None
    created_at: str | None = None
    modified_at: str | None = None
    footnote_numbering_format: Literal[
        "decimal", "roman_lower", "roman_upper",
        "alpha_lower", "alpha_upper", "symbol",
    ] | None = None
    endnote_numbering_format: Literal[
        "decimal", "roman_lower", "roman_upper",
        "alpha_lower", "alpha_upper", "symbol",
    ] | None = None
    columns: ColumnDef | None = None
    sections: list[SectionDef] = []
    compatibility_target: str | None = None


class PageBoundary(_Base):
    """Marks the start (and optional end) block of a physical page."""

    page: int
    start: str
    end: str | None = None
