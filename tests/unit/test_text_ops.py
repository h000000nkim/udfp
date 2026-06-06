"""A4: replace_text / find_text 단위 테스트."""

from __future__ import annotations

import pytest

from udf.core.schema import (
    DocumentMetadata,
    HeadingBlock,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextInline,
    UdfDocument,
)


def _make_doc(blocks: list) -> UdfDocument:
    return UdfDocument(
        source_format="hwp",
        metadata=DocumentMetadata(),
        blocks=blocks,
    )


def _para(text: str, blk_id: str = "b1") -> ParagraphBlock:
    return ParagraphBlock(
        type="paragraph",
        id=blk_id,
        inlines=[TextInline(text=text)],
    )


def _table_with_text(texts: list[list[str]]) -> TableBlock:
    rows = []
    for r_idx, row_texts in enumerate(texts):
        cells = []
        for c_idx, t in enumerate(row_texts):
            cid = f"c{r_idx}_{c_idx}"
            cells.append(TableCell(
                id=cid,
                content=[ParagraphBlock(
                    type="paragraph",
                    id=f"p{cid}",
                    inlines=[TextInline(text=t)],
                )],
            ))
        rows.append(TableRow(cells=cells))
    return TableBlock(type="table", id="t1", rows=rows)


class TestReplaceText:
    def test_basic_replacement(self):
        doc = _make_doc([_para("Hello World")])
        count = doc.replace_text("Hello", "Hi")
        assert count == 1
        assert "Hi World" in doc.blocks[0].inlines[0].text

    def test_no_match_returns_zero(self):
        doc = _make_doc([_para("안녕하세요")])
        count = doc.replace_text("없는텍스트", "대체")
        assert count == 0

    def test_multiple_paragraphs(self):
        doc = _make_doc([
            _para("AAA BBB", "b1"),
            _para("AAA CCC", "b2"),
        ])
        count = doc.replace_text("AAA", "XXX")
        assert count == 2
        assert "XXX" in doc.blocks[0].inlines[0].text
        assert "XXX" in doc.blocks[1].inlines[0].text

    def test_heading_text_replaced(self):
        doc = _make_doc([
            HeadingBlock(type="heading", id="h1", level=1, text="원본 제목"),
        ])
        count = doc.replace_text("원본", "수정")
        assert count >= 1

    def test_table_cell_text_replaced(self):
        doc = _make_doc([_table_with_text([["이름", "나이"], ["홍길동", "30"]])])
        count = doc.replace_text("홍길동", "김영희")
        assert count == 1

    def test_marks_content_modified(self):
        doc = _make_doc([_para("text")])
        doc._content_modified = False
        doc.replace_text("text", "new")
        assert doc._content_modified is True

    def test_no_match_keeps_unmodified(self):
        doc = _make_doc([_para("text")])
        doc._content_modified = False
        doc.replace_text("없음", "x")
        assert doc._content_modified is False


class TestFindText:
    def test_basic_find(self):
        doc = _make_doc([_para("abc 123 def", "b1")])
        matches = doc.find_text(r"\d+")
        assert len(matches) >= 1
        assert matches[0]["text"] == "123"

    def test_no_match_empty(self):
        doc = _make_doc([_para("안녕하세요")])
        matches = doc.find_text(r"\d+")
        assert matches == []

    def test_multiple_matches(self):
        doc = _make_doc([
            _para("aaa 111 bbb", "b1"),
            _para("ccc 222 ddd", "b2"),
        ])
        matches = doc.find_text(r"\d+")
        texts = {m["text"] for m in matches}
        assert "111" in texts
        assert "222" in texts

    def test_returns_block_id(self):
        doc = _make_doc([_para("abc 999", "myblock")])
        matches = doc.find_text(r"\d+")
        assert any(m["block_id"] == "myblock" for m in matches)

    def test_korean_pattern(self):
        doc = _make_doc([_para("이름: 홍길동, 나이: 30")])
        matches = doc.find_text(r"홍길동")
        assert len(matches) == 1
        assert matches[0]["text"] == "홍길동"

    def test_regex_groups(self):
        doc = _make_doc([_para("날짜: 2026-06-06")])
        matches = doc.find_text(r"\d{4}-\d{2}-\d{2}")
        assert len(matches) == 1
        assert matches[0]["text"] == "2026-06-06"
