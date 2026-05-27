"""PDF 파서 단위 테스트."""

from __future__ import annotations

import itertools
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from udf.core.schema import (
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    TableBlock,
    UdfDocument,
)
from udf.schema import (
    ParagraphBlock as V2ParagraphBlock,
    TextInline as V2TextInline,
    LinkInline as V2LinkInline,
)
from udf.parsers.pdf.parse import (
    _apply_links_to_blocks,
    _extract_links,
    _rects_overlap_link,
    parse_pdf,
)
from udf.parsers.pdf.layout import (
    _ExtractedBlock,
    _detect_columns,
    _detect_footnotes,
    _detect_repeating_content,
    _is_repeating_box,
    _snap,
)
from udf.renderers.md import render_md




FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"


class TestSimpleText:
    @pytest.fixture()
    def doc(self) -> UdfDocument:
        return parse_pdf(str(FIXTURES / "simple_text.pdf"))

    def test_block_count(self, doc: UdfDocument) -> None:
        assert len(doc.blocks) == 3

    def test_heading_detected(self, doc: UdfDocument) -> None:
        assert isinstance(doc.blocks[0], HeadingBlock)
        assert doc.blocks[0].text == "Test Heading"

    def test_paragraphs(self, doc: UdfDocument) -> None:
        assert isinstance(doc.blocks[1], ParagraphBlock)
        assert isinstance(doc.blocks[2], ParagraphBlock)

    def test_metadata(self, doc: UdfDocument) -> None:
        assert doc.source_format == "pdf"
        assert doc.metadata.page_width is not None
        assert doc.metadata.page_height is not None

    def test_page_boundaries(self, doc: UdfDocument) -> None:
        assert len(doc.page_boundaries) == 1
        assert doc.page_boundaries[0].page == 1

    def test_conversion_trace(self, doc: UdfDocument) -> None:
        assert doc.conversion_trace is not None
        assert doc.conversion_trace.checksum is not None
        assert len(doc.conversion_trace.checksum) == 64

    def test_md_render(self, doc: UdfDocument) -> None:
        md = render_md(doc, embed_ids=False)
        assert "# Test Heading" in md
        assert "normal text" in md

    def test_loss_report_exists(self, doc: UdfDocument) -> None:
        assert doc.loss_report is not None
        assert doc.loss_report.is_roundtrip_safe is False

    def test_dropped_features_populated(self, doc: UdfDocument) -> None:
        df = doc.loss_report.dropped_features
        assert len(df) > 0
        assert any("heading" in f for f in df)
        assert any("paragraph_formatting" in f for f in df)
        assert any("font_embedding" in f for f in df)


class TestListItems:
    @pytest.fixture()
    def doc(self) -> UdfDocument:
        return parse_pdf(str(FIXTURES / "list_items.pdf"))

    def test_has_list(self, doc: UdfDocument) -> None:
        lists = [b for b in doc.blocks if isinstance(b, ListBlock)]
        assert len(lists) >= 1

    def test_list_items_count(self, doc: UdfDocument) -> None:
        lst = next(b for b in doc.blocks if isinstance(b, ListBlock))
        assert len(lst.items) == 3

    def test_list_not_ordered(self, doc: UdfDocument) -> None:
        lst = next(b for b in doc.blocks if isinstance(b, ListBlock))
        assert lst.ordered is False

    def test_heading_before_list(self, doc: UdfDocument) -> None:
        heading_idx = next(
            i for i, b in enumerate(doc.blocks) if isinstance(b, HeadingBlock)
        )
        list_idx = next(
            i for i, b in enumerate(doc.blocks) if isinstance(b, ListBlock)
        )
        assert heading_idx < list_idx

    def test_md_render(self, doc: UdfDocument) -> None:
        md = render_md(doc, embed_ids=False)
        assert "- Apples" in md
        assert "- Bananas" in md
        assert "- Cherries" in md


