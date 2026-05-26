"""v1/v2 type conversion utilities for schema migration."""

from __future__ import annotations

import re

from udf.schema.types import Color, Ratio, mm_to_pt, pt_to_mm

_DIM_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*(pt|mm|cm|%)?$")


def parse_pt(s: str | None) -> float | None:
    """Parse a point-unit dimension string to float.

    Parameters
    ----------
    s : str or None
        Dimension string (e.g. ``"12.0pt"``).

    Returns
    -------
    float or None
        Numeric value in points, or None if input is None or unparseable.
    """
    if s is None:
        return None
    m = _DIM_RE.match(s)
    if not m:
        return None
    return float(m.group(1))


def parse_mm(s: str | None) -> float | None:
    """Parse a mm/pt dimension string and convert to points.

    Parameters
    ----------
    s : str or None
        Dimension string (e.g. ``"25.4mm"`` or ``"72pt"``).

    Returns
    -------
    float or None
        Value in points, or None.
    """
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
    """Parse a percentage dimension string to float.

    Parameters
    ----------
    s : str or None
        Percentage string (e.g. ``"160%"``).

    Returns
    -------
    float or None
        Numeric percentage value, or None.
    """
    if s is None:
        return None
    m = _DIM_RE.match(s)
    if not m:
        return None
    return float(m.group(1))


def parse_dimension(s: str | None) -> float | None:
    """Parse a dimension string with any unit to points.

    Parameters
    ----------
    s : str, int, float, or None
        Dimension (e.g. ``"210mm"``, ``"595pt"``, ``"21cm"``, or numeric).

    Returns
    -------
    float or None
        Value in points, or None.
    """
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
    """Format a point value as a string with ``pt`` suffix.

    Parameters
    ----------
    v : float or None
        Value in points.

    Returns
    -------
    str or None
        Formatted string (e.g. ``"12.0pt"``), or None.
    """
    if v is None:
        return None
    return f"{v:.1f}pt"


def format_mm(v: float | None) -> str | None:
    """Format a point value as a string with ``mm`` suffix.

    Parameters
    ----------
    v : float or None
        Value in points.

    Returns
    -------
    str or None
        Formatted string (e.g. ``"25.4mm"``), or None.
    """
    if v is None:
        return None
    mm_val = pt_to_mm(v)
    return f"{mm_val:.1f}mm"


def format_pct(v: float | None) -> str | None:
    """Format a numeric percentage as a string with ``%`` suffix.

    Parameters
    ----------
    v : float or None
        Percentage value.

    Returns
    -------
    str or None
        Formatted string (e.g. ``"160%"``), or None.
    """
    if v is None:
        return None
    if v == int(v):
        return f"{int(v)}%"
    return f"{v}%"


def str_to_color(s: str | None) -> Color | None:
    """Convert a hex color string to a Color object.

    Parameters
    ----------
    s : str or None
        Hex color string (e.g. ``"#FF0000"``).

    Returns
    -------
    Color or None
    """
    if s is None:
        return None
    return Color.from_hex(s)


def color_to_str(c: Color | None) -> str | None:
    """Convert a Color object to a hex string.

    Parameters
    ----------
    c : Color or None

    Returns
    -------
    str or None
        Hex color string, or None.
    """
    if c is None:
        return None
    return c.to_hex()


def int_to_ratio(v: int | None) -> Ratio | None:
    """Convert an integer percentage to a Ratio object.

    Parameters
    ----------
    v : int or None
        Percentage value (e.g. 160).

    Returns
    -------
    Ratio or None
    """
    if v is None:
        return None
    return Ratio(float(v))


def ratio_to_int(r: Ratio | None) -> int | None:
    """Convert a Ratio object to an integer percentage.

    Parameters
    ----------
    r : Ratio or None

    Returns
    -------
    int or None
        Percentage as integer, or None.
    """
    if r is None:
        return None
    return int(r.percent)


def line_spacing_to_v2(
    val: str | None, ls_type: str | None
) -> float | Ratio | None:
    """Convert v1 line-spacing string to v2 typed value.

    Parameters
    ----------
    val : str or None
        Line spacing value (e.g. ``"160%"``, ``"12mm"``).
    ls_type : str or None
        Spacing type hint (``"ratio"`` or ``"fixed"``).

    Returns
    -------
    float, Ratio, or None
        Ratio for percentage spacing, float (pt) for fixed spacing.
    """
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
    """Convert v2 typed line-spacing value to v1 string.

    Parameters
    ----------
    val : float, Ratio, or None
        Line spacing (Ratio for percentage, float for fixed pt).
    ls_type : str or None
        Spacing type hint.

    Returns
    -------
    str or None
        Formatted string (e.g. ``"160%"`` or ``"12.0mm"``).
    """
    if val is None:
        return None
    if isinstance(val, Ratio):
        pct = val.percent
        if pct == int(pct):
            return f"{int(pct)}%"
        return f"{pct}%"
    return format_mm(val)
