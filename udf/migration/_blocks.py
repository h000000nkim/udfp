"""Block 17종 재귀 변환 + ExtensionCollector/ExtensionLookup.

Converts all 17 block types between v1 and v2 schema representations,
including recursive traversal of nested content (tables, lists, text boxes, etc.).
"""

from __future__ import annotations

from udf.core import _schema_v1 as v1

from udf.schema import blocks as v2b
from udf.schema.extensions import (
    FormatExtension,
    HwpExtension,
    HwpxExtension,
)

from ._formats import (
    block_format_to_v1,
    block_format_to_v2,
    cell_format_to_v1,
    cell_format_to_v2,
    position_to_v1,
    position_to_v2,
    revision_to_v1,
    revision_to_v2,
)
from ._inlines import inline_to_v1, inline_to_v2
from ._types import format_mm, format_pt, parse_dimension


# ---------------------------------------------------------------------------
# ExtensionCollector — v1→v2 시 확장 필드 수집
# ---------------------------------------------------------------------------

class ExtensionCollector:
    """Collects format-specific extension fields during v1-to-v2 migration.

    During conversion from v1 to v2 schema, format-specific fields that have
    no direct v2 equivalent are collected here and later serialized into the
    document's ``extensions`` dict.
    """

    def __init__(self, source_format: str) -> None:
        """Initialize collector for a given source format.

        Parameters
        ----------
        source_format : str
            The original document format (e.g. "hwp", "hwpx").
        """
        self.source_format = source_format
        self._inline_text: dict[str, dict] = {}
        self._inline_equations: dict[str, dict] = {}
        self._blocks: dict[str, dict] = {}
        self._positions: dict[str, dict] = {}

    def add_inline_text(self, key: str, **fields: object) -> None:
        """Record format-specific text inline extension fields."""
        self._inline_text.setdefault(key, {}).update(fields)

    def add_inline_equation(self, key: str, **fields: object) -> None:
        """Record format-specific equation inline extension fields."""
        self._inline_equations.setdefault(key, {}).update(fields)

    def add_block_ext(self, block_id: str, **fields: object) -> None:
        """Record format-specific block-level extension fields."""
        self._blocks.setdefault(block_id, {}).update(fields)

    def add_position_ext(self, block_id: str, **fields: object) -> None:
        """Record format-specific position extension fields."""
        self._positions.setdefault(block_id, {}).update(fields)

    def to_extensions(self) -> dict[str, FormatExtension]:
        """Build the final extensions dict from all collected fields.

        Returns
        -------
        dict[str, FormatExtension]
            Mapping from format name to its FormatExtension model.
            Empty dict if no extension data was collected.
        """
        has_data = (
            self._inline_text
            or self._inline_equations
            or self._blocks
            or self._positions
        )
        if not has_data:
            return {}

        if self.source_format in ("hwp", "hwpx"):
            ExtClass = HwpxExtension if self.source_format == "hwpx" else HwpExtension
            TextExt = ExtClass.TextExt
            EqExt = ExtClass.EquationExt
            BlkExt = ExtClass.BlockExt
            PosExt = ExtClass.PositionExt

            return {
                self.source_format: ExtClass(
                    inline_text={k: TextExt(**v) for k, v in self._inline_text.items()},
                    inline_equations={k: EqExt(**v) for k, v in self._inline_equations.items()},
                    blocks={k: BlkExt(**{f: v.get(f) for f in _block_ext_fields(ExtClass)}) for k, v in self._blocks.items()},
                    positions={k: PosExt(**v) for k, v in self._positions.items()},
                ),
            }
        return {}


def _block_ext_fields(ext_cls: type) -> list[str]:
    """Return field names for a given extension class's BlockExt model."""
    return list(ext_cls.BlockExt.model_fields.keys())


# ---------------------------------------------------------------------------
# ExtensionLookup — v2→v1 시 확장에서 필드 복원
# ---------------------------------------------------------------------------

