"""Phase 9.5 UdfDocument API 테스트 — deep CRUD, inline, table, metadata."""

from __future__ import annotations


from udf.pipeline.document import UdfDocument
from udf.schema.blocks import (
    Block,
    FootnoteBlock,
    HeadingBlock,
    ImageBlock,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
)
from udf.schema.formats import BlockFormat
from udf.schema.inlines import TextInline


def _para(id: str, text: str = "", **kwargs) -> ParagraphBlock:
    return ParagraphBlock(
        id=id,
        inlines=[TextInline(text=text)] if text else [],
        **kwargs,
    )


def _heading(id: str, text: str, level: int = 1) -> HeadingBlock:
    return HeadingBlock(id=id, text=text, level=level)


def _table(id: str, cells: list[list[str]]) -> TableBlock:
    rows = []
    for ri, row_data in enumerate(cells):
        row_cells = []
        for ci, text in enumerate(row_data):
            row_cells.append(TableCell(
                id=f"{id}_c{ri}{ci}",
                content=[_para(f"{id}_p{ri}{ci}", text)],
            ))
        rows.append(TableRow(cells=row_cells))
    return TableBlock(id=id, rows=rows)


def _doc(*blocks: Block) -> UdfDocument:
    return UdfDocument(source_format="test", blocks=list(blocks))


# ============================================================
# Deep Block CRUD
# ============================================================


class TestGetBlockDeep:
    def test_top_level(self) -> None:
        doc = _doc(_para("p1", "hello"))
        assert doc.get_block("p1") is not None
        assert doc.get_block("p1").id == "p1"

    def test_not_found(self) -> None:
        doc = _doc(_para("p1"))
        assert doc.get_block("nonexistent") is None

    def test_inside_table_cell(self) -> None:
        tbl = _table("t1", [["A", "B"], ["C", "D"]])
        doc = _doc(tbl)
        block = doc.get_block("t1_p01")
        assert block is not None
        assert isinstance(block, ParagraphBlock)

    def test_inside_footnote(self) -> None:
        fn = FootnoteBlock(
            id="fn1", ref="1",
            content=[_para("fn1_p", "footnote text")],
        )
        doc = _doc(fn)
        block = doc.get_block("fn1_p")
        assert block is not None
        assert isinstance(block, ParagraphBlock)

    def test_inside_textbox(self) -> None:
        tb = TextBoxBlock(
            id="tb1",
            content=[_para("tb1_p", "textbox"), _heading("tb1_h", "heading")],
        )
        doc = _doc(tb)
        assert doc.get_block("tb1_p") is not None
        assert doc.get_block("tb1_h") is not None

    def test_nested_table_in_textbox(self) -> None:
        tbl = _table("inner_t", [["X"]])
        tb = TextBoxBlock(id="tb1", content=[tbl])
        doc = _doc(tb)
        assert doc.get_block("inner_t_p00") is not None


class TestFindBlocksDeep:
    def test_find_paragraphs_in_table(self) -> None:
        tbl = _table("t1", [["A", "B"]])
        doc = _doc(_para("p1", "top"), tbl)
        paras = doc.find_blocks("paragraph")
        assert len(paras) == 3  # p1 + 2 cell paragraphs

    def test_find_headings_in_footnote(self) -> None:
        fn = FootnoteBlock(
            id="fn1", ref="1",
            content=[_heading("fn_h", "note heading")],
        )
        doc = _doc(fn)
        headings = doc.find_blocks("heading")
        assert len(headings) == 1
        assert headings[0].id == "fn_h"

    def test_convenience_properties_deep(self) -> None:
        tbl = _table("t1", [["A"]])
        doc = _doc(_para("p1", "top"), tbl, _heading("h1", "title"))
        assert len(doc.paragraphs) == 2  # p1 + cell para
        assert len(doc.headings) == 1
        assert len(doc.tables) == 1


