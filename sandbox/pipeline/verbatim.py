"""Verbatim 레이어 — 같은 포맷 왕복을 위한 원본 바이트 보존."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from sandbox.schema.formats import BlockFormat


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class VerbatimBlock(_Base):
    raw_tag_id: int | None = None
    level: int | None = None
    raw_bytes: str | None = None
    decoded: dict[str, Any] | None = None


class FontFallbacks(_Base):
    latin: str | None = None
    hangul: str | None = None
    hanja: str | None = None
    japanese: str | None = None
    other: str | None = None
    symbol: str | None = None
    user_defined: str | None = None


class StyleDef(_Base):
    id: str
    name: str
    style_type: str | None = None
    parent_id: str | None = None
    format: BlockFormat | None = None


class NumberingLevel(_Base):
    level: int
    format: str | None = None
    prefix: str | None = None
    suffix: str | None = None
    indent: str | None = None


class NumberingDef(_Base):
    id: str
    levels: list[NumberingLevel] = []


class BulletDef(_Base):
    id: str
    char: str | None = None
    image_ref: str | None = None


class TabStop(_Base):
    position: str
    align: str | None = None


class TabDef(_Base):
    id: str
    stops: list[TabStop] = []


class BorderFillDef(_Base):
    id: str
    border_color: str | None = None
    border_style: str | None = None
    fill_color: str | None = None
    border_left_color: str | None = None
    border_left_style: str | None = None
    border_left_width: float | None = None
    border_right_color: str | None = None
    border_right_style: str | None = None
    border_right_width: float | None = None
    border_top_color: str | None = None
    border_top_style: str | None = None
    border_top_width: float | None = None
    border_bottom_color: str | None = None
    border_bottom_style: str | None = None
    border_bottom_width: float | None = None


class GlobalResources(_Base):
    char_shapes: dict[str, Any] = {}
    para_shapes: dict[str, Any] = {}
    border_fills: dict[str, BorderFillDef] = {}
    bin_data: dict[str, Any] = {}
    styles: dict[str, StyleDef] = {}
    face_names: dict[str, FontFallbacks] = {}
    numberings: dict[str, NumberingDef] = {}
    bullets: dict[str, BulletDef] = {}
    tab_defs: dict[str, TabDef] = {}


class VerbatimLayer(_Base):
    format: str
    version: str | None = None
    blocks: dict[str, VerbatimBlock] = {}
    block_mapping: dict[str, str] = {}
    global_resources: GlobalResources = Field(default_factory=GlobalResources)
    unknown_chunks: list[Any] = []
    section_streams: dict[str, str] = {}
    bindata_streams: dict[str, str] = {}
