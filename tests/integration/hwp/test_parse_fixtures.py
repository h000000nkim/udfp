"""실제 HWP fixture 파일 통합 파싱 테스트"""

from __future__ import annotations

import pathlib

import pytest

from udf.parsers.hwp.parse import parse_hwp
from udf.core.schema import HeadingBlock, ParagraphBlock, TableBlock, TextInline

FIXTURES = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "hwp"


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


def _text_of(doc, block_idx: int) -> str:
    block = doc.blocks[block_idx]
    if isinstance(block, ParagraphBlock):
        return "".join(i.text for i in block.inlines if hasattr(i, "text"))
    return ""


def _all_text(doc) -> list[str]:
    texts = []
    for block in doc.blocks:
        if isinstance(block, ParagraphBlock):
            t = "".join(i.text for i in block.inlines if hasattr(i, "text"))
            texts.append(t)
    return texts


class TestAllFixturesParse:
    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f02_char_format.hwp",
            "f03_para_align.hwp",
            "f04_simple_table.hwp",
            "f05_table_cell_text.hwp",
            "f06_multiline.hwp",
            "f07_hangul_latin.hwp",
            "f08_empty_paras.hwp",
            "f09_heading_h1h2.hwp",
            "f10_inline_mixed.hwp",
            "f11_para_align_4.hwp",
            "f12_heading_h1h4.hwp",
            "f13_pure_hangul.hwp",
            "f14_multilang_format.hwp",
            "plain_text.hwp",
            "paragraph_styles.hwp",
        ],
    )
    def test_parses_without_error(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        assert doc is not None
        assert doc.source_format == "hwp"

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f02_char_format.hwp",
            "f03_para_align.hwp",
            "f04_simple_table.hwp",
            "f05_table_cell_text.hwp",
            "f06_multiline.hwp",
            "f07_hangul_latin.hwp",
            "f08_empty_paras.hwp",
            "f09_heading_h1h2.hwp",
            "f10_inline_mixed.hwp",
            "f11_para_align_4.hwp",
            "f12_heading_h1h4.hwp",
            "f13_pure_hangul.hwp",
            "f14_multilang_format.hwp",
        ],
    )
    def test_section_streams_stored(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        assert doc.verbatim is not None
        assert "Section0" in doc.verbatim.section_streams
        assert len(doc.verbatim.section_streams["Section0"]) > 0

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f02_char_format.hwp",
            "f03_para_align.hwp",
            "f06_multiline.hwp",
            "f07_hangul_latin.hwp",
        ],
    )
    def test_has_paragraph_blocks(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        para_blocks = [b for b in doc.blocks if isinstance(b, ParagraphBlock)]
        assert len(para_blocks) >= 1


class TestF01PlainText:
    def test_text_content(self) -> None:
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        texts = _all_text(doc)
        # 최소 3개 텍스트 단락
        non_empty = [t for t in texts if t.strip()]
        assert len(non_empty) >= 3

    def test_text_values(self) -> None:
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        texts = [t for t in _all_text(doc) if t.strip()]
        assert any("첫 번째 단락" in t for t in texts)
        assert any("두 번째 단락" in t for t in texts)
        assert any("세 번째 단락" in t for t in texts)

    def test_verbatim_offsets_stored(self) -> None:
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        assert doc.verbatim is not None
        para_blocks = [b for b in doc.blocks if isinstance(b, ParagraphBlock)]
        for pb in para_blocks:
            if pb.verbatim_ref and pb.verbatim_ref in doc.verbatim.blocks:
                vb = doc.verbatim.blocks[pb.verbatim_ref]
                assert vb.decoded is not None
                assert "ph_offset" in vb.decoded
                assert "section" in vb.decoded


class TestF02CharFormat:
    def test_bold_formatting(self) -> None:
        doc = parse_hwp(_fixture("f02_char_format.hwp"))
        all_inlines = [
            inline
            for b in doc.blocks
            if isinstance(b, ParagraphBlock)
            for inline in b.inlines
            if hasattr(inline, "text")
        ]
        bold_inlines = [i for i in all_inlines if getattr(i, "bold", None)]
        assert len(bold_inlines) >= 1, "볼드 텍스트가 없음"

    def test_italic_formatting(self) -> None:
        doc = parse_hwp(_fixture("f02_char_format.hwp"))
        all_inlines = [
            inline
            for b in doc.blocks
            if isinstance(b, ParagraphBlock)
            for inline in b.inlines
            if hasattr(inline, "text")
        ]
        italic_inlines = [i for i in all_inlines if getattr(i, "italic", None)]
        assert len(italic_inlines) >= 1, "이탤릭 텍스트가 없음"


class TestF03ParaAlign:
    def test_alignments_present(self) -> None:
        doc = parse_hwp(_fixture("f03_para_align.hwp"))
        formats = [
            b.format for b in doc.blocks if isinstance(b, ParagraphBlock) and b.format
        ]
        alignments = {f.alignment for f in formats if f.alignment}
        # 최소 2가지 정렬 있어야 함
        assert len(alignments) >= 2


class TestF04SimpleTable:
    def test_table_exists(self) -> None:
        doc = parse_hwp(_fixture("f04_simple_table.hwp"))
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) >= 1

    def test_table_2x3(self) -> None:
        doc = parse_hwp(_fixture("f04_simple_table.hwp"))
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        tbl = tables[0]
        assert len(tbl.rows) == 2
        assert all(len(r.cells) == 3 for r in tbl.rows)


