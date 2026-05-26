"""Normalized value types — Color, Ratio, and unit conversion functions shared across all formats.

All length fields in the schema are stored as float in pt (points).
Format-specific units (HwpUnit, EMU, twip, etc.) are converted via helper functions.
"""

from __future__ import annotations

from typing import Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


# ===================================================================
# 단위 변환 함수 — 파서/렌더러에서 사용
# ===================================================================

# HWP: 1 HwpUnit = 1/100 pt, 1mm ≈ 283.46 HwpUnit
def hwpunit_to_pt(value: int) -> float:
    """Convert HWP units to points.

    Parameters
    ----------
    value : int
        Length in HWP units (1 HwpUnit = 1/100 pt).

    Returns
    -------
    float
        Equivalent length in points.
    """
    return value / 100

def pt_to_hwpunit(pt: float) -> int:
    """Convert points to HWP units.

    Parameters
    ----------
    pt : float
        Length in points.

    Returns
    -------
    int
        Equivalent length in HWP units (rounded).
    """
    return round(pt * 100)

# OOXML EMU: 1 pt = 12700 EMU
def emu_to_pt(value: int) -> float:
    """Convert OOXML English Metric Units to points.

    Parameters
    ----------
    value : int
        Length in EMU (1 pt = 12700 EMU).

    Returns
    -------
    float
        Equivalent length in points.
    """
    return value / 12700

def pt_to_emu(pt: float) -> int:
    """Convert points to OOXML English Metric Units.

    Parameters
    ----------
    pt : float
        Length in points.

    Returns
    -------
    int
        Equivalent length in EMU (rounded).
    """
    return round(pt * 12700)

# OOXML half-point: w:sz, 1 half-pt = 0.5 pt
def halfpt_to_pt(value: int) -> float:
    """Convert OOXML half-points to points.

    Parameters
    ----------
    value : int
        Length in half-points (used in w:sz elements).

    Returns
    -------
    float
        Equivalent length in points.
    """
    return value / 2

def pt_to_halfpt(pt: float) -> int:
    """Convert points to OOXML half-points.

    Parameters
    ----------
    pt : float
        Length in points.

    Returns
    -------
    int
        Equivalent length in half-points (rounded).
    """
    return round(pt * 2)

# OOXML twip: 1 twip = 1/20 pt
def twip_to_pt(value: int) -> float:
    """Convert OOXML twips to points.

    Parameters
    ----------
    value : int
        Length in twips (1 twip = 1/20 pt).

    Returns
    -------
    float
        Equivalent length in points.
    """
    return value / 20

def pt_to_twip(pt: float) -> int:
    """Convert points to OOXML twips.

    Parameters
    ----------
    pt : float
        Length in points.

    Returns
    -------
    int
        Equivalent length in twips (rounded).
    """
    return round(pt * 20)

# mm ↔ pt
def mm_to_pt(value: float) -> float:
    """Convert millimeters to points.

    Parameters
    ----------
    value : float
        Length in millimeters.

    Returns
    -------
    float
        Equivalent length in points.
    """
    return value / 0.352778

def pt_to_mm(pt: float) -> float:
    """Convert points to millimeters.

    Parameters
    ----------
    pt : float
        Length in points.

    Returns
    -------
    float
        Equivalent length in millimeters.
    """
    return pt * 0.352778

# px ↔ pt
def px_to_pt(value: float, dpi: float = 96) -> float:
    """Convert pixels to points at the given DPI.

    Parameters
    ----------
    value : float
        Length in pixels.
    dpi : float, default 96
        Dots per inch for the conversion.

    Returns
    -------
    float
        Equivalent length in points.
    """
    return value * 72 / dpi

def pt_to_px(pt: float, dpi: float = 96) -> float:
    """Convert points to pixels at the given DPI.

    Parameters
    ----------
    pt : float
        Length in points.
    dpi : float, default 96
        Dots per inch for the conversion.

    Returns
    -------
    float
        Equivalent length in pixels.
    """
    return pt * dpi / 72


# ===================================================================
# Color
# ===================================================================