class TestTable:
    @pytest.fixture()
    def doc(self) -> UdfDocument:
        return parse_pdf(str(FIXTURES / "table_simple.pdf"))

    def test_has_table(self, doc: UdfDocument) -> None:
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) == 1

    def test_table_dimensions(self, doc: UdfDocument) -> None:
        tbl = next(b for b in doc.blocks if isinstance(b, TableBlock))
        assert len(tbl.rows) == 3
        assert all(len(row.cells) == 3 for row in tbl.rows)

    def test_table_header_content(self, doc: UdfDocument) -> None:
        tbl = next(b for b in doc.blocks if isinstance(b, TableBlock))
        header_texts = []
        for cell in tbl.rows[0].cells:
            for cb in cell.content:
                if isinstance(cb, ParagraphBlock) and cb.inlines:
                    header_texts.append(cb.inlines[0].text)
        assert header_texts == ["Name", "Age", "City"]

    def test_reading_order(self, doc: UdfDocument) -> None:
        """헤딩이 테이블보다 먼저 나와야 한다."""
        heading_idx = next(
            i for i, b in enumerate(doc.blocks) if isinstance(b, HeadingBlock)
        )
        table_idx = next(
            i for i, b in enumerate(doc.blocks) if isinstance(b, TableBlock)
        )
        assert heading_idx < table_idx

    def test_text_after_table(self, doc: UdfDocument) -> None:
        last = doc.blocks[-1]
        assert isinstance(last, ParagraphBlock)
        text = "".join(i.text for i in last.inlines)
        assert "after the table" in text

    def test_md_render(self, doc: UdfDocument) -> None:
        md = render_md(doc, embed_ids=False)
        assert "<table" in md
        assert "<td>Name</td>" in md
        assert "<td>Alice</td>" in md


class TestPdfMdRoundtrip:
    """PDF→MD 단방향 변환 검증 (PDF는 라운드트립 아님)."""

    def test_all_blocks_have_ids(self) -> None:
        doc = parse_pdf(str(FIXTURES / "simple_text.pdf"))
        for block in doc.blocks:
            assert block.id.startswith("pdf_")

    def test_md_parseable(self) -> None:
        doc = parse_pdf(str(FIXTURES / "simple_text.pdf"))
        md = render_md(doc, embed_ids=True)
        assert "<!-- id:" in md

    def test_heading_levels(self) -> None:
        """24pt vs 12pt body → heading should be level 1."""
        doc = parse_pdf(str(FIXTURES / "simple_text.pdf"))
        h = next(b for b in doc.blocks if isinstance(b, HeadingBlock))
        assert h.level == 1


# ---------------------------------------------------------------------------
# 하이퍼링크 추출 테스트
# ---------------------------------------------------------------------------


class TestExtractLinks:
    def test_extract_links_empty(self) -> None:
        """어노테이션이 없는 PdfReader는 빈 링크 목록을 반환."""
        mock_page = MagicMock()
        mock_page.get.return_value = None  # /Annots 없음
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        result = _extract_links(mock_reader)
        assert result == {1: []}

    def test_rects_overlap_link_true(self) -> None:
        bbox = (100.0, 200.0, 300.0, 250.0)
        link_rect = [150.0, 210.0, 250.0, 240.0]
        assert _rects_overlap_link(bbox, link_rect) is True

    def test_rects_overlap_link_false(self) -> None:
        bbox = (100.0, 200.0, 300.0, 250.0)
        link_rect = [400.0, 500.0, 600.0, 700.0]
        assert _rects_overlap_link(bbox, link_rect) is False

    def test_apply_links_wraps_text_inline(self) -> None:
        """링크 rect와 겹치는 ParagraphBlock의 TextInline이 LinkInline으로 변환."""
        para = V2ParagraphBlock(
            type="paragraph",
            id="pdf_p_1",
            inlines=[V2TextInline(text="click here")],
        )
        eb = _ExtractedBlock(
            block=para,
            bbox=(100.0, 200.0, 300.0, 220.0),
            verbatim_data={},
        )
        page_links = [{"url": "https://example.com", "rect": [100.0, 200.0, 300.0, 220.0]}]
        result = _apply_links_to_blocks([para], [eb], page_links)
        assert len(result) == 1
        assert isinstance(result[0], V2ParagraphBlock)
        assert len(result[0].inlines) == 1
        assert isinstance(result[0].inlines[0], V2LinkInline)
        assert result[0].inlines[0].url == "https://example.com"
        assert result[0].inlines[0].text == "click here"

    def test_apply_links_no_match(self) -> None:
        """링크 rect와 겹치지 않으면 블록 변경 없음."""
        para = V2ParagraphBlock(
            type="paragraph",
            id="pdf_p_1",
            inlines=[V2TextInline(text="no link")],
        )
        eb = _ExtractedBlock(
            block=para,
            bbox=(100.0, 200.0, 300.0, 220.0),
            verbatim_data={},
        )
        page_links = [{"url": "https://example.com", "rect": [500.0, 500.0, 600.0, 520.0]}]
        result = _apply_links_to_blocks([para], [eb], page_links)
        assert isinstance(result[0].inlines[0], V2TextInline)