class TestAddBlockDeep:
    def test_add_to_top_level(self) -> None:
        doc = _doc(_para("p1"))
        doc.add_block(_para("p2", "new"))
        assert len(doc.blocks) == 2

    def test_add_after(self) -> None:
        doc = _doc(_para("p1"), _para("p3"))
        doc.add_block(_para("p2", "middle"), after="p1")
        assert [b.id for b in doc.blocks] == ["p1", "p2", "p3"]

    def test_add_to_parent(self) -> None:
        tb = TextBoxBlock(id="tb1", content=[_para("tb_p1")])
        doc = _doc(tb)
        doc.add_block(_para("tb_p2", "added"), parent_id="tb1")
        assert len(tb.content) == 2
        assert tb.content[1].id == "tb_p2"

    def test_add_to_parent_after(self) -> None:
        fn = FootnoteBlock(
            id="fn1", ref="1",
            content=[_para("fn_p1"), _para("fn_p3")],
        )
        doc = _doc(fn)
        doc.add_block(_para("fn_p2"), parent_id="fn1", after="fn_p1")
        assert [b.id for b in fn.content] == ["fn_p1", "fn_p2", "fn_p3"]


class TestRemoveBlockDeep:
    def test_remove_top_level(self) -> None:
        doc = _doc(_para("p1"), _para("p2"))
        removed = doc.remove_block("p1")
        assert removed is not None
        assert removed.id == "p1"
        assert len(doc.blocks) == 1

    def test_remove_from_table_cell(self) -> None:
        tbl = _table("t1", [["A"]])
        doc = _doc(tbl)
        cell = tbl.rows[0].cells[0]
        assert len(cell.content) == 1
        removed = doc.remove_block("t1_p00")
        assert removed is not None
        assert len(cell.content) == 0

    def test_remove_nonexistent(self) -> None:
        doc = _doc(_para("p1"))
        assert doc.remove_block("nope") is None


class TestMoveBlockDeep:
    def test_move_within_top_level(self) -> None:
        doc = _doc(_para("p1"), _para("p2"), _para("p3"))
        assert doc.move_block("p3", after="p1")
        assert [b.id for b in doc.blocks] == ["p1", "p3", "p2"]

    def test_move_to_parent(self) -> None:
        tb = TextBoxBlock(id="tb1", content=[])
        doc = _doc(_para("p1", "moveme"), tb)
        assert doc.move_block("p1", parent_id="tb1")
        assert len(doc.blocks) == 1  # only tb1
        assert len(tb.content) == 1
        assert tb.content[0].id == "p1"


# ============================================================
# Inline 조작
# ============================================================


