"""sandbox schema v2 기본 동작 검증."""

import pytest

from udf.schema import (
    BlockFormat,
    Color,
    DocxExtension,
    DocumentMetadata,
    DocumentSchema,
    DrawingBlock,
    HeadingBlock,
    HwpExtension,
    HwpxExtension,
    ImageBlock,
    ListBlock,
    ListItem,
    PageBreakBlock,
    ParagraphBlock,
    PdfExtension,
    PositionInfo,
    Ratio,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
    TextInline,
    UnknownBlock,
    UnsupportedFeature,
    XmlExtension,
    create_extension,
    emu_to_pt,
    halfpt_to_pt,
    hwpunit_to_pt,
    mm_to_pt,
    pt_to_emu,
    pt_to_hwpunit,
    pt_to_mm,
    pt_to_twip,
    px_to_pt,
    twip_to_pt,
)
from udf.pipeline import (
    BlockLoss,
    LossCategory,
    LossReport,
    UdfDocument,
    VerbatimLayer,
)
from udf.pipeline.container import ConversionTrace, OriginalContainer
from udf.pipeline.verbatim import BorderFillDef, StyleDef


# ---------------------------------------------------------------------------
# types.py
# ---------------------------------------------------------------------------

class TestUnitConverters:
    """단위 변환 함수 검증."""

    def test_hwpunit_to_pt(self):
        assert hwpunit_to_pt(2400) == 24.0

    def test_pt_to_hwpunit(self):
        assert pt_to_hwpunit(24.0) == 2400

    def test_hwpunit_roundtrip(self):
        assert pt_to_hwpunit(hwpunit_to_pt(2400)) == 2400

    def test_emu_to_pt(self):
        assert emu_to_pt(12700) == 1.0

    def test_pt_to_emu(self):
        assert pt_to_emu(1.0) == 12700

    def test_emu_roundtrip(self):
        assert pt_to_emu(emu_to_pt(914400)) == 914400

    def test_halfpt_to_pt(self):
        assert halfpt_to_pt(24) == 12.0

    def test_twip_to_pt(self):
        assert twip_to_pt(20) == 1.0

    def test_twip_roundtrip(self):
        assert pt_to_twip(twip_to_pt(240)) == 240

    def test_mm_to_pt(self):
        assert abs(mm_to_pt(25.4) - 72.0) < 0.1

    def test_pt_to_mm(self):
        assert abs(pt_to_mm(72.0) - 25.4) < 0.1

    def test_px_to_pt_default_dpi(self):
        assert px_to_pt(96) == 72.0


class TestSchemaStoresPt:
    """스키마 필드는 항상 pt(float)로 저장되는지 검증."""

    def _roundtrip(self, fmt: BlockFormat) -> BlockFormat:
        return BlockFormat.model_validate(fmt.model_dump())

    def test_font_size_is_float(self):
        fmt = BlockFormat(font_size=12.0)
        assert fmt.font_size == 12.0
        restored = self._roundtrip(fmt)
        assert restored.font_size == 12.0

    def test_indent_is_float(self):
        fmt = BlockFormat(indent_left=mm_to_pt(10))
        restored = self._roundtrip(fmt)
        assert abs(restored.indent_left - mm_to_pt(10)) < 0.01

    def test_space_before_is_float(self):
        fmt = BlockFormat(space_before=twip_to_pt(240))
        restored = self._roundtrip(fmt)
        assert restored.space_before == 12.0

    def test_converter_used_in_schema(self):
        """파서가 변환 함수로 pt 값을 만들어 스키마에 넣는 패턴."""
        hwp_raw = 2400
        fmt = BlockFormat(font_size=hwpunit_to_pt(hwp_raw))
        assert fmt.font_size == 24.0


class TestColorSerialization:
    """Color 직렬화→역직렬화 시 hex 색상코드로 저장, RGBA 복원 검증."""

    def test_serializes_as_hex(self):
        ti = TextInline(text="x", color=Color(255, 0, 0))
        dumped = ti.model_dump()
        assert dumped["color"] == "#ff0000"

    def test_rgb_preserves(self):
        ti = TextInline(text="x", color=Color(10, 20, 30))
        restored = TextInline.model_validate(ti.model_dump())
        assert restored.color.r == 10
        assert restored.color.g == 20
        assert restored.color.b == 30
        assert restored.color.a == 1.0

    def test_alpha_preserves(self):
        ti = TextInline(text="x", color=Color(255, 0, 0, 0.5))
        dumped = ti.model_dump()
        assert dumped["color"] == "#ff000080"
        restored = TextInline.model_validate(dumped)
        assert restored.color.a == pytest.approx(128 / 255, abs=0.01)

    def test_bgr_roundtrip(self):
        original = Color.from_bgr(0x00FF00)
        ti = TextInline(text="x", color=original)
        restored = TextInline.model_validate(ti.model_dump())
        assert restored.color == original