# ---------------------------------------------------------------------------
# 머리글/바닥글 감지 테스트
# ---------------------------------------------------------------------------


def _make_mock_textbox(text: str, x0: float, y0: float, x1: float, y1: float):
    """테스트용 mock LTTextBox 생성."""
    box = MagicMock()
    box.x0 = x0
    box.y0 = y0
    box.x1 = x1
    box.y1 = y1
    box.get_text.return_value = text + "\n"
    # _extract_spans_from_box를 위해 iter를 빈 리스트로
    box.__iter__ = MagicMock(return_value=iter([]))
    return box


def _make_mock_page(y0: float = 0.0, y1: float = 792.0, x0: float = 0.0, x1: float = 612.0):
    """테스트용 mock LTPage 생성."""
    page = MagicMock()
    page.x0 = x0
    page.y0 = y0
    page.x1 = x1
    page.y1 = y1
    page.__iter__ = MagicMock(return_value=iter([]))
    return page


class TestHeaderFooterDetection:
    def test_no_repeating_single_page(self) -> None:
        """단일 페이지에서는 머리글/바닥글 감지 안 함."""
        page = _make_mock_page()
        box = _make_mock_textbox("Header Text", 100, 770, 300, 790)
        page_data = [(page, [box], 1)]
        result = _detect_repeating_content(page_data)
        assert result == set()

    def test_repeating_header_detected(self) -> None:
        """동일 텍스트가 3페이지 중 2페이지 이상에서 상단에 나타나면 머리글 감지."""
        pages_data = []
        for pnum in range(1, 4):
            page = _make_mock_page()
            # 페이지 상단 (y > 792 - 63.36 = 728.64, 8% margin)
            header_box = _make_mock_textbox("My Document Title", 100, 760, 400, 785)
            body_box = _make_mock_textbox(f"Body text page {pnum}", 100, 400, 400, 420)
            pages_data.append((page, [header_box, body_box], pnum))
        result = _detect_repeating_content(pages_data)
        assert len(result) >= 1
        texts = {text for text, _ in result}
        assert "My Document Title" in texts

    def test_repeating_footer_detected(self) -> None:
        """동일 텍스트가 하단에 반복되면 바닥글 감지."""
        pages_data = []
        for pnum in range(1, 4):
            page = _make_mock_page()
            footer_box = _make_mock_textbox("Page Footer", 100, 10, 300, 30)
            body_box = _make_mock_textbox(f"Body {pnum}", 100, 400, 400, 420)
            pages_data.append((page, [footer_box, body_box], pnum))
        result = _detect_repeating_content(pages_data)
        texts = {text for text, _ in result}
        assert "Page Footer" in texts

    def test_non_repeating_not_detected(self) -> None:
        """각 페이지마다 다른 텍스트는 머리글/바닥글로 감지 안 함."""
        pages_data = []
        for pnum in range(1, 4):
            page = _make_mock_page()
            header_box = _make_mock_textbox(f"Unique Header {pnum}", 100, 770, 400, 790)
            pages_data.append((page, [header_box], pnum))
        result = _detect_repeating_content(pages_data)
        assert result == set()

    def test_is_repeating_box(self) -> None:
        """_is_repeating_box가 반복 세트에 포함된 박스를 올바르게 식별."""
        repeating = {("Header", _snap(777.5, tol=5.0))}
        box = _make_mock_textbox("Header", 100, 770, 300, 785)
        assert _is_repeating_box(box, repeating) is True

        non_match_box = _make_mock_textbox("Other Text", 100, 770, 300, 785)
        assert _is_repeating_box(non_match_box, repeating) is False


# ---------------------------------------------------------------------------
# 각주 감지 테스트
# ---------------------------------------------------------------------------


class TestFootnoteDetection:
    def test_no_separator_no_footnotes(self) -> None:
        """수평 구분선이 없으면 각주 감지 안 함."""
        page = _make_mock_page()
        box = _make_mock_textbox("1. Some footnote text", 72, 30, 400, 50)
        counter = itertools.count(1)
        fn_blocks, excluded = _detect_footnotes([box], page, counter)
        assert fn_blocks == []
        assert excluded == set()

    def test_footnote_regex_matches(self) -> None:
        """하단 텍스트가 숫자로 시작하는 패턴 확인 (함수 내부 로직 간접 테스트)."""
        from udf.parsers.pdf.layout import _FOOTNOTE_RE

        assert _FOOTNOTE_RE.match("1. First footnote") is not None
        assert _FOOTNOTE_RE.match("2) Second footnote") is not None
        assert _FOOTNOTE_RE.match("12 Twelfth footnote") is not None
        assert _FOOTNOTE_RE.match("No number here") is None
        assert _FOOTNOTE_RE.match("abc not a footnote") is None