class TestF05TableCellText:
    def test_cell_text_parsed(self) -> None:
        doc = parse_hwp(_fixture("f05_table_cell_text.hwp"))
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) >= 1
        tbl = tables[0]
        # 헤더 행에 "이름", "나이", "직업"이 있어야 함
        all_cell_texts: list[str] = []
        for row in tbl.rows:
            for cell in row.cells:
                for blk in cell.content:
                    if isinstance(blk, ParagraphBlock):
                        t = "".join(i.text for i in blk.inlines if hasattr(i, "text"))
                        all_cell_texts.append(t)
        assert any("이름" in t for t in all_cell_texts)
        assert any("나이" in t for t in all_cell_texts)
        assert any("홍길동" in t for t in all_cell_texts)


class TestF06Multiline:
    def test_many_paragraphs(self) -> None:
        doc = parse_hwp(_fixture("f06_multiline.hwp"))
        para_blocks = [b for b in doc.blocks if isinstance(b, ParagraphBlock)]
        assert len(para_blocks) >= 25  # 30개 단락 + 일부 secd/cold

    def test_numbered_paragraphs(self) -> None:
        doc = parse_hwp(_fixture("f06_multiline.hwp"))
        texts = [t for t in _all_text(doc) if "단락" in t]
        assert len(texts) >= 25


class TestF07HangulLatin:
    def test_mixed_text(self) -> None:
        doc = parse_hwp(_fixture("f07_hangul_latin.hwp"))
        all_text = " ".join(_all_text(doc))
        assert "한글" in all_text or "가나다" in all_text
        assert "English" in all_text or "quick" in all_text


class TestF08EmptyParas:
    def test_empty_paragraphs_exist(self) -> None:
        doc = parse_hwp(_fixture("f08_empty_paras.hwp"))
        para_blocks = [b for b in doc.blocks if isinstance(b, ParagraphBlock)]
        empty = [
            p for p in para_blocks if not any(getattr(i, "text", "") for i in p.inlines)
        ]
        assert len(empty) >= 1  # 빈 단락 최소 1개


class TestF09HeadingH1H2:
    def test_heading_blocks_exist(self) -> None:
        doc = parse_hwp(_fixture("f09_heading_h1h2.hwp"))
        headings = [b for b in doc.blocks if isinstance(b, HeadingBlock)]
        assert len(headings) >= 2

    def test_heading_levels(self) -> None:
        doc = parse_hwp(_fixture("f09_heading_h1h2.hwp"))
        headings = [b for b in doc.blocks if isinstance(b, HeadingBlock)]
        levels = {h.level for h in headings}
        assert 1 in levels


class TestF10InlineMixed:
    def test_bold_italic_coexist(self) -> None:
        doc = parse_hwp(_fixture("f10_inline_mixed.hwp"))
        all_inlines = [
            i for b in doc.blocks if isinstance(b, ParagraphBlock)
            for i in b.inlines if isinstance(i, TextInline)
        ]
        has_bold = any(i.bold for i in all_inlines)
        has_italic = any(i.italic for i in all_inlines)
        assert has_bold, "볼드 인라인이 없음"
        assert has_italic, "이탤릭 인라인이 없음"


class TestF11ParaAlign4:
    def test_four_alignments(self) -> None:
        doc = parse_hwp(_fixture("f11_para_align_4.hwp"))
        formats = [
            b.format for b in doc.blocks
            if isinstance(b, ParagraphBlock) and b.format
        ]
        alignments = {f.alignment for f in formats if f.alignment}
        assert alignments >= {"left", "center", "right", "justify"}


class TestF12HeadingH1H4:
    def test_heading_levels_1_to_4(self) -> None:
        doc = parse_hwp(_fixture("f12_heading_h1h4.hwp"))
        headings = [b for b in doc.blocks if isinstance(b, HeadingBlock)]
        levels = {h.level for h in headings}
        assert levels >= {1, 2, 3, 4}


class TestF13PureHangul:
    def test_hangul_text_intact(self) -> None:
        doc = parse_hwp(_fixture("f13_pure_hangul.hwp"))
        all_text = " ".join(_all_text(doc))
        assert "UDFP" in all_text or "문서" in all_text


class TestF14MultilangFormat:
    def test_multilang_text(self) -> None:
        doc = parse_hwp(_fixture("f14_multilang_format.hwp"))
        all_text = " ".join(_all_text(doc))
        assert "한글" in all_text or "가나다" in all_text
        assert "English" in all_text or "quick" in all_text
