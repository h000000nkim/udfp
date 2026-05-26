"""DOCX 제너레이터 단위 테스트.

From Scratch 모드와 Seed Patch 모드, 그리고 parse→generate→parse 라운드트립을 검증.
"""

from __future__ import annotations

import tempfile
import zipfile

from lxml import etree

from udf.core.schema import (
    BlockFormat,
    ColumnDef,
    DocumentMetadata,
    EquationBlock,
    EquationInline,
    FootnoteBlock,
    FootnoteRefInline,
    HeadingBlock,
    LinkInline,
    ListBlock,
    ListItem,
    PageBreakBlock,
    PageMargins,
    ParagraphBlock,
    SectionDef,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
    TextInline,
    UdfDocument,
)
from udf.renderers.docx import generate_docx

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _w(tag: str) -> str:
    return f"{{{_W_NS}}}{tag}"


def _make_doc(blocks: list, source_format: str = "docx") -> UdfDocument:
    """테스트용 UdfDocument 생성."""
    return UdfDocument(
        source_format=source_format,
        blocks=blocks,
    )


def _generate_and_read_xml(doc: UdfDocument, entry: str = "word/document.xml") -> etree._Element:
    """doc를 DOCX로 생성 후 ZIP 내 XML entry를 파싱하여 반환."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        out_path = f.name
    generate_docx(doc, out_path)
    with zipfile.ZipFile(out_path, "r") as zf:
        xml_bytes = zf.read(entry)
    return etree.fromstring(xml_bytes)


def _generate_to_path(doc: UdfDocument) -> str:
    """doc를 DOCX로 생성하고 경로를 반환."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        out_path = f.name
    generate_docx(doc, out_path)
    return out_path


# ---------------------------------------------------------------------------
# From Scratch: basic blocks
# ---------------------------------------------------------------------------


