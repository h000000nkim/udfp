"""문서 메타데이터 — 문서 전체에 대한 정보. 길이 값은 항상 pt."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class PageMargins(_Base):
    top: float
    bottom: float
    left: float
    right: float


class ColumnDef(_Base):
    count: int = 1
    gap: float | None = None
    same_width: bool = True
    widths: list[float] = []  # 각 컬럼의 너비 (pt)


class SectionDef(_Base):
    page_width: float | None = None
    page_height: float | None = None
    margins: PageMargins | None = None
    header_margin: float | None = None
    footer_margin: float | None = None
    gutter: float | None = None
    columns: ColumnDef | None = None


class DocumentMetadata(_Base):
    title: str | None = None
    author: str | None = None
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
    columns: ColumnDef | None = None
    sections: list[SectionDef] = []


class PageBoundary(_Base):
    page: int
    start: str
    end: str | None = None
