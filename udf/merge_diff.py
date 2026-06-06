"""Merge-diff engine for MD round-trip editing.

Compares an edited UdfDocument (parsed from user-edited Markdown) against
the original UdfDocument, and applies the changes to a deep copy of the
original — preserving verbatim layer, format-specific data, and blocks
that cannot be represented in Markdown.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Iterator, Literal

from udf.schema.blocks import (
    BlockBase,
    BookmarkBlock,
    ChartBlock,
    CommentBlock,
    DrawingBlock,
    EndnoteBlock,
    FieldBlock,
    FooterBlock,
    FootnoteBlock,
    HeaderBlock,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TextArtBlock,
    TextBoxBlock,
)
from udf.pipeline.document import UdfDocument

Block = BlockBase

_MD_UNREPRESENTABLE_TYPES = (
    TextBoxBlock,
    DrawingBlock,
    ChartBlock,
    TextArtBlock,
    FootnoteBlock,
    EndnoteBlock,
    HeaderBlock,
    FooterBlock,
    CommentBlock,
    BookmarkBlock,
    FieldBlock,
)


@dataclass
class Change:
    """A single change detected by merge_diff."""

    block_id: str
    change_type: Literal["text_edit", "added", "removed", "reordered"]
    description: str


@dataclass
class MergeDiffResult:
    """Result of a merge-diff operation."""

    document: "UdfDocument"  # noqa: F821
    changes: list[Change] = field(default_factory=list)
    preserved_ids: list[str] = field(default_factory=list)


def merge_diff(
    original: "UdfDocument",  # noqa: F821
    edited: "UdfDocument",  # noqa: F821
) -> MergeDiffResult:
    """Diff *edited* against *original* and apply changes to a deep copy.

    Parameters
    ----------
    original : UdfDocument
        The original document (with verbatim layer).
    edited : UdfDocument
        The document parsed from user-edited Markdown.

    Returns
    -------
    MergeDiffResult
        Patched document, list of changes, and preserved block IDs.
    """
    patched = copy.deepcopy(original)

    orig_index = _build_block_index(original.blocks)
    edited_index = _build_block_index(edited.blocks)
    patched_index = _build_block_index(patched.blocks)

    changes: list[Change] = []
    preserved: list[str] = []

    for bid, edited_block in edited_index.items():
        if bid not in orig_index:
            changes.append(Change(bid, "added", f"New block: {edited_block.text_content()[:40]}"))
            patched.add_block(edited_block)
            continue

        patched_block = patched_index.get(bid)
        if patched_block is None:
            continue

        changed = _apply_edit(patched_block, edited_block)
        if changed:
            patched._content_modified = True
            changes.append(Change(bid, "text_edit", f"Text changed in {bid}"))

    for bid, orig_block in orig_index.items():
        if bid in edited_index:
            continue
        if isinstance(orig_block, _MD_UNREPRESENTABLE_TYPES):
            preserved.append(bid)
            continue
        if isinstance(orig_block, ImageBlock):
            preserved.append(bid)
            continue
        patched.remove_block(bid)
        changes.append(Change(bid, "removed", f"Block {bid} removed"))

    _apply_table_cell_edits(patched, orig_index, edited_index, changes)
    _apply_list_item_edits(patched, orig_index, edited_index, changes)
    _apply_reorder(patched, edited, changes)

    return MergeDiffResult(document=patched, changes=changes, preserved_ids=preserved)


def _build_block_index(blocks: list) -> dict[str, BlockBase]:
    """Build a flat {id: block} index from the top-level block list."""
    index: dict[str, BlockBase] = {}
    for b in _iter_blocks_deep(blocks):
        bid = getattr(b, "id", None)
        if bid:
            index[bid] = b
    return index


def _iter_blocks_deep(blocks: list) -> Iterator[BlockBase]:
    """Recursively yield all blocks (top-level only, not cells/items)."""
    for b in blocks:
        if not isinstance(b, BlockBase):
            continue
        yield b
        content = getattr(b, "content", None)
        if isinstance(content, list):
            yield from _iter_blocks_deep(content)
        children = getattr(b, "children", None)
        if isinstance(children, list):
            yield from _iter_blocks_deep(children)


def _build_cell_index(blocks: list) -> dict[str, TableCell]:
    """Build a flat {id: cell} index for all table cells."""
    index: dict[str, TableCell] = {}
    for b in _iter_blocks_deep(blocks):
        if isinstance(b, TableBlock):
            for row in b.rows:
                for cell in row.cells:
                    index[cell.id] = cell
    return index


def _build_item_index(blocks: list) -> dict[str, ListItem]:
    """Build a flat {id: item} index for all list items."""
    index: dict[str, ListItem] = {}
    for b in _iter_blocks_deep(blocks):
        if isinstance(b, ListBlock):
            for item in b.items:
                index[item.id] = item
                for child in item.children:
                    index[child.id] = child
    return index


def _text_of(block: object) -> str:
    """Extract plain text from a block or item."""
    if hasattr(block, "text_content"):
        return block.text_content()
    inlines = getattr(block, "inlines", None)
    if inlines:
        return "".join(getattr(i, "text", "") for i in inlines)
    return ""


def _apply_edit(patched_block: BlockBase, edited_block: BlockBase) -> bool:
    """Apply text changes from edited_block to patched_block. Returns True if changed."""
    orig_text = _text_of(patched_block).strip()
    new_text = _text_of(edited_block).strip()
    if orig_text == new_text:
        return False

    if isinstance(patched_block, ParagraphBlock) and isinstance(edited_block, ParagraphBlock):
        _replace_inlines(patched_block, edited_block.inlines)
        return True

    if isinstance(patched_block, HeadingBlock) and isinstance(edited_block, HeadingBlock):
        patched_block.text = edited_block.text
        _replace_inlines(patched_block, edited_block.inlines)
        if edited_block.level != patched_block.level:
            patched_block.level = edited_block.level
        return True

    return False


def _replace_inlines(block: BlockBase, new_inlines: list) -> None:
    """Replace inlines on a block wholesale."""
    if hasattr(block, "inlines"):
        block.inlines = list(new_inlines)


def _apply_table_cell_edits(
    patched: "UdfDocument",
    orig_index: dict[str, BlockBase],
    edited_index: dict[str, BlockBase],
    changes: list[Change],
) -> None:
    """Compare table cells by ID and apply text edits."""
    patched_cells = _build_cell_index(patched.blocks)
    edited_cells = _build_cell_index(
        [edited_index[k] for k in edited_index if isinstance(edited_index[k], TableBlock)]
    )
    # Also build from all edited blocks (not just those in orig_index)
    for b in _iter_blocks_deep(
        [v for v in edited_index.values() if isinstance(v, BlockBase)]
    ):
        if isinstance(b, TableBlock):
            for row in b.rows:
                for cell in row.cells:
                    if cell.id not in edited_cells:
                        edited_cells[cell.id] = cell

    for cell_id, edited_cell in edited_cells.items():
        patched_cell = patched_cells.get(cell_id)
        if patched_cell is None:
            continue

        orig_text = _cell_text(patched_cell).strip()
        new_text = _cell_text(edited_cell).strip()
        if orig_text == new_text:
            continue

        _replace_cell_content(patched_cell, edited_cell)
        patched._content_modified = True
        changes.append(Change(cell_id, "text_edit", f"Cell {cell_id} text changed"))


def _cell_text(cell: TableCell) -> str:
    """Concatenated text of all paragraphs in a cell."""
    parts = []
    for b in cell.content:
        if hasattr(b, "text_content"):
            parts.append(b.text_content())
    return "\n".join(parts)


def _replace_cell_content(patched_cell: TableCell, edited_cell: TableCell) -> None:
    """Replace paragraph inlines in patched_cell from edited_cell."""
    edited_paras = [b for b in edited_cell.content if isinstance(b, ParagraphBlock)]
    patched_paras = [b for b in patched_cell.content if isinstance(b, ParagraphBlock)]

    for i, ep in enumerate(edited_paras):
        if i < len(patched_paras):
            pp = patched_paras[i]
            if _text_of(pp).strip() != _text_of(ep).strip():
                _replace_inlines(pp, ep.inlines)
        else:
            patched_cell.content.append(ep)


def _apply_list_item_edits(
    patched: "UdfDocument",
    orig_index: dict[str, BlockBase],
    edited_index: dict[str, BlockBase],
    changes: list[Change],
) -> None:
    """Compare list items by ID and apply text edits."""
    patched_items = _build_item_index(patched.blocks)
    edited_items: dict[str, ListItem] = {}
    for b in _iter_blocks_deep(
        [v for v in edited_index.values() if isinstance(v, BlockBase)]
    ):
        if isinstance(b, ListBlock):
            for item in b.items:
                edited_items[item.id] = item
                for child in item.children:
                    edited_items[child.id] = child

    for item_id, edited_item in edited_items.items():
        patched_item = patched_items.get(item_id)
        if patched_item is None:
            continue

        orig_text = _text_of(patched_item).strip()
        new_text = _text_of(edited_item).strip()
        if orig_text == new_text:
            continue

        _replace_inlines(patched_item, edited_item.inlines)
        patched._content_modified = True
        changes.append(Change(item_id, "text_edit", f"List item {item_id} text changed"))


def _apply_reorder(
    patched: "UdfDocument",
    edited: "UdfDocument",
    changes: list[Change],
) -> None:
    """Reorder patched top-level blocks to match edited order.

    MD-unrepresentable blocks are anchored after the preceding
    MD-representable block from the original order.
    """
    edited_ids = [getattr(b, "id", None) for b in edited.blocks]
    edited_ids = [bid for bid in edited_ids if bid]

    patched_blocks_by_id: dict[str, BlockBase] = {}
    unrepresentable: list[tuple[str | None, BlockBase]] = []
    last_representable_id: str | None = None

    for b in patched.blocks:
        bid = getattr(b, "id", None)
        if bid:
            patched_blocks_by_id[bid] = b
        if isinstance(b, (_MD_UNREPRESENTABLE_TYPES, ImageBlock)):
            unrepresentable.append((last_representable_id, b))
        else:
            last_representable_id = bid

    representable_ids = [
        bid for bid in edited_ids if bid in patched_blocks_by_id
    ]
    patched_representable = [
        getattr(b, "id", None)
        for b in patched.blocks
        if not isinstance(b, (_MD_UNREPRESENTABLE_TYPES, ImageBlock))
        and getattr(b, "id", None)
    ]

    if representable_ids == patched_representable:
        return

    new_blocks: list[BlockBase] = []
    placed_ids: set[str] = set()

    for bid in representable_ids:
        for anchor_id, unrep_block in unrepresentable:
            unrep_bid = getattr(unrep_block, "id", None)
            if anchor_id == bid and unrep_bid and unrep_bid not in placed_ids:
                continue
        block = patched_blocks_by_id.get(bid)
        if block and bid not in placed_ids:
            new_blocks.append(block)
            placed_ids.add(bid)
            for anchor_id, unrep_block in unrepresentable:
                unrep_bid = getattr(unrep_block, "id", None)
                if anchor_id == bid and unrep_bid and unrep_bid not in placed_ids:
                    new_blocks.append(unrep_block)
                    placed_ids.add(unrep_bid)

    for anchor_id, unrep_block in unrepresentable:
        unrep_bid = getattr(unrep_block, "id", None)
        if unrep_bid and unrep_bid not in placed_ids:
            new_blocks.append(unrep_block)
            placed_ids.add(unrep_bid)

    for b in patched.blocks:
        bid = getattr(b, "id", None)
        if bid and bid not in placed_ids:
            new_blocks.append(b)
            placed_ids.add(bid)

    patched.document.blocks = new_blocks
    patched._content_modified = True
    changes.append(Change("*", "reordered", "Block order changed"))
