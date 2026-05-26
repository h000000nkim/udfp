"""Format definitions — visual properties applied to blocks and cells. Lengths are always in pt."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from .types import Color, Ratio


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class TabStop(_Base):
    """A tab stop position with alignment and leader character."""
    position: float
    align: Literal["left", "center", "right", "decimal"] | None = None
    leader: Literal["none", "dot", "hyphen", "underscore", "heavy", "middle_dot"] | None = None


class RevisionInfo(_Base):
    """Track-changes metadata (author, date, revision type)."""
    revision_type: Literal["insert", "delete", "format_change", "move"] | None = None
    revision_id: str | None = None
    author: str | None = None
    date: str | None = None


class BlockFormat(_Base):
    """Paragraph-level formatting: font, alignment, spacing, indentation, borders."""

    font_name: str | None = None
    font_size: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    alignment: Literal["left", "center", "right", "justify"] | None = None
    line_spacing: float | Ratio | None = None
    line_spacing_type: Literal["follow_char", "fixed", "leading_only", "minimum", "ratio"] | None = None
    space_before: float | None = None
    space_after: float | None = None
    indent_left: float | None = None
    indent_right: float | None = None
    indent_first: float | None = None
    text_direction: Literal["horizontal", "vertical"] | None = None
    keep_with_next: bool | None = None
    widow_orphan: bool | None = None
    page_break_before: bool | None = None
    outline_level: int | None = None
    drop_cap_lines: int | None = None
    drop_cap_distance: float | None = None
    break_asian_latin: bool | None = None
    background_color: Color | None = None
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    bidi: bool | None = None
    tab_stops: list[TabStop] | None = None
    column_break_before: bool | None = None


class CellFormat(_Base):
    """Table cell formatting: background, borders, padding, alignment."""

    background_color: Color | None = None
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    padding: float | None = None
    padding_top: float | None = None
    padding_bottom: float | None = None
    padding_left: float | None = None
    padding_right: float | None = None
    vertical_align: Literal["top", "middle", "bottom"] | None = None
    text_direction: Literal["horizontal", "vertical"] | None = None
    no_wrap: bool | None = None


class PositionInfo(_Base):
    """Position and layout info for floating objects (images, tables, text boxes). Lengths in pt."""
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    z_order: int | None = None
    flow: Literal["float", "block", "back", "front", "tight", "through"] | None = None
    like_char: bool | None = None
    text_side: Literal["both", "left", "right", "larger"] | None = None
    halign: Literal["left", "center", "right", "inside", "outside"] | None = None
    valign: Literal["top", "middle", "bottom"] | None = None
    hrelto: Literal["paper", "page", "column", "paragraph"] | None = None
    vrelto: Literal["paper", "page", "paragraph"] | None = None
    margin_top: float | None = None
    margin_bottom: float | None = None
    margin_left: float | None = None
    margin_right: float | None = None
    rotation: float | None = None
    opacity: float | None = None
    width_relto: Literal["paper", "page", "column", "paragraph", "absolute"] | None = None
    height_relto: Literal["paper", "page", "absolute"] | None = None
    restrict_in_page: bool | None = None
    overlap_others: bool | None = None
    affect_line_spacing: bool | None = None
    text_wrap: Literal[
        "wrap_both", "wrap_left", "wrap_right", "wrap_largest",
        "square", "behind", "in_front",
    ] | None = None
    allow_overlap: bool | None = None
    flow_with_text: bool | None = None