class TestRatioSerialization:
    def test_ratio_preserves(self):
        fmt = BlockFormat(line_spacing=Ratio(160))
        restored = BlockFormat.model_validate(fmt.model_dump())
        assert isinstance(restored.line_spacing, Ratio)
        assert restored.line_spacing.percent == 160

    def test_ratio_serializes_as_dict(self):
        fmt = BlockFormat(line_spacing=Ratio(160))
        data = fmt.model_dump()
        assert data["line_spacing"] == {"percent": 160}

    def test_float_vs_ratio_in_line_spacing(self):
        """line_spacing이 float(pt)일 때와 Ratio(%)일 때 구분."""
        fmt_fixed = BlockFormat(line_spacing=14.0, line_spacing_type="fixed")
        fmt_ratio = BlockFormat(line_spacing=Ratio(160), line_spacing_type="ratio")
        d_fixed = fmt_fixed.model_dump()
        d_ratio = fmt_ratio.model_dump()
        assert isinstance(d_fixed["line_spacing"], float)
        assert isinstance(d_ratio["line_spacing"], dict)


class TestColor:
    def test_from_hex(self):
        c = Color.from_hex("#ff0000")
        assert c.r == 255 and c.g == 0 and c.b == 0

    def test_to_hex(self):
        assert Color(255, 0, 0).to_hex() == "#ff0000"

    def test_from_bgr(self):
        c = Color.from_bgr(0x00FF00)
        assert c.r == 0 and c.g == 255 and c.b == 0

    def test_equality(self):
        assert Color(10, 20, 30) == Color(10, 20, 30)
        assert Color(10, 20, 30) != Color(10, 20, 31)

    def test_from_hex_with_alpha(self):
        c = Color.from_hex("#ff000080")
        assert c.a == pytest.approx(128 / 255, abs=0.01)


class TestRatio:
    def test_percent(self):
        r = Ratio(160)
        assert r.percent == 160
        assert r.factor == pytest.approx(1.6)

    def test_equality(self):
        assert Ratio(160) == Ratio(160)
        assert Ratio(160) != Ratio(150)


# ---------------------------------------------------------------------------
# blocks + inlines
# ---------------------------------------------------------------------------

class TestBlocks:
    def test_heading_text_content(self):
        h = HeadingBlock(id="b_0001", level=1, text="제목")
        assert h.text_content() == "제목"

    def test_paragraph_text_content(self):
        p = ParagraphBlock(
            id="b_0002",
            inlines=[
                TextInline(text="hello "),
                TextInline(text="world", bold=True),
            ],
        )
        assert p.text_content() == "hello world"

    def test_heading_no_level_constraint(self):
        """v2에서는 level 범위 제약이 없음 — 검증 레이어로 분리."""
        h = HeadingBlock(id="b_0001", level=10, text="HWP 개요 10")
        assert h.level == 10

    def test_table_text_content(self):
        t = TableBlock(
            id="b_0003",
            rows=[
                TableRow(cells=[
                    TableCell(id="c_01", content=[
                        ParagraphBlock(id="b_0004", inlines=[TextInline(text="A")])
                    ]),
                    TableCell(id="c_02", content=[
                        ParagraphBlock(id="b_0005", inlines=[TextInline(text="B")])
                    ]),
                ])
            ],
        )
        assert t.text_content() == "A B"

    def test_list_text_content(self):
        lb = ListBlock(
            id="b_0006",
            ordered=True,
            items=[
                ListItem(id="li_01", inlines=[TextInline(text="첫째")]),
                ListItem(id="li_02", inlines=[TextInline(text="둘째")]),
            ],
        )
        assert lb.text_content() == "첫째\n둘째"

    def test_image_text_content(self):
        img = ImageBlock(id="b_0007", src="photo.jpg", alt="사진")
        assert img.text_content() == "사진"

    def test_page_break_text_content(self):
        pb = PageBreakBlock(id="b_0008")
        assert pb.text_content() == ""


# ---------------------------------------------------------------------------
# formats
# ---------------------------------------------------------------------------

class TestFormats:
    def test_block_format_with_pt(self):
        fmt = BlockFormat(
            font_size=12.0,
            line_spacing=Ratio(160),
            indent_left=mm_to_pt(10),
        )
        assert fmt.font_size == 12.0
        assert fmt.line_spacing == Ratio(160)

    def test_text_inline_with_color(self):
        ti = TextInline(
            text="빨간 글씨",
            color=Color.from_hex("#ff0000"),
            font_size=14.0,
        )
        assert ti.color.to_hex() == "#ff0000"
        assert ti.font_size == 14.0


