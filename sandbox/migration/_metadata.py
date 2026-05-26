"""DocumentMetadata, PageMargins, SectionDef, ColumnDef v1↔v2 변환."""

from __future__ import annotations

from udf.core import schema as v1

from sandbox.schema import metadata as v2m

from ._types import format_mm, parse_dimension, parse_mm


def _margins_to_v2(m: v1.PageMargins | None) -> v2m.PageMargins | None:
    if m is None:
        return None
    return v2m.PageMargins(
        top=parse_mm(m.top) or 0.0,
        bottom=parse_mm(m.bottom) or 0.0,
        left=parse_mm(m.left) or 0.0,
        right=parse_mm(m.right) or 0.0,
    )


def _margins_to_v1(m: v2m.PageMargins | None) -> v1.PageMargins | None:
    if m is None:
        return None
    return v1.PageMargins(
        top=format_mm(m.top) or "0.0mm",
        bottom=format_mm(m.bottom) or "0.0mm",
        left=format_mm(m.left) or "0.0mm",
        right=format_mm(m.right) or "0.0mm",
    )


def _column_to_v2(c: v1.ColumnDef | None) -> v2m.ColumnDef | None:
    if c is None:
        return None
    return v2m.ColumnDef(
        count=c.count,
        gap=parse_mm(c.gap),
        same_width=c.same_width,
        widths=[parse_mm(w) or 0.0 for w in c.widths],
    )


def _column_to_v1(c: v2m.ColumnDef | None) -> v1.ColumnDef | None:
    if c is None:
        return None
    return v1.ColumnDef(
        count=c.count,
        gap=format_mm(c.gap),
        same_width=c.same_width,
        widths=[format_mm(w) or "0.0mm" for w in c.widths],
    )


def _section_to_v2(s: v1.SectionDef) -> v2m.SectionDef:
    return v2m.SectionDef(
        page_width=parse_dimension(s.page_width),
        page_height=parse_dimension(s.page_height),
        margins=_margins_to_v2(s.margins),
        header_margin=parse_mm(s.header_margin),
        footer_margin=parse_mm(s.footer_margin),
        gutter=parse_mm(s.gutter),
        columns=_column_to_v2(s.columns),
    )


def _section_to_v1(s: v2m.SectionDef) -> v1.SectionDef:
    return v1.SectionDef(
        page_width=format_mm(s.page_width),
        page_height=format_mm(s.page_height),
        margins=_margins_to_v1(s.margins),
        header_margin=format_mm(s.header_margin),
        footer_margin=format_mm(s.footer_margin),
        gutter=format_mm(s.gutter),
        columns=_column_to_v1(s.columns),
    )


def metadata_to_v2(meta: v1.DocumentMetadata) -> v2m.DocumentMetadata:
    return v2m.DocumentMetadata(
        title=meta.title,
        author=meta.author,
        page_width=parse_dimension(getattr(meta, "paper_width", None)),
        page_height=parse_dimension(getattr(meta, "paper_height", None)),
        margins=_margins_to_v2(meta.margins),
        header_margin=parse_mm(meta.header_margin),
        footer_margin=parse_mm(meta.footer_margin),
        gutter=parse_mm(meta.gutter),
        start_page_number=getattr(meta, "start_page_number", None),
        start_footnote_number=getattr(meta, "start_footnote_number", None),
        start_endnote_number=getattr(meta, "start_endnote_number", None),
        start_picture_number=getattr(meta, "start_picture_number", None),
        start_table_number=getattr(meta, "start_table_number", None),
        start_equation_number=getattr(meta, "start_equation_number", None),
        created_at=meta.created_at,
        modified_at=meta.modified_at,
        columns=_column_to_v2(meta.columns),
        sections=[_section_to_v2(s) for s in meta.sections],
    )


def metadata_to_v1(meta: v2m.DocumentMetadata) -> v1.DocumentMetadata:
    return v1.DocumentMetadata(
        title=meta.title,
        author=meta.author,
        paper_width=format_mm(meta.page_width),
        paper_height=format_mm(meta.page_height),
        margins=_margins_to_v1(meta.margins),
        header_margin=format_mm(meta.header_margin),
        footer_margin=format_mm(meta.footer_margin),
        gutter=format_mm(meta.gutter),
        start_page_number=meta.start_page_number,
        start_footnote_number=meta.start_footnote_number,
        start_endnote_number=meta.start_endnote_number,
        start_picture_number=meta.start_picture_number,
        start_table_number=meta.start_table_number,
        start_equation_number=meta.start_equation_number,
        created_at=meta.created_at,
        modified_at=meta.modified_at,
        columns=_column_to_v1(meta.columns),
        sections=[_section_to_v1(s) for s in meta.sections],
    )
