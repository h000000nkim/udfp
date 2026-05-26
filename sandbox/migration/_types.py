"""v1↔v2 타입 변환 유틸리티."""

from __future__ import annotations

import re

from sandbox.schema.types import Color, Ratio, mm_to_pt, pt_to_mm

_DIM_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*(pt|mm|cm|%)?$")


def parse_pt(s: str | None) -> float | None:
    if s is None:
        return None
    m = _DIM_RE.match(s)
    if not m:
        return None
    return float(m.group(1))


def parse_mm(s: str | None) -> float | None:
    if s is None:
        return None
    m = _DIM_RE.match(s)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "mm":
        return mm_to_pt(val)
    if unit == "pt":
        return val
    return mm_to_pt(val)


def parse_pct(s: str | None) -> float | None:
    if s is None:
        return None
    m = _DIM_RE.match(s)
    if not m:
        return None
    return float(m.group(1))


def parse_dimension(s: str | None) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = _DIM_RE.match(s)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "mm":
        return mm_to_pt(val)
    if unit == "cm":
        return mm_to_pt(val * 10)
    return val


def format_pt(v: float | None) -> str | None:
    if v is None:
        return None
    return f"{v:.1f}pt"


def format_mm(v: float | None) -> str | None:
    if v is None:
        return None
    mm_val = pt_to_mm(v)
    return f"{mm_val:.1f}mm"


def format_pct(v: float | None) -> str | None:
    if v is None:
        return None
    if v == int(v):
        return f"{int(v)}%"
    return f"{v}%"


def str_to_color(s: str | None) -> Color | None:
    if s is None:
        return None
    return Color.from_hex(s)


def color_to_str(c: Color | None) -> str | None:
    if c is None:
        return None
    return c.to_hex()


def int_to_ratio(v: int | None) -> Ratio | None:
    if v is None:
        return None
    return Ratio(float(v))


def ratio_to_int(r: Ratio | None) -> int | None:
    if r is None:
        return None
    return int(r.percent)


def line_spacing_to_v2(
    val: str | None, ls_type: str | None
) -> float | Ratio | None:
    if val is None:
        return None
    m = _DIM_RE.match(val)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "%" or ls_type in (None, "ratio"):
        return Ratio(num)
    if unit == "mm":
        return mm_to_pt(num)
    return num


def line_spacing_to_v1(
    val: float | Ratio | None, ls_type: str | None
) -> str | None:
    if val is None:
        return None
    if isinstance(val, Ratio):
        pct = val.percent
        if pct == int(pct):
            return f"{int(pct)}%"
        return f"{pct}%"
    return format_mm(val)