# ---------------------------------------------------------------------------
# DocumentSchema
# ---------------------------------------------------------------------------

class TestDocumentSchema:
    def test_empty_document(self):
        doc = DocumentSchema()
        assert doc.blocks == []
        assert doc.metadata.title is None

    def test_document_with_blocks(self):
        doc = DocumentSchema(
            metadata=DocumentMetadata(title="테스트 문서"),
            blocks=[
                HeadingBlock(id="b_0001", level=1, text="제목"),
                ParagraphBlock(
                    id="b_0002",
                    inlines=[TextInline(text="본문")],
                ),
            ],
        )
        assert len(doc.blocks) == 2
        assert doc.metadata.title == "테스트 문서"

    def test_all_text_content(self):
        doc = DocumentSchema(
            blocks=[
                HeadingBlock(id="b_0001", level=1, text="제목"),
                ParagraphBlock(
                    id="b_0002",
                    inlines=[TextInline(text="본문 내용")],
                ),
            ],
        )
        full_text = "\n".join(b.text_content() for b in doc.blocks)
        assert "제목" in full_text
        assert "본문 내용" in full_text


# ---------------------------------------------------------------------------
# UdfDocument — schema + pipeline 조립
# ---------------------------------------------------------------------------

class TestUdfDocument:
    def test_schema_and_pipeline_separated(self):
        schema = DocumentSchema(
            metadata=DocumentMetadata(title="분리된 문서"),
            blocks=[
                HeadingBlock(id="b_0001", level=1, text="제목"),
            ],
        )
        doc = UdfDocument(
            source_format="hwp",
            document=schema,
            verbatim=VerbatimLayer(format="hwp", version="5.1"),
        )
        assert doc.document.metadata.title == "분리된 문서"
        assert doc.document.blocks[0].text_content() == "제목"
        assert doc.verbatim.format == "hwp"
        assert doc.udf == "1.0"

    def test_document_without_verbatim(self):
        """Builder나 from-scratch에서는 verbatim이 없을 수 있음."""
        doc = UdfDocument(
            source_format="udf",
            document=DocumentSchema(
                blocks=[ParagraphBlock(id="b_0001", inlines=[TextInline(text="새 문서")])],
            ),
        )
        assert doc.verbatim is None
        assert doc.document.blocks[0].text_content() == "새 문서"


# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------

class TestHwpExtension:
    def test_create_empty(self):
        ext = HwpExtension()
        assert ext.format == "hwp"
        assert ext.inline_text == {}
        assert ext.blocks == {}
        assert ext.positions == {}

    def test_inline_text_ext(self):
        ext = HwpExtension(
            inline_text={
                "b_0001:0": HwpExtension.TextExt(emboss=True),
                "b_0001:2": HwpExtension.TextExt(engrave=True),
            },
        )
        assert ext.inline_text["b_0001:0"].emboss is True
        assert ext.inline_text["b_0001:2"].engrave is True

    def test_inline_equation_ext(self):
        ext = HwpExtension(
            inline_equations={
                "b_0010:0": HwpExtension.EquationExt(hwp_script="LEFT { a+b }"),
            },
        )
        assert ext.inline_equations["b_0010:0"].hwp_script == "LEFT { a+b }"

    def test_block_ext(self):
        ext = HwpExtension(
            blocks={
                "b_0001": HwpExtension.BlockExt(
                    char_shape_id=3, para_shape_id=1, border_fill_id=5,
                ),
            },
        )
        assert ext.blocks["b_0001"].char_shape_id == 3
        assert ext.blocks["b_0001"].border_fill_id == 5

    def test_position_ext(self):
        ext = HwpExtension(
            positions={
                "b_0020": HwpExtension.PositionExt(
                    like_char=True,
                    width_relto="column",
                    restrict_in_page=True,
                ),
            },
        )
        assert ext.positions["b_0020"].like_char is True
        assert ext.positions["b_0020"].width_relto == "column"

    def test_serialization_roundtrip(self):
        ext = HwpExtension(
            inline_text={"b_0001:0": HwpExtension.TextExt(emboss=True)},
            blocks={"b_0001": HwpExtension.BlockExt(char_shape_id=7)},
            positions={"b_0002": HwpExtension.PositionExt(like_char=False)},
        )
        data = ext.model_dump()
        restored = HwpExtension.model_validate(data)
        assert restored.inline_text["b_0001:0"].emboss is True
        assert restored.blocks["b_0001"].char_shape_id == 7
        assert restored.positions["b_0002"].like_char is False


