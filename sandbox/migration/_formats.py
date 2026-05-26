"""BlockFormat, CellFormat, PositionInfo v1↔v2 변환."""

from __future__ import annotations

from typing import TYPE_CHECKING

from udf.core import schema as v1

from sandbox.schema import formats as v2f

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

if TYPE_CHECKING:
    from ._blocks import ExtensionCollector, ExtensionLookup


def block_format_to_v2(bf: v1.BlockFormat | None) -> v2f.BlockFormat | None:
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
    )


def block_format_to_v1(bf: v2f.BlockFormat | None) -> v1.BlockFormat | None:
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
    )


def cell_format_to_v2(cf: v1.CellFormat | None) -> v2f.CellFormat | None:
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
    )


def cell_format_to_v1(cf: v2f.CellFormat | None) -> v1.CellFormat | None:
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
    )


def position_to_v2(
    pos: v1.PositionInfo | None,
    collector: ExtensionCollector,
    block_id: str,
) -> v2f.PositionInfo | None:
    if pos is None:
        return None

    ext_fields = {}
    for f in ("width_relto", "height_relto", "restrict_in_page",
              "overlap_others", "affect_line_spacing"):
        val = getattr(pos, f, None)
        if val is not None:
            ext_fields[f] = val

    if pos.like_char is not None:
        ext_fields["like_char"] = pos.like_char

    if ext_fields:
        collector.add_position_ext(block_id, **ext_fields)

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
    )


def position_to_v1(
    pos: v2f.PositionInfo | None,
    ext_lookup: ExtensionLookup,
    block_id: str,
) -> v1.PositionInfo | None:
    if pos is None:
        return None

    pext = ext_lookup.get_position(block_id)

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
        width_relto=pext.get("width_relto"),
        height_relto=pext.get("height_relto"),
        restrict_in_page=pext.get("restrict_in_page"),
        overlap_others=pext.get("overlap_others"),
        affect_line_spacing=pext.get("affect_line_spacing"),
    )