class ExtensionLookup:
    """Restores format-specific fields from extensions during v2-to-v1 migration.

    The inverse of ExtensionCollector: reads previously collected extension
    data and provides lookup methods to restore fields into v1 block models.
    """

    def __init__(self, extensions: dict[str, FormatExtension]) -> None:
        """Initialize lookup from a document's extensions dict.

        Parameters
        ----------
        extensions : dict[str, FormatExtension]
            The extensions dictionary from a v2 UdfDocument.
        """
        self._ext = extensions
        self._hwp = None
        for ext in extensions.values():
            if isinstance(ext, (HwpExtension, HwpxExtension)):
                self._hwp = ext
                break

    def get_position(self, block_id: str) -> dict:
        """Retrieve position extension fields for a block.

        Parameters
        ----------
        block_id : str
            Block identifier to look up.

        Returns
        -------
        dict
            Non-None position extension fields, or empty dict if not found.
        """
        if self._hwp is None:
            return {}
        pext = self._hwp.positions.get(block_id)
        if pext is None:
            return {}
        return {k: v for k, v in pext.model_dump().items() if v is not None}

    def get_equation(self, key: str) -> dict:
        """Retrieve equation extension fields by key.

        Parameters
        ----------
        key : str
            Equation inline lookup key.

        Returns
        -------
        dict
            Non-None equation extension fields, or empty dict if not found.
        """
        if self._hwp is None:
            return {}
        eext = self._hwp.inline_equations.get(key)
        if eext is None:
            return {}
        return {k: v for k, v in eext.model_dump().items() if v is not None}

    def get_block(self, block_id: str) -> dict:
        """Retrieve block-level extension fields by block ID.

        Parameters
        ----------
        block_id : str
            Block identifier to look up.

        Returns
        -------
        dict
            Non-None block extension fields, or empty dict if not found.
        """
        if self._hwp is None:
            return {}
        bext = self._hwp.blocks.get(block_id)
        if bext is None:
            return {}
        return {k: v for k, v in bext.model_dump().items() if v is not None}

    def get_inline_text(self, key: str) -> dict:
        """Retrieve text inline extension fields by key.

        Parameters
        ----------
        key : str
            Text inline lookup key.

        Returns
        -------
        dict
            Non-None text extension fields, or empty dict if not found.
        """
        if self._hwp is None:
            return {}
        text = self._hwp.inline_text.get(key)
        if text is None:
            return {}
        return {k: v for k, v in text.model_dump().items() if v is not None}


# ---------------------------------------------------------------------------
# v1→v2 블록 변환
# ---------------------------------------------------------------------------

def _inlines_to_v2(inlines: list, collector: ExtensionCollector, block_id: str) -> list:
    """Convert a list of v1 inlines to v2."""
    return [inline_to_v2(inl, collector, block_id, i) for i, inl in enumerate(inlines)]


def _inlines_to_v1(inlines: list, ext_lookup: ExtensionLookup, block_id: str) -> list:
    """Convert a list of v2 inlines to v1."""
    return [inline_to_v1(inl, ext_lookup, block_id, i) for i, inl in enumerate(inlines)]


def _blocks_to_v2(blocks: list, collector: ExtensionCollector) -> list:
    """Recursively convert a list of v1 blocks to v2."""
    return [block_to_v2(b, collector) for b in blocks]


def _blocks_to_v1(blocks: list, ext_lookup: ExtensionLookup) -> list:
    """Recursively convert a list of v2 blocks to v1."""
    return [block_to_v1(b, ext_lookup) for b in blocks]


