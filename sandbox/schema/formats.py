"""서식 정의 — 블록과 셀에 적용되는 시각적 속성. 길이 값은 항상 pt."""

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


class BlockFormat(_Base):
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


class CellFormat(_Base):
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


class PositionInfo(_Base):
    """개체(이미지, 표, 텍스트박스 등)의 위치 및 레이어 정보. 길이 값은 pt."""
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
