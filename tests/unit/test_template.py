"""M1: fill_template / set_placeholders / list_placeholders 단위 테스트."""

from __future__ import annotations

import pytest

from udf.core.schema import (
    DocumentMetadata,
    HeadingBlock,
    ParagraphBlock,
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


class TestFillTemplate:
    def test_basic_replacement(self):
        doc = _make_doc([_para("이름: {{이름}}, 학번: {{학번}}")])
        counts = doc.fill_template({"이름": "김훈", "학번": "30217"})
        assert counts["이름"] == 1
        assert counts["학번"] == 1
        text = doc.blocks[0].inlines[0].text
        assert "김훈" in text
        assert "30217" in text
        assert "{{" not in text

    def test_unused_key_returns_zero(self):
        doc = _make_doc([_para("안녕하세요")])
        counts = doc.fill_template({"없는키": "값"})
        assert counts["없는키"] == 0

    def test_strict_raises_on_unmatched(self):
        doc = _make_doc([_para("{{미등록}}")])
        with pytest.raises(ValueError, match="Unmatched"):
            doc.fill_template({}, strict=True)

    def test_strict_passes_when_all_matched(self):
        doc = _make_doc([_para("{{이름}}")])
        counts = doc.fill_template({"이름": "홍길동"}, strict=True)
        assert counts["이름"] == 1

    def test_custom_delimiter(self):
        doc = _make_doc([_para("이름: <<이름>>")])
        counts = doc.fill_template({"이름": "홍길동"}, delimiter=("<<", ">>"))
        assert counts["이름"] == 1
        assert "홍길동" in doc.blocks[0].inlines[0].text

    def test_multiple_occurrences(self):
        doc = _make_doc([
            _para("{{X}} and {{X}}", "b1"),
            _para("also {{X}}", "b2"),
        ])
        counts = doc.fill_template({"X": "val"})
        assert counts["X"] >= 2


class TestListPlaceholders:
    def test_finds_placeholders(self):
        doc = _make_doc([_para("{{이름}} 님, {{직책}}", "b1")])
        phs = doc.list_placeholders()
        keys = {p["key"] for p in phs}
        assert "이름" in keys
        assert "직책" in keys

    def test_empty_when_no_placeholders(self):
        doc = _make_doc([_para("일반 텍스트")])
        assert doc.list_placeholders() == []

    def test_custom_delimiter(self):
        doc = _make_doc([_para("<<name>>")])
        phs = doc.list_placeholders(delimiter=("<<", ">>"))
        assert len(phs) == 1
        assert phs[0]["key"] == "name"


class TestSetPlaceholders:
    def test_set_placeholder_replaces_text(self):
        doc = _make_doc([_para("홍길동", "b1")])
        results = doc.set_placeholders([
            {"block_id": "b1", "inline_idx": 0, "key": "이름"},
        ])
        assert len(results) >= 1
        assert "{{이름}}" in doc.blocks[0].inlines[0].text

    def test_roundtrip_set_then_fill(self):
        doc = _make_doc([_para("홍길동", "b1")])
        doc.set_placeholders([
            {"block_id": "b1", "inline_idx": 0, "key": "이름"},
        ])
        doc.fill_template({"이름": "김영희"})
        assert "김영희" in doc.blocks[0].inlines[0].text
        assert "{{" not in doc.blocks[0].inlines[0].text
