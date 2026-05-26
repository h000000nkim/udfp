"""정규화 값 타입 — 모든 포맷에서 공통으로 사용하는 색상, 비율, 단위 변환.

스키마의 길이 필드는 항상 float(pt) 값으로 저장.
포맷별 원본 단위(HwpUnit, EMU 등)는 변환 함수로 pt ↔ 변환.
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
    return value / 100

def pt_to_hwpunit(pt: float) -> int:
    return round(pt * 100)

# OOXML EMU: 1 pt = 12700 EMU
def emu_to_pt(value: int) -> float:
    return value / 12700

def pt_to_emu(pt: float) -> int:
    return round(pt * 12700)

# OOXML half-point: w:sz, 1 half-pt = 0.5 pt
def halfpt_to_pt(value: int) -> float:
    return value / 2

def pt_to_halfpt(pt: float) -> int:
    return round(pt * 2)

# OOXML twip: 1 twip = 1/20 pt
def twip_to_pt(value: int) -> float:
    return value / 20

def pt_to_twip(pt: float) -> int:
    return round(pt * 20)

# mm ↔ pt
def mm_to_pt(value: float) -> float:
    return value / 0.352778

def pt_to_mm(pt: float) -> float:
    return pt * 0.352778

# px ↔ pt
def px_to_pt(value: float, dpi: float = 96) -> float:
    return value * 72 / dpi

def pt_to_px(pt: float, dpi: float = 96) -> float:
    return pt * dpi / 72


# ===================================================================
# Color
# ===================================================================

class Color:
    """정규화 색상. 파서가 어떤 형식이든 이걸로 변환."""

    __slots__ = ("r", "g", "b", "a")

    def __init__(self, r: int, g: int, b: int, a: float = 1.0) -> None:
        self.r = r
        self.g = g
        self.b = b
        self.a = a

    @classmethod
    def from_hex(cls, hex_str: str) -> Color:
        h = hex_str.lstrip("#")
        if len(h) == 6:
            return cls(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        if len(h) == 8:
            return cls(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16) / 255)
        raise ValueError(f"Invalid hex color: {hex_str!r}")

    @classmethod
    def from_bgr(cls, bgr: int) -> Color:
        return cls(r=(bgr >> 16) & 0xFF, g=(bgr >> 8) & 0xFF, b=bgr & 0xFF)

    def to_hex(self) -> str:
        if self.a == 1.0:
            return f"#{self.r:02x}{self.g:02x}{self.b:02x}"
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}{round(self.a * 255):02x}"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Color):
            return self.r == other.r and self.g == other.g and self.b == other.b and self.a == other.a
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.r, self.g, self.b, self.a))

    def __repr__(self) -> str:
        if self.a == 1.0:
            return f"Color({self.to_hex()})"
        return f"Color({self.to_hex()}, a={self.a:.2f})"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        def validate(value: Any) -> Color:
            if isinstance(value, Color):
                return value
            if isinstance(value, dict):
                return cls(value["r"], value["g"], value["b"], value.get("a", 1.0))
            if isinstance(value, str):
                return cls.from_hex(value)
            raise ValueError(f"Cannot convert {value!r} to Color")

        def serialize(value: Color) -> str:
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
    """비율 값. 줄간격 160%, 장평 85% 등."""

    __slots__ = ("_percent",)

    def __init__(self, percent: float) -> None:
        self._percent = percent

    @property
    def percent(self) -> float:
        return self._percent

    @property
    def factor(self) -> float:
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
            if isinstance(value, Ratio):
                return value
            if isinstance(value, dict):
                return cls(value["percent"])
            if isinstance(value, (int, float)):
                return cls(value)
            raise ValueError(f"Cannot convert {value!r} to Ratio")

        def serialize(value: Ratio) -> dict[str, float]:
            return {"percent": value.percent}

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                serialize, info_arg=False
            ),
        )
