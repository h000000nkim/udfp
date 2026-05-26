"""DOCX 파서 단위 테스트.

테스트 fixture는 lxml + zipfile로 프로그래밍 생성한다 (외부 도구 불필요).
"""

from __future__ import annotations

import io
import tempfile
import zipfile

import pytest
from lxml import etree

from udf.parsers.docx.parse import DocxParseError, parse_docx
from udf.core.schema import (
    EndnoteBlock,
    EquationBlock,
    EquationInline,
    FootnoteBlock,
    FootnoteRefInline,
    FooterBlock,
    HeaderBlock,
    HeadingBlock,
    ImageBlock,
    ImageInline,
    ListBlock,
    PageBreakBlock,
    ParagraphBlock,
    TableBlock,
    TextInline,
    LinkInline,
)
from udf.schema.types import Color

# ---------------------------------------------------------------------------
# DOCX fixture builder
# ---------------------------------------------------------------------------

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
_M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_WPS_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"

_NSMAP = {"w": _W_NS, "r": _R_NS}


def _w(tag: str) -> str:
    return f"{{{_W_NS}}}{tag}"


def _r(tag: str) -> str:
    return f"{{{_R_NS}}}{tag}"


def _m(tag: str) -> str:
    return f"{{{_M_NS}}}{tag}"


def _wps(tag: str) -> str:
    return f"{{{_WPS_NS}}}{tag}"


def _make_paragraph(text: str, style: str | None = None, bold: bool = False) -> etree._Element:
    p = etree.Element(_w("p"), nsmap=_NSMAP)
    if style:
        ppr = etree.SubElement(p, _w("pPr"))
        ps = etree.SubElement(ppr, _w("pStyle"))
        ps.set(_w("val"), style)

    r = etree.SubElement(p, _w("r"))
    if bold:
        rpr = etree.SubElement(r, _w("rPr"))
        etree.SubElement(rpr, _w("b"))

    t = etree.SubElement(r, _w("t"))
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    return p


def _make_table(rows_data: list[list[str]]) -> etree._Element:
    tbl = etree.Element(_w("tbl"), nsmap=_NSMAP)
    for row_data in rows_data:
        tr = etree.SubElement(tbl, _w("tr"))
        for cell_text in row_data:
            tc = etree.SubElement(tr, _w("tc"))
            p = _make_paragraph(cell_text)
            tc.append(p)
    return tbl


def _make_hyperlink(text: str, rid: str) -> etree._Element:
    p = etree.Element(_w("p"), nsmap=_NSMAP)
    hl = etree.SubElement(p, _w("hyperlink"))
    hl.set(_r("id"), rid)
    r = etree.SubElement(hl, _w("r"))
    t = etree.SubElement(r, _w("t"))
    t.text = text
    return p


def _make_list_paragraph(text: str, num_id: str, ilvl: int = 0) -> etree._Element:
    p = etree.Element(_w("p"), nsmap=_NSMAP)
    ppr = etree.SubElement(p, _w("pPr"))
    num_pr = etree.SubElement(ppr, _w("numPr"))
    ilvl_el = etree.SubElement(num_pr, _w("ilvl"))
    ilvl_el.set(_w("val"), str(ilvl))
    num_id_el = etree.SubElement(num_pr, _w("numId"))
    num_id_el.set(_w("val"), num_id)

    r = etree.SubElement(p, _w("r"))
    t = etree.SubElement(r, _w("t"))
    t.text = text
    return p


def _build_document_xml(body_elements: list[etree._Element], sect_pr: etree._Element | None = None) -> bytes:
    doc = etree.Element(_w("document"), nsmap=_NSMAP)
    body = etree.SubElement(doc, _w("body"))
    for el in body_elements:
        body.append(el)
    if sect_pr is not None:
        body.append(sect_pr)
    return etree.tostring(doc, xml_declaration=True, encoding="UTF-8")


def _build_styles_xml(
    heading_styles: list[int] | None = None,
    default_font_size: str | None = None,
) -> bytes:
    styles = etree.Element(_w("styles"), nsmap=_NSMAP)

    if default_font_size:
        defaults = etree.SubElement(styles, _w("docDefaults"))
        rpr_def = etree.SubElement(etree.SubElement(defaults, _w("rPrDefault")), _w("rPr"))
        sz = etree.SubElement(rpr_def, _w("sz"))
        sz.set(_w("val"), default_font_size)

    for lvl in (heading_styles or [1, 2, 3, 4, 5, 6]):
        s = etree.SubElement(styles, _w("style"))
        s.set(_w("type"), "paragraph")
        s.set(_w("styleId"), f"Heading{lvl}")
        name_el = etree.SubElement(s, _w("name"))
        name_el.set(_w("val"), f"heading {lvl}")
        ppr = etree.SubElement(s, _w("pPr"))
        outline = etree.SubElement(ppr, _w("outlineLvl"))
        outline.set(_w("val"), str(lvl - 1))

    return etree.tostring(styles, xml_declaration=True, encoding="UTF-8")


def _build_numbering_xml() -> bytes:
    numbering = etree.Element(_w("numbering"), nsmap=_NSMAP)
    an = etree.SubElement(numbering, _w("abstractNum"))
    an.set(_w("abstractNumId"), "0")
    for i in range(3):
        lvl = etree.SubElement(an, _w("lvl"))
        lvl.set(_w("ilvl"), str(i))
        fmt = etree.SubElement(lvl, _w("numFmt"))
        fmt.set(_w("val"), "decimal")
        txt = etree.SubElement(lvl, _w("lvlText"))
        txt.set(_w("val"), f"%{i+1}.")

    num = etree.SubElement(numbering, _w("num"))
    num.set(_w("numId"), "1")
    ref = etree.SubElement(num, _w("abstractNumId"))
    ref.set(_w("val"), "0")

    return etree.tostring(numbering, xml_declaration=True, encoding="UTF-8")


def _build_rels_xml(rels: dict[str, tuple[str, str]] | None = None) -> bytes:
    root = etree.Element(f"{{{_RELS_NS}}}Relationships")
    for rid, (target, rel_type) in (rels or {}).items():
        rel = etree.SubElement(root, f"{{{_RELS_NS}}}Relationship")
        rel.set("Id", rid)
        rel.set("Target", target)
        rel.set("Type", rel_type)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _build_content_types() -> bytes:
    ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    types = etree.Element(f"{{{ct_ns}}}Types")
    d = etree.SubElement(types, f"{{{ct_ns}}}Default")
    d.set("Extension", "rels")
    d.set("ContentType", "application/vnd.openxmlformats-package.relationships+xml")
    d2 = etree.SubElement(types, f"{{{ct_ns}}}Default")
    d2.set("Extension", "xml")
    d2.set("ContentType", "application/xml")
    return etree.tostring(types, xml_declaration=True, encoding="UTF-8")


