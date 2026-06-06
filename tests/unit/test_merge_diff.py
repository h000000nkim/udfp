"""Tests for Phase 13: MD merge-diff (13a-13d)."""

from __future__ import annotations

from udf.core.ids import max_block_index
from udf.merge_diff import merge_diff
from udf.parsers.md.parse import parse_md
from udf.pipeline.document import UdfDocument
from udf.renderers.md import render_md
from udf.schema.blocks import (
    DrawingBlock,
    HeadingBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
)
from udf.schema.document import DocumentSchema
from udf.schema.inlines import TextInline
from udf.schema.metadata import DocumentMetadata
from udf.pipeline.verbatim import VerbatimLayer


def _make_doc(blocks: list) -> UdfDocument:
    return UdfDocument(
        source_format="hwp",
        document=DocumentSchema(metadata=DocumentMetadata(), blocks=blocks),
        verbatim=VerbatimLayer(format="hwp"),
    )


def _para(id: str, text: str) -> ParagraphBlock:
    return ParagraphBlock(
        type="paragraph", id=id,
        inlines=[TextInline(type="text", text=text)],
    )


def _heading(id: str, text: str, level: int = 1) -> HeadingBlock:
    return HeadingBlock(
        type="heading", id=id, level=level, text=text,
        inlines=[TextInline(type="text", text=text)],
    )


# -----------------------------------------------------------------------
# Phase 13a: MD renderer — cell/item ID embedding
# -----------------------------------------------------------------------

class TestRenderCellIds:
    def test_table_cell_bid_with_embed_ids(self):
        table = TableBlock(
            type="table", id="t1",
            rows=[TableRow(cells=[
                TableCell(id="c1", content=[_para("p1", "Hello")]),
                TableCell(id="c2", content=[_para("p2", "World")]),
            ])],
        )
        doc = _make_doc([table])
        md = render_md(doc, embed_ids=True)
        assert 'data-bid="c1"' in md
        assert 'data-bid="c2"' in md

    def test_table_cell_no_bid_without_embed_ids(self):
        table = TableBlock(
            type="table", id="t1",
            rows=[TableRow(cells=[
                TableCell(id="c1", content=[_para("p1", "Hello")]),
            ])],
        )
        doc = _make_doc([table])
        md = render_md(doc, embed_ids=False)
        assert "data-bid" not in md


class TestRenderListItemIds:
    def test_list_item_id_with_embed_ids(self):
        lst = ListBlock(
            type="list", id="l1", ordered=False,
            items=[
                ListItem(id="i1", inlines=[TextInline(type="text", text="First")]),
                ListItem(id="i2", inlines=[TextInline(type="text", text="Second")]),
            ],
        )
        doc = _make_doc([lst])
        md = render_md(doc, embed_ids=True)
        assert "<!-- item: i1 -->" in md
        assert "<!-- item: i2 -->" in md

    def test_list_item_no_id_without_embed_ids(self):
        lst = ListBlock(
            type="list", id="l1", ordered=False,
            items=[
                ListItem(id="i1", inlines=[TextInline(type="text", text="First")]),
            ],
        )
        doc = _make_doc([lst])
        md = render_md(doc, embed_ids=False)
        assert "<!-- item:" not in md


# -----------------------------------------------------------------------
# Phase 13b: MD parser — cell/item ID extraction
# -----------------------------------------------------------------------

class TestParseCellIds:
    def test_cell_bid_roundtrip(self):
        table = TableBlock(
            type="table", id="t1",
            rows=[TableRow(cells=[
                TableCell(id="c_001", content=[_para("p1", "Alpha")]),
                TableCell(id="c_002", content=[_para("p2", "Beta")]),
            ])],
        )
        doc = _make_doc([table])
        md = render_md(doc, embed_ids=True)
        parsed = parse_md(md)
        tables = [b for b in parsed.blocks if isinstance(b, TableBlock)]
        assert len(tables) == 1
        cells = tables[0].rows[0].cells
        assert cells[0].id == "c_001"
        assert cells[1].id == "c_002"

    def test_cell_fresh_id_without_bid(self):
        md_text = '<table width="100%">\n<tr>\n<td>Hello</td>\n</tr>\n</table>'
        parsed = parse_md(md_text)
        tables = [b for b in parsed.blocks if isinstance(b, TableBlock)]
        assert len(tables) == 1
        cell = tables[0].rows[0].cells[0]
        assert cell.id.startswith("b_")