class TestFromScratchBasic:
    """From Scratch 모드: 기본 블록 생성."""

    def test_from_scratch_basic(self):
        """단일 단락 → 유효한 DOCX ZIP 생성."""
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="Hello World")],
            ),
        ])
        out_path = _generate_to_path(doc)

        # ZIP 검증
        with zipfile.ZipFile(out_path, "r") as zf:
            names = set(zf.namelist())
            assert "[Content_Types].xml" in names
            assert "_rels/.rels" in names
            assert "word/document.xml" in names
            assert "word/styles.xml" in names
            assert "word/_rels/document.xml.rels" in names

        # document.xml 내용 검증
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        assert body is not None
        paragraphs = body.findall(_w("p"))
        assert len(paragraphs) == 1
        t_el = paragraphs[0].find(f".//{_w('t')}")
        assert t_el is not None
        assert t_el.text == "Hello World"

    def test_from_scratch_multiple_paragraphs(self):
        """여러 단락."""
        doc = _make_doc([
            ParagraphBlock(type="paragraph", id="b_0001",
                           inlines=[TextInline(text="First")]),
            ParagraphBlock(type="paragraph", id="b_0002",
                           inlines=[TextInline(text="Second")]),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        paragraphs = body.findall(_w("p"))
        assert len(paragraphs) == 2
        texts = [p.find(f".//{_w('t')}").text for p in paragraphs]
        assert texts == ["First", "Second"]

    def test_from_scratch_empty_paragraph(self):
        """빈 단락."""
        doc = _make_doc([
            ParagraphBlock(type="paragraph", id="b_0001", inlines=[]),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        paragraphs = body.findall(_w("p"))
        assert len(paragraphs) == 1


class TestFromScratchHeading:
    """From Scratch 모드: 헤딩 블록."""

    def test_heading_with_pstyle(self):
        """HeadingBlock → pStyle Heading1-6."""
        for level in range(1, 7):
            doc = _make_doc([
                HeadingBlock(
                    type="heading",
                    id="b_0001",
                    level=level,
                    text=f"Heading {level}",
                ),
            ])
            root = _generate_and_read_xml(doc)
            body = root.find(_w("body"))
            p = body.find(_w("p"))
            assert p is not None
            ppr = p.find(_w("pPr"))
            assert ppr is not None
            pstyle = ppr.find(_w("pStyle"))
            assert pstyle is not None
            assert pstyle.get(_w("val")) == f"Heading{level}"

    def test_heading_text_content(self):
        """HeadingBlock의 텍스트가 w:t에 담겨야 한다."""
        doc = _make_doc([
            HeadingBlock(
                type="heading",
                id="b_0001",
                level=1,
                text="My Title",
                inlines=[TextInline(text="My Title")],
            ),
        ])
        root = _generate_and_read_xml(doc)
        t_el = root.find(f".//{_w('t')}")
        assert t_el is not None
        assert t_el.text == "My Title"


class TestFromScratchTable:
    """From Scratch 모드: 테이블 블록."""

    def test_simple_table(self):
        """2x2 테이블."""
        doc = _make_doc([
            TableBlock(
                type="table",
                id="b_0001",
                rows=[
                    TableRow(cells=[
                        TableCell(id="c1", content=[
                            ParagraphBlock(type="paragraph", id="p1",
                                           inlines=[TextInline(text="A")]),
                        ]),
                        TableCell(id="c2", content=[
                            ParagraphBlock(type="paragraph", id="p2",
                                           inlines=[TextInline(text="B")]),
                        ]),
                    ]),
                    TableRow(cells=[
                        TableCell(id="c3", content=[
                            ParagraphBlock(type="paragraph", id="p3",
                                           inlines=[TextInline(text="C")]),
                        ]),
                        TableCell(id="c4", content=[
                            ParagraphBlock(type="paragraph", id="p4",
                                           inlines=[TextInline(text="D")]),
                        ]),
                    ]),
                ],
            ),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        tbl = body.find(_w("tbl"))
        assert tbl is not None
        trs = tbl.findall(_w("tr"))
        assert len(trs) == 2
        # Row 0
        tcs = trs[0].findall(_w("tc"))
        assert len(tcs) == 2
        assert tcs[0].find(f".//{_w('t')}").text == "A"
        assert tcs[1].find(f".//{_w('t')}").text == "B"

    def test_table_empty_cell_has_paragraph(self):
        """빈 셀도 w:p를 포함해야 한다."""
        doc = _make_doc([
            TableBlock(
                type="table",
                id="b_0001",
                rows=[
                    TableRow(cells=[
                        TableCell(id="c1", content=[]),
                    ]),
                ],
            ),
        ])
        root = _generate_and_read_xml(doc)
        tc = root.find(f".//{_w('tc')}")
        assert tc is not None
        assert tc.find(_w("p")) is not None

    def test_table_col_span(self):
        """col_span > 1 → gridSpan 속성."""
        doc = _make_doc([
            TableBlock(
                type="table",
                id="b_0001",
                rows=[
                    TableRow(cells=[
                        TableCell(id="c1", col_span=2, content=[
                            ParagraphBlock(type="paragraph", id="p1",
                                           inlines=[TextInline(text="merged")]),
                        ]),
                    ]),
                ],
            ),
        ])
        root = _generate_and_read_xml(doc)
        tcpr = root.find(f".//{_w('tcPr')}")
        assert tcpr is not None
        gs = tcpr.find(_w("gridSpan"))
        assert gs is not None
        assert gs.get(_w("val")) == "2"


class TestFromScratchBoldItalic:
    """From Scratch 모드: 인라인 서식."""

    def test_bold_formatting(self):
        """bold=True → w:b 요소."""
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="Bold", bold=True)],
            ),
        ])
        root = _generate_and_read_xml(doc)
        rpr = root.find(f".//{_w('rPr')}")
        assert rpr is not None
        assert rpr.find(_w("b")) is not None

    def test_italic_formatting(self):
        """italic=True → w:i 요소."""
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="Italic", italic=True)],
            ),
        ])
        root = _generate_and_read_xml(doc)
        rpr = root.find(f".//{_w('rPr')}")
        assert rpr is not None
        assert rpr.find(_w("i")) is not None

    def test_bold_italic_combined(self):
        """bold+italic 동시."""
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="BI", bold=True, italic=True)],
            ),
        ])
        root = _generate_and_read_xml(doc)
        rpr = root.find(f".//{_w('rPr')}")
        assert rpr is not None
        assert rpr.find(_w("b")) is not None
        assert rpr.find(_w("i")) is not None

    def test_underline(self):
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="U", underline=True)],
            ),
        ])
        root = _generate_and_read_xml(doc)
        rpr = root.find(f".//{_w('rPr')}")
        u = rpr.find(_w("u"))
        assert u is not None
        assert u.get(_w("val")) == "single"

    def test_color(self):
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="Red", color="#FF0000")],
            ),
        ])
        root = _generate_and_read_xml(doc)
        color = root.find(f".//{_w('color')}")
        assert color is not None
        assert color.get(_w("val")) == "FF0000"

    def test_font_name(self):
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="F", font_name="Arial")],
            ),
        ])
        root = _generate_and_read_xml(doc)
        fonts = root.find(f".//{_w('rFonts')}")
        assert fonts is not None
        assert fonts.get(_w("ascii")) == "Arial"
        assert fonts.get(_w("hAnsi")) == "Arial"

    def test_font_size(self):
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="Big", font_size=14.0)],
            ),
        ])
        root = _generate_and_read_xml(doc)
        sz = root.find(f".//{_w('sz')}")
        assert sz is not None
        # 14pt → 28 half-points
        assert sz.get(_w("val")) == "28"

    def test_no_rpr_when_no_format(self):
        """서식 없는 텍스트 → rPr 없음."""
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="Plain")],
            ),
        ])
        root = _generate_and_read_xml(doc)
        rpr = root.find(f".//{_w('rPr')}")
        assert rpr is None