class TestPdfExtension:
    def test_image_ext(self):
        ext = PdfExtension(
            images={
                "b_0050": PdfExtension.ImageExt(
                    crop_left=10, crop_top=20, brightness=80,
                ),
            },
        )
        assert ext.images["b_0050"].crop_left == 10
        assert ext.images["b_0050"].brightness == 80

    def test_serialization_roundtrip(self):
        ext = PdfExtension(
            images={"b_0001": PdfExtension.ImageExt(contrast=120)},
        )
        data = ext.model_dump()
        restored = PdfExtension.model_validate(data)
        assert restored.images["b_0001"].contrast == 120


class TestXmlExtension:
    def test_is_base_of_docx(self):
        assert issubclass(DocxExtension, XmlExtension)

    def test_is_base_of_hwpx(self):
        assert issubclass(HwpxExtension, XmlExtension)

    def test_not_base_of_hwp(self):
        assert not issubclass(HwpExtension, XmlExtension)

    def test_namespaces(self):
        ext = HwpxExtension(
            namespaces={
                "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
                "hc": "http://www.hancom.co.kr/hwpml/2011/core",
            },
        )
        assert ext.namespaces["hp"].endswith("/paragraph")

    def test_unknown_elements_preserved(self):
        ext = DocxExtension(
            unknown_elements={
                "b_0001": [
                    XmlExtension.UnknownElement(
                        tag="{http://example.com}custom",
                        xml='<custom xmlns="http://example.com">data</custom>',
                    ),
                ],
            },
        )
        assert len(ext.unknown_elements["b_0001"]) == 1
        assert ext.unknown_elements["b_0001"][0].tag.endswith("}custom")


class TestHwpxExtension:
    def test_create_empty(self):
        ext = HwpxExtension()
        assert ext.format == "hwpx"
        assert ext.namespaces == {}

    def test_inline_text_ext(self):
        ext = HwpxExtension(
            inline_text={"b_0001:0": HwpxExtension.TextExt(emboss=True)},
        )
        assert ext.inline_text["b_0001:0"].emboss is True

    def test_block_ext_idref(self):
        ext = HwpxExtension(
            blocks={
                "b_0001": HwpxExtension.BlockExt(
                    char_pr_id_ref=3, para_pr_id_ref=1, style_id_ref=0, border_fill_id_ref=5,
                ),
            },
        )
        assert ext.blocks["b_0001"].char_pr_id_ref == 3
        assert ext.blocks["b_0001"].style_id_ref == 0

    def test_image_ref_ext(self):
        ext = HwpxExtension(
            image_refs={"b_0010": HwpxExtension.ImageRefExt(bin_item_id_ref="IMG01")},
        )
        assert ext.image_refs["b_0010"].bin_item_id_ref == "IMG01"

    def test_serialization_roundtrip(self):
        ext = HwpxExtension(
            namespaces={"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"},
            inline_equations={"b_0002:0": HwpxExtension.EquationExt(hwp_script="sqrt{2}")},
            blocks={"b_0001": HwpxExtension.BlockExt(char_pr_id_ref=7)},
            image_refs={"b_0010": HwpxExtension.ImageRefExt(bin_item_id_ref="BIN0001")},
        )
        data = ext.model_dump()
        restored = HwpxExtension.model_validate(data)
        assert restored.namespaces["hp"].endswith("/paragraph")
        assert restored.inline_equations["b_0002:0"].hwp_script == "sqrt{2}"
        assert restored.blocks["b_0001"].char_pr_id_ref == 7
        assert restored.image_refs["b_0010"].bin_item_id_ref == "BIN0001"


class TestDocxExtension:
    def test_create_empty(self):
        ext = DocxExtension()
        assert ext.format == "docx"
        assert ext.namespaces == {}

    def test_revision_ext(self):
        ext = DocxExtension(
            revisions={
                "b_0001:0": DocxExtension.RevisionExt(
                    author="홍길동", date="2026-05-24", revision_type="insert",
                ),
            },
        )
        assert ext.revisions["b_0001:0"].author == "홍길동"
        assert ext.revisions["b_0001:0"].revision_type == "insert"

    def test_content_control_ext(self):
        ext = DocxExtension(
            content_controls={
                "b_0005": DocxExtension.ContentControlExt(tag="name_field", alias="이름"),
            },
        )
        assert ext.content_controls["b_0005"].tag == "name_field"

    def test_compat_ext(self):
        ext = DocxExtension(
            compat=DocxExtension.CompatExt(space_for_ul=True),
        )
        assert ext.compat.space_for_ul is True

    def test_serialization_roundtrip(self):
        ext = DocxExtension(
            namespaces={"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"},
            revisions={"b_0001:0": DocxExtension.RevisionExt(author="user", revision_type="delete")},
            content_controls={"b_0005": DocxExtension.ContentControlExt(tag="field")},
        )
        data = ext.model_dump()
        restored = DocxExtension.model_validate(data)
        assert restored.namespaces["w"].endswith("/main")
        assert restored.revisions["b_0001:0"].revision_type == "delete"
        assert restored.content_controls["b_0005"].tag == "field"

    def test_inherits_xml_unknown_elements(self):
        ext = DocxExtension(
            unknown_elements={"b_0001": [XmlExtension.UnknownElement(tag="x", xml="<x/>")]},
        )
        assert len(ext.unknown_elements["b_0001"]) == 1