class TestParseListItemIds:
    def test_item_id_roundtrip(self):
        lst = ListBlock(
            type="list", id="l1", ordered=False,
            items=[
                ListItem(id="item_01", inlines=[TextInline(type="text", text="First")]),
                ListItem(id="item_02", inlines=[TextInline(type="text", text="Second")]),
            ],
        )
        doc = _make_doc([lst])
        md = render_md(doc, embed_ids=True)
        parsed = parse_md(md)
        lists = [b for b in parsed.blocks if isinstance(b, ListBlock)]
        assert len(lists) == 1
        assert lists[0].items[0].id == "item_01"
        assert lists[0].items[1].id == "item_02"

    def test_item_fresh_id_without_comment(self):
        md_text = "- Hello\n- World"
        parsed = parse_md(md_text)
        lists = [b for b in parsed.blocks if isinstance(b, ListBlock)]
        assert len(lists) == 1
        assert lists[0].items[0].id.startswith("b_")


# -----------------------------------------------------------------------
# Phase 13c: ID collision prevention
# -----------------------------------------------------------------------

class TestMaxBlockIndex:
    def test_simple(self):
        blocks = [_para("b_0010", "A"), _para("b_0003", "B")]
        assert max_block_index(blocks) == 10

    def test_table_cells(self):
        table = TableBlock(
            type="table", id="b_0001",
            rows=[TableRow(cells=[
                TableCell(id="b_0050", content=[_para("b_0002", "X")]),
            ])],
        )
        assert max_block_index([table]) == 50

    def test_list_items(self):
        lst = ListBlock(
            type="list", id="b_0001", ordered=False,
            items=[ListItem(id="b_0099", inlines=[])],
        )
        assert max_block_index([lst]) == 99

    def test_empty(self):
        assert max_block_index([]) == 0


class TestParseMdStartId:
    def test_start_id(self):
        md_text = "Hello world"
        parsed = parse_md(md_text, start_id=100)
        assert parsed.blocks[0].id == "b_0100"

    def test_default_start(self):
        md_text = "Hello world"
        parsed = parse_md(md_text)
        assert parsed.blocks[0].id == "b_0001"


# -----------------------------------------------------------------------
# Phase 13d: merge_diff module
# -----------------------------------------------------------------------

class TestMergeDiffNoChange:
    def test_identical_docs(self):
        doc = _make_doc([_para("b_0001", "Hello")])
        edited = _make_doc([_para("b_0001", "Hello")])
        result = merge_diff(doc, edited)
        assert len(result.changes) == 0
        assert result.document.blocks[0].text_content() == "Hello"


class TestMergeDiffTextEdit:
    def test_paragraph_text_change(self):
        original = _make_doc([_para("b_0001", "Old text")])
        edited = _make_doc([_para("b_0001", "New text")])
        result = merge_diff(original, edited)
        assert len(result.changes) == 1
        assert result.changes[0].change_type == "text_edit"
        assert result.document.blocks[0].text_content() == "New text"

    def test_heading_text_change(self):
        original = _make_doc([_heading("b_0001", "Old", level=1)])
        edited = _make_doc([_heading("b_0001", "New", level=2)])
        result = merge_diff(original, edited)
        assert len(result.changes) == 1
        h = result.document.blocks[0]
        assert isinstance(h, HeadingBlock)
        assert h.text == "New"
        assert h.level == 2


class TestMergeDiffBlockRemoval:
    def test_remove_paragraph(self):
        original = _make_doc([
            _para("b_0001", "Keep"),
            _para("b_0002", "Remove"),
        ])
        edited = _make_doc([_para("b_0001", "Keep")])
        result = merge_diff(original, edited)
        removed = [c for c in result.changes if c.change_type == "removed"]
        assert len(removed) == 1
        assert removed[0].block_id == "b_0002"
        assert len(result.document.blocks) == 1

    def test_preserve_md_unrepresentable(self):
        original = _make_doc([
            _para("b_0001", "Text"),
            TextBoxBlock(type="text_box", id="b_0002", content=[]),
            DrawingBlock(type="drawing", id="b_0003", content=[]),
        ])
        edited = _make_doc([_para("b_0001", "Text")])
        result = merge_diff(original, edited)
        assert "b_0002" in result.preserved_ids
        assert "b_0003" in result.preserved_ids
        assert len(result.document.blocks) == 3


