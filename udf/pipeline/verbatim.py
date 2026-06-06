"""Verbatim layer (원본 보존 계층) — raw byte preservation for lossless same-format roundtrip."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from udf.schema.formats import BlockFormat


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class VerbatimBlock(_Base):
    """Raw byte-level record of a single block for exact reconstruction."""

    raw_tag_id: int | None = None
    level: int | None = None
    raw_bytes: str | None = None
    decoded: dict[str, Any] | None = None


class FontFallbacks(_Base):
    """Per-script font face names for fallback resolution."""

    latin: str | None = None
    hangul: str | None = None
    hanja: str | None = None
    japanese: str | None = None
    other: str | None = None
    symbol: str | None = None
    user_defined: str | None = None
    substitute_name: str | None = None
    panose: str | None = None


class StyleDef(_Base):
    """A named paragraph or character style definition."""

    id: str
    name: str
    english_name: str | None = None
    style_type: Literal["paragraph", "character"] | None = None
    parent_id: str | None = None
    next_style_id: str | None = None
    format: BlockFormat | None = None


class NumberingLevel(_Base):
    """Configuration for a single level within a numbering definition."""

    level: int
    format: str | None = None
    prefix: str | None = None
    suffix: str | None = None
    indent: str | None = None
    start: int | None = None


class NumberingDef(_Base):
    """A numbered list definition with per-level format settings."""

    id: str
    levels: list[NumberingLevel] = []


class BulletDef(_Base):
    """A bullet list definition (character or image marker)."""

    id: str
    char: str | None = None
    image_ref: str | None = None


class TabStop(_Base):
    position: str
    align: Literal["left", "center", "right", "decimal"] | None = None
    leader: Literal["none", "dot", "hyphen", "underscore", "heavy", "middle_dot"] | None = None


class TabDef(_Base):
    """A reusable set of tab stop positions."""

    id: str
    stops: list[TabStop] = []


class BorderFillDef(_Base):
    """Border and fill style definition (color, gradient, pattern, image)."""

    id: str
    border_color: str | None = None
    border_style: str | None = None
    fill_color: str | None = None
    fill_type: Literal["solid", "gradient", "pattern", "image"] | None = None
    gradient_type: str | None = None
    gradient_angle: float | None = None
    gradient_colors: list[str] | None = None
    pattern_type: str | None = None
    pattern_color: str | None = None
    image_ref: str | None = None
    image_mode: str | None = None
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
    diagonal_color: str | None = None
    diagonal_style: str | None = None
    diagonal_width: float | None = None


_SENTINEL = object()


class CharShapeDef(_Base):
    """Character shape definition — font, size, color, decorations for a text run."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )

    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    underline_type: str | None = None
    underline_color: str | None = None
    strikethrough: bool | None = None
    strikeout_type: str | None = None
    strikeout_color: str | None = None
    outline: bool | None = None
    shadow: bool | None = None
    emboss: bool | None = None
    engrave: bool | None = None
    superscript: bool | None = None
    subscript: bool | None = None
    small_caps: bool | None = None
    hidden: bool | None = None
    font_size_pt: float | None = None
    color: str | None = None
    shade_color: str | None = None
    char_scale: int | None = None
    letter_spacing: str | None = None
    char_offset: str | None = None
    shadow_offset_x: int | None = None
    shadow_offset_y: int | None = None
    border_fill_id: int | None = None
    hangul_face_id: int | None = None
    latin_face_id: int | None = None
    hanja_face_id: int | None = None
    japanese_face_id: int | None = None
    other_face_id: int | None = None
    symbol_face_id: int | None = None
    user_defined_face_id: int | None = None
    outline_type: str | None = None
    shadow_type: str | None = None

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve an attribute by name, falling back to model extras.

        Parameters
        ----------
        key : str
            Attribute name to look up.
        default : Any, optional
            Value to return if the key is not found.

        Returns
        -------
        Any
            The attribute value, extra field value, or default.
        """
        val = getattr(self, key, _SENTINEL)
        if val is not _SENTINEL:
            return val
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default


class ParaShapeDef(_Base):
    """Paragraph shape definition — alignment, spacing, indentation, numbering."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )

    alignment: str | None = None
    line_spacing_type: str | None = None
    line_spacing_hwp: int | None = None
    indent_left_hwp: int | None = None
    indent_right_hwp: int | None = None
    indent_first_hwp: int | None = None
    space_before_hwp: int | None = None
    space_after_hwp: int | None = None
    protect: bool | None = None
    start_new_page: bool | None = None
    with_next_paragraph: bool | None = None
    tab_def_id: int | None = None
    numbering_bullet_id: int | None = None
    border_fill_id: int | None = None
    level: int | None = None

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve an attribute by name, falling back to model extras.

        Parameters
        ----------
        key : str
            Attribute name to look up.
        default : Any, optional
            Value to return if the key is not found.

        Returns
        -------
        Any
            The attribute value, extra field value, or default.
        """
        val = getattr(self, key, _SENTINEL)
        if val is not _SENTINEL:
            return val
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default


class BinDataDef(_Base):
    """Binary data reference (embedded images, OLE objects) in HWP/HWPX."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )

    flags: int | None = None
    bin_type: str | None = None
    bin_id: int | None = None
    ext: str | None = None
    stream: str | None = None

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve an attribute by name, falling back to model extras.

        Parameters
        ----------
        key : str
            Attribute name to look up.
        default : Any, optional
            Value to return if the key is not found.

        Returns
        -------
        Any
            The attribute value, extra field value, or default.
        """
        val = getattr(self, key, _SENTINEL)
        if val is not _SENTINEL:
            return val
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default


class GlobalResources(_Base):
    """Shared document-level resources (char shapes, para shapes, fonts, numberings, etc.)."""

    char_shapes: dict[str, CharShapeDef] = {}
    para_shapes: dict[str, ParaShapeDef] = {}
    border_fills: dict[str, BorderFillDef] = {}
    bin_data: dict[str, BinDataDef] = {}
    styles: dict[str, StyleDef] = {}
    face_names: dict[str, FontFallbacks] = {}
    numberings: dict[str, NumberingDef] = {}
    bullets: dict[str, BulletDef] = {}
    tab_defs: dict[str, TabDef] = {}


class VerbatimLayer(_Base):
    """Top-level verbatim preservation layer for lossless same-format roundtrip."""

    format: str
    version: str | None = None
    blocks: dict[str, VerbatimBlock] = {}
    block_mapping: dict[str, str] = {}
    global_resources: GlobalResources = Field(default_factory=GlobalResources)
    unknown_chunks: list[Any] = []
    section_streams: dict[str, str] = {}
    bindata_streams: dict[str, str] = {}
