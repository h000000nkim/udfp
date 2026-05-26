"""VerbatimLayer, GlobalResources v1↔v2 변환."""

from __future__ import annotations

from typing import Any

from udf.core import schema as v1

from sandbox.pipeline import verbatim as v2v

from ._formats import block_format_to_v1, block_format_to_v2


def _style_to_v2(s: v1.StyleDef) -> v2v.StyleDef:
    return v2v.StyleDef(
        id=s.id,
        name=s.name,
        style_type=s.style_type,
        parent_id=s.parent_id,
        format=block_format_to_v2(s.format),
    )


def _style_to_v1(s: v2v.StyleDef) -> v1.StyleDef:
    return v1.StyleDef(
        id=s.id,
        name=s.name,
        style_type=s.style_type,
        parent_id=s.parent_id,
        format=block_format_to_v1(s.format),
    )


def _font_fallbacks_to_v2(f: v1.FontFallbacks) -> v2v.FontFallbacks:
    return v2v.FontFallbacks(
        latin=f.latin,
        hangul=f.hangul,
        hanja=f.hanja,
        japanese=f.japanese,
        other=f.other,
        symbol=f.symbol,
        user_defined=f.user_defined,
    )


def _font_fallbacks_to_v1(f: v2v.FontFallbacks) -> v1.FontFallbacks:
    return v1.FontFallbacks(
        latin=f.latin,
        hangul=f.hangul,
        hanja=f.hanja,
        japanese=f.japanese,
        other=f.other,
        symbol=f.symbol,
        user_defined=f.user_defined,
    )


def _numbering_level_to_v2(nl: v1.NumberingLevel) -> v2v.NumberingLevel:
    return v2v.NumberingLevel(
        level=nl.level,
        format=nl.format,
        prefix=nl.prefix,
        suffix=nl.suffix,
        indent=nl.indent,
    )


def _numbering_level_to_v1(nl: v2v.NumberingLevel) -> v1.NumberingLevel:
    return v1.NumberingLevel(
        level=nl.level,
        format=nl.format,
        prefix=nl.prefix,
        suffix=nl.suffix,
        indent=nl.indent,
    )


def _numbering_to_v2(n: v1.NumberingDef) -> v2v.NumberingDef:
    return v2v.NumberingDef(
        id=n.id,
        levels=[_numbering_level_to_v2(lv) for lv in n.levels],
    )


def _numbering_to_v1(n: v2v.NumberingDef) -> v1.NumberingDef:
    return v1.NumberingDef(
        id=n.id,
        levels=[_numbering_level_to_v1(lv) for lv in n.levels],
    )


def _bullet_to_v2(b: v1.BulletDef) -> v2v.BulletDef:
    return v2v.BulletDef(id=b.id, char=b.char, image_ref=b.image_ref)


def _bullet_to_v1(b: v2v.BulletDef) -> v1.BulletDef:
    return v1.BulletDef(id=b.id, char=b.char, image_ref=b.image_ref)


def _tab_stop_to_v2(t: v1.TabStop) -> v2v.TabStop:
    return v2v.TabStop(position=t.position, align=t.align)


def _tab_stop_to_v1(t: v2v.TabStop) -> v1.TabStop:
    return v1.TabStop(position=t.position, align=t.align)


def _tab_to_v2(t: v1.TabDef) -> v2v.TabDef:
    return v2v.TabDef(
        id=t.id,
        stops=[_tab_stop_to_v2(s) for s in t.stops],
    )


def _tab_to_v1(t: v2v.TabDef) -> v1.TabDef:
    return v1.TabDef(
        id=t.id,
        stops=[_tab_stop_to_v1(s) for s in t.stops],
    )


def _border_fill_to_v2(bf: v1.BorderFillDef) -> v2v.BorderFillDef:
    return v2v.BorderFillDef(
        id=bf.id,
        border_color=bf.border_color,
        border_style=bf.border_style,
        fill_color=bf.fill_color,
        border_left_color=bf.border_left_color,
        border_left_style=bf.border_left_style,
        border_left_width=bf.border_left_width,
        border_right_color=bf.border_right_color,
        border_right_style=bf.border_right_style,
        border_right_width=bf.border_right_width,
        border_top_color=bf.border_top_color,
        border_top_style=bf.border_top_style,
        border_top_width=bf.border_top_width,
        border_bottom_color=bf.border_bottom_color,
        border_bottom_style=bf.border_bottom_style,
        border_bottom_width=bf.border_bottom_width,
    )


