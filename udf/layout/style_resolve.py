"""Style resolution — convert UDF schema to render parameters.

Bridges the gap between UDF's BlockFormat/TextInline model and the
layout engine's computation parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from udf.core.schema import UdfDocument
from udf.schema.formats import BlockFormat, PositionInfo
from udf.schema.types import Ratio


@dataclass
class PageDims:
    width: float = 595.0
    height: float = 842.0
    margin_top: float = 57.0
    margin_bottom: float = 43.0
    margin_left: float = 57.0
    margin_right: float = 57.0

    @property
    def content_width(self) -> float:
        return self.width - self.margin_left - self.margin_right

    @property
    def content_height(self) -> float:
        return self.height - self.margin_top - self.margin_bottom


def extract_page_dims(doc: UdfDocument) -> PageDims:
    dims = PageDims()
    if not doc.metadata or not doc.metadata.sections:
        return dims
    sec = doc.metadata.sections[0]
    try:
        if sec.page_width:
            dims.width = _to_float(sec.page_width)
        if sec.page_height:
            dims.height = _to_float(sec.page_height)
        if sec.margins:
            dims.margin_top = _to_float(sec.margins.top)
            dims.margin_bottom = _to_float(sec.margins.bottom)
            dims.margin_left = _to_float(sec.margins.left)
            dims.margin_right = _to_float(sec.margins.right)
    except (ValueError, AttributeError):
        pass
    return dims


def _to_float(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        return float(v.replace("pt", "").replace("mm", "").replace("%", "").strip())
    if hasattr(v, "percent"):
        return float(v.percent)
    return 0.0


def resolve_line_spacing(fmt: BlockFormat | None) -> float:
    if not fmt or fmt.line_spacing is None:
        return 1.6
    ls = fmt.line_spacing
    if isinstance(ls, Ratio):
        return ls.factor
    if isinstance(ls, (int, float)):
        v = float(ls)
        return v / 100 if v > 5 else v
    return 1.6


def resolve_font(fmt: BlockFormat | None, inline: Any = None,
                 default_font: str = "맑은 고딕", default_size: float = 10.0
                 ) -> tuple[str, float]:
    fn = default_font
    fs = default_size
    if fmt:
        if fmt.font_name:
            fn = fmt.font_name
        if fmt.font_size:
            fs = float(fmt.font_size)
    if inline:
        if getattr(inline, "font_name", None):
            fn = inline.font_name
        if getattr(inline, "font_size", None):
            fs = float(inline.font_size)
    return fn, fs