# ---------------------------------------------------------------------------
# 다단 감지 테스트
# ---------------------------------------------------------------------------


class TestColumnDetection:
    def test_single_column_returns_none(self) -> None:
        """단일 컬럼 레이아웃은 None 반환."""
        page = _make_mock_page()
        boxes = [
            _make_mock_textbox("Line 1", 72, 700, 500, 720),
            _make_mock_textbox("Line 2", 72, 670, 500, 690),
            _make_mock_textbox("Line 3", 72, 640, 500, 660),
            _make_mock_textbox("Line 4", 72, 610, 500, 630),
        ]
        result = _detect_columns(boxes, set(), page)
        assert result is None

    def test_two_columns_detected(self) -> None:
        """좌/우 컬럼이 명확히 구분되면 2-column 감지."""
        page = _make_mock_page()
        # 왼쪽 컬럼: x 72~280
        left_boxes = [
            _make_mock_textbox("Left 1", 72, 700, 280, 720),
            _make_mock_textbox("Left 2", 72, 670, 280, 690),
            _make_mock_textbox("Left 3", 72, 640, 280, 660),
        ]
        # 오른쪽 컬럼: x 330~540 (간격 50pt > 20pt threshold)
        right_boxes = [
            _make_mock_textbox("Right 1", 330, 700, 540, 720),
            _make_mock_textbox("Right 2", 330, 670, 540, 690),
            _make_mock_textbox("Right 3", 330, 640, 540, 660),
        ]
        all_boxes = left_boxes + right_boxes
        result = _detect_columns(all_boxes, set(), page)
        assert result is not None
        assert len(result) == 2
        assert result[0].x_max < result[1].x_min

    def test_too_few_boxes_returns_none(self) -> None:
        """박스가 3개 이하면 컬럼 감지 안 함."""
        page = _make_mock_page()
        boxes = [
            _make_mock_textbox("A", 72, 700, 200, 720),
            _make_mock_textbox("B", 400, 700, 540, 720),
        ]
        result = _detect_columns(boxes, set(), page)
        assert result is None

    def test_excluded_indices_respected(self) -> None:
        """excluded 인덱스의 박스는 컬럼 감지에서 제외.
        """
        page = _make_mock_page()
        boxes = [
            _make_mock_textbox("Left 1", 72, 700, 280, 720),
            _make_mock_textbox("Left 2", 72, 670, 280, 690),
            _make_mock_textbox("Right 1", 330, 700, 540, 720),
            _make_mock_textbox("Right 2", 330, 670, 540, 690),
            _make_mock_textbox("Right 3", 330, 640, 540, 660),
        ]
        # 왼쪽 박스 하나를 제외하면 left가 1개뿐 → 컬럼 감지 안 함
        result = _detect_columns(boxes, {0}, page)
        assert result is None


class TestPdfErrorHandling:
    """Verify parse_pdf raises on invalid inputs.

    잘못된 입력(존재하지 않는 파일, 빈 파일, 손상된 파일)에 대한 에러 처리 검증.
    """

    def test_nonexistent_file(self) -> None:
        """Assert FileNotFoundError for a path that does not exist.

        존재하지 않는 경로에 대해 FileNotFoundError 발생 확인.

        Asserts
        -------
        - FileNotFoundError is raised.
        """
        with pytest.raises(FileNotFoundError):
            parse_pdf("/tmp/nonexistent_pdf_file_99.pdf")

    def test_empty_file(self, tmp_path: Path) -> None:
        """Assert an exception for a zero-byte file.

        0바이트 파일 파싱 시 예외 발생 확인.

        Asserts
        -------
        - Some exception is raised (pdfminer cannot parse empty input).
        """
        empty = tmp_path / "empty.pdf"
        empty.write_bytes(b"")
        with pytest.raises(Exception):
            parse_pdf(str(empty))

    def test_corrupt_file(self, tmp_path: Path) -> None:
        """Assert an exception for a file with non-PDF content.

        PDF가 아닌 바이트 내용을 가진 파일 파싱 시 예외 발생 확인.

        Asserts
        -------
        - Some exception is raised (invalid PDF magic bytes).
        """
        corrupt = tmp_path / "corrupt.pdf"
        corrupt.write_bytes(b"this is not a pdf file at all")
        with pytest.raises(Exception):
            parse_pdf(str(corrupt))
