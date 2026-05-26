"""udf.core.schema — Pydantic v2 스키마 단위 테스트"""

import json

import pytest

from udf.core.schema import (
    BlockFormat,
    BorderFillDef,
    BulletDef,
    ColumnDef,
    DrawingBlock,
    EndnoteBlock,
    FieldBlock,
    FooterBlock,
    FootnoteRefInline,
    GlobalResources,
    HeaderBlock,
    LinkInline,
    ListBlock,
    LossCategory,
    LossReport,
    NumberingDef,
    NumberingLevel,
    ParagraphBlock,
    SectionDef,
    StyleDef,
    TextBoxBlock,
    TextInline,
    UdfDocument,
    FontFallbacks,
    DocumentMetadata,
)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def roundtrip(model_class, data: dict):
    """dict → 모델 → JSON → 모델 왕복 검증."""
    obj = model_class.model_validate(data)
    raw = obj.model_dump_json(by_alias=True, exclude_none=True)
    obj2 = model_class.model_validate_json(raw)
    assert obj == obj2
    return obj


# ---------------------------------------------------------------------------
# S6: Inline discriminated union
# ---------------------------------------------------------------------------


class TestInlineDiscriminatedUnion:
    def test_text_inline_type_field(self):
        t = TextInline(text="hello")
        assert t.type == "text"

    def test_link_inline(self):
        obj = roundtrip(
            ParagraphBlock,
            {
                "type": "paragraph",
                "id": "b_0001",
                "inlines": [
                    {"type": "link", "text": "링크", "url": "https://example.com"}
                ],
            },
        )
        assert obj.inlines[0].url == "https://example.com"

    def test_image_inline(self):
        obj = roundtrip(
            ParagraphBlock,
            {
                "type": "paragraph",
                "id": "b_0001",
                "inlines": [{"type": "image_inline", "src": "img.png", "alt": "그림"}],
            },
        )
        assert obj.inlines[0].src == "img.png"

    def test_footnote_ref_inline(self):
        obj = roundtrip(
            ParagraphBlock,
            {
                "type": "paragraph",
                "id": "b_0001",
                "inlines": [{"type": "footnote_ref", "refId": "fn1", "number": 1}],
            },
        )
        assert obj.inlines[0].ref_id == "fn1"

    def test_mixed_inlines(self):
        para = ParagraphBlock(
            type="paragraph",
            id="b_0001",
            inlines=[
                TextInline(text="일반"),
                TextInline(text="굵게", bold=True),
                LinkInline(text="링크", url="https://example.com"),
                FootnoteRefInline(ref_id="fn1"),
            ],
        )
        raw = para.model_dump(by_alias=True, exclude_none=True)
        types = [i["type"] for i in raw["inlines"]]
        assert types == ["text", "text", "link", "footnote_ref"]


# ---------------------------------------------------------------------------
# S1: TextInline 확장 — exclude_none 출력 검증
# ---------------------------------------------------------------------------


class TestTextInlineExcludeNone:
    def test_plain_text_no_noise(self):
        t = TextInline(text="일반")
        raw = json.loads(t.model_dump_json(by_alias=True, exclude_none=True))
        # type 필드와 text만 있어야 함
        assert set(raw.keys()) == {"type", "text"}

    def test_bold_only(self):
        t = TextInline(text="굵게", bold=True)
        raw = json.loads(t.model_dump_json(by_alias=True, exclude_none=True))
        assert raw["bold"] is True
        assert "italic" not in raw
        assert "underline" not in raw

    def test_s1_fields(self):
        from udf.schema.types import Ratio

        t = TextInline(
            text="수식",
            superscript=True,
            underline_type="wave",
            underline_color="#FF0000",
            char_scale=Ratio(80),
            letter_spacing=-5.0,
        )
        raw = json.loads(t.model_dump_json(by_alias=True, exclude_none=True))
        assert raw["superscript"] is True
        assert raw["underlineType"] == "wave"
        assert raw["underlineColor"] == "#ff0000"
        assert raw["charScale"] == {"percent": 80}
        assert raw["letterSpacing"] == -5.0

    def test_hwp_exclusive_flags(self):
        t = TextInline(text="양각", emboss=True, engrave=False)
        raw = json.loads(t.model_dump_json(by_alias=True, exclude_none=True))
        assert raw["emboss"] is True
        # engrave=False는 None이 아니므로 포함됨
        assert raw["engrave"] is False


# ---------------------------------------------------------------------------
# S2: BlockFormat 확장
# ---------------------------------------------------------------------------