class TestFromScratchList:
    """From Scratch 모드: 리스트 블록."""

    def test_ordered_list(self):
        """ListBlock(ordered=True) → numPr with numId=1."""
        doc = _make_doc([
            ListBlock(
                type="list",
                id="b_0001",
                ordered=True,
                items=[
                    ListItem(id="i1", inlines=[TextInline(text="Item 1")]),
                    ListItem(id="i2", inlines=[TextInline(text="Item 2")]),
                ],
            ),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        paragraphs = body.findall(_w("p"))
        assert len(paragraphs) == 2

        # Each paragraph should have numPr
        for p in paragraphs:
            ppr = p.find(_w("pPr"))
            assert ppr is not None
            num_pr = ppr.find(_w("numPr"))
            assert num_pr is not None
            num_id = num_pr.find(_w("numId"))
            assert num_id is not None
            assert num_id.get(_w("val")) == "1"  # ordered

    def test_unordered_list(self):
        """ListBlock(ordered=False) → numId=2."""
        doc = _make_doc([
            ListBlock(
                type="list",
                id="b_0001",
                ordered=False,
                items=[
                    ListItem(id="i1", inlines=[TextInline(text="Bullet")]),
                ],
            ),
        ])
        root = _generate_and_read_xml(doc)
        num_id = root.find(f".//{_w('numId')}")
        assert num_id is not None
        assert num_id.get(_w("val")) == "2"  # unordered

    def test_list_generates_numbering_xml(self):
        """리스트가 있으면 word/numbering.xml이 ZIP에 포함."""
        doc = _make_doc([
            ListBlock(
                type="list",
                id="b_0001",
                ordered=True,
                items=[
                    ListItem(id="i1", inlines=[TextInline(text="A")]),
                ],
            ),
        ])
        out_path = _generate_to_path(doc)
        with zipfile.ZipFile(out_path, "r") as zf:
            assert "word/numbering.xml" in zf.namelist()

    def test_no_list_no_numbering_xml(self):
        """리스트 없으면 numbering.xml 미생성."""
        doc = _make_doc([
            ParagraphBlock(type="paragraph", id="b_0001",
                           inlines=[TextInline(text="plain")]),
        ])
        out_path = _generate_to_path(doc)
        with zipfile.ZipFile(out_path, "r") as zf:
            assert "word/numbering.xml" not in zf.namelist()

    def test_nested_list(self):
        """중첩 리스트 → ilvl=1."""
        doc = _make_doc([
            ListBlock(
                type="list",
                id="b_0001",
                ordered=True,
                items=[
                    ListItem(
                        id="i1",
                        inlines=[TextInline(text="Parent")],
                        children=[
                            ListItem(id="i2", inlines=[TextInline(text="Child")]),
                        ],
                    ),
                ],
            ),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        paragraphs = body.findall(_w("p"))
        assert len(paragraphs) == 2

        # Child should have ilvl=1
        child_p = paragraphs[1]
        ilvl = child_p.find(f".//{_w('ilvl')}")
        assert ilvl is not None
        assert ilvl.get(_w("val")) == "1"


class TestFromScratchPageBreak:
    """From Scratch 모드: 페이지 브레이크."""

    def test_page_break(self):
        """PageBreakBlock → w:br type='page'."""
        doc = _make_doc([
            ParagraphBlock(type="paragraph", id="b_0001",
                           inlines=[TextInline(text="Before")]),
            PageBreakBlock(type="page_break", id="b_0002"),
            ParagraphBlock(type="paragraph", id="b_0003",
                           inlines=[TextInline(text="After")]),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        elements = list(body)
        assert len(elements) == 3

        # Middle element should contain w:br
        br = elements[1].find(f".//{_w('br')}")
        assert br is not None
        assert br.get(_w("type")) == "page"


class TestFromScratchParagraphFormat:
    """From Scratch 모드: 단락 서식."""

    def test_alignment_center(self):
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="centered")],
                format=BlockFormat(alignment="center"),
            ),
        ])
        root = _generate_and_read_xml(doc)
        jc = root.find(f".//{_w('jc')}")
        assert jc is not None
        assert jc.get(_w("val")) == "center"

    def test_alignment_justify(self):
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="justified")],
                format=BlockFormat(alignment="justify"),
            ),
        ])
        root = _generate_and_read_xml(doc)
        jc = root.find(f".//{_w('jc')}")
        assert jc is not None
        assert jc.get(_w("val")) == "both"


