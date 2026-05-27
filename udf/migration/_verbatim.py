"""VerbatimLayer, GlobalResources v1↔v2 변환."""

from __future__ import annotations

from typing import Any

from udf.core import _schema_v1 as v1

from udf.pipeline import verbatim as v2v

from ._formats import block_format_to_v1, block_format_to_v2


def _style_to_v2(s: v1.StyleDef) -> v2v.StyleDef:
    return v2v.StyleDef(
        id=s.id,
        name=s.name,
        english_name=s.english_name,
        style_type=s.style_type,
        parent_id=s.parent_id,
        next_style_id=s.next_style_id,
        format=block_format_to_v2(s.format),
    )


def _style_to_v1(s: v2v.StyleDef) -> v1.StyleDef:
    return v1.StyleDef(
        id=s.id,
        name=s.name,
        english_name=s.english_name,
        style_type=s.style_type,
        parent_id=s.parent_id,
        next_style_id=s.next_style_id,
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
        substitute_name=f.substitute_name,
        panose=f.panose,
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
        substitute_name=f.substitute_name,
        panose=f.panose,
    )


def _numbering_level_to_v2(nl: v1.NumberingLevel) -> v2v.NumberingLevel:
    return v2v.NumberingLevel(
        level=nl.level,
        format=nl.format,
        prefix=nl.prefix,
        suffix=nl.suffix,
        indent=nl.indent,
        start=nl.start,
    )


def _numbering_level_to_v1(nl: v2v.NumberingLevel) -> v1.NumberingLevel:
    return v1.NumberingLevel(
        level=nl.level,
        format=nl.format,
        prefix=nl.prefix,
        suffix=nl.suffix,
        indent=nl.indent,
        start=nl.start,
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
    return v2v.TabStop(position=t.position, align=t.align, leader=t.leader)


def _tab_stop_to_v1(t: v2v.TabStop) -> v1.TabStop:
    return v1.TabStop(position=t.position, align=t.align, leader=t.leader)


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
        fill_type=bf.fill_type,
        gradient_type=bf.gradient_type,
        gradient_angle=bf.gradient_angle,
        gradient_colors=bf.gradient_colors,
        pattern_type=bf.pattern_type,
        pattern_color=bf.pattern_color,
        image_ref=bf.image_ref,
        image_mode=bf.image_mode,
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
        diagonal_color=bf.diagonal_color,
        diagonal_style=bf.diagonal_style,
        diagonal_width=bf.diagonal_width,
    )


def _border_fill_to_v1(bf: v2v.BorderFillDef) -> v1.BorderFillDef:
    return v1.BorderFillDef(
        id=bf.id,
        border_color=bf.border_color,
        border_style=bf.border_style,
        fill_color=bf.fill_color,
        fill_type=bf.fill_type,
        gradient_type=bf.gradient_type,
        gradient_angle=bf.gradient_angle,
        gradient_colors=bf.gradient_colors,
        pattern_type=bf.pattern_type,
        pattern_color=bf.pattern_color,
        image_ref=bf.image_ref,
        image_mode=bf.image_mode,
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
        diagonal_color=bf.diagonal_color,
        diagonal_style=bf.diagonal_style,
        diagonal_width=bf.diagonal_width,
    )


def _char_shape_to_v2(cs: v1.CharShapeDef) -> v2v.CharShapeDef:
    data = cs.model_dump()
    return v2v.CharShapeDef(**data)


def _char_shape_to_v1(cs: v2v.CharShapeDef) -> v1.CharShapeDef:
    data = cs.model_dump()
    return v1.CharShapeDef(**data)


def _para_shape_to_v2(ps: v1.ParaShapeDef) -> v2v.ParaShapeDef:
    data = ps.model_dump()
    return v2v.ParaShapeDef(**data)


def _para_shape_to_v1(ps: v2v.ParaShapeDef) -> v1.ParaShapeDef:
    data = ps.model_dump()
    return v1.ParaShapeDef(**data)


def _bin_data_to_v2(bd: v1.BinDataDef) -> v2v.BinDataDef:
    data = bd.model_dump()
    return v2v.BinDataDef(**data)


def _bin_data_to_v1(bd: v2v.BinDataDef) -> v1.BinDataDef:
    data = bd.model_dump()
    return v1.BinDataDef(**data)


def _global_resources_to_v2(gr: v1.GlobalResources) -> v2v.GlobalResources:
    return v2v.GlobalResources(
        char_shapes={k: _char_shape_to_v2(v) for k, v in gr.char_shapes.items()},
        para_shapes={k: _para_shape_to_v2(v) for k, v in gr.para_shapes.items()},
        border_fills={k: _border_fill_to_v2(v) for k, v in gr.border_fills.items()},
        bin_data={k: _bin_data_to_v2(v) for k, v in gr.bin_data.items()},
        styles={k: _style_to_v2(v) for k, v in gr.styles.items()},
        face_names={k: _font_fallbacks_to_v2(v) for k, v in gr.face_names.items()},
        numberings={k: _numbering_to_v2(v) for k, v in gr.numberings.items()},
        bullets={k: _bullet_to_v2(v) for k, v in gr.bullets.items()},
        tab_defs={k: _tab_to_v2(v) for k, v in gr.tab_defs.items()},
    )


def _global_resources_to_v1(gr: v2v.GlobalResources) -> v1.GlobalResources:
    return v1.GlobalResources(
        char_shapes={k: _char_shape_to_v1(v) for k, v in gr.char_shapes.items()},
        para_shapes={k: _para_shape_to_v1(v) for k, v in gr.para_shapes.items()},
        border_fills={k: _border_fill_to_v1(v) for k, v in gr.border_fills.items()},
        bin_data={k: _bin_data_to_v1(v) for k, v in gr.bin_data.items()},
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
    """Convert v1 VerbatimLayer to v2 VerbatimLayer.

    Parameters
    ----------
    vl : v1.VerbatimLayer
        Source v1 verbatim layer.

    Returns
    -------
    v2v.VerbatimLayer
        Converted v2 verbatim layer.
    """
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
    """Convert v2 VerbatimLayer to v1 VerbatimLayer.

    Parameters
    ----------
    vl : v2v.VerbatimLayer
        Source v2 verbatim layer.

    Returns
    -------
    v1.VerbatimLayer
        Converted v1 verbatim layer.
    """
    return v1.VerbatimLayer(
        format=vl.format,
        version=vl.version,
        blocks={k: _verbatim_block_to_v1(v) for k, v in vl.blocks.items()},
        global_resources=_global_resources_to_v1(vl.global_resources),
        unknown_chunks=list(vl.unknown_chunks),
        section_streams=dict(vl.section_streams),
        bindata_streams=dict(vl.bindata_streams),
    )