def _border_fill_to_v1(bf: v2v.BorderFillDef) -> v1.BorderFillDef:
    return v1.BorderFillDef(
        id=bf.id,
        border_color=bf.border_color,
        border_style=bf.border_style,
        fill_color=bf.fill_color,
        border_left_color=bf.border_left_color,
        border_left_style=bf.border_left_style,
        border_left_width=bf.border_left_width,
        border_right_color=bf.border_right_color,
        border_right_style=bf.border_right_style,
        border_right_width=bf.border_right_width,
        border_top_color=bf.border_top_color,
        border_top_style=bf.border_top_style,
        border_top_width=bf.border_top_width,
        border_bottom_color=bf.border_bottom_color,
        border_bottom_style=bf.border_bottom_style,
        border_bottom_width=bf.border_bottom_width,
    )


def _global_resources_to_v2(gr: v1.GlobalResources) -> v2v.GlobalResources:
    return v2v.GlobalResources(
        char_shapes=dict(gr.char_shapes),
        para_shapes=dict(gr.para_shapes),
        border_fills={k: _border_fill_to_v2(v) for k, v in gr.border_fills.items()},
        bin_data=dict(gr.bin_data),
        styles={k: _style_to_v2(v) for k, v in gr.styles.items()},
        face_names={k: _font_fallbacks_to_v2(v) for k, v in gr.face_names.items()},
        numberings={k: _numbering_to_v2(v) for k, v in gr.numberings.items()},
        bullets={k: _bullet_to_v2(v) for k, v in gr.bullets.items()},
        tab_defs={k: _tab_to_v2(v) for k, v in gr.tab_defs.items()},
    )


def _global_resources_to_v1(gr: v2v.GlobalResources) -> v1.GlobalResources:
    return v1.GlobalResources(
        char_shapes=dict(gr.char_shapes),
        para_shapes=dict(gr.para_shapes),
        border_fills={k: _border_fill_to_v1(v) for k, v in gr.border_fills.items()},
        bin_data=dict(gr.bin_data),
        styles={k: _style_to_v1(v) for k, v in gr.styles.items()},
        face_names={k: _font_fallbacks_to_v1(v) for k, v in gr.face_names.items()},
        numberings={k: _numbering_to_v1(v) for k, v in gr.numberings.items()},
        bullets={k: _bullet_to_v1(v) for k, v in gr.bullets.items()},
        tab_defs={k: _tab_to_v1(v) for k, v in gr.tab_defs.items()},
    )


def _verbatim_block_to_v2(vb: v1.VerbatimBlock) -> v2v.VerbatimBlock:
    return v2v.VerbatimBlock(
        raw_tag_id=vb.raw_tag_id,
        level=vb.level,
        raw_bytes=vb.raw_bytes,
        decoded=dict(vb.decoded) if vb.decoded else None,
    )


def _verbatim_block_to_v1(vb: v2v.VerbatimBlock) -> v1.VerbatimBlock:
    return v1.VerbatimBlock(
        raw_tag_id=vb.raw_tag_id,
        level=vb.level,
        raw_bytes=vb.raw_bytes,
        decoded=dict(vb.decoded) if vb.decoded else None,
    )


def verbatim_to_v2(vl: v1.VerbatimLayer) -> v2v.VerbatimLayer:
    return v2v.VerbatimLayer(
        format=vl.format,
        version=vl.version,
        blocks={k: _verbatim_block_to_v2(v) for k, v in vl.blocks.items()},
        block_mapping={},
        global_resources=_global_resources_to_v2(vl.global_resources),
        unknown_chunks=list(vl.unknown_chunks),
        section_streams=dict(vl.section_streams),
        bindata_streams=dict(vl.bindata_streams),
    )


def verbatim_to_v1(vl: v2v.VerbatimLayer) -> v1.VerbatimLayer:
    return v1.VerbatimLayer(
        format=vl.format,
        version=vl.version,
        blocks={k: _verbatim_block_to_v1(v) for k, v in vl.blocks.items()},
        global_resources=_global_resources_to_v1(vl.global_resources),
        unknown_chunks=list(vl.unknown_chunks),
        section_streams=dict(vl.section_streams),
        bindata_streams=dict(vl.bindata_streams),
    )