def _make_sect_pr(width_twip: int = 12240, height_twip: int = 15840,
                  top: int = 1440, bottom: int = 1440, left: int = 1440, right: int = 1440) -> etree._Element:
    sect = etree.Element(_w("sectPr"), nsmap=_NSMAP)
    pg_sz = etree.SubElement(sect, _w("pgSz"))
    pg_sz.set(_w("w"), str(width_twip))
    pg_sz.set(_w("h"), str(height_twip))
    pg_mar = etree.SubElement(sect, _w("pgMar"))
    pg_mar.set(_w("top"), str(top))
    pg_mar.set(_w("bottom"), str(bottom))
    pg_mar.set(_w("left"), str(left))
    pg_mar.set(_w("right"), str(right))
    return sect


def _create_docx(
    body_elements: list[etree._Element],
    styles_xml: bytes | None = None,
    numbering_xml: bytes | None = None,
    rels: dict[str, tuple[str, str]] | None = None,
    media_files: dict[str, bytes] | None = None,
    sect_pr: etree._Element | None = None,
    extra_xml: dict[str, bytes] | None = None,
) -> str:
    """프로그래밍으로 최소 DOCX 생성. 임시 파일 경로를 반환."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _build_content_types())
        zf.writestr("_rels/.rels", _build_rels_xml())
        zf.writestr("word/document.xml", _build_document_xml(body_elements, sect_pr))
        zf.writestr("word/_rels/document.xml.rels", _build_rels_xml(rels))
        if styles_xml:
            zf.writestr("word/styles.xml", styles_xml)
        if numbering_xml:
            zf.writestr("word/numbering.xml", numbering_xml)
        for name, data in (media_files or {}).items():
            zf.writestr(f"word/media/{name}", data)
        for path, data in (extra_xml or {}).items():
            zf.writestr(path, data)

    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    tmp.write(buf.getvalue())
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------


class TestPlainText:
    def test_single_paragraph(self):
        path = _create_docx([_make_paragraph("Hello World")])
        doc = parse_docx(path)
        assert doc.source_format == "docx"
        assert len(doc.blocks) == 1
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert len(b.inlines) == 1
        assert isinstance(b.inlines[0], TextInline)
        assert b.inlines[0].text == "Hello World"

    def test_multiple_paragraphs(self):
        path = _create_docx([
            _make_paragraph("First"),
            _make_paragraph("Second"),
            _make_paragraph("Third"),
        ])
        doc = parse_docx(path)
        assert len(doc.blocks) == 3
        texts = [
            b.inlines[0].text
            for b in doc.blocks
            if isinstance(b, ParagraphBlock) and b.inlines
        ]
        assert texts == ["First", "Second", "Third"]

    def test_bold_formatting(self):
        path = _create_docx([_make_paragraph("Bold text", bold=True)])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert b.inlines[0].bold is True


class TestCharFormat:
    def test_italic_underline(self):
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        rpr = etree.SubElement(r, _w("rPr"))
        etree.SubElement(rpr, _w("i"))
        etree.SubElement(rpr, _w("u")).set(_w("val"), "single")
        t = etree.SubElement(r, _w("t"))
        t.text = "styled"

        path = _create_docx([p])
        doc = parse_docx(path)
        il = doc.blocks[0].inlines[0]
        assert il.italic is True
        assert il.underline is True

    def test_font_size_color(self):
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        rpr = etree.SubElement(r, _w("rPr"))
        sz = etree.SubElement(rpr, _w("sz"))
        sz.set(_w("val"), "28")  # 14pt
        color = etree.SubElement(rpr, _w("color"))
        color.set(_w("val"), "FF0000")
        t = etree.SubElement(r, _w("t"))
        t.text = "red large"

        path = _create_docx([p])
        doc = parse_docx(path)
        il = doc.blocks[0].inlines[0]
        assert il.font_size == 14.0
        assert il.color == Color.from_hex("#ff0000")


class TestHeadings:
    def test_heading_detection(self):
        styles = _build_styles_xml()
        path = _create_docx(
            [
                _make_paragraph("Title", style="Heading1"),
                _make_paragraph("Subtitle", style="Heading2"),
                _make_paragraph("Normal text"),
            ],
            styles_xml=styles,
        )
        doc = parse_docx(path)
        assert len(doc.blocks) == 3
        h1 = doc.blocks[0]
        h2 = doc.blocks[1]
        p = doc.blocks[2]
        assert isinstance(h1, HeadingBlock)
        assert h1.level == 1
        assert h1.text == "Title"
        assert isinstance(h2, HeadingBlock)
        assert h2.level == 2
        assert isinstance(p, ParagraphBlock)


class TestTables:
    def test_simple_table(self):
        tbl = _make_table([["A", "B"], ["C", "D"]])
        path = _create_docx([tbl])
        doc = parse_docx(path)
        assert len(doc.blocks) == 1
        t = doc.blocks[0]
        assert isinstance(t, TableBlock)
        assert len(t.rows) == 2
        assert len(t.rows[0].cells) == 2
        c00 = t.rows[0].cells[0]
        assert len(c00.content) == 1
        assert isinstance(c00.content[0], ParagraphBlock)
        assert c00.content[0].inlines[0].text == "A"

    def test_merged_cells(self):
        """gridSpan(colSpan) + vMerge(rowSpan) 테스트."""
        tbl = etree.Element(_w("tbl"), nsmap=_NSMAP)

        # Row 0: [A (gridSpan=2)] [B]
        tr0 = etree.SubElement(tbl, _w("tr"))
        tc0 = etree.SubElement(tr0, _w("tc"))
        tcpr0 = etree.SubElement(tc0, _w("tcPr"))
        gs = etree.SubElement(tcpr0, _w("gridSpan"))
        gs.set(_w("val"), "2")
        tc0.append(_make_paragraph("A"))
        tc1 = etree.SubElement(tr0, _w("tc"))
        tc1.append(_make_paragraph("B"))

        # Row 1: [C] [D] [E]
        tr1 = etree.SubElement(tbl, _w("tr"))
        for text in ["C", "D", "E"]:
            tc = etree.SubElement(tr1, _w("tc"))
            tc.append(_make_paragraph(text))

        path = _create_docx([tbl])
        doc = parse_docx(path)
        t = doc.blocks[0]
        assert isinstance(t, TableBlock)
        assert t.rows[0].cells[0].col_span == 2


class TestLists:
    def test_ordered_list(self):
        numbering = _build_numbering_xml()
        path = _create_docx(
            [
                _make_list_paragraph("Item 1", "1", 0),
                _make_list_paragraph("Item 2", "1", 0),
                _make_list_paragraph("Sub item", "1", 1),
            ],
            numbering_xml=numbering,
        )
        doc = parse_docx(path)
        assert len(doc.blocks) == 1
        lb = doc.blocks[0]
        assert isinstance(lb, ListBlock)
        assert len(lb.items) == 2
        assert lb.items[0].inlines[0].text == "Item 1"
        assert len(lb.items[1].children) == 1
        assert lb.items[1].children[0].inlines[0].text == "Sub item"


class TestHyperlinks:
    def test_hyperlink(self):
        rels = {
            "rId1": ("https://example.com", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"),
        }
        path = _create_docx(
            [_make_hyperlink("Click here", "rId1")],
            rels=rels,
        )
        doc = parse_docx(path)
        assert len(doc.blocks) == 1
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert len(b.inlines) == 1
        il = b.inlines[0]
        assert isinstance(il, LinkInline)
        assert il.text == "Click here"
        assert il.url == "https://example.com"


class TestPageLayout:
    def test_section_properties(self):
        sect = _make_sect_pr(width_twip=12240, height_twip=15840, top=1440, bottom=1440, left=1800, right=1800)
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        assert len(doc.metadata.sections) == 1
        s = doc.metadata.sections[0]
        assert s.page_width == 612.0   # 12240 twips → 612.0pt
        assert s.page_height == 792.0  # 15840 twips → 792.0pt
        assert s.margins is not None
        assert s.margins.left == 90.0  # 1800 twips → 90.0pt


class TestVerbatim:
    def test_verbatim_preservation(self):
        path = _create_docx([_make_paragraph("Hello")])
        doc = parse_docx(path)
        assert doc.verbatim is not None
        assert doc.verbatim.format == "docx"
        assert "word/document.xml" in doc.verbatim.section_streams

        b = doc.blocks[0]
        assert b.verbatim_ref is not None
        assert b.verbatim_ref in doc.verbatim.blocks


class TestOriginalContainer:
    def test_container_info(self):
        path = _create_docx([_make_paragraph("test")])
        doc = parse_docx(path)
        assert doc.original_container is not None
        assert doc.original_container.format == "zip"
        assert doc.original_container.checksum


class TestBulletListUnordered:
    """B1: bullet 리스트가 ordered=False로 판별되어야 함."""

    def _build_bullet_numbering_xml(self) -> bytes:
        numbering = etree.Element(_w("numbering"), nsmap=_NSMAP)
        an = etree.SubElement(numbering, _w("abstractNum"))
        an.set(_w("abstractNumId"), "0")
        lvl = etree.SubElement(an, _w("lvl"))
        lvl.set(_w("ilvl"), "0")
        fmt = etree.SubElement(lvl, _w("numFmt"))
        fmt.set(_w("val"), "bullet")
        txt = etree.SubElement(lvl, _w("lvlText"))
        txt.set(_w("val"), "•")

        num = etree.SubElement(numbering, _w("num"))
        num.set(_w("numId"), "1")
        ref = etree.SubElement(num, _w("abstractNumId"))
        ref.set(_w("val"), "0")
        return etree.tostring(numbering, xml_declaration=True, encoding="UTF-8")

    def test_bullet_list_unordered(self):
        numbering = self._build_bullet_numbering_xml()
        path = _create_docx(
            [
                _make_list_paragraph("Bullet A", "1", 0),
                _make_list_paragraph("Bullet B", "1", 0),
            ],
            numbering_xml=numbering,
        )
        doc = parse_docx(path)
        assert len(doc.blocks) == 1
        lb = doc.blocks[0]
        assert isinstance(lb, ListBlock)
        assert lb.ordered is False

    def test_decimal_list_remains_ordered(self):
        numbering = _build_numbering_xml()
        path = _create_docx(
            [_make_list_paragraph("Item 1", "1", 0)],
            numbering_xml=numbering,
        )
        doc = parse_docx(path)
        lb = doc.blocks[0]
        assert isinstance(lb, ListBlock)
        assert lb.ordered is True


class TestPageBreakBlock:
    """B2: w:br type='page'가 PageBreakBlock을 생성해야 함."""

    def _make_page_break_paragraph(self) -> etree._Element:
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        br = etree.SubElement(r, _w("br"))
        br.set(_w("type"), "page")
        return p

    def test_page_break_block(self):
        path = _create_docx([
            _make_paragraph("Before"),
            self._make_page_break_paragraph(),
            _make_paragraph("After"),
        ])
        doc = parse_docx(path)
        types = [type(b).__name__ for b in doc.blocks]
        assert "PageBreakBlock" in types
        pb_indices = [i for i, b in enumerate(doc.blocks) if isinstance(b, PageBreakBlock)]
        assert len(pb_indices) >= 1

    def test_page_break_sentinel_not_in_inlines(self):
        path = _create_docx([self._make_page_break_paragraph()])
        doc = parse_docx(path)
        for b in doc.blocks:
            if isinstance(b, ParagraphBlock):
                for il in b.inlines:
                    if isinstance(il, TextInline):
                        assert "\f" not in il.text


class TestImageInlineType:
    """B3: 이미지 drawing이 ImageInline으로 파싱되어야 함."""

    def _make_image_paragraph(self, rid: str = "rId1") -> etree._Element:
        nsmap = {
            "w": _W_NS,
            "r": _R_NS,
            "wp": _WP_NS,
            "a": _A_NS,
            "pic": _PIC_NS,
        }
        p = etree.Element(_w("p"), nsmap=nsmap)
        r = etree.SubElement(p, _w("r"))
        drawing = etree.SubElement(r, _w("drawing"))
        inline = etree.SubElement(drawing, f"{{{_WP_NS}}}inline")
        extent = etree.SubElement(inline, f"{{{_WP_NS}}}extent")
        extent.set("cx", "914400")  # 72pt
        extent.set("cy", "457200")  # 36pt
        graphic = etree.SubElement(inline, f"{{{_A_NS}}}graphic")
        gd = etree.SubElement(graphic, f"{{{_A_NS}}}graphicData")
        pic = etree.SubElement(gd, f"{{{_PIC_NS}}}pic")
        bf = etree.SubElement(pic, f"{{{_PIC_NS}}}blipFill")
        blip = etree.SubElement(bf, f"{{{_A_NS}}}blip")
        blip.set(f"{{{_R_NS}}}embed", rid)
        return p

    def test_image_inline_type(self):
        rels = {
            "rId1": (
                "media/image1.png",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            ),
        }
        path = _create_docx(
            [self._make_image_paragraph("rId1")],
            rels=rels,
            media_files={"image1.png": b"\x89PNG\r\n"},
        )
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ImageBlock)
        assert "image1.png" in b.src


class TestTrackedInsertText:
    """B4: w:ins 내 텍스트가 파싱 결과에 포함되어야 함."""

    def _make_ins_paragraph(self, text: str) -> etree._Element:
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        ins = etree.SubElement(p, _w("ins"))
        ins.set(_w("author"), "test")
        r = etree.SubElement(ins, _w("r"))
        t = etree.SubElement(r, _w("t"))
        t.text = text
        return p

    def test_tracked_insert_text(self):
        path = _create_docx([self._make_ins_paragraph("inserted text")])
        doc = parse_docx(path)
        assert len(doc.blocks) == 1
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert len(b.inlines) == 1
        assert b.inlines[0].text == "inserted text"

    def test_mixed_normal_and_insert(self):
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r1 = etree.SubElement(p, _w("r"))
        t1 = etree.SubElement(r1, _w("t"))
        t1.text = "normal "
        ins = etree.SubElement(p, _w("ins"))
        r2 = etree.SubElement(ins, _w("r"))
        t2 = etree.SubElement(r2, _w("t"))
        t2.text = "inserted"

        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        texts = [il.text for il in b.inlines if isinstance(il, TextInline)]
        assert "".join(texts) == "normal inserted"


class TestErrorHandling:
    def test_invalid_zip(self, tmp_path):
        bad_file = tmp_path / "bad.docx"
        bad_file.write_bytes(b"not a zip file")
        with pytest.raises(DocxParseError, match="ZIP"):
            parse_docx(str(bad_file))

    def test_missing_document_xml(self, tmp_path):
        docx_path = tmp_path / "no_doc.docx"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("[Content_Types].xml", b"<Types/>")
        docx_path.write_bytes(buf.getvalue())
        with pytest.raises(DocxParseError, match="document.xml"):
            parse_docx(str(docx_path))


# ---------------------------------------------------------------------------
# Phase 1: OMML Equations
# ---------------------------------------------------------------------------


class TestOmmlEquation:
    """m:oMath inline and m:oMathPara display equation parsing."""

    def _make_omath_inline_paragraph(self, text: str) -> etree._Element:
        """Create w:p with m:oMath as direct child (inline equation)."""
        nsmap = {"w": _W_NS, "m": _M_NS}
        p = etree.Element(_w("p"), nsmap=nsmap)
        # Normal text before equation
        r = etree.SubElement(p, _w("r"))
        t = etree.SubElement(r, _w("t"))
        t.text = "See "
        # Inline equation
        omath = etree.SubElement(p, _m("oMath"))
        mr = etree.SubElement(omath, _m("r"))
        mt = etree.SubElement(mr, _m("t"))
        mt.text = text
        return p

    def _make_omath_para(self, text: str) -> etree._Element:
        """Create m:oMathPara (display equation, direct child of w:body)."""
        nsmap = {"m": _M_NS}
        omath_para = etree.Element(_m("oMathPara"), nsmap=nsmap)
        omath = etree.SubElement(omath_para, _m("oMath"))
        mr = etree.SubElement(omath, _m("r"))
        mt = etree.SubElement(mr, _m("t"))
        mt.text = text
        return omath_para

    def test_inline_equation(self):
        p = self._make_omath_inline_paragraph("x+1")
        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert len(b.inlines) == 2
        assert isinstance(b.inlines[0], TextInline)
        assert b.inlines[0].text == "See "
        eq_inline = b.inlines[1]
        assert isinstance(eq_inline, EquationInline)
        assert eq_inline.latex == "x+1"

    def test_inline_equation_empty(self):
        """oMath with no m:t text → EquationInline(latex=None)."""
        nsmap = {"w": _W_NS, "m": _M_NS}
        p = etree.Element(_w("p"), nsmap=nsmap)
        omath = etree.SubElement(p, _m("oMath"))
        # No m:t children
        etree.SubElement(omath, _m("r"))
        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert len(b.inlines) == 1
        eq = b.inlines[0]
        assert isinstance(eq, EquationInline)
        assert eq.latex is None

    def test_display_equation(self):
        omath_para = self._make_omath_para("a^2+b^2=c^2")
        path = _create_docx([omath_para])
        doc = parse_docx(path)
        assert len(doc.blocks) == 1
        eq = doc.blocks[0]
        assert isinstance(eq, EquationBlock)
        assert eq.display is True
        assert eq.latex == "a^2+b^2=c^2"

    def test_display_equation_multiple_omath(self):
        """m:oMathPara with multiple m:oMath elements → concatenated text."""
        nsmap = {"m": _M_NS}
        omath_para = etree.Element(_m("oMathPara"), nsmap=nsmap)
        for text in ["x", "+", "y"]:
            omath = etree.SubElement(omath_para, _m("oMath"))
            mr = etree.SubElement(omath, _m("r"))
            mt = etree.SubElement(mr, _m("t"))
            mt.text = text
        path = _create_docx([omath_para])
        doc = parse_docx(path)
        eq = doc.blocks[0]
        assert isinstance(eq, EquationBlock)
        assert eq.latex == "x+y"

    def test_mixed_paragraphs_and_equations(self):
        """Normal paragraph followed by display equation."""
        p = _make_paragraph("Hello")
        omath_para = self._make_omath_para("E=mc^2")
        p2 = _make_paragraph("World")
        path = _create_docx([p, omath_para, p2])
        doc = parse_docx(path)
        assert len(doc.blocks) == 3
        assert isinstance(doc.blocks[0], ParagraphBlock)
        assert isinstance(doc.blocks[1], EquationBlock)
        assert isinstance(doc.blocks[2], ParagraphBlock)


# ---------------------------------------------------------------------------
# Phase 2: Footnote/Endnote References
# ---------------------------------------------------------------------------


class TestFootnoteRef:
    """w:footnoteReference in a run → FootnoteRefInline."""

    def _make_footnote_ref_paragraph(self, fn_id: str) -> etree._Element:
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        t = etree.SubElement(r, _w("t"))
        t.text = "See note"
        r2 = etree.SubElement(p, _w("r"))
        fnref = etree.SubElement(r2, _w("footnoteReference"))
        fnref.set(_w("id"), fn_id)
        return p

    def test_footnote_ref(self):
        p = self._make_footnote_ref_paragraph("1")
        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert len(b.inlines) == 2
        assert isinstance(b.inlines[0], TextInline)
        ref = b.inlines[1]
        assert isinstance(ref, FootnoteRefInline)
        assert ref.ref_id == "1"
        assert ref.number == 1

    def test_footnote_ref_non_numeric_id(self):
        p = self._make_footnote_ref_paragraph("abc")
        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        ref = b.inlines[1]
        assert isinstance(ref, FootnoteRefInline)
        assert ref.ref_id == "abc"
        assert ref.number is None


class TestEndnoteRef:
    """w:endnoteReference in a run → FootnoteRefInline."""

    def _make_endnote_ref_paragraph(self, en_id: str) -> etree._Element:
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        enref = etree.SubElement(r, _w("endnoteReference"))
        enref.set(_w("id"), en_id)
        return p

    def test_endnote_ref(self):
        p = self._make_endnote_ref_paragraph("2")
        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert len(b.inlines) == 1
        ref = b.inlines[0]
        assert isinstance(ref, FootnoteRefInline)
        assert ref.ref_id == "2"
        assert ref.number == 2


# ---------------------------------------------------------------------------
# Phase 2: Footnote/Endnote XML Parsing
# ---------------------------------------------------------------------------


class TestFootnoteParsing:
    """Full footnotes.xml parsing via ZIP."""

    def _build_footnotes_xml(self, footnotes: dict[str, str]) -> bytes:
        """Build a word/footnotes.xml.

        footnotes: {id: text} — separator ids 0, -1 are auto-added.
        """
        root = etree.Element(_w("footnotes"), nsmap=_NSMAP)
        # Separator and continuation separator
        for sep_id in ("0", "-1"):
            fn = etree.SubElement(root, _w("footnote"))
            fn.set(_w("id"), sep_id)
            fn.set(_w("type"), "separator")
        for fn_id, text in footnotes.items():
            fn = etree.SubElement(root, _w("footnote"))
            fn.set(_w("id"), fn_id)
            p = _make_paragraph(text)
            fn.append(p)
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8")

    def test_footnotes_parsed(self):
        fn_xml = self._build_footnotes_xml({"1": "First footnote", "2": "Second footnote"})
        path = _create_docx(
            [_make_paragraph("Main text")],
            extra_xml={"word/footnotes.xml": fn_xml},
        )
        doc = parse_docx(path)
        fn_blocks = [b for b in doc.blocks if isinstance(b, FootnoteBlock)]
        assert len(fn_blocks) == 2
        assert fn_blocks[0].ref == "1"
        assert fn_blocks[1].ref == "2"
        # Footnote content should contain paragraphs
        assert len(fn_blocks[0].content) == 1
        assert isinstance(fn_blocks[0].content[0], ParagraphBlock)
        assert fn_blocks[0].content[0].inlines[0].text == "First footnote"

    def test_separator_footnotes_skipped(self):
        fn_xml = self._build_footnotes_xml({"1": "Real note"})
        path = _create_docx(
            [_make_paragraph("text")],
            extra_xml={"word/footnotes.xml": fn_xml},
        )
        doc = parse_docx(path)
        fn_blocks = [b for b in doc.blocks if isinstance(b, FootnoteBlock)]
        assert len(fn_blocks) == 1
        assert fn_blocks[0].ref == "1"

    def test_no_footnotes_file(self):
        """DOCX without word/footnotes.xml should parse without error."""
        path = _create_docx([_make_paragraph("text")])
        doc = parse_docx(path)
        fn_blocks = [b for b in doc.blocks if isinstance(b, FootnoteBlock)]
        assert len(fn_blocks) == 0


class TestEndnoteParsing:
    """Full endnotes.xml parsing via ZIP."""

    def _build_endnotes_xml(self, endnotes: dict[str, str]) -> bytes:
        root = etree.Element(_w("endnotes"), nsmap=_NSMAP)
        for sep_id in ("0", "-1"):
            en = etree.SubElement(root, _w("endnote"))
            en.set(_w("id"), sep_id)
            en.set(_w("type"), "separator")
        for en_id, text in endnotes.items():
            en = etree.SubElement(root, _w("endnote"))
            en.set(_w("id"), en_id)
            p = _make_paragraph(text)
            en.append(p)
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8")

    def test_endnotes_parsed(self):
        en_xml = self._build_endnotes_xml({"1": "End note text"})
        path = _create_docx(
            [_make_paragraph("Main")],
            extra_xml={"word/endnotes.xml": en_xml},
        )
        doc = parse_docx(path)
        en_blocks = [b for b in doc.blocks if isinstance(b, EndnoteBlock)]
        assert len(en_blocks) == 1
        assert en_blocks[0].ref == "1"
        assert en_blocks[0].content[0].inlines[0].text == "End note text"


# ---------------------------------------------------------------------------
# Phase 3: Headers and Footers
# ---------------------------------------------------------------------------


class TestHeaderFooterParsing:
    """Header/footer XML parsing via ZIP with sectPr references."""

    def _build_header_xml(self, text: str) -> bytes:
        root = etree.Element(_w("hdr"), nsmap=_NSMAP)
        root.append(_make_paragraph(text))
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8")

    def _build_footer_xml(self, text: str) -> bytes:
        root = etree.Element(_w("ftr"), nsmap=_NSMAP)
        root.append(_make_paragraph(text))
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8")

    def test_header_parsed(self):
        hdr_xml = self._build_header_xml("My Header")
        sect = _make_sect_pr()
        # Add headerReference to sectPr
        href = etree.SubElement(sect, _w("headerReference"))
        href.set(_w("type"), "default")
        href.set(_r("id"), "rId10")

        rels = {
            "rId10": (
                "header1.xml",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header",
            ),
        }
        path = _create_docx(
            [_make_paragraph("Body")],
            rels=rels,
            sect_pr=sect,
            extra_xml={"word/header1.xml": hdr_xml},
        )
        doc = parse_docx(path)
        hdr_blocks = [b for b in doc.blocks if isinstance(b, HeaderBlock)]
        assert len(hdr_blocks) == 1
        assert hdr_blocks[0].apply_to == "all"
        assert len(hdr_blocks[0].content) == 1
        assert hdr_blocks[0].content[0].inlines[0].text == "My Header"

    def test_footer_parsed(self):
        ftr_xml = self._build_footer_xml("Page Footer")
        sect = _make_sect_pr()
        fref = etree.SubElement(sect, _w("footerReference"))
        fref.set(_w("type"), "default")
        fref.set(_r("id"), "rId11")

        rels = {
            "rId11": (
                "footer1.xml",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer",
            ),
        }
        path = _create_docx(
            [_make_paragraph("Body")],
            rels=rels,
            sect_pr=sect,
            extra_xml={"word/footer1.xml": ftr_xml},
        )
        doc = parse_docx(path)
        ftr_blocks = [b for b in doc.blocks if isinstance(b, FooterBlock)]
        assert len(ftr_blocks) == 1
        assert ftr_blocks[0].apply_to == "all"
        assert ftr_blocks[0].content[0].inlines[0].text == "Page Footer"

    def test_first_page_header(self):
        hdr_xml = self._build_header_xml("First Page Header")
        sect = _make_sect_pr()
        href = etree.SubElement(sect, _w("headerReference"))
        href.set(_w("type"), "first")
        href.set(_r("id"), "rId12")

        rels = {
            "rId12": (
                "header2.xml",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header",
            ),
        }
        path = _create_docx(
            [_make_paragraph("Body")],
            rels=rels,
            sect_pr=sect,
            extra_xml={"word/header2.xml": hdr_xml},
        )
        doc = parse_docx(path)
        hdr_blocks = [b for b in doc.blocks if isinstance(b, HeaderBlock)]
        assert len(hdr_blocks) == 1
        assert hdr_blocks[0].apply_to == "first"

    def test_no_sectpr_no_crash(self):
        """DOCX without sectPr should parse without error."""
        path = _create_docx([_make_paragraph("text")])
        doc = parse_docx(path)
        hdr_blocks = [b for b in doc.blocks if isinstance(b, HeaderBlock)]
        assert len(hdr_blocks) == 0


# ---------------------------------------------------------------------------
# Phase 4: Simple Fields
# ---------------------------------------------------------------------------


class TestSimpleField:
    """w:fldSimple with cached display value."""

    def _make_fld_simple_paragraph(self, instr: str, display: str) -> etree._Element:
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        fld = etree.SubElement(p, _w("fldSimple"))
        fld.set(_w("instr"), instr)
        r = etree.SubElement(fld, _w("r"))
        t = etree.SubElement(r, _w("t"))
        t.text = display
        return p

    def test_fld_simple_cached_value(self):
        p = self._make_fld_simple_paragraph(" PAGE ", "3")
        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert len(b.inlines) == 1
        assert isinstance(b.inlines[0], TextInline)
        assert b.inlines[0].text == "3"

    def test_fld_simple_empty(self):
        """fldSimple with no display text → no inline."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        fld = etree.SubElement(p, _w("fldSimple"))
        fld.set(_w("instr"), " PAGE ")
        # No run children
        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert len(b.inlines) == 0

    def test_fld_simple_with_surrounding_text(self):
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r1 = etree.SubElement(p, _w("r"))
        t1 = etree.SubElement(r1, _w("t"))
        t1.text = "Page "
        fld = etree.SubElement(p, _w("fldSimple"))
        fld.set(_w("instr"), " PAGE ")
        r2 = etree.SubElement(fld, _w("r"))
        t2 = etree.SubElement(r2, _w("t"))
        t2.text = "5"
        r3 = etree.SubElement(p, _w("r"))
        t3 = etree.SubElement(r3, _w("t"))
        t3.text = " of 10"

        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        texts = [il.text for il in b.inlines if isinstance(il, TextInline)]
        assert "".join(texts) == "Page 5 of 10"