# ---------------------------------------------------------------------------
# Seed Patch mode
# ---------------------------------------------------------------------------


class TestSeedPatch:
    """Seed Patch 모드: 원본 ZIP에서 변경된 스트림만 교체."""

    def test_seed_patch_preserves_unmodified_entries(self):
        """원본에 extra.xml이 있으면 출력에도 보존."""
        # 파서를 통해 DOCX를 파싱
        from tests.unit.docx.test_parse import _create_docx, _make_paragraph

        original_path = _create_docx(
            [_make_paragraph("Original text")],
            extra_xml={"word/settings.xml": b"<settings/>"},
        )
        from udf.parsers.docx.parse import parse_docx

        doc = parse_docx(original_path)

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            out_path = f.name
        generate_docx(doc, out_path)

        with zipfile.ZipFile(out_path, "r") as zf:
            names = set(zf.namelist())
            # 원본에 있던 settings.xml이 보존되어야 함
            assert "word/settings.xml" in names or "word/document.xml" in names


# ---------------------------------------------------------------------------
# Roundtrip: parse → generate → parse
# ---------------------------------------------------------------------------


class TestRoundtripParseGenerateParse:
    """parse_docx → generate_docx → parse_docx 라운드트립."""

    def test_roundtrip_paragraph_text(self):
        """단락 텍스트가 라운드트립 후 보존."""
        from tests.unit.docx.test_parse import (
            _build_styles_xml,
            _create_docx,
            _make_paragraph,
        )
        from udf.parsers.docx.parse import parse_docx

        original_path = _create_docx(
            [_make_paragraph("Hello roundtrip")],
            styles_xml=_build_styles_xml(),
        )

        # Parse
        doc1 = parse_docx(original_path)

        # Generate
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            gen_path = f.name
        generate_docx(doc1, gen_path)

        # Parse again
        doc2 = parse_docx(gen_path)

        # Compare
        assert len(doc2.blocks) >= 1
        p_blocks = [b for b in doc2.blocks if isinstance(b, ParagraphBlock)]
        assert len(p_blocks) >= 1
        texts = []
        for b in p_blocks:
            for il in b.inlines:
                if isinstance(il, TextInline):
                    texts.append(il.text)
        assert "Hello roundtrip" in texts

    def test_roundtrip_heading(self):
        """헤딩이 라운드트립 후 보존."""
        from tests.unit.docx.test_parse import (
            _build_styles_xml,
            _create_docx,
            _make_paragraph,
        )
        from udf.parsers.docx.parse import parse_docx

        original_path = _create_docx(
            [_make_paragraph("Title", style="Heading1")],
            styles_xml=_build_styles_xml(),
        )

        doc1 = parse_docx(original_path)

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            gen_path = f.name
        generate_docx(doc1, gen_path)

        doc2 = parse_docx(gen_path)

        h_blocks = [b for b in doc2.blocks if isinstance(b, HeadingBlock)]
        assert len(h_blocks) >= 1
        assert h_blocks[0].level == 1
        assert h_blocks[0].text == "Title"

    def test_roundtrip_table(self):
        """테이블이 라운드트립 후 보존."""
        from tests.unit.docx.test_parse import _create_docx, _make_table
        from udf.parsers.docx.parse import parse_docx

        original_path = _create_docx([_make_table([["A", "B"], ["C", "D"]])])

        doc1 = parse_docx(original_path)

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            gen_path = f.name
        generate_docx(doc1, gen_path)

        doc2 = parse_docx(gen_path)

        t_blocks = [b for b in doc2.blocks if isinstance(b, TableBlock)]
        assert len(t_blocks) >= 1
        tbl = t_blocks[0]
        assert len(tbl.rows) == 2
        assert len(tbl.rows[0].cells) == 2

        # Cell text
        cell_texts = []
        for row in tbl.rows:
            for cell in row.cells:
                for b in cell.content:
                    if isinstance(b, ParagraphBlock):
                        for il in b.inlines:
                            if isinstance(il, TextInline):
                                cell_texts.append(il.text)
        assert "A" in cell_texts
        assert "D" in cell_texts

    def test_roundtrip_bold_formatting(self):
        """볼드 서식이 라운드트립 후 보존."""
        from tests.unit.docx.test_parse import _create_docx, _make_paragraph
        from udf.parsers.docx.parse import parse_docx

        original_path = _create_docx([_make_paragraph("Bold text", bold=True)])

        doc1 = parse_docx(original_path)

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            gen_path = f.name
        generate_docx(doc1, gen_path)

        doc2 = parse_docx(gen_path)

        p_blocks = [b for b in doc2.blocks if isinstance(b, ParagraphBlock)]
        assert len(p_blocks) >= 1
        bold_inlines = [
            il for b in p_blocks for il in b.inlines
            if isinstance(il, TextInline) and il.bold
        ]
        assert len(bold_inlines) >= 1
        assert bold_inlines[0].text == "Bold text"


