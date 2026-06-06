"""A2: udf.render() 포맷별 dispatch 단위 테스트."""

from __future__ import annotations

import pathlib

import pytest

import udf
from udf.core.schema import (
    DocumentMetadata,
    HeadingBlock,
    ParagraphBlock,
    TextInline,
    UdfDocument,
)


def _make_doc() -> UdfDocument:
    return UdfDocument(
        source_format="test",
        metadata=DocumentMetadata(title="테스트 문서"),
        blocks=[
            HeadingBlock(type="heading", id="h1", level=1, text="제목"),
            ParagraphBlock(
                type="paragraph",
                id="b1",
                inlines=[TextInline(text="본문 텍스트입니다.")],
            ),
        ],
    )


class TestRenderToMd:
    def test_returns_string(self):
        doc = _make_doc()
        result = udf.render(doc, "md")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_heading(self):
        doc = _make_doc()
        md = udf.render(doc, "md")
        assert "# 제목" in md

    def test_contains_text(self):
        doc = _make_doc()
        md = udf.render(doc, "md")
        assert "본문 텍스트입니다" in md


class TestRenderToHtml:
    def test_returns_string(self):
        doc = _make_doc()
        result = udf.render(doc, "html")
        assert isinstance(result, str)
        assert "<" in result

    def test_contains_heading_tag(self):
        doc = _make_doc()
        html = udf.render(doc, "html")
        assert "<h1" in html
        assert "제목" in html

    def test_contains_paragraph(self):
        doc = _make_doc()
        html = udf.render(doc, "html")
        assert "본문 텍스트입니다" in html


class TestRenderToHwp:
    def test_creates_file(self, tmp_path: pathlib.Path):
        doc = _make_doc()
        out = str(tmp_path / "out.hwp")
        result = udf.render(doc, "hwp", output_path=out)
        assert result is None
        assert pathlib.Path(out).exists()
        assert pathlib.Path(out).stat().st_size > 0

    def test_reparsable(self, tmp_path: pathlib.Path):
        doc = _make_doc()
        out = str(tmp_path / "out.hwp")
        udf.render(doc, "hwp", output_path=out)
        reparsed = udf.parse(out)
        assert len(reparsed.blocks) > 0


class TestRenderToDocx:
    def test_creates_file(self, tmp_path: pathlib.Path):
        doc = _make_doc()
        out = str(tmp_path / "out.docx")
        result = udf.render(doc, "docx", output_path=out)
        assert result is None
        assert pathlib.Path(out).exists()
        assert pathlib.Path(out).stat().st_size > 0


class TestRenderToHwpx:
    def test_creates_file(self, tmp_path: pathlib.Path):
        doc = _make_doc()
        out = str(tmp_path / "out.hwpx")
        result = udf.render(doc, "hwpx", output_path=out)
        assert result is None
        assert pathlib.Path(out).exists()
        assert pathlib.Path(out).stat().st_size > 0


class TestRenderUnsupported:
    def test_raises_on_unknown_format(self):
        doc = _make_doc()
        with pytest.raises(Exception):
            udf.render(doc, "xyz")