def block_to_v2(blk: v1.Block, collector: ExtensionCollector) -> v2b.Block:  # noqa: C901
    """Convert a single v1 block to its v2 equivalent.

    Handles all 17 block types via isinstance dispatch. Format-specific
    fields are extracted into the collector for later serialization as
    extensions.

    Parameters
    ----------
    blk : v1.Block
        The v1 schema block to convert.
    collector : ExtensionCollector
        Accumulator for format-specific extension fields.

    Returns
    -------
    v2b.Block
        The converted v2 block.

    Raises
    ------
    TypeError
        If the block type is not recognized.
    """
    bid = blk.id

    if isinstance(blk, v1.HeadingBlock):
        return v2b.HeadingBlock(
            id=bid, level=blk.level, text=blk.text,
            inlines=_inlines_to_v2(blk.inlines, collector, bid),
            format=block_format_to_v2(blk.format),
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v2(blk.unsupported),
            revision=revision_to_v2(blk.revision),
        )

    if isinstance(blk, v1.ParagraphBlock):
        return v2b.ParagraphBlock(
            id=bid,
            inlines=_inlines_to_v2(blk.inlines, collector, bid),
            format=block_format_to_v2(blk.format),
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v2(blk.unsupported),
            revision=revision_to_v2(blk.revision),
        )

    if isinstance(blk, v1.TableBlock):
        return v2b.TableBlock(
            id=bid,
            width=parse_dimension(blk.width) if isinstance(blk.width, str) else blk.width,
            rows=[
                v2b.TableRow(
                    cells=[
                        v2b.TableCell(
                            id=c.id,
                            row_span=c.row_span, col_span=c.col_span,
                            width=c.width, height=c.height,
                            content=_blocks_to_v2(c.content, collector),
                            format=cell_format_to_v2(c.format),
                            is_header=c.is_header,
                            verbatim_ref=c.verbatim_ref,
                            unsupported=_unsupported_to_v2(getattr(c, "unsupported", None)),
                        ) for c in r.cells
                    ],
                    height=parse_dimension(r.height) if isinstance(getattr(r, "height", None), str) else getattr(r, "height", None),
                    revision=revision_to_v2(getattr(r, "revision", None)),
                ) for r in blk.rows
            ],
            format=block_format_to_v2(blk.format),
            position=position_to_v2(blk.position, collector, bid),
            cell_spacing=parse_dimension(blk.cell_spacing),
            default_padding=parse_dimension(blk.default_padding),
            repeat_header=blk.repeat_header,
            border_top=blk.border_top,
            border_bottom=blk.border_bottom,
            border_left=blk.border_left,
            border_right=blk.border_right,
            border_inside_h=blk.border_inside_h,
            border_inside_v=blk.border_inside_v,
            caption=_inlines_to_v2(blk.caption, collector, bid) if blk.caption else None,
            description=blk.description,
            border_fill_id=blk.border_fill_id,
            col_widths=[v2b.TableColumnDef(width=parse_dimension(cw.width) if isinstance(cw.width, str) else cw.width) for cw in blk.col_widths],
            layout_type=blk.layout_type,
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v2(blk.unsupported),
        )

    if isinstance(blk, v1.ListBlock):
        return v2b.ListBlock(
            id=bid, ordered=blk.ordered,
            start=blk.start,
            items=[_list_item_to_v2(it, collector, bid) for it in blk.items],
            format=block_format_to_v2(blk.format),
            numbering_id=blk.numbering_id,
            bullet_id=blk.bullet_id,
            list_style=blk.list_style,
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v1.ImageBlock):
        return v2b.ImageBlock(
            id=bid, src=blk.src, alt=blk.alt,
            width=parse_dimension(blk.width) if isinstance(blk.width, str) else blk.width,
            height=parse_dimension(blk.height) if isinstance(blk.height, str) else blk.height,
            caption=_inlines_to_v2(blk.caption, collector, bid) if blk.caption else None,
            position=position_to_v2(blk.position, collector, bid),
            crop_left=blk.crop_left, crop_top=blk.crop_top,
            crop_right=blk.crop_right, crop_bottom=blk.crop_bottom,
            brightness=blk.brightness, contrast=blk.contrast,
            original_width=parse_dimension(blk.original_width) if isinstance(blk.original_width, str) else blk.original_width,
            original_height=parse_dimension(blk.original_height) if isinstance(blk.original_height, str) else blk.original_height,
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v2(blk.unsupported),
        )

    if isinstance(blk, v1.CodeBlock):
        return v2b.CodeBlock(
            id=bid, language=blk.language, code=blk.code,
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v1.QuoteBlock):
        return v2b.QuoteBlock(
            id=bid, content=_blocks_to_v2(blk.content, collector),
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v1.EquationBlock):
        return v2b.EquationBlock(
            id=bid, latex=blk.latex,
            hwp_script=blk.hwp_script,
            display=blk.display,
            mathml=blk.mathml,
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v2(blk.unsupported),
        )

    if isinstance(blk, v1.FootnoteBlock):
        return v2b.FootnoteBlock(
            id=bid, ref=blk.ref,
            content=_blocks_to_v2(blk.content, collector),
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v1.EndnoteBlock):
        return v2b.EndnoteBlock(
            id=bid, ref=blk.ref,
            content=_blocks_to_v2(blk.content, collector),
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v1.HeaderBlock):
        return v2b.HeaderBlock(
            id=bid, apply_to=blk.apply_to,
            content=_blocks_to_v2(blk.content, collector),
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v1.FooterBlock):
        return v2b.FooterBlock(
            id=bid, apply_to=blk.apply_to,
            content=_blocks_to_v2(blk.content, collector),
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v1.FieldBlock):
        return v2b.FieldBlock(
            id=bid, field_type=blk.field_type, value=blk.value,
            inlines=_inlines_to_v2(blk.inlines, collector, bid),
            options=blk.options,
            default_value=blk.default_value,
            required=blk.required,
            max_length=blk.max_length,
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v1.TextBoxBlock):
        return v2b.TextBoxBlock(
            id=bid,
            content=_blocks_to_v2(blk.content, collector),
            width=parse_dimension(blk.width) if isinstance(blk.width, str) else blk.width,
            height=parse_dimension(blk.height) if isinstance(blk.height, str) else blk.height,
            position=position_to_v2(blk.position, collector, bid),
            padding_top=parse_dimension(blk.padding_top) if hasattr(blk, "padding_top") else None,
            padding_bottom=parse_dimension(blk.padding_bottom) if hasattr(blk, "padding_bottom") else None,
            padding_left=parse_dimension(blk.padding_left) if hasattr(blk, "padding_left") else None,
            padding_right=parse_dimension(blk.padding_right) if hasattr(blk, "padding_right") else None,
            vertical_align=getattr(blk, "vertical_align", None),
            background_color=blk.background_color,
            background_image=getattr(blk, "background_image", None),
            line_color=getattr(blk, "line_color", None),
            line_width=getattr(blk, "line_width", None),
            border_radius=getattr(blk, "border_radius", None),
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v2(blk.unsupported),
        )

    if isinstance(blk, v1.DrawingBlock):
        return v2b.DrawingBlock(
            id=bid, shape_type=blk.shape_type,
            position=position_to_v2(blk.position, collector, bid),
            background_color=blk.background_color,
            line_color=blk.line_color,
            line_width=blk.line_width,
            line_style=blk.line_style,
            vertices=blk.vertices,
            content=_blocks_to_v2(blk.content, collector),
            children=[block_to_v2(c, collector) for c in blk.children],
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v2(blk.unsupported),
        )

    if isinstance(blk, v1.HorizontalRuleBlock):
        return v2b.HorizontalRuleBlock(
            id=bid, verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v1.BookmarkBlock):
        return v2b.BookmarkBlock(
            id=bid, name=blk.name,
            start_block_id=blk.start_block_id,
            end_block_id=blk.end_block_id,
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v1.CommentBlock):
        return v2b.CommentBlock(
            id=bid, author=blk.author, date=blk.date,
            content=_blocks_to_v2(blk.content, collector),
            anchor_start_id=blk.anchor_start_id,
            anchor_end_id=blk.anchor_end_id,
            resolved=blk.resolved,
            color=blk.color,
            opacity=blk.opacity,
            parent_comment_id=blk.parent_comment_id,
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v1.PageBreakBlock):
        return v2b.PageBreakBlock(
            id=bid, verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v1.UnknownBlock):
        return v2b.UnknownBlock(
            id=bid, raw_bytes=blk.raw_bytes,
            description=blk.description,
            verbatim_ref=blk.verbatim_ref,
        )

    raise TypeError(f"Unknown block type: {type(blk)}")