class Color:
    """Normalized RGBA color. Parsers convert any color representation to this type."""

    __slots__ = ("r", "g", "b", "a")

    def __init__(self, r: int, g: int, b: int, a: float = 1.0) -> None:
        """Initialize an RGBA color.

        Parameters
        ----------
        r : int
            Red channel (0--255).
        g : int
            Green channel (0--255).
        b : int
            Blue channel (0--255).
        a : float, default 1.0
            Alpha (opacity) from 0.0 (transparent) to 1.0 (opaque).
        """
        self.r = r
        self.g = g
        self.b = b
        self.a = a

    @classmethod
    def from_hex(cls, hex_str: str) -> Color:
        """Create a Color from a hex string (e.g. "#ff8800" or "#ff880080").

        Parameters
        ----------
        hex_str : str
            Hex color string, with or without leading '#'. Supports 6 (RGB) or 8 (RGBA) digits.

        Returns
        -------
        Color
            Parsed color instance.

        Raises
        ------
        ValueError
            If the hex string is not 6 or 8 hex digits.
        """
        h = hex_str.lstrip("#")
        if len(h) == 6:
            return cls(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        if len(h) == 8:
            return cls(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16) / 255)
        raise ValueError(f"Invalid hex color: {hex_str!r}")

    @classmethod
    def from_bgr(cls, bgr: int) -> Color:
        """Create a Color from a packed BGR integer (HWP native color format).

        Parameters
        ----------
        bgr : int
            24-bit color packed as 0xRRGGBB (despite the name, HWP stores R in high byte).

        Returns
        -------
        Color
            Parsed color instance with alpha=1.0.
        """
        return cls(r=(bgr >> 16) & 0xFF, g=(bgr >> 8) & 0xFF, b=bgr & 0xFF)

    def to_hex(self) -> str:
        """Serialize this color to a lowercase hex string.

        Returns
        -------
        str
            "#rrggbb" if fully opaque, "#rrggbbaa" otherwise.
        """
        if self.a == 1.0:
            return f"#{self.r:02x}{self.g:02x}{self.b:02x}"
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}{round(self.a * 255):02x}"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Color):
            return self.r == other.r and self.g == other.g and self.b == other.b and self.a == other.a
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.r, self.g, self.b, self.a))

    def __str__(self) -> str:
        return self.to_hex()

    def __repr__(self) -> str:
        if self.a == 1.0:
            return f"Color({self.to_hex()})"
        return f"Color({self.to_hex()}, a={self.a:.2f})"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        def validate(value: Any) -> Color:
            """Pydantic validator for Color."""
            if isinstance(value, Color):
                return value
            if isinstance(value, dict):
                return cls(value["r"], value["g"], value["b"], value.get("a", 1.0))
            if isinstance(value, str):
                return cls.from_hex(value)
            raise ValueError(f"Cannot convert {value!r} to Color")

        def serialize(value: Any) -> str:
            """Pydantic serializer for Color."""
            if isinstance(value, str):
                return value
            return value.to_hex()

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                serialize, info_arg=False
            ),
        )


# ===================================================================
# Ratio — 줄간격 배수, 장평 등 비율 값
# ===================================================================

class Ratio:
    """A percentage ratio value (e.g., line spacing 160%, character scale 85%)."""

    __slots__ = ("_percent",)

    def __init__(self, percent: float) -> None:
        """Initialize a ratio value.

        Parameters
        ----------
        percent : float
            The ratio expressed as a percentage (e.g. 160.0 means 160%).
        """
        self._percent = percent

    @property
    def percent(self) -> float:
        """Return the ratio as a percentage value."""
        return self._percent

    @property
    def factor(self) -> float:
        """Return the ratio as a decimal factor (percent / 100)."""
        return self._percent / 100

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Ratio):
            return abs(self._percent - other._percent) < 0.01
        return NotImplemented

    def __hash__(self) -> int:
        return hash(round(self._percent, 2))

    def __repr__(self) -> str:
        return f"Ratio({self._percent}%)"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        def validate(value: Any) -> Ratio:
            """Pydantic validator for Ratio."""
            if isinstance(value, Ratio):
                return value
            if isinstance(value, dict):
                return cls(value["percent"])
            if isinstance(value, (int, float)):
                return cls(value)
            raise ValueError(f"Cannot convert {value!r} to Ratio")

        def serialize(value: Any) -> dict[str, float]:
            """Pydantic serializer for Ratio."""
            if isinstance(value, dict):
                return value
            if isinstance(value, (int, float)):
                return {"percent": float(value)}
            return {"percent": value.percent}

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                serialize, info_arg=False
            ),
        )