class TestCreateExtension:
    def test_create_hwp(self):
        ext = create_extension("hwp")
        assert isinstance(ext, HwpExtension)

    def test_create_hwpx(self):
        ext = create_extension("hwpx")
        assert isinstance(ext, HwpxExtension)

    def test_create_pdf(self):
        ext = create_extension("pdf")
        assert isinstance(ext, PdfExtension)

    def test_create_docx(self):
        ext = create_extension("docx")
        assert isinstance(ext, DocxExtension)

    def test_unknown_format_raises(self):
        import pytest
        with pytest.raises(ValueError, match="Unknown format"):
            create_extension("xlsx")


class TestUdfDocumentWithExtensions:
    def test_hwp_extension_attached(self):
        doc = UdfDocument(
            source_format="hwp",
            document=DocumentSchema(
                blocks=[
                    ParagraphBlock(
                        id="b_0001",
                        inlines=[
                            TextInline(text="양각 텍스트"),
                        ],
                    ),
                ],
            ),
            extensions={
                "hwp": HwpExtension(
                    inline_text={
                        "b_0001:0": HwpExtension.TextExt(emboss=True),
                    },
                ),
            },
        )
        hwp_ext = doc.extensions["hwp"]
        assert isinstance(hwp_ext, HwpExtension)
        assert hwp_ext.inline_text["b_0001:0"].emboss is True

    def test_extension_json_roundtrip(self):
        doc = UdfDocument(
            source_format="hwp",
            extensions={
                "hwp": HwpExtension(
                    blocks={"b_0001": HwpExtension.BlockExt(char_shape_id=5)},
                    positions={"b_0002": HwpExtension.PositionExt(like_char=True)},
                ),
            },
        )
        data = doc.model_dump()
        restored = UdfDocument.model_validate(data)
        hwp = restored.extensions["hwp"]
        assert isinstance(hwp, HwpExtension)
        assert hwp.blocks["b_0001"].char_shape_id == 5
        assert hwp.positions["b_0002"].like_char is True

    def test_multiple_extensions(self):
        doc = UdfDocument(
            source_format="hwp",
            extensions={
                "hwp": HwpExtension(
                    inline_text={"b_0001:0": HwpExtension.TextExt(emboss=True)},
                ),
                "pdf": PdfExtension(
                    images={"b_0010": PdfExtension.ImageExt(crop_left=5)},
                ),
            },
        )
        assert isinstance(doc.extensions["hwp"], HwpExtension)
        assert isinstance(doc.extensions["pdf"], PdfExtension)


# ---------------------------------------------------------------------------
# C2: UnsupportedFeature + BlockBase verbatim_ref/unsupported
# ---------------------------------------------------------------------------

class TestUnsupportedFeature:

    def test_create(self):
        uf = UnsupportedFeature(feature="pdf.vector_chart", reason="not representable")
        assert uf.feature == "pdf.vector_chart"
        assert uf.reason == "not representable"
        assert uf.value is None

    def test_minimal(self):
        uf = UnsupportedFeature(feature="emboss")
        assert uf.feature == "emboss"

    def test_serialization_roundtrip(self):
        uf = UnsupportedFeature(feature="x", value="y", reason="z")
        data = uf.model_dump()
        restored = UnsupportedFeature.model_validate(data)
        assert restored.feature == "x"
        assert restored.value == "y"
        assert restored.reason == "z"


class TestBlockBaseFields:

    def test_paragraph_with_verbatim_ref(self):
        p = ParagraphBlock(id="b_001", verbatim_ref="vb_001")
        assert p.verbatim_ref == "vb_001"

    def test_heading_with_unsupported(self):
        h = HeadingBlock(
            id="b_002", level=1, text="제목",
            unsupported=UnsupportedFeature(feature="custom_numbering"),
        )
        assert h.unsupported.feature == "custom_numbering"

    def test_default_none(self):
        p = ParagraphBlock(id="b_003")
        assert p.verbatim_ref is None
        assert p.unsupported is None

    def test_table_cell_verbatim_ref(self):
        cell = TableCell(id="c_001", verbatim_ref="vc_001")
        assert cell.verbatim_ref == "vc_001"

    def test_table_cell_unsupported(self):
        cell = TableCell(
            id="c_002",
            unsupported=UnsupportedFeature(feature="diagonal_border"),
        )
        assert cell.unsupported.feature == "diagonal_border"

    def test_list_item_verbatim_ref(self):
        item = ListItem(id="li_001", verbatim_ref="vl_001")
        assert item.verbatim_ref == "vl_001"

    def test_serialization_roundtrip(self):
        p = ParagraphBlock(
            id="b_004",
            verbatim_ref="vb_004",
            unsupported=UnsupportedFeature(feature="x", value="1"),
        )
        data = p.model_dump()
        restored = ParagraphBlock.model_validate(data)
        assert restored.verbatim_ref == "vb_004"
        assert restored.unsupported.feature == "x"