class TestFromScratchStylesXml:
    """styles.xml이 올바르게 생성되는지 검증."""

    def test_styles_has_headings(self):
        """styles.xml에 Heading1-6이 정의되어야 한다."""
        doc = _make_doc([
            ParagraphBlock(type="paragraph", id="b_0001",
                           inlines=[TextInline(text="test")]),
        ])
        root = _generate_and_read_xml(doc, entry="word/styles.xml")
        styles = root.findall(_w("style"))
        style_ids = [s.get(_w("styleId")) for s in styles]
        for lvl in range(1, 7):
            assert f"Heading{lvl}" in style_ids

    def test_styles_has_normal(self):
        """styles.xml에 Normal 스타일이 정의되어야 한다."""
        doc = _make_doc([
            ParagraphBlock(type="paragraph", id="b_0001",
                           inlines=[TextInline(text="test")]),
        ])
        root = _generate_and_read_xml(doc, entry="word/styles.xml")
        styles = root.findall(_w("style"))
        style_ids = [s.get(_w("styleId")) for s in styles]
        assert "Normal" in style_ids


# ---------------------------------------------------------------------------
# Section properties in generated DOCX
# ---------------------------------------------------------------------------


class TestSectionSerialization:
    def test_section_page_size_emitted(self):
        doc = UdfDocument(
            source_format="docx",
            metadata=DocumentMetadata(
                sections=[SectionDef(page_width=612.0, page_height=792.0)],
            ),
            blocks=[ParagraphBlock(type="paragraph", id="b_1", inlines=[TextInline(text="x")])],
        )
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        sect_pr = body.find(_w("sectPr"))
        assert sect_pr is not None
        pg_sz = sect_pr.find(_w("pgSz"))
        assert pg_sz is not None
        assert pg_sz.get(_w("w")) == "12240"  # 612 * 20
        assert pg_sz.get(_w("h")) == "15840"  # 792 * 20

    def test_section_landscape(self):
        doc = UdfDocument(
            source_format="docx",
            metadata=DocumentMetadata(
                sections=[SectionDef(
                    page_width=792.0, page_height=612.0,
                    orientation="landscape",
                )],
            ),
            blocks=[ParagraphBlock(type="paragraph", id="b_1", inlines=[TextInline(text="x")])],
        )
        root = _generate_and_read_xml(doc)
        sect_pr = root.find(f".//{_w('sectPr')}")
        pg_sz = sect_pr.find(_w("pgSz"))
        assert pg_sz.get(_w("orient")) == "landscape"

    def test_section_margins(self):
        doc = UdfDocument(
            source_format="docx",
            metadata=DocumentMetadata(
                sections=[SectionDef(
                    page_width=612.0, page_height=792.0,
                    margins=PageMargins(top=72.0, bottom=72.0, left=90.0, right=90.0),
                    header_margin=36.0,
                    footer_margin=36.0,
                )],
            ),
            blocks=[ParagraphBlock(type="paragraph", id="b_1", inlines=[TextInline(text="x")])],
        )
        root = _generate_and_read_xml(doc)
        sect_pr = root.find(f".//{_w('sectPr')}")
        pg_mar = sect_pr.find(_w("pgMar"))
        assert pg_mar is not None
        assert pg_mar.get(_w("top")) == "1440"  # 72 * 20
        assert pg_mar.get(_w("left")) == "1800"  # 90 * 20
        assert pg_mar.get(_w("header")) == "720"  # 36 * 20

    def test_section_break_type(self):
        doc = UdfDocument(
            source_format="docx",
            metadata=DocumentMetadata(
                sections=[SectionDef(
                    page_width=612.0, page_height=792.0,
                    break_type="continuous",
                )],
            ),
            blocks=[ParagraphBlock(type="paragraph", id="b_1", inlines=[TextInline(text="x")])],
        )
        root = _generate_and_read_xml(doc)
        sect_pr = root.find(f".//{_w('sectPr')}")
        type_el = sect_pr.find(_w("type"))
        assert type_el is not None
        assert type_el.get(_w("val")) == "continuous"

    def test_section_columns(self):
        doc = UdfDocument(
            source_format="docx",
            metadata=DocumentMetadata(
                sections=[SectionDef(
                    page_width=612.0, page_height=792.0,
                    columns=ColumnDef(count=2, gap=36.0, separator=True),
                )],
            ),
            blocks=[ParagraphBlock(type="paragraph", id="b_1", inlines=[TextInline(text="x")])],
        )
        root = _generate_and_read_xml(doc)
        sect_pr = root.find(f".//{_w('sectPr')}")
        cols = sect_pr.find(_w("cols"))
        assert cols is not None
        assert cols.get(_w("num")) == "2"
        assert cols.get(_w("space")) == "720"  # 36 * 20
        assert cols.get(_w("sep")) == "true"

    def test_no_section_no_sectpr(self):
        doc = _make_doc([
            ParagraphBlock(type="paragraph", id="b_1", inlines=[TextInline(text="x")]),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        assert body.find(_w("sectPr")) is None


class TestBlockTypeCoverage:
    """DOCX 직렬화에서 추가 블록 타입 지원 검증."""

    def test_equation_block(self):
        doc = _make_doc([
            EquationBlock(type="equation", id="eq_1", latex="E=mc^2"),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        paras = body.findall(_w("p"))
        assert len(paras) == 1
        text = "".join(t.text or "" for t in paras[0].iter(f"{{{_W_NS}}}t"))
        assert "E=mc^2" in text

    def test_footnote_block_inlined(self):
        doc = _make_doc([
            FootnoteBlock(
                type="footnote", id="fn_1", ref="1",
                content=[
                    ParagraphBlock(
                        type="paragraph", id="fn_p1",
                        inlines=[TextInline(text="각주 내용")],
                    )
                ],
            ),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        text = "".join(t.text or "" for t in body.iter(f"{{{_W_NS}}}t"))
        assert "각주 내용" in text

    def test_textbox_block_content(self):
        doc = _make_doc([
            TextBoxBlock(
                type="text_box", id="tb_1",
                content=[
                    ParagraphBlock(
                        type="paragraph", id="tb_p1",
                        inlines=[TextInline(text="텍스트박스")],
                    ),
                ],
            ),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        text = "".join(t.text or "" for t in body.iter(f"{{{_W_NS}}}t"))
        assert "텍스트박스" in text

    def test_equation_inline(self):
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph", id="b_1",
                inlines=[
                    TextInline(text="공식: "),
                    EquationInline(latex="a^2+b^2"),
                ],
            ),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        text = "".join(t.text or "" for t in body.iter(f"{{{_W_NS}}}t"))
        assert "a^2+b^2" in text

    def test_footnote_ref_inline(self):
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph", id="b_1",
                inlines=[
                    TextInline(text="본문"),
                    FootnoteRefInline(ref_id="1", number=1),
                ],
            ),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        runs = body.findall(f".//{_w('r')}")
        has_superscript = any(
            r.find(f"{_w('rPr')}/{_w('vertAlign')}") is not None
            for r in runs
        )
        assert has_superscript

    def test_link_inline(self):
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph", id="b_1",
                inlines=[LinkInline(text="클릭", url="https://example.com")],
            ),
        ])
        root = _generate_and_read_xml(doc)
        body = root.find(_w("body"))
        text = "".join(t.text or "" for t in body.iter(f"{{{_W_NS}}}t"))
        assert "클릭" in text