# ---------------------------------------------------------------------------
# Complex Fields (w:fldChar state machine)
# ---------------------------------------------------------------------------


class TestComplexField:
    """w:fldChar begin/separate/end state machine."""

    def _make_complex_field_para(self, instr: str, display: str,
                                  prefix: str = "", suffix: str = "") -> etree._Element:
        """Build a paragraph with a complex field: prefix + begin + instrText + separate + display + end + suffix."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)

        if prefix:
            r = etree.SubElement(p, _w("r"))
            t = etree.SubElement(r, _w("t"))
            t.text = prefix

        # begin
        r_begin = etree.SubElement(p, _w("r"))
        fc_begin = etree.SubElement(r_begin, _w("fldChar"))
        fc_begin.set(_w("fldCharType"), "begin")

        # instrText
        r_instr = etree.SubElement(p, _w("r"))
        it = etree.SubElement(r_instr, _w("instrText"))
        it.text = instr

        # separate
        r_sep = etree.SubElement(p, _w("r"))
        fc_sep = etree.SubElement(r_sep, _w("fldChar"))
        fc_sep.set(_w("fldCharType"), "separate")

        # display value
        r_disp = etree.SubElement(p, _w("r"))
        t_disp = etree.SubElement(r_disp, _w("t"))
        t_disp.text = display

        # end
        r_end = etree.SubElement(p, _w("r"))
        fc_end = etree.SubElement(r_end, _w("fldChar"))
        fc_end.set(_w("fldCharType"), "end")

        if suffix:
            r = etree.SubElement(p, _w("r"))
            t = etree.SubElement(r, _w("t"))
            t.text = suffix

        return p

    def test_complex_field_display_value(self):
        p = self._make_complex_field_para(" PAGE ", "7")
        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        texts = [il.text for il in b.inlines if isinstance(il, TextInline)]
        assert "7" in texts

    def test_complex_field_instrtext_not_emitted(self):
        p = self._make_complex_field_para(" DATE \\@ yyyy-MM-dd ", "2026-05-25")
        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        texts = [il.text for il in b.inlines if isinstance(il, TextInline)]
        joined = "".join(texts)
        assert "2026-05-25" in joined
        assert "DATE" not in joined
        assert "yyyy" not in joined

    def test_complex_field_with_surrounding_text(self):
        p = self._make_complex_field_para(" PAGE ", "3", prefix="Page ", suffix=" of 10")
        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        texts = [il.text for il in b.inlines if isinstance(il, TextInline)]
        assert "".join(texts) == "Page 3 of 10"

    def test_nested_complex_fields(self):
        """Nested fields: only outermost display is emitted."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)

        # outer begin
        r = etree.SubElement(p, _w("r"))
        fc = etree.SubElement(r, _w("fldChar"))
        fc.set(_w("fldCharType"), "begin")
        r = etree.SubElement(p, _w("r"))
        it = etree.SubElement(r, _w("instrText"))
        it.text = " IF "

        # inner begin (nested)
        r = etree.SubElement(p, _w("r"))
        fc = etree.SubElement(r, _w("fldChar"))
        fc.set(_w("fldCharType"), "begin")
        r = etree.SubElement(p, _w("r"))
        it = etree.SubElement(r, _w("instrText"))
        it.text = " PAGE "
        r = etree.SubElement(p, _w("r"))
        fc = etree.SubElement(r, _w("fldChar"))
        fc.set(_w("fldCharType"), "separate")
        r = etree.SubElement(p, _w("r"))
        t = etree.SubElement(r, _w("t"))
        t.text = "5"
        r = etree.SubElement(p, _w("r"))
        fc = etree.SubElement(r, _w("fldChar"))
        fc.set(_w("fldCharType"), "end")
        # inner end

        # outer separate
        r = etree.SubElement(p, _w("r"))
        fc = etree.SubElement(r, _w("fldChar"))
        fc.set(_w("fldCharType"), "separate")
        r = etree.SubElement(p, _w("r"))
        t = etree.SubElement(r, _w("t"))
        t.text = "Result"
        # outer end
        r = etree.SubElement(p, _w("r"))
        fc = etree.SubElement(r, _w("fldChar"))
        fc.set(_w("fldCharType"), "end")

        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        texts = [il.text for il in b.inlines if isinstance(il, TextInline)]
        assert "Result" in texts

    def test_complex_field_no_separate(self):
        """Field with begin/end but no separate — no display text emitted."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        fc = etree.SubElement(r, _w("fldChar"))
        fc.set(_w("fldCharType"), "begin")
        r = etree.SubElement(p, _w("r"))
        it = etree.SubElement(r, _w("instrText"))
        it.text = " TOC "
        r = etree.SubElement(p, _w("r"))
        fc = etree.SubElement(r, _w("fldChar"))
        fc.set(_w("fldCharType"), "end")

        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert len(b.inlines) == 0


# ---------------------------------------------------------------------------
# Phase 4: Structured Document Tags (SDT)
# ---------------------------------------------------------------------------


class TestSdtParsing:
    """w:sdt → extract content from w:sdtContent."""

    def _make_sdt(self, text: str) -> etree._Element:
        sdt = etree.Element(_w("sdt"), nsmap=_NSMAP)
        etree.SubElement(sdt, _w("sdtPr"))
        sdt_content = etree.SubElement(sdt, _w("sdtContent"))
        sdt_content.append(_make_paragraph(text))
        return sdt

    def test_sdt_content_extracted(self):
        sdt = self._make_sdt("SDT text")
        path = _create_docx([sdt])
        doc = parse_docx(path)
        assert len(doc.blocks) == 1
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert b.inlines[0].text == "SDT text"

    def test_sdt_with_surrounding_paragraphs(self):
        sdt = self._make_sdt("Inner")
        path = _create_docx([
            _make_paragraph("Before"),
            sdt,
            _make_paragraph("After"),
        ])
        doc = parse_docx(path)
        assert len(doc.blocks) == 3
        texts = []
        for b in doc.blocks:
            if isinstance(b, ParagraphBlock) and b.inlines:
                texts.append(b.inlines[0].text)
        assert texts == ["Before", "Inner", "After"]


# ---------------------------------------------------------------------------
# Phase 4: TextBox in drawing
# ---------------------------------------------------------------------------


class TestTextBoxInDrawing:
    """wps:txbx > w:txbxContent inside drawing → TextBoxBlock inlines."""

    def _make_textbox_paragraph(self, text: str) -> etree._Element:
        nsmap = {
            "w": _W_NS,
            "r": _R_NS,
            "wp": _WP_NS,
            "wps": _WPS_NS,
        }
        p = etree.Element(_w("p"), nsmap=nsmap)
        r = etree.SubElement(p, _w("r"))
        drawing = etree.SubElement(r, _w("drawing"))
        anchor = etree.SubElement(drawing, f"{{{_WP_NS}}}anchor")
        extent = etree.SubElement(anchor, f"{{{_WP_NS}}}extent")
        extent.set("cx", "914400")
        extent.set("cy", "457200")
        # wps:wsp > wps:txbx > w:txbxContent > w:p
        wsp = etree.SubElement(anchor, _wps("wsp"))
        txbx = etree.SubElement(wsp, _wps("txbx"))
        txbx_content = etree.SubElement(txbx, _w("txbxContent"))
        inner_p = _make_paragraph(text)
        txbx_content.append(inner_p)
        return p

    def test_textbox_inlines_extracted(self):
        p = self._make_textbox_paragraph("Box text")
        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        # TextBox content inlines are flattened into the paragraph
        text_inlines = [il for il in b.inlines if isinstance(il, TextInline)]
        assert len(text_inlines) >= 1
        assert any(il.text == "Box text" for il in text_inlines)


# ---------------------------------------------------------------------------
# Section breaks, orientation, columns (Phase 4)
# ---------------------------------------------------------------------------


class TestSectionOrientation:
    def test_landscape_orientation(self):
        sect = _make_sect_pr(width_twip=15840, height_twip=12240)
        pg_sz = sect.find(_w("pgSz"))
        pg_sz.set(_w("orient"), "landscape")
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        assert len(doc.metadata.sections) == 1
        assert doc.metadata.sections[0].orientation == "landscape"

    def test_portrait_default(self):
        sect = _make_sect_pr()
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        assert doc.metadata.sections[0].orientation is None


class TestSectionBreakType:
    def _make_sect_with_break(self, break_type: str) -> etree._Element:
        sect = _make_sect_pr()
        type_el = etree.SubElement(sect, _w("type"))
        type_el.set(_w("val"), break_type)
        return sect

    def test_continuous_break(self):
        sect = self._make_sect_with_break("continuous")
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        assert doc.metadata.sections[0].break_type == "continuous"

    def test_next_page_break(self):
        sect = self._make_sect_with_break("nextPage")
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        assert doc.metadata.sections[0].break_type == "next_page"

    def test_even_page_break(self):
        sect = self._make_sect_with_break("evenPage")
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        assert doc.metadata.sections[0].break_type == "even_page"

    def test_odd_page_break(self):
        sect = self._make_sect_with_break("oddPage")
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        assert doc.metadata.sections[0].break_type == "odd_page"

    def test_no_break_type(self):
        sect = _make_sect_pr()
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        assert doc.metadata.sections[0].break_type is None


class TestSectionColumns:
    def _make_sect_with_cols(self, **attrs) -> etree._Element:
        sect = _make_sect_pr()
        cols = etree.SubElement(sect, _w("cols"))
        for k, v in attrs.items():
            cols.set(_w(k), str(v))
        return sect

    def test_two_columns_equal(self):
        sect = self._make_sect_with_cols(num="2", space="720")
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        c = doc.metadata.sections[0].columns
        assert c is not None
        assert c.count == 2
        assert c.gap == 36.0  # 720 twips → 36.0pt
        assert c.same_width is True

    def test_columns_with_separator(self):
        sect = self._make_sect_with_cols(num="3", space="360", sep="true")
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        c = doc.metadata.sections[0].columns
        assert c is not None
        assert c.count == 3
        assert c.separator is True

    def test_unequal_columns(self):
        sect = _make_sect_pr()
        cols = etree.SubElement(sect, _w("cols"))
        cols.set(_w("num"), "2")
        cols.set(_w("equalWidth"), "false")
        c1 = etree.SubElement(cols, _w("col"))
        c1.set(_w("w"), "6000")
        c1.set(_w("space"), "720")
        c2 = etree.SubElement(cols, _w("col"))
        c2.set(_w("w"), "4800")
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        c = doc.metadata.sections[0].columns
        assert c is not None
        assert c.same_width is False
        assert len(c.widths) == 2
        assert c.widths[0] == 300.0  # 6000 twips → 300.0pt
        assert c.widths[1] == 240.0  # 4800 twips → 240.0pt

    def test_no_columns(self):
        sect = _make_sect_pr()
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        assert doc.metadata.sections[0].columns is None


class TestMultiSection:
    def _make_para_with_sect_pr(self, text: str, **sect_attrs) -> etree._Element:
        """Create a paragraph with w:pPr/w:sectPr (intermediate section break)."""
        p = _make_paragraph(text)
        ppr = p.find(_w("pPr"))
        if ppr is None:
            ppr = etree.SubElement(p, _w("pPr"))
        sect = etree.SubElement(ppr, _w("sectPr"))
        pg_sz = etree.SubElement(sect, _w("pgSz"))
        pg_sz.set(_w("w"), str(sect_attrs.get("width", 12240)))
        pg_sz.set(_w("h"), str(sect_attrs.get("height", 15840)))
        if sect_attrs.get("orient"):
            pg_sz.set(_w("orient"), sect_attrs["orient"])
        if sect_attrs.get("break_type"):
            type_el = etree.SubElement(sect, _w("type"))
            type_el.set(_w("val"), sect_attrs["break_type"])
        if sect_attrs.get("cols"):
            cols = etree.SubElement(sect, _w("cols"))
            cols.set(_w("num"), str(sect_attrs["cols"]))
        return p

    def test_two_sections(self):
        p1 = self._make_para_with_sect_pr("section 1", break_type="continuous")
        p2 = _make_paragraph("section 2")
        final_sect = _make_sect_pr()
        path = _create_docx([p1, p2], sect_pr=final_sect)
        doc = parse_docx(path)
        assert len(doc.metadata.sections) == 2
        assert doc.metadata.sections[0].break_type == "continuous"
        assert doc.metadata.sections[1].break_type is None

    def test_three_sections_mixed_orientation(self):
        p1 = self._make_para_with_sect_pr("portrait section")
        p2 = self._make_para_with_sect_pr("landscape section",
                                           width=15840, height=12240,
                                           orient="landscape",
                                           break_type="nextPage")
        p3 = _make_paragraph("back to portrait")
        final_sect = _make_sect_pr()
        path = _create_docx([p1, p2, p3], sect_pr=final_sect)
        doc = parse_docx(path)
        assert len(doc.metadata.sections) == 3
        assert doc.metadata.sections[0].orientation is None
        assert doc.metadata.sections[1].orientation == "landscape"
        assert doc.metadata.sections[1].break_type == "next_page"
        assert doc.metadata.sections[2].orientation is None

    def test_section_with_columns_and_break(self):
        p1 = self._make_para_with_sect_pr("col section",
                                           cols=2, break_type="continuous")
        p2 = _make_paragraph("normal section")
        final_sect = _make_sect_pr()
        path = _create_docx([p1, p2], sect_pr=final_sect)
        doc = parse_docx(path)
        assert len(doc.metadata.sections) == 2
        s0 = doc.metadata.sections[0]
        assert s0.columns is not None
        assert s0.columns.count == 2
        assert s0.break_type == "continuous"


class TestPageNumbering:
    def test_start_page_number(self):
        sect = _make_sect_pr()
        pgn = etree.SubElement(sect, _w("pgNumType"))
        pgn.set(_w("start"), "5")
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        assert doc.metadata.sections[0].start_page_number == 5

    def test_page_number_format_roman(self):
        sect = _make_sect_pr()
        pgn = etree.SubElement(sect, _w("pgNumType"))
        pgn.set(_w("fmt"), "lowerRoman")
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        assert doc.metadata.sections[0].page_number_format == "roman_lower"


class TestPageBorders:
    def test_page_borders(self):
        sect = _make_sect_pr()
        borders = etree.SubElement(sect, _w("pgBorders"))
        top = etree.SubElement(borders, _w("top"))
        top.set(_w("val"), "single")
        top.set(_w("sz"), "8")
        top.set(_w("color"), "FF0000")
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        s = doc.metadata.sections[0]
        assert s.border_top is not None
        assert "FF0000" in s.border_top


class TestLineNumbering:
    def test_line_numbering_detected(self):
        sect = _make_sect_pr()
        etree.SubElement(sect, _w("lnNumType"))
        path = _create_docx([_make_paragraph("text")], sect_pr=sect)
        doc = parse_docx(path)
        assert doc.metadata.sections[0].line_numbering is True