class TestBlockFormat:
    def test_outline_level_range(self):
        # 유효 범위 0~7
        for lvl in range(8):
            fmt = BlockFormat(outline_level=lvl)
            assert fmt.outline_level == lvl

    def test_outline_level_no_constraint(self):
        fmt = BlockFormat(outline_level=8)
        assert fmt.outline_level == 8

    def test_s2_fields(self):
        fmt = BlockFormat(
            text_direction="vertical",
            keep_with_next=True,
            line_spacing_type="fixed",
            drop_cap_lines=3,
        )
        raw = json.loads(fmt.model_dump_json(by_alias=True, exclude_none=True))
        assert raw["textDirection"] == "vertical"
        assert raw["keepWithNext"] is True
        assert raw["lineSpacingType"] == "fixed"
        assert raw["dropCapLines"] == 3


# ---------------------------------------------------------------------------
# S3: 새 블록 타입 — 직렬화/역직렬화
# ---------------------------------------------------------------------------


class TestNewBlockTypes:
    def test_endnote_block(self):
        obj = roundtrip(EndnoteBlock, {"type": "endnote", "id": "b_0001", "ref": "e1"})
        assert obj.type == "endnote"
        assert obj.ref == "e1"

    def test_header_block_apply_to(self):
        obj = roundtrip(
            HeaderBlock,
            {
                "type": "header",
                "id": "b_0002",
                "applyTo": "odd",
            },
        )
        assert obj.apply_to == "odd"

    def test_footer_block(self):
        obj = roundtrip(FooterBlock, {"type": "footer", "id": "b_0003"})
        assert obj.apply_to is None

    def test_field_block(self):
        obj = roundtrip(
            FieldBlock,
            {
                "type": "field",
                "id": "b_0004",
                "fieldType": "page_number",
            },
        )
        assert obj.field_type == "page_number"

    def test_text_box_block_with_content(self):
        obj = roundtrip(
            TextBoxBlock,
            {
                "type": "text_box",
                "id": "b_0005",
                "width": 141.7,
                "content": [{"type": "paragraph", "id": "b_0006", "inlines": []}],
            },
        )
        assert obj.content[0].type == "paragraph"

    def test_drawing_block(self):
        obj = roundtrip(
            DrawingBlock,
            {
                "type": "drawing",
                "id": "b_0007",
                "shapeType": "rect",
            },
        )
        assert obj.shape_type == "rect"


# ---------------------------------------------------------------------------
# Block discriminated union — 전체 타입
# ---------------------------------------------------------------------------


class TestBlockDiscriminatedUnion:
    ALL_TYPES = [
        {"type": "heading", "id": "b_0001", "level": 1, "text": "제목"},
        {"type": "paragraph", "id": "b_0002"},
        {"type": "table", "id": "b_0003"},
        {"type": "list", "id": "b_0004"},
        {"type": "image", "id": "b_0005", "src": "a.png"},
        {"type": "code", "id": "b_0006", "code": "print()"},
        {"type": "quote", "id": "b_0007"},
        {"type": "equation", "id": "b_0008"},
        {"type": "footnote", "id": "b_0009", "ref": "fn1"},
        {"type": "endnote", "id": "b_0010", "ref": "en1"},
        {"type": "header", "id": "b_0011"},
        {"type": "footer", "id": "b_0012"},
        {"type": "field", "id": "b_0013", "fieldType": "page_number"},
        {"type": "text_box", "id": "b_0014"},
        {"type": "drawing", "id": "b_0015"},
        {"type": "page_break", "id": "b_0016"},
        {"type": "unknown", "id": "b_0017", "rawBytes": "AAAA"},
    ]

    def test_all_block_types_parse(self):
        doc = UdfDocument(
            source_format="test",
            blocks=[
                UdfDocument.model_validate(
                    {
                        "udf": "1.0",
                        "sourceFormat": "test",
                        "blocks": self.ALL_TYPES,
                    }
                ).blocks[i]
                for i in range(len(self.ALL_TYPES))
            ],
        )
        assert len(doc.blocks) == len(self.ALL_TYPES)

    @pytest.mark.parametrize("data", ALL_TYPES)
    def test_each_block_roundtrip(self, data):
        doc_data = {"udf": "1.0", "sourceFormat": "test", "blocks": [data]}
        obj = UdfDocument.model_validate(doc_data)
        raw = obj.model_dump_json(by_alias=True, exclude_none=True)
        obj2 = UdfDocument.model_validate_json(raw)
        assert obj.blocks[0].type == data["type"]
        assert obj == obj2


# ---------------------------------------------------------------------------
# S4: DocumentMetadata 확장
# ---------------------------------------------------------------------------


