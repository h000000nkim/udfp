"""Inline element v1 to v2 (and v2 to v1) conversion.

Converts all inline types (text, link, image, footnote/endnote ref,
equation, ruby, code) between schema versions, including unit
conversions for dimensions, colors, and character properties.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from udf.core import _schema_v1 as v1

from udf.schema import inlines as v2i

from ._formats import revision_to_v1, revision_to_v2
from ._types import (
    color_to_str,
    format_pct,
    format_pt,
    int_to_ratio,
    parse_dimension,
    parse_pct,
    parse_pt,
    ratio_to_int,
    str_to_color,
)

if TYPE_CHECKING:
    from ._blocks import ExtensionCollector, ExtensionLookup


def inline_to_v2(
    inl: object,
    collector: ExtensionCollector,
    block_id: str,
    idx: int,
) -> object:
    """Convert a single v1 inline element to its v2 equivalent.

    Parameters
    ----------
    inl : object
        The v1 inline element (TextInline, LinkInline, etc.).
    collector : ExtensionCollector
        Accumulator for format-specific extension fields.
    block_id : str
        ID of the parent block.
    idx : int
        Index of this inline within the parent block's inline list.

    Returns
    -------
    object
        The converted v2 inline element.

    Raises
    ------
    TypeError
        If the inline type is not recognized.
    """
    if isinstance(inl, v1.TextInline):
        return v2i.TextInline(
            text=inl.text,
            bold=inl.bold,
            italic=inl.italic,
            underline=inl.underline,
            strikethrough=inl.strikethrough,
            superscript=inl.superscript,
            subscript=inl.subscript,
            small_caps=inl.small_caps,
            hidden=inl.hidden,
            outline=inl.outline,
            shadow=inl.shadow,
            emboss=inl.emboss,
            engrave=inl.engrave,
            color=str_to_color(inl.color),
            background_color=str_to_color(inl.background_color),
            font_name=inl.font_name,
            font_size=parse_pt(inl.font_size),
            letter_spacing=parse_pct(inl.letter_spacing),
            char_scale=int_to_ratio(inl.char_scale),
            char_offset=parse_pct(inl.char_offset),
            underline_type=inl.underline_type,
            underline_color=str_to_color(inl.underline_color),
            strikeout_type=inl.strikeout_type,
            strikeout_color=str_to_color(inl.strikeout_color),
            all_caps=inl.all_caps,
            highlight_color=str_to_color(inl.highlight_color),
            emphasis_mark=inl.emphasis_mark,
            rtl=inl.rtl,
            revision=revision_to_v2(inl.revision),
        )

    if isinstance(inl, v1.LinkInline):
        return v2i.LinkInline(text=inl.text, url=inl.url, title=inl.title)

    if isinstance(inl, v1.ImageInline):
        return v2i.ImageInline(
            src=inl.src,
            alt=inl.alt,
            width=parse_dimension(inl.width) if isinstance(inl.width, str) else inl.width,
            height=parse_dimension(inl.height) if isinstance(inl.height, str) else inl.height,
            original_width=parse_dimension(inl.original_width) if isinstance(inl.original_width, str) else inl.original_width,
            original_height=parse_dimension(inl.original_height) if isinstance(inl.original_height, str) else inl.original_height,
        )

    if isinstance(inl, v1.FootnoteRefInline):
        return v2i.FootnoteRefInline(ref_id=inl.ref_id, number=inl.number)

    if isinstance(inl, v1.EndnoteRefInline):
        return v2i.EndnoteRefInline(ref_id=inl.ref_id, number=inl.number)

    if isinstance(inl, v1.EquationInline):
        return v2i.EquationInline(
            latex=inl.latex,
            hwp_script=inl.hwp_script,
            mathml=inl.mathml,
        )

    if isinstance(inl, v1.RubyInline):
        return v2i.RubyInline(
            base_text=inl.base_text,
            ruby_text=inl.ruby_text,
            position=inl.position,
        )

    if isinstance(inl, v1.CodeInline):
        return v2i.CodeInline(code=inl.code, language=inl.language)

    raise TypeError(f"Unknown inline type: {type(inl)}")


def inline_to_v1(
    inl: object,
    ext_lookup: ExtensionLookup,
    block_id: str,
    idx: int,
) -> object:
    """Convert a single v2 inline element to its v1 equivalent.

    Parameters
    ----------
    inl : object
        The v2 inline element (TextInline, LinkInline, etc.).
    ext_lookup : ExtensionLookup
        Provider of format-specific extension fields.
    block_id : str
        ID of the parent block.
    idx : int
        Index of this inline within the parent block's inline list.

    Returns
    -------
    object
        The converted v1 inline element.

    Raises
    ------
    TypeError
        If the inline type is not recognized.
    """
    if isinstance(inl, v2i.TextInline):
        return v1.TextInline(
            text=inl.text,
            bold=inl.bold,
            italic=inl.italic,
            underline=inl.underline,
            strikethrough=inl.strikethrough,
            superscript=inl.superscript,
            subscript=inl.subscript,
            small_caps=inl.small_caps,
            hidden=inl.hidden,
            outline=inl.outline,
            shadow=inl.shadow,
            emboss=inl.emboss,
            engrave=inl.engrave,
            color=color_to_str(inl.color),
            background_color=color_to_str(inl.background_color),
            font_name=inl.font_name,
            font_size=format_pt(inl.font_size),
            letter_spacing=format_pct(inl.letter_spacing),
            char_scale=ratio_to_int(inl.char_scale),
            char_offset=format_pct(inl.char_offset),
            underline_type=inl.underline_type,
            underline_color=color_to_str(inl.underline_color),
            strikeout_type=inl.strikeout_type,
            strikeout_color=color_to_str(inl.strikeout_color),
            all_caps=inl.all_caps,
            highlight_color=color_to_str(inl.highlight_color),
            emphasis_mark=inl.emphasis_mark,
            rtl=inl.rtl,
            revision=revision_to_v1(inl.revision),
        )

    if isinstance(inl, v2i.LinkInline):
        return v1.LinkInline(text=inl.text, url=inl.url, title=inl.title)

    if isinstance(inl, v2i.ImageInline):
        return v1.ImageInline(
            src=inl.src,
            alt=inl.alt,
            width=format_pt(inl.width) if inl.width is not None else None,
            height=format_pt(inl.height) if inl.height is not None else None,
            original_width=format_pt(inl.original_width) if inl.original_width is not None else None,
            original_height=format_pt(inl.original_height) if inl.original_height is not None else None,
        )

    if isinstance(inl, v2i.FootnoteRefInline):
        return v1.FootnoteRefInline(ref_id=inl.ref_id, number=inl.number)

    if isinstance(inl, v2i.EndnoteRefInline):
        return v1.EndnoteRefInline(ref_id=inl.ref_id, number=inl.number)

    if isinstance(inl, v2i.EquationInline):
        return v1.EquationInline(
            latex=inl.latex,
            hwp_script=inl.hwp_script,
            mathml=inl.mathml,
        )

    if isinstance(inl, v2i.RubyInline):
        return v1.RubyInline(
            base_text=inl.base_text,
            ruby_text=inl.ruby_text,
            position=inl.position,
        )

    if isinstance(inl, v2i.CodeInline):
        return v1.CodeInline(code=inl.code, language=inl.language)

    raise TypeError(f"Unknown inline type: {type(inl)}")
