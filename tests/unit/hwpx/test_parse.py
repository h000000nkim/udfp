"""HWPX parser unit tests.

Verifies parsing of HWPX (한글 OOXML) files: block extraction, table structure,
character formatting, page definition, binary data, and verbatim layer.

HWPX 파서 단위 테스트. 블록 추출, 테이블 구조, 글자 서식, 페이지 정의,
바이너리 데이터, verbatim 계층을 검증한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from udf.core.schema import (
    ParagraphBlock,
    TextInline,
)
from udf.parsers.hwpx.parse import parse_hwpx

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "hwpx"


@pytest.fixture
def table_doc():
    return parse_hwpx(str(FIXTURES / "table_text.hwpx"))


@pytest.fixture
def img_doc():
    return parse_hwpx(str(FIXTURES / "tac_img.hwpx"))


@pytest.fixture
def reading_doc():
    return parse_hwpx(str(FIXTURES / "reading_log.hwpx"))


@pytest.fixture
def report_doc():
    return parse_hwpx(str(FIXTURES / "report_form.hwpx"))


class TestBasicParsing:
    """Verify basic parse output structure across HWPX fixtures.

    기본 파싱 결과 구조 검증: source_format, 블록 수, conversion_trace, container.
    """

    def test_source_format(self, table_doc):
        """Assert source_format is 'hwpx' after parsing."""
        assert table_doc.source_format == "hwpx"

    def test_returns_blocks(self, table_doc):
        """Assert table_text.hwpx produces exactly 1 block (a single table).

        table_text.hwpx가 정확히 1개 블록(테이블)을 생성하는지 확인.
        """
        assert len(table_doc.blocks) == 1

    def test_block_count_per_fixture(self, reading_doc, report_doc, img_doc):
        """Assert exact block counts for each fixture to catch silent data loss.

        각 fixture의 정확한 블록 수를 검증하여 데이터 소실을 감지.

        Expected
        --------
        reading_log.hwpx : 59 blocks (including header + footer)
        report_form.hwpx : 3 blocks
        tac_img.hwpx     : >= 100 blocks (large document)
        """
        assert len(reading_doc.blocks) == 59
        assert len(report_doc.blocks) == 3
        assert len(img_doc.blocks) >= 100

    def test_conversion_trace(self, table_doc):
        """Assert conversion trace includes a SHA-256 checksum."""
        assert table_doc.conversion_trace is not None
        assert table_doc.conversion_trace.checksum is not None
        assert len(table_doc.conversion_trace.checksum) == 64

    def test_original_container(self, table_doc):
        """Assert original container is recorded as ZIP format."""
        assert table_doc.original_container is not None
        assert table_doc.original_container.format == "zip"


class TestTableParsing:
    """Verify table structure extraction from HWPX.

    HWPX 테이블 구조 파싱 검증: 행 수, 셀 텍스트, span, vertical align.
    """

    def test_table_block_exists(self, table_doc):
        """Assert at least one TableBlock is parsed."""
        tables = [b for b in table_doc.blocks if b.type == "table"]
        assert len(tables) >= 1

    def test_table_has_rows(self, table_doc):
        """Assert the first table has exactly 3 rows."""
        tbl = next(b for b in table_doc.blocks if b.type == "table")
        assert len(tbl.rows) == 3

    def test_cell_text_extraction(self, table_doc):
        """Assert first cell contains '기부 금액(원, %)' — exact content match.

        첫 번째 셀의 정확한 텍스트 내용을 검증.
        """
        tbl = next(b for b in table_doc.blocks if b.type == "table")
        first_cell = tbl.rows[0].cells[0]
        texts = []
        for para in first_cell.content:
            if hasattr(para, "inlines"):
                for i in para.inlines:
                    if isinstance(i, TextInline):
                        texts.append(i.text)
        assert "기부 금액(원, %)" in " ".join(texts)

    def test_cell_span(self, table_doc):
        """Assert first cell has col_span=4 (merged across 4 columns)."""
        tbl = next(b for b in table_doc.blocks if b.type == "table")
        first_cell = tbl.rows[0].cells[0]
        assert first_cell.col_span == 4

    def test_cell_vertical_align(self, table_doc):
        """Assert first cell vertical alignment is 'middle'."""
        tbl = next(b for b in table_doc.blocks if b.type == "table")
        first_cell = tbl.rows[0].cells[0]
        assert first_cell.format is not None
        assert first_cell.format.vertical_align == "middle"


class TestCharFormatting:
    """Verify character-level formatting extraction from HWPX.

    글자 서식(bold, font_name, font_size) 추출 검증.
    """

    def test_bold_detected(self, reading_doc):
        """Assert at least 1 bold TextInline is found in reading_log.hwpx.

        reading_log.hwpx에서 bold 인라인이 1개 이상 파싱되는지 확인.
        """
        bold_inlines = []
        for b in reading_doc.blocks:
            if hasattr(b, "inlines"):
                for i in b.inlines:
                    if isinstance(i, TextInline) and i.bold:
                        bold_inlines.append(i)
        assert len(bold_inlines) >= 1

    def test_font_name_resolved(self, table_doc):
        """Assert at least one inline has a resolved font name string.

        테이블 셀에서 font_name이 문자열로 해석되는지 확인.
        """
        for b in table_doc.blocks:
            if b.type == "table":
                for row in b.rows:
                    for cell in row.cells:
                        for para in cell.content:
                            if hasattr(para, "inlines"):
                                for i in para.inlines:
                                    if isinstance(i, TextInline) and i.font_name:
                                        assert isinstance(i.font_name, str)
                                        assert len(i.font_name) > 0
                                        return
        pytest.fail("No font_name found in any inline")

    def test_font_size(self, reading_doc):
        """Assert at least one inline has a positive float font_size.

        reading_log.hwpx에서 font_size가 양수 float으로 파싱되는지 확인.
        """
        for b in reading_doc.blocks:
            if hasattr(b, "inlines"):
                for i in b.inlines:
                    if isinstance(i, TextInline) and i.font_size:
                        assert isinstance(i.font_size, float)
                        assert i.font_size > 0
                        return
        pytest.fail("No font_size found")


class TestPageDef:
    """Verify page definition (section, dimensions, margins) from HWPX.

    페이지 정의 검증: 섹션 존재, A4 크기(595.28 x 841.86pt), 여백.
    """

    def test_section_def_exists(self, table_doc):
        """Assert at least one section definition exists in metadata."""
        assert len(table_doc.metadata.sections) >= 1

    def test_a4_page_width(self, table_doc):
        """Assert page width is ~595.28pt (A4).

        A4 용지 너비 595.28pt 검증 (오차 0.1pt 이내).
        """
        sec = table_doc.metadata.sections[0]
        assert isinstance(sec.page_width, float)
        assert abs(sec.page_width - 595.28) < 0.1

    def test_a4_page_height(self, table_doc):
        """Assert page height is ~841.86pt (A4).

        A4 용지 높이 841.86pt 검증 (오차 0.1pt 이내).
        """
        sec = table_doc.metadata.sections[0]
        assert isinstance(sec.page_height, float)
        assert abs(sec.page_height - 841.86) < 0.1

    def test_margins_present(self, table_doc):
        """Assert page margins (left, top) are populated."""
        sec = table_doc.metadata.sections[0]
        assert sec.margins is not None
        assert sec.margins.left is not None
        assert sec.margins.top is not None


class TestBinData:
    """Verify binary data (images) extraction from HWPX ZIP.

    HWPX ZIP 내 바이너리 데이터(이미지) 추출 검증.
    """

    def test_images_extracted(self, img_doc):
        """Assert tac_img.hwpx produces exactly 19 bindata streams."""
        assert img_doc.verbatim is not None
        assert len(img_doc.verbatim.bindata_streams) == 19

    def test_image_names(self, img_doc):
        """Assert 'image1.JPG' is among the extracted bindata names."""
        names = img_doc.verbatim.bindata_streams.keys()
        assert "image1.JPG" in names


class TestVerbatimLayer:
    """Verify verbatim (lossless) layer preservation from HWPX.

    HWPX verbatim 계층 보존 검증: format, section streams, global resources.
    """

    def test_format_hwpx(self, table_doc):
        """Assert verbatim layer format is 'hwpx'."""
        assert table_doc.verbatim is not None
        assert table_doc.verbatim.format == "hwpx"

    def test_section_streams_preserved(self, table_doc):
        """Assert section0.xml and header.xml are preserved in verbatim."""
        assert "section0.xml" in table_doc.verbatim.section_streams
        assert "header.xml" in table_doc.verbatim.section_streams

    def test_section_stream_is_base64(self, table_doc):
        """Assert section stream decodes to valid XML content."""
        import base64
        raw = base64.b64decode(table_doc.verbatim.section_streams["section0.xml"])
        assert raw.startswith(b"<?xml") or raw.startswith(b"<hs:sec")

    def test_global_resources_populated(self, table_doc):
        """Assert char_shapes, para_shapes, and face_names are non-empty.

        글자 모양, 문단 모양, 글꼴 이름이 파싱되었는지 확인.
        """
        gr = table_doc.verbatim.global_resources
        assert len(gr.char_shapes) > 0
        assert len(gr.para_shapes) > 0
        assert len(gr.face_names) > 0


class TestParagraphBlocks:
    """Verify paragraph block extraction and formatting from HWPX.

    문단 블록 추출 및 서식 검증.
    """

    def test_paragraph_format_alignment(self, report_doc):
        """Assert at least one paragraph has a valid alignment value.

        report_form.hwpx에서 alignment가 유효한 값인지 확인.
        """
        for b in report_doc.blocks:
            if isinstance(b, ParagraphBlock) and b.format:
                if b.format.alignment:
                    assert b.format.alignment in ("left", "center", "right", "justify")
                    return
        pytest.fail("No paragraph with alignment found")

    def test_text_extraction(self, report_doc):
        """Assert '미적분' appears in extracted text from report_form.hwpx.

        report_form.hwpx의 텍스트에 '미적분'이 포함되는지 확인.
        """
        texts = []
        for b in report_doc.blocks:
            if isinstance(b, ParagraphBlock):
                for i in b.inlines:
                    if isinstance(i, TextInline):
                        texts.append(i.text)
        full_text = " ".join(texts)
        assert "미적분" in full_text


class TestCLIIntegration:
    """Verify CLI can convert HWPX files.

    CLI가 HWPX 파일을 변환할 수 있는지 확인.
    """

    def test_cli_convert_hwpx(self):
        """Assert CLI convert command returns exit code 0 for HWPX input."""
        from udf.cli import _cmd_convert
        import argparse
        args = argparse.Namespace(
            input=str(FIXTURES / "report_form.hwpx"),
            output=None,
            embed_ids=False,
        )
        rc = _cmd_convert(args)
        assert rc == 0