class TestMergeDiffBlockAddition:
    def test_add_paragraph(self):
        original = _make_doc([_para("b_0001", "Existing")])
        edited = _make_doc([
            _para("b_0001", "Existing"),
            _para("b_0100", "New paragraph"),
        ])
        result = merge_diff(original, edited)
        added = [c for c in result.changes if c.change_type == "added"]
        assert len(added) == 1
        assert added[0].block_id == "b_0100"


class TestMergeDiffTableCells:
    def test_cell_text_edit(self):
        table = TableBlock(
            type="table", id="b_0001",
            rows=[TableRow(cells=[
                TableCell(id="b_0010", content=[_para("b_0011", "Old")]),
                TableCell(id="b_0020", content=[_para("b_0021", "Keep")]),
            ])],
        )
        edited_table = TableBlock(
            type="table", id="b_0001",
            rows=[TableRow(cells=[
                TableCell(id="b_0010", content=[_para("b_0011", "New")]),
                TableCell(id="b_0020", content=[_para("b_0021", "Keep")]),
            ])],
        )
        original = _make_doc([table])
        edited = _make_doc([edited_table])
        result = merge_diff(original, edited)
        cell_edits = [c for c in result.changes if c.block_id == "b_0010"]
        assert len(cell_edits) == 1
        patched_table = result.document.blocks[0]
        assert isinstance(patched_table, TableBlock)
        cell0 = patched_table.rows[0].cells[0]
        assert cell0.content[0].text_content() == "New"
        cell1 = patched_table.rows[0].cells[1]
        assert cell1.content[0].text_content() == "Keep"


class TestMergeDiffListItems:
    def test_item_text_edit(self):
        lst = ListBlock(
            type="list", id="b_0001", ordered=False,
            items=[
                ListItem(id="b_0010", inlines=[TextInline(type="text", text="Old")]),
                ListItem(id="b_0020", inlines=[TextInline(type="text", text="Keep")]),
            ],
        )
        edited_lst = ListBlock(
            type="list", id="b_0001", ordered=False,
            items=[
                ListItem(id="b_0010", inlines=[TextInline(type="text", text="New")]),
                ListItem(id="b_0020", inlines=[TextInline(type="text", text="Keep")]),
            ],
        )
        original = _make_doc([lst])
        edited = _make_doc([edited_lst])
        result = merge_diff(original, edited)
        item_edits = [c for c in result.changes if c.block_id == "b_0010"]
        assert len(item_edits) == 1
        patched_list = result.document.blocks[0]
        assert isinstance(patched_list, ListBlock)
        assert patched_list.items[0].inlines[0].text == "New"
        assert patched_list.items[1].inlines[0].text == "Keep"


# -----------------------------------------------------------------------
# Phase 13: Block reorder
# -----------------------------------------------------------------------

class TestMergeDiffReorder:
    def test_reorder_two_blocks(self):
        original = _make_doc([
            _para("b_0001", "First"),
            _para("b_0002", "Second"),
        ])
        edited = _make_doc([
            _para("b_0002", "Second"),
            _para("b_0001", "First"),
        ])
        result = merge_diff(original, edited)
        reordered = [c for c in result.changes if c.change_type == "reordered"]
        assert len(reordered) == 1
        assert result.document.blocks[0].id == "b_0002"
        assert result.document.blocks[1].id == "b_0001"

    def test_no_reorder_same_order(self):
        original = _make_doc([
            _para("b_0001", "First"),
            _para("b_0002", "Second"),
        ])
        edited = _make_doc([
            _para("b_0001", "First"),
            _para("b_0002", "Second"),
        ])
        result = merge_diff(original, edited)
        reordered = [c for c in result.changes if c.change_type == "reordered"]
        assert len(reordered) == 0

    def test_reorder_preserves_unrepresentable(self):
        original = _make_doc([
            _para("b_0001", "First"),
            TextBoxBlock(type="text_box", id="b_0002", content=[]),
            _para("b_0003", "Third"),
        ])
        edited = _make_doc([
            _para("b_0003", "Third"),
            _para("b_0001", "First"),
        ])
        result = merge_diff(original, edited)
        ids = [b.id for b in result.document.blocks]
        assert ids.index("b_0003") < ids.index("b_0001")
        assert "b_0002" in ids