class TestInlineAPI:
    def test_get_inline(self) -> None:
        doc = _doc(_para("p1", "hello"))
        inline = doc.get_inline("p1", 0)
        assert inline is not None
        assert inline.text == "hello"

    def test_get_inline_out_of_range(self) -> None:
        doc = _doc(_para("p1", "hello"))
        assert doc.get_inline("p1", 5) is None

    def test_set_inline_text(self) -> None:
        doc = _doc(_para("p1", "old"))
        doc.set_inline_text("p1", 0, "new")
        assert doc.get_inline("p1", 0).text == "new"

    def test_set_inline_text_heading(self) -> None:
        doc = _doc(_heading("h1", "old title"))
        doc.set_inline_text("h1", 0, "new title")
        block = doc.get_block("h1")
        assert block.text == "new title"

    def test_set_inline_format(self) -> None:
        doc = _doc(_para("p1", "text"))
        doc.set_inline_format("p1", 0, bold=True)
        inline = doc.get_inline("p1", 0)
        assert inline.bold is True

    def test_add_inline(self) -> None:
        doc = _doc(_para("p1", "first"))
        doc.add_inline("p1", TextInline(text=" second"))
        block = doc.get_block("p1")
        assert len(block.inlines) == 2

    def test_add_inline_at(self) -> None:
        doc = _doc(_para("p1", "B"))
        doc.add_inline("p1", TextInline(text="A"), at=0)
        assert doc.get_inline("p1", 0).text == "A"
        assert doc.get_inline("p1", 1).text == "B"

    def test_remove_inline(self) -> None:
        p = ParagraphBlock(
            id="p1",
            inlines=[TextInline(text="A"), TextInline(text="B")],
        )
        doc = _doc(p)
        removed = doc.remove_inline("p1", 0)
        assert removed.text == "A"
        assert len(p.inlines) == 1

    def test_split_inline(self) -> None:
        doc = _doc(_para("p1", "helloworld"))
        doc.split_inline("p1", 0, 5)
        assert doc.get_inline("p1", 0).text == "hello"
        assert doc.get_inline("p1", 1).text == "world"

    def test_inline_in_deep_block(self) -> None:
        """테이블 셀 내부 단락의 인라인 수정."""
        tbl = _table("t1", [["cell text"]])
        doc = _doc(tbl)
        doc.set_inline_text("t1_p00", 0, "modified")
        assert doc.get_inline("t1_p00", 0).text == "modified"

    def test_set_inline_text_on_empty_block_creates_inline(self) -> None:
        """Auto-create TextInline when set_inline_text targets an empty block.

        빈 블록(inlines=[])에 set_inline_text 호출 시 새 TextInline 자동 생성 확인.

        Asserts
        -------
        - Block has exactly 1 inline after the call.
        - Inline text matches the inserted value.
        """
        doc = _doc(_para("p1"))  # inlines=[]
        doc.set_inline_text("p1", 0, "auto created")
        block = doc.get_block("p1")
        assert len(block.inlines) == 1
        assert block.inlines[0].text == "auto created"

    def test_add_inline_to_empty_block(self) -> None:
        """Append a TextInline to an empty paragraph via add_inline.

        빈 단락에 add_inline으로 텍스트 추가 후 인라인 생성 확인.

        Asserts
        -------
        - Block has exactly 1 inline after the call.
        - Inline text matches the inserted value.
        """
        doc = _doc(_para("p1"))
        doc.add_inline("p1", TextInline(text="filled"))
        block = doc.get_block("p1")
        assert len(block.inlines) == 1
        assert block.inlines[0].text == "filled"

    def test_add_inline_to_empty_table_cell(self) -> None:
        """Append a TextInline to an empty table cell paragraph.

        빈 테이블 셀의 단락에 add_inline 후 텍스트 접근 가능 확인.

        Asserts
        -------
        - get_inline returns the inserted text at index 0.
        """
        tbl = _table("t1", [[""]])  # empty cell
        doc = _doc(tbl)
        doc.add_inline("t1_p00", TextInline(text="cell filled"))
        assert doc.get_inline("t1_p00", 0).text == "cell filled"


# ============================================================
# Block 서식
# ============================================================


class TestBlockFormatAPI:
    def test_get_block_format_none(self) -> None:
        doc = _doc(_para("p1", "text"))
        assert doc.get_block_format("p1") is None

    def test_set_block_format(self) -> None:
        doc = _doc(_para("p1", "text"))
        doc.set_block_format("p1", alignment="center")
        fmt = doc.get_block_format("p1")
        assert fmt is not None
        assert fmt.alignment == "center"

    def test_update_block_format(self) -> None:
        p = ParagraphBlock(
            id="p1", inlines=[], format=BlockFormat(alignment="left"),
        )
        doc = _doc(p)
        doc.set_block_format("p1", alignment="right")
        assert doc.get_block_format("p1").alignment == "right"


# ============================================================
# 테이블 구조
# ============================================================


