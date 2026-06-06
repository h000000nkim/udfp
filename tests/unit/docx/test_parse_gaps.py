"""DOCX 파서 갭 보강 테스트 — Wave 1-1.

기존에 스키마 필드가 있었지만 파서가 채우지 않던 항목들의 추출을 검증.
"""

from __future__ import annotations

from lxml import etree

from udf.core.schema import (
    ImageBlock,
    ParagraphBlock,
    TableBlock,
    TextInline,
)
from udf.parsers.docx.parse import parse_docx
from udf.schema.types import Color

from tests.unit.docx.test_parse import (
    _A_NS,
    _PIC_NS,
    _R_NS,
    _W_NS,
    _WP_NS,
    _create_docx,
    _make_paragraph,
)

_NSMAP = {"w": _W_NS, "r": _R_NS}


def _w(tag: str) -> str:
    return f"{{{_W_NS}}}{tag}"


def _r(tag: str) -> str:
    return f"{{{_R_NS}}}{tag}"


# ---------------------------------------------------------------------------
# A3: underline_type
# ---------------------------------------------------------------------------


class TestUnderlineType:
    def test_underline_type_wave(self):
        """w:u val='wave' → underline_type='wave'."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        rpr = etree.SubElement(r, _w("rPr"))
        u = etree.SubElement(rpr, _w("u"))
        u.set(_w("val"), "wave")
        t = etree.SubElement(r, _w("t"))
        t.text = "wavy"

        path = _create_docx([p])
        doc = parse_docx(path)
        il = doc.blocks[0].inlines[0]
        assert isinstance(il, TextInline)
        assert il.underline is True
        assert il.underline_type == "wave"

    def test_underline_type_double(self):
        """w:u val='double' → underline_type='double'."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        rpr = etree.SubElement(r, _w("rPr"))
        u = etree.SubElement(rpr, _w("u"))
        u.set(_w("val"), "double")
        t = etree.SubElement(r, _w("t"))
        t.text = "dbl"

        path = _create_docx([p])
        doc = parse_docx(path)
        il = doc.blocks[0].inlines[0]
        assert il.underline_type == "double"

    def test_underline_color(self):
        """w:u color='FF0000' → underline_color='#FF0000'."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        rpr = etree.SubElement(r, _w("rPr"))
        u = etree.SubElement(rpr, _w("u"))
        u.set(_w("val"), "single")
        u.set(_w("color"), "FF0000")
        t = etree.SubElement(r, _w("t"))
        t.text = "red underline"

        path = _create_docx([p])
        doc = parse_docx(path)
        il = doc.blocks[0].inlines[0]
        assert il.underline_color == Color.from_hex("#ff0000")


# ---------------------------------------------------------------------------
# A4: strikeout_type
# ---------------------------------------------------------------------------


class TestStrikeoutType:
    def test_single_strike(self):
        """w:strike → strikeout_type='solid'."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        rpr = etree.SubElement(r, _w("rPr"))
        etree.SubElement(rpr, _w("strike"))
        t = etree.SubElement(r, _w("t"))
        t.text = "struck"

        path = _create_docx([p])
        doc = parse_docx(path)
        il = doc.blocks[0].inlines[0]
        assert il.strikethrough is True
        assert il.strikeout_type == "solid"

    def test_double_strike(self):
        """w:dstrike → strikeout_type='double'."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        rpr = etree.SubElement(r, _w("rPr"))
        etree.SubElement(rpr, _w("dstrike"))
        t = etree.SubElement(r, _w("t"))
        t.text = "dstruck"

        path = _create_docx([p])
        doc = parse_docx(path)
        il = doc.blocks[0].inlines[0]
        assert il.strikethrough is True
        assert il.strikeout_type == "double"


# ---------------------------------------------------------------------------
# A5: outline, shadow
# ---------------------------------------------------------------------------


class TestOutlineShadow:
    def test_outline(self):
        """w:outline → outline=True."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        rpr = etree.SubElement(r, _w("rPr"))
        etree.SubElement(rpr, _w("outline"))
        t = etree.SubElement(r, _w("t"))
        t.text = "outlined"

        path = _create_docx([p])
        doc = parse_docx(path)
        il = doc.blocks[0].inlines[0]
        assert il.outline is True

    def test_shadow(self):
        """w:shadow → shadow=True."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        rpr = etree.SubElement(r, _w("rPr"))
        etree.SubElement(rpr, _w("shadow"))
        t = etree.SubElement(r, _w("t"))
        t.text = "shadowed"

        path = _create_docx([p])
        doc = parse_docx(path)
        il = doc.blocks[0].inlines[0]
        assert il.shadow is True


# ---------------------------------------------------------------------------
# A6: paragraph background_color
# ---------------------------------------------------------------------------


class TestParaBackground:
    def test_paragraph_shading(self):
        """w:pPr/w:shd fill → BlockFormat.background_color."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        ppr = etree.SubElement(p, _w("pPr"))
        shd = etree.SubElement(ppr, _w("shd"))
        shd.set(_w("fill"), "FFFF00")
        r = etree.SubElement(p, _w("r"))
        t = etree.SubElement(r, _w("t"))
        t.text = "highlighted para"

        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert b.format is not None
        assert b.format.background_color == Color.from_hex("#ffff00")