class TestDocumentMetadata:
    def test_sections_and_columns(self):
        meta = DocumentMetadata(
            title="테스트",
            start_page_number=1,
            start_footnote_number=1,
            columns=ColumnDef(count=2, gap=14.17),
            sections=[SectionDef(page_width=595.28, page_height=841.86)],
        )
        raw = json.loads(meta.model_dump_json(by_alias=True, exclude_none=True))
        assert raw["startPageNumber"] == 1
        assert raw["columns"]["count"] == 2
        assert raw["sections"][0]["pageWidth"] == 595.28

    def test_all_start_numbers(self):
        meta = DocumentMetadata(
            start_page_number=3,
            start_footnote_number=1,
            start_endnote_number=1,
            start_picture_number=1,
            start_table_number=1,
            start_equation_number=1,
        )
        raw = json.loads(meta.model_dump_json(by_alias=True, exclude_none=True))
        assert raw["startPageNumber"] == 3
        assert raw["startEquationNumber"] == 1


# ---------------------------------------------------------------------------
# S5: GlobalResources 타입 정의 강화
# ---------------------------------------------------------------------------


class TestGlobalResources:
    def test_style_def(self):
        gr = GlobalResources(
            styles={"s1": StyleDef(id="s1", name="본문", style_type="paragraph")},
        )
        assert gr.styles["s1"].name == "본문"

    def test_font_fallbacks(self):
        gr = GlobalResources(
            face_names={
                "f1": FontFallbacks(latin="Times New Roman", hangul="맑은 고딕")
            },
        )
        assert gr.face_names["f1"].hangul == "맑은 고딕"

    def test_numbering_def(self):
        gr = GlobalResources(
            numberings={
                "n1": NumberingDef(
                    id="n1",
                    levels=[
                        NumberingLevel(level=1, format="decimal"),
                        NumberingLevel(level=2, format="korean"),
                    ],
                )
            },
        )
        assert len(gr.numberings["n1"].levels) == 2

    def test_border_fill_def(self):
        gr = GlobalResources(
            border_fills={"bf1": BorderFillDef(id="bf1", fill_color="#FF0000")},
        )
        assert gr.border_fills["bf1"].fill_color == "#FF0000"

    def test_bullet_def(self):
        gr = GlobalResources(
            bullets={"b1": BulletDef(id="b1", char="•")},
        )
        assert gr.bullets["b1"].char == "•"


# ---------------------------------------------------------------------------
# 재귀 모델 (model_rebuild 검증)
# ---------------------------------------------------------------------------


class TestRecursiveModels:
    def test_table_cell_nested_block(self):
        doc = UdfDocument.model_validate(
            {
                "udf": "1.0",
                "sourceFormat": "hwp",
                "blocks": [
                    {
                        "type": "table",
                        "id": "b_0001",
                        "rows": [
                            {
                                "cells": [
                                    {
                                        "id": "c_0001",
                                        "content": [
                                            {
                                                "type": "paragraph",
                                                "id": "b_0002",
                                                "inlines": [
                                                    {"type": "text", "text": "셀 내용"}
                                                ],
                                            }
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        )
        cell = doc.blocks[0].rows[0].cells[0]
        assert cell.content[0].type == "paragraph"

    def test_list_item_nested(self):
        block = ListBlock.model_validate(
            {
                "type": "list",
                "id": "b_0001",
                "ordered": True,
                "items": [
                    {
                        "id": "li_0001",
                        "inlines": [{"type": "text", "text": "항목"}],
                        "children": [
                            {
                                "id": "li_0002",
                                "inlines": [{"type": "text", "text": "하위"}],
                            }
                        ],
                    }
                ],
            }
        )
        assert block.items[0].children[0].inlines[0].text == "하위"

    def test_quote_block_nested(self):
        block = UdfDocument.model_validate(
            {
                "udf": "1.0",
                "sourceFormat": "test",
                "blocks": [
                    {
                        "type": "quote",
                        "id": "b_0001",
                        "content": [
                            {
                                "type": "paragraph",
                                "id": "b_0002",
                                "inlines": [{"type": "text", "text": "인용"}],
                            }
                        ],
                    }
                ],
            }
        )
        assert block.blocks[0].content[0].type == "paragraph"


# ---------------------------------------------------------------------------
# 손실 보고서
# ---------------------------------------------------------------------------


class TestLossReport:
    def test_roundtrip_safe_false(self):
        report = LossReport(
            total_blocks=10,
            lossless_blocks=8,
            lossy_blocks=[],
            dropped_features=["emboss"],
            is_roundtrip_safe=False,
        )
        assert not report.is_roundtrip_safe
        assert "emboss" in report.dropped_features

    def test_loss_category_values(self):
        assert LossCategory.FORMAT_LIMIT == "format_limit"
        assert LossCategory.UNINTENDED == "unintended"