def _list_item_to_v2(item: v1.ListItem, collector: ExtensionCollector, parent_id: str) -> v2b.ListItem:
    """Convert a v1 list item to v2, including nested children."""
    return v2b.ListItem(
        id=item.id,
        inlines=_inlines_to_v2(item.inlines, collector, item.id),
        children=[_list_item_to_v2(c, collector, item.id) for c in item.children],
        checked=item.checked,
        format=block_format_to_v2(item.format),
        verbatim_ref=item.verbatim_ref,
    )


def _unsupported_to_v2(u: v1.UnsupportedFeature | None) -> v2b.UnsupportedFeature | None:
    """Convert a v1 UnsupportedFeature to v2."""
    if u is None:
        return None
    return v2b.UnsupportedFeature(
        feature=u.feature, value=u.value, reason=u.reason,
    )


# ---------------------------------------------------------------------------
# v2→v1 블록 변환
# ---------------------------------------------------------------------------

def block_to_v1(blk: v2b.Block, ext_lookup: ExtensionLookup) -> v1.Block:  # noqa: C901
    """Convert a single v2 block to its v1 equivalent.

    Handles all 17 block types via isinstance dispatch. Format-specific
    extension fields are restored from the lookup into v1 model fields.

    Parameters
    ----------
    blk : v2b.Block
        The v2 schema block to convert.
    ext_lookup : ExtensionLookup
        Provider of format-specific extension fields.

    Returns
    -------
    v1.Block
        The converted v1 block.

    Raises
    ------
    TypeError
        If the block type is not recognized.
    """
    bid = blk.id

    if isinstance(blk, v2b.HeadingBlock):
        return v1.HeadingBlock(
            type="heading", id=bid, level=blk.level, text=blk.text,
            inlines=_inlines_to_v1(blk.inlines, ext_lookup, bid),
            format=block_format_to_v1(blk.format),
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v1(blk.unsupported),
            revision=revision_to_v1(blk.revision),
        )

    if isinstance(blk, v2b.ParagraphBlock):
        return v1.ParagraphBlock(
            type="paragraph", id=bid,
            inlines=_inlines_to_v1(blk.inlines, ext_lookup, bid),
            format=block_format_to_v1(blk.format),
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v1(blk.unsupported),
            revision=revision_to_v1(blk.revision),
        )

    if isinstance(blk, v2b.TableBlock):
        return v1.TableBlock(
            type="table", id=bid,
            width=format_pt(blk.width) if blk.width is not None else None,
            rows=[
                v1.TableRow(
                    cells=[
                        v1.TableCell(
                            id=c.id,
                            row_span=c.row_span, col_span=c.col_span,
                            width=c.width, height=c.height,
                            content=_blocks_to_v1(c.content, ext_lookup),
                            format=cell_format_to_v1(c.format),
                            is_header=c.is_header,
                            verbatim_ref=c.verbatim_ref,
                            unsupported=_unsupported_to_v1(c.unsupported),
                        ) for c in r.cells
                    ],
                    height=format_pt(r.height) if r.height is not None else None,
                    revision=revision_to_v1(r.revision),
                ) for r in blk.rows
            ],
            format=block_format_to_v1(blk.format),
            position=position_to_v1(blk.position, ext_lookup, bid),
            cell_spacing=format_mm(blk.cell_spacing),
            default_padding=format_mm(blk.default_padding),
            repeat_header=blk.repeat_header,
            border_top=blk.border_top,
            border_bottom=blk.border_bottom,
            border_left=blk.border_left,
            border_right=blk.border_right,
            border_inside_h=blk.border_inside_h,
            border_inside_v=blk.border_inside_v,
            caption=_inlines_to_v1(blk.caption, ext_lookup, bid) if blk.caption else None,
            description=blk.description,
            border_fill_id=blk.border_fill_id,
            col_widths=[v1.TableColumnDef(width=format_pt(cw.width) if cw.width is not None else None) for cw in blk.col_widths],
            layout_type=blk.layout_type,
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v1(blk.unsupported),
        )

    if isinstance(blk, v2b.ListBlock):
        return v1.ListBlock(
            type="list", id=bid, ordered=blk.ordered,
            start=blk.start,
            items=[_list_item_to_v1(it, ext_lookup) for it in blk.items],
            format=block_format_to_v1(blk.format),
            numbering_id=blk.numbering_id,
            bullet_id=blk.bullet_id,
            list_style=blk.list_style,
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v2b.ImageBlock):
        return v1.ImageBlock(
            type="image", id=bid, src=blk.src, alt=blk.alt,
            width=format_pt(blk.width) if blk.width is not None else None,
            height=format_pt(blk.height) if blk.height is not None else None,
            caption=_inlines_to_v1(blk.caption, ext_lookup, bid) if blk.caption else None,
            position=position_to_v1(blk.position, ext_lookup, bid),
            crop_left=blk.crop_left, crop_top=blk.crop_top,
            crop_right=blk.crop_right, crop_bottom=blk.crop_bottom,
            brightness=blk.brightness, contrast=blk.contrast,
            original_width=format_pt(blk.original_width) if blk.original_width is not None else None,
            original_height=format_pt(blk.original_height) if blk.original_height is not None else None,
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v1(blk.unsupported),
        )

    if isinstance(blk, v2b.CodeBlock):
        return v1.CodeBlock(
            type="code", id=bid, language=blk.language, code=blk.code,
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v2b.QuoteBlock):
        return v1.QuoteBlock(
            type="quote", id=bid, content=_blocks_to_v1(blk.content, ext_lookup),
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v2b.EquationBlock):
        return v1.EquationBlock(
            type="equation", id=bid, latex=blk.latex, display=blk.display,
            hwp_script=blk.hwp_script,
            mathml=blk.mathml,
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v1(blk.unsupported),
        )

    if isinstance(blk, v2b.FootnoteBlock):
        return v1.FootnoteBlock(
            type="footnote", id=bid, ref=blk.ref,
            content=_blocks_to_v1(blk.content, ext_lookup),
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v2b.EndnoteBlock):
        return v1.EndnoteBlock(
            type="endnote", id=bid, ref=blk.ref,
            content=_blocks_to_v1(blk.content, ext_lookup),
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v2b.HeaderBlock):
        return v1.HeaderBlock(
            type="header", id=bid, apply_to=blk.apply_to,
            content=_blocks_to_v1(blk.content, ext_lookup),
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v2b.FooterBlock):
        return v1.FooterBlock(
            type="footer", id=bid, apply_to=blk.apply_to,
            content=_blocks_to_v1(blk.content, ext_lookup),
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v2b.FieldBlock):
        return v1.FieldBlock(
            type="field", id=bid, field_type=blk.field_type, value=blk.value,
            inlines=_inlines_to_v1(blk.inlines, ext_lookup, bid),
            options=blk.options,
            default_value=blk.default_value,
            required=blk.required,
            max_length=blk.max_length,
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v2b.TextBoxBlock):
        return v1.TextBoxBlock(
            type="text_box", id=bid,
            content=_blocks_to_v1(blk.content, ext_lookup),
            width=format_pt(blk.width),
            height=format_pt(blk.height),
            position=position_to_v1(blk.position, ext_lookup, bid),
            padding_top=format_mm(blk.padding_top),
            padding_bottom=format_mm(blk.padding_bottom),
            padding_left=format_mm(blk.padding_left),
            padding_right=format_mm(blk.padding_right),
            vertical_align=blk.vertical_align,
            background_color=blk.background_color,
            background_image=blk.background_image,
            line_color=blk.line_color,
            line_width=blk.line_width,
            border_radius=blk.border_radius,
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v1(blk.unsupported),
        )

    if isinstance(blk, v2b.DrawingBlock):
        return v1.DrawingBlock(
            type="drawing", id=bid, shape_type=blk.shape_type,
            position=position_to_v1(blk.position, ext_lookup, bid),
            background_color=blk.background_color,
            line_color=blk.line_color,
            line_width=blk.line_width,
            line_style=blk.line_style,
            vertices=blk.vertices,
            content=_blocks_to_v1(blk.content, ext_lookup),
            children=[block_to_v1(c, ext_lookup) for c in blk.children],
            verbatim_ref=blk.verbatim_ref,
            unsupported=_unsupported_to_v1(blk.unsupported),
        )

    if isinstance(blk, v2b.HorizontalRuleBlock):
        return v1.HorizontalRuleBlock(
            type="horizontal_rule", id=bid, verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v2b.BookmarkBlock):
        return v1.BookmarkBlock(
            type="bookmark", id=bid, name=blk.name,
            start_block_id=blk.start_block_id,
            end_block_id=blk.end_block_id,
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v2b.CommentBlock):
        return v1.CommentBlock(
            type="comment", id=bid, author=blk.author, date=blk.date,
            content=_blocks_to_v1(blk.content, ext_lookup),
            anchor_start_id=blk.anchor_start_id,
            anchor_end_id=blk.anchor_end_id,
            resolved=blk.resolved,
            color=blk.color,
            opacity=blk.opacity,
            parent_comment_id=blk.parent_comment_id,
            verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v2b.PageBreakBlock):
        return v1.PageBreakBlock(
            type="page_break", id=bid, verbatim_ref=blk.verbatim_ref,
        )

    if isinstance(blk, v2b.UnknownBlock):
        return v1.UnknownBlock(
            type="unknown", id=bid, raw_bytes=blk.raw_bytes,
            description=blk.description,
            verbatim_ref=blk.verbatim_ref,
        )

    raise TypeError(f"Unknown block type: {type(blk)}")


def _list_item_to_v1(item: v2b.ListItem, ext_lookup: ExtensionLookup) -> v1.ListItem:
    """Convert a v2 list item to v1, including nested children."""
    return v1.ListItem(
        id=item.id,
        inlines=_inlines_to_v1(item.inlines, ext_lookup, item.id),
        children=[_list_item_to_v1(c, ext_lookup) for c in item.children],
        checked=item.checked,
        format=block_format_to_v1(item.format),
        verbatim_ref=item.verbatim_ref,
    )


def _unsupported_to_v1(u: v2b.UnsupportedFeature | None) -> v1.UnsupportedFeature | None:
    """Convert a v2 UnsupportedFeature to v1."""
    if u is None:
        return None
    return v1.UnsupportedFeature(
        feature=u.feature, value=u.value, reason=u.reason,
    )