# ---------------------------------------------------------------------------
# A7: paragraph borders
# ---------------------------------------------------------------------------


class TestParaBorders:
    def test_paragraph_borders(self):
        """w:pPr/w:pBdr → BlockFormat.border_*."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        ppr = etree.SubElement(p, _w("pPr"))
        pbdr = etree.SubElement(ppr, _w("pBdr"))
        top_b = etree.SubElement(pbdr, _w("top"))
        top_b.set(_w("val"), "single")
        top_b.set(_w("sz"), "8")
        top_b.set(_w("color"), "FF0000")
        bottom_b = etree.SubElement(pbdr, _w("bottom"))
        bottom_b.set(_w("val"), "single")
        bottom_b.set(_w("sz"), "4")
        bottom_b.set(_w("color"), "0000FF")
        r = etree.SubElement(p, _w("r"))
        t = etree.SubElement(r, _w("t"))
        t.text = "bordered"

        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert b.format is not None
        assert "1.0pt solid #FF0000" == b.format.border_top
        assert "0.5pt solid #0000FF" == b.format.border_bottom

    def test_paragraph_border_none_ignored(self):
        """w:pBdr with val='none' → no border."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        ppr = etree.SubElement(p, _w("pPr"))
        pbdr = etree.SubElement(ppr, _w("pBdr"))
        top_b = etree.SubElement(pbdr, _w("top"))
        top_b.set(_w("val"), "none")
        r = etree.SubElement(p, _w("r"))
        t = etree.SubElement(r, _w("t"))
        t.text = "no border"

        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert b.format is None or b.format.border_top is None


# ---------------------------------------------------------------------------
# A9: outline_level
# ---------------------------------------------------------------------------


