"""Inline 5종 v1↔v2 변환."""

from __future__ import annotations

from typing import TYPE_CHECKING

from udf.core import schema as v1

from sandbox.schema import inlines as v2i

from ._types import (
    color_to_str,
    format_pct,
    format_pt,
    int_to_ratio,
    parse_pct,
    parse_pt,
    ratio_to_int,
    str_to_color,
)

if TYPE_CHECKING:
    from ._blocks import ExtensionCollector, ExtensionLookup


def inline_to_v2(
    inl: v1.TextInline | v1.LinkInline | v1.ImageInline | v1.FootnoteRefInline | v1.EquationInline,
    collector: ExtensionCollector,
    block_id: str,
    idx: int,
) -> v2i.TextInline | v2i.LinkInline | v2i.ImageInline | v2i.FootnoteRefInline | v2i.EquationInline:
    if isinstance(inl, v1.TextInline):
        key = f"{block_id}:{idx}"
        text_ext = {}
        if inl.emboss is not None:
            text_ext["emboss"] = inl.emboss
        if inl.engrave is not None:
            text_ext["engrave"] = inl.engrave
        if text_ext:
            collector.add_inline_text(key, **text_ext)

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
        )

    if isinstance(inl, v1.LinkInline):
        return v2i.LinkInline(text=inl.text, url=inl.url)

    if isinstance(inl, v1.ImageInline):
        return v2i.ImageInline(
            src=inl.src,
            alt=inl.alt,
            width=parse_pt(inl.width) if isinstance(inl.width, str) else inl.width,
            height=parse_pt(inl.height) if isinstance(inl.height, str) else inl.height,
        )

    if isinstance(inl, v1.FootnoteRefInline):
        return v2i.FootnoteRefInline(ref_id=inl.ref_id, number=inl.number)

    if isinstance(inl, v1.EquationInline):
        if inl.hwp_script is not None:
            key = f"{block_id}:{idx}"
            collector.add_inline_equation(key, hwp_script=inl.hwp_script)
        return v2i.EquationInline(latex=inl.latex)

    raise TypeError(f"Unknown inline type: {type(inl)}")


def inline_to_v1(
    inl: v2i.TextInline | v2i.LinkInline | v2i.ImageInline | v2i.FootnoteRefInline | v2i.EquationInline,
    ext_lookup: ExtensionLookup,
    block_id: str,
    idx: int,
) -> v1.TextInline | v1.LinkInline | v1.ImageInline | v1.FootnoteRefInline | v1.EquationInline:
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
        )

    if isinstance(inl, v2i.LinkInline):
        return v1.LinkInline(text=inl.text, url=inl.url)

    if isinstance(inl, v2i.ImageInline):
        return v1.ImageInline(
            src=inl.src,
            alt=inl.alt,
            width=format_pt(inl.width) if inl.width is not None else None,
            height=format_pt(inl.height) if inl.height is not None else None,
        )

    if isinstance(inl, v2i.FootnoteRefInline):
        return v1.FootnoteRefInline(ref_id=inl.ref_id, number=inl.number)

    if isinstance(inl, v2i.EquationInline):
        key = f"{block_id}:{idx}"
        ext = ext_lookup.get_equation(key)
        return v1.EquationInline(
            latex=inl.latex,
            hwp_script=ext.get("hwp_script"),
        )

    raise TypeError(f"Unknown inline type: {type(inl)}")