# ---------------------------------------------------------------------------
# C1: UnknownBlock
# ---------------------------------------------------------------------------

class TestUnknownBlock:

    def test_create(self):
        ub = UnknownBlock(id="b_099", raw_bytes="deadbeef")
        assert ub.type == "unknown"
        assert ub.raw_bytes == "deadbeef"

    def test_text_content(self):
        ub = UnknownBlock(id="b_099", raw_bytes="ff")
        assert ub.text_content() == ""

    def test_with_description(self):
        ub = UnknownBlock(id="b_099", raw_bytes="ff", description="unrecognized CTRL")
        assert ub.description == "unrecognized CTRL"

    def test_in_document(self):
        doc = DocumentSchema(
            blocks=[UnknownBlock(id="b_001", raw_bytes="aa")],
        )
        assert len(doc.blocks) == 1
        assert doc.blocks[0].type == "unknown"

    def test_discriminator_roundtrip(self):
        doc = DocumentSchema(
            blocks=[UnknownBlock(id="b_001", raw_bytes="bb")],
        )
        data = doc.model_dump()
        restored = DocumentSchema.model_validate(data)
        assert isinstance(restored.blocks[0], UnknownBlock)
        assert restored.blocks[0].raw_bytes == "bb"

    def test_inherits_verbatim_ref(self):
        ub = UnknownBlock(id="b_099", raw_bytes="cc", verbatim_ref="vb_099")
        assert ub.verbatim_ref == "vb_099"


# ---------------------------------------------------------------------------
# C3: ImageBlock crop/brightness/contrast
# ---------------------------------------------------------------------------

class TestImageBlockCrop:

    def test_with_crop(self):
        img = ImageBlock(
            id="b_010", src="photo.jpg",
            crop_left=10, crop_top=20, crop_right=30, crop_bottom=40,
            brightness=5, contrast=-3,
        )
        assert img.crop_left == 10
        assert img.crop_bottom == 40
        assert img.brightness == 5
        assert img.contrast == -3

    def test_defaults_none(self):
        img = ImageBlock(id="b_010", src="photo.jpg")
        assert img.crop_left is None
        assert img.brightness is None
        assert img.contrast is None

    def test_roundtrip(self):
        img = ImageBlock(
            id="b_010", src="x.png",
            crop_left=100, crop_top=200, crop_right=300, crop_bottom=400,
            brightness=10, contrast=20,
        )
        data = img.model_dump()
        restored = ImageBlock.model_validate(data)
        assert restored.crop_left == 100
        assert restored.brightness == 10
        assert restored.contrast == 20


# ---------------------------------------------------------------------------
# C4: TextInline emboss/engrave
# ---------------------------------------------------------------------------

class TestTextInlineEmbossEngrave:

    def test_emboss(self):
        t = TextInline(type="text", text="양각", emboss=True)
        assert t.emboss is True

    def test_engrave(self):
        t = TextInline(type="text", text="음각", engrave=True)
        assert t.engrave is True

    def test_default_none(self):
        t = TextInline(type="text", text="일반")
        assert t.emboss is None
        assert t.engrave is None

    def test_roundtrip(self):
        t = TextInline(type="text", text="x", emboss=True, engrave=False)
        data = t.model_dump()
        restored = TextInline.model_validate(data)
        assert restored.emboss is True
        assert restored.engrave is False


# ---------------------------------------------------------------------------
# I1: PositionInfo.like_char
# ---------------------------------------------------------------------------

class TestPositionInfoLikeChar:

    def test_like_char_true(self):
        pos = PositionInfo(like_char=True, x=10.0, y=20.0)
        assert pos.like_char is True

    def test_like_char_false(self):
        pos = PositionInfo(like_char=False)
        assert pos.like_char is False

    def test_default_none(self):
        pos = PositionInfo()
        assert pos.like_char is None

    def test_roundtrip(self):
        pos = PositionInfo(like_char=True, flow="float", width=100.0)
        data = pos.model_dump()
        restored = PositionInfo.model_validate(data)
        assert restored.like_char is True
        assert restored.flow == "float"


# ---------------------------------------------------------------------------
# I2: TextBoxBlock/DrawingBlock styling
# ---------------------------------------------------------------------------

