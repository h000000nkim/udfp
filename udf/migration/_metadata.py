"""DocumentMetadata, PageMargins, SectionDef, ColumnDef v1↔v2 변환."""

from __future__ import annotations

from udf.core import _schema_v1 as v1

from udf.schema import metadata as v2m

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
        separator=c.separator,
    )


def _column_to_v1(c: v2m.ColumnDef | None) -> v1.ColumnDef | None:
    if c is None:
        return None
    return v1.ColumnDef(
        count=c.count,
        gap=format_mm(c.gap),
        same_width=c.same_width,
        widths=[format_mm(w) or "0.0mm" for w in c.widths],
        separator=c.separator,
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
        start_page_number=s.start_page_number,
        orientation=s.orientation,
        break_type=s.break_type,
        page_number_format=s.page_number_format,
        background_color=s.background_color,
        background_image=s.background_image,
        border_top=s.border_top,
        border_bottom=s.border_bottom,
        border_left=s.border_left,
        border_right=s.border_right,
        line_numbering=s.line_numbering,
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
        start_page_number=s.start_page_number,
        orientation=s.orientation,
        break_type=s.break_type,
        page_number_format=s.page_number_format,
        background_color=s.background_color,
        background_image=s.background_image,
        border_top=s.border_top,
        border_bottom=s.border_bottom,
        border_left=s.border_left,
        border_right=s.border_right,
        line_numbering=s.line_numbering,
    )


def metadata_to_v2(meta: v1.DocumentMetadata) -> v2m.DocumentMetadata:
    """Convert v1 DocumentMetadata to v2 DocumentMetadata.

    Parameters
    ----------
    meta : v1.DocumentMetadata
        Source v1 metadata.

    Returns
    -------
    v2m.DocumentMetadata
        Converted v2 metadata.
    """
    return v2m.DocumentMetadata(
        title=meta.title,
        author=meta.author,
        subject=meta.subject,
        keywords=list(meta.keywords),
        language=meta.language,
        page_size=meta.page_size,
        page_width=parse_dimension(getattr(meta, "paper_width", None)),
        page_height=parse_dimension(getattr(meta, "paper_height", None)),
        margins=_margins_to_v2(meta.margins),
        header_margin=parse_mm(meta.header_margin),
        footer_margin=parse_mm(meta.footer_margin),
        gutter=parse_mm(meta.gutter),
        start_page_number=meta.start_page_number,
        start_footnote_number=meta.start_footnote_number,
        start_endnote_number=meta.start_endnote_number,
        start_picture_number=meta.start_picture_number,
        start_table_number=meta.start_table_number,
        start_equation_number=meta.start_equation_number,
        created_at=meta.created_at,
        modified_at=meta.modified_at,
        footnote_numbering_format=meta.footnote_numbering_format,
        endnote_numbering_format=meta.endnote_numbering_format,
        columns=_column_to_v2(meta.columns),
        sections=[_section_to_v2(s) for s in meta.sections],
        compatibility_target=meta.compatibility_target,
    )


def metadata_to_v1(meta: v2m.DocumentMetadata) -> v1.DocumentMetadata:
    """Convert v2 DocumentMetadata to v1 DocumentMetadata.

    Parameters
    ----------
    meta : v2m.DocumentMetadata
        Source v2 metadata.

    Returns
    -------
    v1.DocumentMetadata
        Converted v1 metadata.
    """
    return v1.DocumentMetadata(
        title=meta.title,
        author=meta.author,
        subject=meta.subject,
        keywords=list(meta.keywords),
        language=meta.language,
        page_size=meta.page_size,
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
        footnote_numbering_format=meta.footnote_numbering_format,
        endnote_numbering_format=meta.endnote_numbering_format,
        columns=_column_to_v1(meta.columns),
        sections=[_section_to_v1(s) for s in meta.sections],
        compatibility_target=meta.compatibility_target,
    )