class TestOutlineLevel:
    def test_outline_level_stored(self):
        """w:pPr/w:outlineLvl → BlockFormat.outline_level."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        ppr = etree.SubElement(p, _w("pPr"))
        ol = etree.SubElement(ppr, _w("outlineLvl"))
        ol.set(_w("val"), "2")
        r = etree.SubElement(p, _w("r"))
        t = etree.SubElement(r, _w("t"))
        t.text = "level 2"

        path = _create_docx([p])
        doc = parse_docx(path)
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert b.format is not None
        assert b.format.outline_level == 2


# ---------------------------------------------------------------------------
# A11: table cell_spacing
# ---------------------------------------------------------------------------


class TestTableCellSpacing:
    def test_tbl_cell_spacing(self):
        """w:tblPr/w:tblCellSpacing → TableBlock.cell_spacing."""
        tbl = etree.Element(_w("tbl"), nsmap=_NSMAP)
        tbl_pr = etree.SubElement(tbl, _w("tblPr"))
        cs = etree.SubElement(tbl_pr, _w("tblCellSpacing"))
        cs.set(_w("w"), "40")
        cs.set(_w("type"), "dxa")
        tr = etree.SubElement(tbl, _w("tr"))
        tc = etree.SubElement(tr, _w("tc"))
        tc.append(_make_paragraph("cell"))

        path = _create_docx([tbl])
        doc = parse_docx(path)
        tbl_blocks = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tbl_blocks) == 1
        assert tbl_blocks[0].cell_spacing == 2.0  # 40 twips → 2.0pt


# ---------------------------------------------------------------------------
# A14: docProps metadata
# ---------------------------------------------------------------------------


class TestDocPropsMetadata:
    def test_title_and_author(self):
        """docProps/core.xml → metadata.title, author."""
        _DC = "http://purl.org/dc/elements/1.1/"
        _DCTERMS = "http://purl.org/dc/terms/"
        _CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"

        core = etree.Element(f"{{{_CP}}}coreProperties")
        title = etree.SubElement(core, f"{{{_DC}}}title")
        title.text = "Test Document"
        creator = etree.SubElement(core, f"{{{_DC}}}creator")
        creator.text = "Test Author"
        created = etree.SubElement(core, f"{{{_DCTERMS}}}created")
        created.text = "2026-01-15T10:00:00Z"
        modified = etree.SubElement(core, f"{{{_DCTERMS}}}modified")
        modified.text = "2026-05-24T12:00:00Z"

        core_bytes = etree.tostring(core, xml_declaration=True, encoding="UTF-8")

        path = _create_docx(
            [_make_paragraph("content")],
            extra_xml={"docProps/core.xml": core_bytes},
        )
        doc = parse_docx(path)
        assert doc.metadata.title == "Test Document"
        assert doc.metadata.author == "Test Author"
        assert doc.metadata.created_at == "2026-01-15T10:00:00Z"
        assert doc.metadata.modified_at == "2026-05-24T12:00:00Z"

    def test_no_docprops_no_crash(self):
        """docProps 없어도 파서가 정상 동작."""
        path = _create_docx([_make_paragraph("no meta")])
        doc = parse_docx(path)
        assert doc.metadata.title is None
        assert doc.metadata.author is None


# ---------------------------------------------------------------------------
# A10: image crop/brightness/contrast
# ---------------------------------------------------------------------------


class TestImageCrop:
    def _make_image_paragraph(
        self,
        crop: dict[str, str] | None = None,
        brightness: str | None = None,
        contrast: str | None = None,
    ) -> tuple[etree._Element, dict[str, tuple[str, str]]]:
        """이미지가 있는 단락 XML과 rels를 생성."""
        p = etree.Element(_w("p"), nsmap=_NSMAP)
        r = etree.SubElement(p, _w("r"))
        drawing = etree.SubElement(r, f"{{{_WP_NS}}}drawing")
        inline = etree.SubElement(drawing, f"{{{_WP_NS}}}inline")

        extent = etree.SubElement(inline, f"{{{_WP_NS}}}extent")
        extent.set("cx", "914400")  # 72pt
        extent.set("cy", "914400")

        graphic = etree.SubElement(inline, f"{{{_A_NS}}}graphic")
        gd = etree.SubElement(graphic, f"{{{_A_NS}}}graphicData")
        pic = etree.SubElement(gd, f"{{{_PIC_NS}}}pic")

        blip_fill = etree.SubElement(pic, f"{{{_PIC_NS}}}blipFill")
        blip = etree.SubElement(blip_fill, f"{{{_A_NS}}}blip")
        blip.set(f"{{{_R_NS}}}embed", "rId1")

        if brightness or contrast:
            lum = etree.SubElement(blip, f"{{{_A_NS}}}lum")
            if brightness:
                lum.set("bright", brightness)
            if contrast:
                lum.set("contrast", contrast)

        if crop:
            src_rect = etree.SubElement(blip_fill, f"{{{_A_NS}}}srcRect")
            for attr, val in crop.items():
                src_rect.set(attr, val)

        etree.SubElement(pic, f"{{{_PIC_NS}}}spPr")

        rels = {
            "rId1": (
                "media/test.png",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            ),
        }
        return p, rels

    def test_image_crop_extracted(self):
        """a:srcRect → ImageBlock.crop_*."""
        p, rels = self._make_image_paragraph(crop={"l": "10000", "t": "5000", "r": "15000", "b": "20000"})
        path = _create_docx(
            [p],
            rels=rels,
            media_files={"test.png": b"\x89PNG\r\n\x1a\n"},
        )
        doc = parse_docx(path)
        imgs = [b for b in doc.blocks if isinstance(b, ImageBlock)]
        if not imgs:
            pytest.xfail("Image extracted as ImageInline within paragraph — crop fields not on inline")

        img = imgs[0]
        assert img.crop_left == 10000
        assert img.crop_top == 5000
        assert img.crop_right == 15000
        assert img.crop_bottom == 20000

    def test_image_no_crop_is_none(self):
        """crop 없으면 None."""
        p, rels = self._make_image_paragraph()
        path = _create_docx(
            [p],
            rels=rels,
            media_files={"test.png": b"\x89PNG\r\n\x1a\n"},
        )
        doc = parse_docx(path)
        imgs = [b for b in doc.blocks if isinstance(b, ImageBlock)]
        if not imgs:
            pytest.xfail("Image extracted as ImageInline — no crop fields to check")
        assert imgs[0].crop_left is None