class TestTextBoxBlockStyling:

    def test_full_styling(self):
        tb = TextBoxBlock(
            id="b_020",
            padding_top=5.0, padding_bottom=5.0,
            padding_left=10.0, padding_right=10.0,
            vertical_align="middle",
            background_color="#ff0000",
            background_image="bg.png",
            line_color="#000000",
            line_width=0.5,
            border_radius=3.0,
        )
        assert tb.padding_top == 5.0
        assert tb.vertical_align == "middle"
        assert tb.background_image == "bg.png"
        assert tb.line_color == "#000000"
        assert tb.line_width == 0.5
        assert tb.border_radius == 3.0

    def test_defaults_none(self):
        tb = TextBoxBlock(id="b_021")
        assert tb.padding_top is None
        assert tb.vertical_align is None
        assert tb.line_color is None

    def test_roundtrip(self):
        tb = TextBoxBlock(
            id="b_022", line_color="#333", line_width=1.0,
            background_image="x.jpg", border_radius=5.0,
        )
        data = tb.model_dump()
        restored = TextBoxBlock.model_validate(data)
        assert restored.line_color == "#333"
        assert restored.border_radius == 5.0


class TestDrawingBlockStyling:

    def test_styling(self):
        d = DrawingBlock(
            id="b_030", shape_type="$rec",
            background_color="#ffffff",
            line_color="#000000",
            line_width=0.25,
        )
        assert d.background_color == "#ffffff"
        assert d.line_color == "#000000"
        assert d.line_width == 0.25

    def test_defaults_none(self):
        d = DrawingBlock(id="b_031")
        assert d.background_color is None
        assert d.line_color is None
        assert d.line_width is None

    def test_roundtrip(self):
        d = DrawingBlock(
            id="b_032", background_color="#eee", line_width=2.0,
        )
        data = d.model_dump()
        restored = DrawingBlock.model_validate(data)
        assert restored.background_color == "#eee"
        assert restored.line_width == 2.0


# ---------------------------------------------------------------------------
# I3: DocumentMetadata start_*_number
# ---------------------------------------------------------------------------

class TestDocumentMetadataStartNumbers:

    def test_with_start_numbers(self):
        meta = DocumentMetadata(
            start_page_number=3,
            start_footnote_number=1,
            start_endnote_number=1,
            start_picture_number=1,
            start_table_number=1,
            start_equation_number=1,
        )
        assert meta.start_page_number == 3
        assert meta.start_equation_number == 1

    def test_defaults_none(self):
        meta = DocumentMetadata()
        assert meta.start_page_number is None
        assert meta.start_footnote_number is None
        assert meta.start_endnote_number is None
        assert meta.start_picture_number is None
        assert meta.start_table_number is None
        assert meta.start_equation_number is None

    def test_roundtrip(self):
        meta = DocumentMetadata(start_page_number=5, start_table_number=10)
        data = meta.model_dump()
        restored = DocumentMetadata.model_validate(data)
        assert restored.start_page_number == 5
        assert restored.start_table_number == 10


# ---------------------------------------------------------------------------
# I5: StyleDef.format
# ---------------------------------------------------------------------------

class TestPipelineStyleDef:

    def test_with_format(self):
        sd = StyleDef(
            id="s1", name="Normal",
            format=BlockFormat(font_size=12.0, font_name="맑은 고딕"),
        )
        assert sd.format.font_size == 12.0
        assert sd.format.font_name == "맑은 고딕"

    def test_format_default_none(self):
        sd = StyleDef(id="s2", name="Heading 1")
        assert sd.format is None

    def test_roundtrip(self):
        sd = StyleDef(
            id="s3", name="Body",
            style_type="paragraph",
            format=BlockFormat(alignment="justify", line_spacing=1.5),
        )
        data = sd.model_dump()
        restored = StyleDef.model_validate(data)
        assert restored.format.alignment == "justify"


# ---------------------------------------------------------------------------
# I7: BorderFillDef directional borders
# ---------------------------------------------------------------------------

class TestPipelineBorderFillDef:

    def test_directional_borders(self):
        bf = BorderFillDef(
            id="bf1",
            border_left_color="#000", border_left_style="solid", border_left_width=0.5,
            border_right_color="#000", border_right_style="solid", border_right_width=0.5,
            border_top_color="#333", border_top_style="double", border_top_width=1.0,
            border_bottom_color="#333", border_bottom_style="double", border_bottom_width=1.0,
            fill_color="#ffffff",
        )
        assert bf.border_left_color == "#000"
        assert bf.border_top_style == "double"
        assert bf.border_bottom_width == 1.0

    def test_defaults_none(self):
        bf = BorderFillDef(id="bf2")
        assert bf.border_left_color is None
        assert bf.border_top_width is None

    def test_roundtrip(self):
        bf = BorderFillDef(
            id="bf3",
            border_left_color="#f00", border_left_width=2.0,
            border_right_color="#00f",
        )
        data = bf.model_dump()
        restored = BorderFillDef.model_validate(data)
        assert restored.border_left_color == "#f00"
        assert restored.border_left_width == 2.0
        assert restored.border_right_color == "#00f"


