"""BlockFormat, CellFormat, PositionInfo v1 to v2 (and v2 to v1) conversion.

Handles unit conversions (string dimensions to floats and back) and
field mapping for format, cell, position, and revision models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from udf.core import _schema_v1 as v1

from udf.schema import formats as v2f

from ._types import (
    color_to_str,
    format_mm,
    format_pt,
    line_spacing_to_v1,
    line_spacing_to_v2,
    parse_mm,
    parse_pt,
    str_to_color,
)

from udf.schema import formats as v2f_mod

if TYPE_CHECKING:
    from ._blocks import ExtensionCollector, ExtensionLookup


def block_format_to_v2(bf: v1.BlockFormat | None) -> v2f.BlockFormat | None:
    """Convert a v1 BlockFormat to v2, parsing string dimensions to floats.

    Parameters
    ----------
    bf : v1.BlockFormat or None
        The v1 block format. Returns None if input is None.

    Returns
    -------
    v2f.BlockFormat or None
        The converted v2 block format.
    """
    if bf is None:
        return None
    return v2f.BlockFormat(
        font_name=bf.font_name,
        font_size=parse_pt(bf.font_size),
        bold=bf.bold,
        italic=bf.italic,
        alignment=bf.alignment,
        line_spacing=line_spacing_to_v2(bf.line_spacing, bf.line_spacing_type),
        line_spacing_type=bf.line_spacing_type,
        space_before=parse_mm(bf.space_before),
        space_after=parse_mm(bf.space_after),
        indent_left=parse_mm(bf.indent_left),
        indent_right=parse_mm(bf.indent_right),
        indent_first=parse_mm(bf.indent_first),
        text_direction=bf.text_direction,
        keep_with_next=bf.keep_with_next,
        widow_orphan=bf.widow_orphan,
        page_break_before=bf.page_break_before,
        outline_level=bf.outline_level,
        drop_cap_lines=bf.drop_cap_lines,
        drop_cap_distance=parse_mm(bf.drop_cap_distance),
        break_asian_latin=bf.break_asian_latin,
        background_color=str_to_color(bf.background_color),
        border_top=bf.border_top,
        border_bottom=bf.border_bottom,
        border_left=bf.border_left,
        border_right=bf.border_right,
        bidi=bf.bidi,
        tab_stops=[_tab_stop_schema_to_v2(t) for t in bf.tab_stops] if bf.tab_stops else None,
        column_break_before=bf.column_break_before,
    )


def _tab_stop_schema_to_v2(t: v1.TabStop) -> v2f_mod.TabStop:
    """Convert a v1 tab stop to v2."""
    return v2f_mod.TabStop(
        position=parse_mm(t.position) or 0.0,
        align=t.align,
        leader=t.leader,
    )


def _tab_stop_schema_to_v1(t: v2f_mod.TabStop) -> v1.TabStop:
    """Convert a v2 tab stop to v1."""
    return v1.TabStop(
        position=format_mm(t.position) or "0.0mm",
        align=t.align,
        leader=t.leader,
    )


def block_format_to_v1(bf: v2f.BlockFormat | None) -> v1.BlockFormat | None:
    """Convert a v2 BlockFormat to v1, formatting floats as string dimensions.

    Parameters
    ----------
    bf : v2f.BlockFormat or None
        The v2 block format. Returns None if input is None.

    Returns
    -------
    v1.BlockFormat or None
        The converted v1 block format.
    """
    if bf is None:
        return None
    return v1.BlockFormat(
        font_name=bf.font_name,
        font_size=format_pt(bf.font_size),
        bold=bf.bold,
        italic=bf.italic,
        alignment=bf.alignment,
        line_spacing=line_spacing_to_v1(bf.line_spacing, bf.line_spacing_type),
        line_spacing_type=bf.line_spacing_type,
        space_before=format_mm(bf.space_before),
        space_after=format_mm(bf.space_after),
        indent_left=format_mm(bf.indent_left),
        indent_right=format_mm(bf.indent_right),
        indent_first=format_mm(bf.indent_first),
        text_direction=bf.text_direction,
        keep_with_next=bf.keep_with_next,
        widow_orphan=bf.widow_orphan,
        page_break_before=bf.page_break_before,
        outline_level=bf.outline_level,
        drop_cap_lines=bf.drop_cap_lines,
        drop_cap_distance=format_mm(bf.drop_cap_distance),
        break_asian_latin=bf.break_asian_latin,
        background_color=color_to_str(bf.background_color),
        border_top=bf.border_top,
        border_bottom=bf.border_bottom,
        border_left=bf.border_left,
        border_right=bf.border_right,
        bidi=bf.bidi,
        tab_stops=[_tab_stop_schema_to_v1(t) for t in bf.tab_stops] if bf.tab_stops else None,
        column_break_before=bf.column_break_before,
    )


def cell_format_to_v2(cf: v1.CellFormat | None) -> v2f.CellFormat | None:
    """Convert a v1 CellFormat to v2, parsing string dimensions to floats.

    Parameters
    ----------
    cf : v1.CellFormat or None
        The v1 cell format. Returns None if input is None.

    Returns
    -------
    v2f.CellFormat or None
        The converted v2 cell format.
    """
    if cf is None:
        return None
    return v2f.CellFormat(
        background_color=str_to_color(cf.background_color),
        border_top=cf.border_top,
        border_bottom=cf.border_bottom,
        border_left=cf.border_left,
        border_right=cf.border_right,
        padding=parse_mm(cf.padding),
        padding_top=parse_mm(cf.padding_top),
        padding_bottom=parse_mm(cf.padding_bottom),
        padding_left=parse_mm(cf.padding_left),
        padding_right=parse_mm(cf.padding_right),
        vertical_align=cf.vertical_align,
        text_direction=cf.text_direction,
        no_wrap=cf.no_wrap,
    )


def cell_format_to_v1(cf: v2f.CellFormat | None) -> v1.CellFormat | None:
    """Convert a v2 CellFormat to v1, formatting floats as string dimensions.

    Parameters
    ----------
    cf : v2f.CellFormat or None
        The v2 cell format. Returns None if input is None.

    Returns
    -------
    v1.CellFormat or None
        The converted v1 cell format.
    """
    if cf is None:
        return None
    return v1.CellFormat(
        background_color=color_to_str(cf.background_color),
        border_top=cf.border_top,
        border_bottom=cf.border_bottom,
        border_left=cf.border_left,
        border_right=cf.border_right,
        padding=format_mm(cf.padding),
        padding_top=format_mm(cf.padding_top),
        padding_bottom=format_mm(cf.padding_bottom),
        padding_left=format_mm(cf.padding_left),
        padding_right=format_mm(cf.padding_right),
        vertical_align=cf.vertical_align,
        text_direction=cf.text_direction,
        no_wrap=cf.no_wrap,
    )


def revision_to_v2(r: v1.RevisionInfo | None) -> v2f_mod.RevisionInfo | None:
    """Convert a v1 RevisionInfo to v2.

    Parameters
    ----------
    r : v1.RevisionInfo or None
        The v1 revision info. Returns None if input is None.

    Returns
    -------
    v2f_mod.RevisionInfo or None
        The converted v2 revision info.
    """
    if r is None:
        return None
    return v2f_mod.RevisionInfo(
        revision_type=r.revision_type,
        revision_id=r.revision_id,
        author=r.author,
        date=r.date,
    )


def revision_to_v1(r: v2f_mod.RevisionInfo | None) -> v1.RevisionInfo | None:
    """Convert a v2 RevisionInfo to v1.

    Parameters
    ----------
    r : v2f_mod.RevisionInfo or None
        The v2 revision info. Returns None if input is None.

    Returns
    -------
    v1.RevisionInfo or None
        The converted v1 revision info.
    """
    if r is None:
        return None
    return v1.RevisionInfo(
        revision_type=r.revision_type,
        revision_id=r.revision_id,
        author=r.author,
        date=r.date,
    )


def position_to_v2(
    pos: v1.PositionInfo | None,
    collector: ExtensionCollector,
    block_id: str,
) -> v2f.PositionInfo | None:
    """Convert a v1 PositionInfo to v2.

    Parameters
    ----------
    pos : v1.PositionInfo or None
        The v1 position info. Returns None if input is None.
    collector : ExtensionCollector
        Accumulator for format-specific extension fields.
    block_id : str
        The block ID owning this position.

    Returns
    -------
    v2f.PositionInfo or None
        The converted v2 position info.
    """
    if pos is None:
        return None

    return v2f.PositionInfo(
        x=pos.x,
        y=pos.y,
        width=pos.width,
        height=pos.height,
        z_order=pos.z_order,
        flow=pos.flow,
        like_char=pos.like_char,
        text_side=pos.text_side,
        halign=pos.halign,
        valign=pos.valign,
        hrelto=pos.hrelto,
        vrelto=pos.vrelto,
        margin_top=pos.margin_top,
        margin_bottom=pos.margin_bottom,
        margin_left=pos.margin_left,
        margin_right=pos.margin_right,
        rotation=pos.rotation,
        opacity=pos.opacity,
        width_relto=pos.width_relto,
        height_relto=pos.height_relto,
        restrict_in_page=pos.restrict_in_page,
        overlap_others=pos.overlap_others,
        affect_line_spacing=pos.affect_line_spacing,
        text_wrap=pos.text_wrap,
        allow_overlap=pos.allow_overlap,
        flow_with_text=pos.flow_with_text,
    )


def position_to_v1(
    pos: v2f.PositionInfo | None,
    ext_lookup: ExtensionLookup,
    block_id: str,
) -> v1.PositionInfo | None:
    """Convert a v2 PositionInfo to v1.

    Parameters
    ----------
    pos : v2f.PositionInfo or None
        The v2 position info. Returns None if input is None.
    ext_lookup : ExtensionLookup
        Provider of format-specific extension fields.
    block_id : str
        The block ID owning this position.

    Returns
    -------
    v1.PositionInfo or None
        The converted v1 position info.
    """
    if pos is None:
        return None

    return v1.PositionInfo(
        x=pos.x,
        y=pos.y,
        width=pos.width,
        height=pos.height,
        z_order=pos.z_order,
        flow=pos.flow,
        like_char=pos.like_char,
        text_side=pos.text_side,
        halign=pos.halign,
        valign=pos.valign,
        hrelto=pos.hrelto,
        vrelto=pos.vrelto,
        margin_top=pos.margin_top,
        margin_bottom=pos.margin_bottom,
        margin_left=pos.margin_left,
        margin_right=pos.margin_right,
        rotation=pos.rotation,
        opacity=pos.opacity,
        width_relto=pos.width_relto,
        height_relto=pos.height_relto,
        restrict_in_page=pos.restrict_in_page,
        overlap_others=pos.overlap_others,
        affect_line_spacing=pos.affect_line_spacing,
        text_wrap=pos.text_wrap,
        allow_overlap=pos.allow_overlap,
        flow_with_text=pos.flow_with_text,
    )