class TestTableAPI:
    def test_get_cell(self) -> None:
        tbl = _table("t1", [["A", "B"], ["C", "D"]])
        doc = _doc(tbl)
        cell = doc.get_cell("t1", 0, 1)
        assert cell is not None
        assert cell.id == "t1_c01"

    def test_get_cell_out_of_range(self) -> None:
        tbl = _table("t1", [["A"]])
        doc = _doc(tbl)
        assert doc.get_cell("t1", 5, 0) is None

    def test_add_table_row(self) -> None:
        tbl = _table("t1", [["A", "B"]])
        doc = _doc(tbl)
        new_row = doc.add_table_row("t1")
        assert new_row is not None
        assert len(tbl.rows) == 2
        assert len(tbl.rows[1].cells) == 2

    def test_add_table_row_at(self) -> None:
        tbl = _table("t1", [["A"], ["C"]])
        doc = _doc(tbl)
        doc.add_table_row("t1", at=1)
        assert len(tbl.rows) == 3

    def test_remove_table_row(self) -> None:
        tbl = _table("t1", [["A"], ["B"]])
        doc = _doc(tbl)
        removed = doc.remove_table_row("t1", 0)
        assert removed is not None
        assert len(tbl.rows) == 1

    def test_add_table_column(self) -> None:
        tbl = _table("t1", [["A"], ["B"]])
        doc = _doc(tbl)
        doc.add_table_column("t1")
        assert len(tbl.rows[0].cells) == 2
        assert len(tbl.rows[1].cells) == 2

    def test_remove_table_column(self) -> None:
        tbl = _table("t1", [["A", "B"], ["C", "D"]])
        doc = _doc(tbl)
        doc.remove_table_column("t1", 1)
        assert len(tbl.rows[0].cells) == 1
        assert len(tbl.rows[1].cells) == 1

    def test_merge_cells(self) -> None:
        tbl = _table("t1", [["A", "B"], ["C", "D"]])
        doc = _doc(tbl)
        doc.merge_cells("t1", 0, 0, 1, 1)
        cell = doc.get_cell("t1", 0, 0)
        assert cell.col_span == 2
        assert cell.row_span == 2


# ============================================================
# Metadata
# ============================================================


class TestMetadataAPI:
    def test_set_metadata(self) -> None:
        doc = _doc()
        doc.set_metadata(title="Test Doc", author="User")
        assert doc.metadata.title == "Test Doc"
        assert doc.metadata.author == "User"

    def test_set_metadata_partial(self) -> None:
        doc = _doc()
        doc.set_metadata(title="First")
        doc.set_metadata(author="Second")
        assert doc.metadata.title == "First"
        assert doc.metadata.author == "Second"


# ---------------------------------------------------------------------------
# Phase 15g: 이미지 캐시
# ---------------------------------------------------------------------------


class TestImageCache:
    def test_add_image_block_caches_data_uri(self) -> None:
        import base64
        raw = b"\x89PNG\r\n\x1a\n"
        data_uri = "data:image/png;base64," + base64.b64encode(raw).decode()
        doc = _doc()
        doc.add_block(ImageBlock(type="image", id="img1", src=data_uri))
        assert data_uri in doc._image_cache
        assert doc._image_cache[data_uri] == raw

    def test_add_image_block_caches_file(self, tmp_path) -> None:
        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"FAKE_PNG")
        doc = _doc()
        doc.add_block(ImageBlock(type="image", id="img1", src=str(img_file)))
        assert str(img_file) in doc._image_cache
        assert doc._image_cache[str(img_file)] == b"FAKE_PNG"

    def test_bindata_src_not_cached_on_add(self) -> None:
        doc = _doc()
        doc.add_block(ImageBlock(type="image", id="img1", src="bindata:BIN0001.PNG"))
        assert "bindata:BIN0001.PNG" not in doc._image_cache

    def test_resolve_image_from_cache(self) -> None:
        doc = _doc()
        doc._image_cache["my_img.png"] = b"CACHED"
        assert doc.resolve_image("my_img.png") == b"CACHED"

    def test_resolve_image_from_file(self, tmp_path) -> None:
        img_file = tmp_path / "photo.jpg"
        img_file.write_bytes(b"JPEG_DATA")
        doc = _doc()
        assert doc.resolve_image(str(img_file)) == b"JPEG_DATA"

    def test_resolve_image_returns_none_for_missing(self) -> None:
        doc = _doc()
        assert doc.resolve_image("/nonexistent/path.png") is None

    def test_non_image_block_not_cached(self) -> None:
        doc = _doc()
        doc.add_block(ParagraphBlock(
            type="paragraph", id="p_new",
            inlines=[TextInline(text="hello")],
        ))
        assert len(doc._image_cache) == 0

    def test_cache_is_per_instance(self) -> None:
        doc1 = _doc()
        doc2 = _doc()
        doc1._image_cache["x"] = b"A"
        assert "x" not in doc2._image_cache