# ---------------------------------------------------------------------------
# I6: UdfDocument.loss_report
# ---------------------------------------------------------------------------

class TestUdfDocumentLossReport:

    def test_with_loss_report(self):
        report = LossReport(
            total_blocks=10,
            lossless_blocks=8,
            lossy_blocks=[
                BlockLoss(
                    block_id="b_005",
                    loss_type=LossCategory.FORMAT_LIMIT,
                    description="vector graphics not representable",
                ),
            ],
            dropped_features=["vector_chart"],
            is_roundtrip_safe=False,
        )
        doc = UdfDocument(
            source_format="pdf",
            loss_report=report,
        )
        assert doc.loss_report is not None
        assert doc.loss_report.total_blocks == 10
        assert len(doc.loss_report.lossy_blocks) == 1
        assert doc.loss_report.is_roundtrip_safe is False

    def test_default_none(self):
        doc = UdfDocument(source_format="hwp")
        assert doc.loss_report is None

    def test_roundtrip(self):
        doc = UdfDocument(
            source_format="pdf",
            loss_report=LossReport(
                total_blocks=5,
                lossless_blocks=5,
                is_roundtrip_safe=True,
            ),
        )
        data = doc.model_dump()
        restored = UdfDocument.model_validate(data)
        assert restored.loss_report.is_roundtrip_safe is True
        assert restored.loss_report.lossless_blocks == 5


# ---------------------------------------------------------------------------
# L1: Pipeline 단위 테스트
# ---------------------------------------------------------------------------

class TestPipelineLoss:

    def test_loss_category_values(self):
        assert LossCategory.USER_EDITED.value == "user_edited"
        assert LossCategory.FORMAT_LIMIT.value == "format_limit"
        assert LossCategory.UNINTENDED.value == "unintended"

    def test_block_loss(self):
        bl = BlockLoss(
            block_id="b_001",
            loss_type=LossCategory.FORMAT_LIMIT,
            description="image crop not supported",
        )
        assert bl.block_id == "b_001"
        assert bl.loss_type == LossCategory.FORMAT_LIMIT

    def test_loss_report_roundtrip(self):
        report = LossReport(
            total_blocks=20,
            lossless_blocks=18,
            lossy_blocks=[
                BlockLoss(block_id="b_01", loss_type=LossCategory.UNINTENDED, description="d1"),
                BlockLoss(block_id="b_02", loss_type=LossCategory.USER_EDITED, description="d2"),
            ],
            dropped_features=["emboss", "engrave"],
            is_roundtrip_safe=False,
        )
        data = report.model_dump()
        restored = LossReport.model_validate(data)
        assert restored.total_blocks == 20
        assert len(restored.lossy_blocks) == 2
        assert restored.dropped_features == ["emboss", "engrave"]


class TestPipelineContainer:

    def test_original_container(self):
        oc = OriginalContainer(format="ole2", path="/tmp/test.hwp", checksum="abc123")
        assert oc.format == "ole2"
        assert oc.checksum == "abc123"

    def test_conversion_trace(self):
        ct = ConversionTrace(
            parsed_at="2026-05-24T12:00:00",
            parser_version="0.1.0",
            checksum="sha256:xyz",
        )
        assert ct.parser_version == "0.1.0"

    def test_container_roundtrip(self):
        oc = OriginalContainer(format="zip", path="/tmp/test.hwpx", checksum="def456")
        data = oc.model_dump()
        restored = OriginalContainer.model_validate(data)
        assert restored.format == "zip"
        assert restored.path == "/tmp/test.hwpx"


class TestPipelineVerbatimLayer:

    def test_full_roundtrip(self):
        vl = VerbatimLayer(
            format="hwp",
            version="5.1",
            block_mapping={"b_001": "section0:p0"},
        )
        data = vl.model_dump()
        restored = VerbatimLayer.model_validate(data)
        assert restored.format == "hwp"
        assert restored.block_mapping["b_001"] == "section0:p0"

    def test_with_resources(self):
        from udf.pipeline.verbatim import GlobalResources
        vl = VerbatimLayer(
            format="hwp",
            global_resources=GlobalResources(
                styles={"s1": StyleDef(id="s1", name="Normal", format=BlockFormat(font_size=10.0))},
                border_fills={"bf1": BorderFillDef(id="bf1", border_left_color="#000")},
            ),
        )
        assert vl.global_resources.styles["s1"].format.font_size == 10.0
        assert vl.global_resources.border_fills["bf1"].border_left_color == "#000"
