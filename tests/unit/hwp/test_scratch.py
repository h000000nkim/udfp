"""From Scratch 생성기 유닛 테스트."""

from __future__ import annotations

import pathlib

import pytest

from udf.core.schema import (
    BookmarkBlock,
    CodeBlock,
    EndnoteBlock,
    FieldBlock,
    FootnoteBlock,
    HeadingBlock,
    HorizontalRuleBlock,
    ImageBlock,
    ImageInline,
    ListBlock,
    ListItem,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
    TextInline,
    UdfDocument,
    UnknownBlock,
)
from udf.renderers.hwp.scratch import (
    HWP_DEFAULTS,
    collect_shapes,
    generate_hwp_scratch,
    _charshape_from_inline,
    _charshape_key,
    _parashape_from_block,
    _parashape_key,
    _parse_color,
    _parse_font_size_pt,
)
from udf.renderers.hwp.docinfo_builder import CharShapeSpec, ParaShapeSpec, pack_char_shape, pack_para_shape
from udf.parsers.hwp.parse import parse_hwp

SEED = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "hwp" / "f01_plain_text.hwp"


class TestColorParsing:
    def test_hex_color(self) -> None:
        assert _parse_color("#ff0000") == (255, 0, 0)
        assert _parse_color("#00ff00") == (0, 255, 0)
        assert _parse_color("#0000ff") == (0, 0, 255)

    def test_none_color(self) -> None:
        assert _parse_color(None) == (0, 0, 0)

    def test_invalid_color(self) -> None:
        assert _parse_color("red") == (0, 0, 0)


class TestFontSizeParsing:
    def test_pt_suffix(self) -> None:
        assert _parse_font_size_pt("12pt") == 12.0

    def test_none(self) -> None:
        assert _parse_font_size_pt(None) == HWP_DEFAULTS["font_size_pt"]


class TestCharShapeFromInline:
    def test_plain(self) -> None:
        il = TextInline(text="hello")
        cs = _charshape_from_inline(il)
        assert cs.size_pt == HWP_DEFAULTS["font_size_pt"]
        assert cs.bold is False
        assert cs.color_r == 0

    def test_bold_colored(self) -> None:
        il = TextInline(text="hello", bold=True, color="#ff0000", font_size=14.0)
        cs = _charshape_from_inline(il)
        assert cs.bold is True
        assert cs.color_r == 255
        assert cs.size_pt == 14.0


class TestCollectShapes:
    def test_default_always_present(self) -> None:
        doc = UdfDocument(
            source_format="md",
            blocks=[ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="a")])],
        )
        cs_list, ps_list, cs_map, ps_map = collect_shapes(doc)
        assert len(cs_list) >= 1
        assert len(ps_list) >= 1

    def test_distinct_styles_collected(self) -> None:
        doc = UdfDocument(
            source_format="md",
            blocks=[
                ParagraphBlock(type="paragraph", id="p1", inlines=[
                    TextInline(text="normal"),
                    TextInline(text="bold", bold=True),
                    TextInline(text="colored", color="#ff0000"),
                ]),
            ],
        )
        cs_list, ps_list, cs_map, ps_map = collect_shapes(doc)
        assert len(cs_list) >= 3


class TestGenerateHwpScratch:
    @pytest.fixture
    def seed(self) -> str:
        assert SEED.exists(), f"seed 없음: {SEED}"
        return str(SEED)

    def test_simple_paragraphs(self, seed: str, tmp_path: pathlib.Path) -> None:
        doc = UdfDocument(
            source_format="md",
            blocks=[
                ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="첫 번째")]),
                ParagraphBlock(type="paragraph", id="p2", inlines=[TextInline(text="두 번째")]),
            ],
        )
        out = str(tmp_path / "simple.hwp")
        generate_hwp_scratch(doc, out, seed)

        result = parse_hwp(out)
        texts = []
        for b in result.blocks:
            if isinstance(b, ParagraphBlock):
                t = "".join(i.text for i in b.inlines if isinstance(i, TextInline))
                if t.strip():
                    texts.append(t)
        assert "첫 번째" in texts
        assert "두 번째" in texts

    def test_heading_and_paragraph(self, seed: str, tmp_path: pathlib.Path) -> None:
        doc = UdfDocument(
            source_format="md",
            blocks=[
                HeadingBlock(type="heading", id="h1", level=1, text="제목"),
                ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="본문")]),
            ],
        )
        out = str(tmp_path / "heading.hwp")
        generate_hwp_scratch(doc, out, seed)

        result = parse_hwp(out)
        all_texts = []
        for b in result.blocks:
            if isinstance(b, ParagraphBlock):
                t = "".join(i.text for i in b.inlines if isinstance(i, TextInline))
                if t.strip():
                    all_texts.append(t)
            elif isinstance(b, HeadingBlock):
                all_texts.append(b.text)
        assert "제목" in all_texts
        assert "본문" in all_texts

    @pytest.mark.xfail(reason="MD→HWP scratch: charshape 분리 미구현 (bold/italic 병합됨)")
    def test_bold_italic_preserved(self, seed: str, tmp_path: pathlib.Path) -> None:
        doc = UdfDocument(
            source_format="md",
            blocks=[
                ParagraphBlock(type="paragraph", id="p1", inlines=[
                    TextInline(text="일반 "),
                    TextInline(text="굵게", bold=True),
                    TextInline(text=" 기울임", italic=True),
                ]),
            ],
        )
        out = str(tmp_path / "format.hwp")
        generate_hwp_scratch(doc, out, seed)

        result = parse_hwp(out)
        found_bold = False
        found_italic = False
        for b in result.blocks:
            if isinstance(b, ParagraphBlock):
                for i in b.inlines:
                    if isinstance(i, TextInline):
                        if "굵게" in i.text and i.bold:
                            found_bold = True
                        if "기울임" in i.text and i.italic:
                            found_italic = True
        assert found_bold, "bold=True inline not preserved after roundtrip"
        assert found_italic, "italic=True inline not preserved after roundtrip"

    def test_from_scratch_via_generate_hwp(self, seed: str, tmp_path: pathlib.Path) -> None:
        """generate_hwp()가 verbatim 없을 때 From Scratch fallback."""
        from udf.renderers.hwp import generate_hwp

        doc = UdfDocument(
            source_format="md",
            blocks=[
                ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="fallback 테스트")]),
            ],
        )
        out = str(tmp_path / "fallback.hwp")
        generate_hwp(doc, out, validate=False, seed_path=seed)

        result = parse_hwp(out)
        texts = [
            "".join(i.text for i in b.inlines if isinstance(i, TextInline))
            for b in result.blocks if isinstance(b, ParagraphBlock)
        ]
        assert any("fallback 테스트" in t for t in texts)


class TestBlockTypeCompleteness:
    """22개 블록 타입 전부 From Scratch 렌더링 or LossReport."""

    @pytest.fixture
    def seed(self) -> str:
        assert SEED.exists()
        return str(SEED)

    def _gen(self, blocks, seed, tmp_path):
        doc = UdfDocument(source_format="udf", blocks=blocks)
        out = str(tmp_path / "out.hwp")
        from udf.renderers.hwp.scratch import generate_hwp_scratch
        loss = generate_hwp_scratch(doc, out, seed)
        result = parse_hwp(out)
        return result, loss

    def test_list_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            ListBlock(type="list", id="l1", ordered=True, items=[
                ListItem(id="li1", inlines=[TextInline(text="첫째")]),
                ListItem(id="li2", inlines=[TextInline(text="둘째")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        texts = [b.text_content() for b in result.blocks]
        full = " ".join(texts)
        assert "첫째" in full and "둘째" in full
        assert loss is None

    def test_code_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="intro")]),
            CodeBlock(type="code", id="c1", code="print('hello')"),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "print" in full
        assert loss is None

    def test_quote_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="intro")]),
            QuoteBlock(type="quote", id="q1", content=[
                ParagraphBlock(type="paragraph", id="qp1", inlines=[TextInline(text="인용문")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "인용문" in full
        assert loss is None

    def test_horizontal_rule_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            HorizontalRuleBlock(type="horizontal_rule", id="hr1"),
            ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="after")]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        assert len(result.blocks) >= 3
        assert loss is None

    def test_footnote_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="본문")]),
            FootnoteBlock(type="footnote", id="fn1", ref="1", content=[
                ParagraphBlock(type="paragraph", id="fp1", inlines=[TextInline(text="각주 내용")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "각주 내용" in full
        assert loss is None  # native footnote CTRL_HEADER

    def test_endnote_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="본문")]),
            EndnoteBlock(type="endnote", id="en1", ref="1", content=[
                ParagraphBlock(type="paragraph", id="ep1", inlines=[TextInline(text="미주 내용")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "미주 내용" in full
        assert loss is None  # native endnote CTRL_HEADER

    def test_field_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            FieldBlock(type="field", id="f1", field_type="page_number", value="3"),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "3" in full
        assert loss is None

    def test_textbox_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            TextBoxBlock(type="text_box", id="tb1", content=[
                ParagraphBlock(type="paragraph", id="tp1", inlines=[TextInline(text="박스 내용")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "박스 내용" in full
        assert loss is None

    def test_image_block_loss(self, seed: str, tmp_path) -> None:
        """이미지 파일이 없으면 loss 보고."""
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            ImageBlock(type="image", id="img1", src="nonexistent_file.png"),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        assert loss is not None
        assert any("not found" in bl.description.lower() or "Image" in bl.description for bl in loss.lossy_blocks)

    def test_unknown_block_loss(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            UnknownBlock(type="unknown", id="u1", raw_bytes="deadbeef"),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        assert loss is not None
        assert any("UnknownBlock" in bl.description for bl in loss.lossy_blocks)

    def test_bookmark_skip(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            BookmarkBlock(type="bookmark", id="bm1", name="test"),
            ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="after")]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "before" in full and "after" in full
        assert loss is None

    def test_table_multi_content(self, seed: str, tmp_path) -> None:
        """셀 내 다중 블록이 모두 렌더링되는지 확인."""
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="intro")]),
            TableBlock(type="table", id="t1", rows=[
                TableRow(cells=[
                    TableCell(id="c1", content=[
                        ParagraphBlock(type="paragraph", id="cp1", inlines=[TextInline(text="셀A ")]),
                        ParagraphBlock(type="paragraph", id="cp2", inlines=[TextInline(text="셀B")]),
                    ]),
                ]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "셀A" in full and "셀B" in full

    def test_footnote_native_structure(self, seed: str, tmp_path) -> None:
        """네이티브 각주가 FootnoteBlock으로 파싱되는지 확인."""
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="본문")]),
            FootnoteBlock(type="footnote", id="fn1", ref="1", content=[
                ParagraphBlock(type="paragraph", id="fp1", inlines=[TextInline(text="각주 텍스트")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        fn_blocks = [b for b in result.blocks if isinstance(b, FootnoteBlock)]
        assert len(fn_blocks) >= 1, "파싱 결과에 FootnoteBlock이 있어야 함"
        assert fn_blocks[0].ref == "1"
        assert "각주 텍스트" in fn_blocks[0].text_content()
        assert loss is None

    def test_endnote_native_structure(self, seed: str, tmp_path) -> None:
        """네이티브 미주가 EndnoteBlock으로 파싱되는지 확인."""
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="본문")]),
            EndnoteBlock(type="endnote", id="en1", ref="2", content=[
                ParagraphBlock(type="paragraph", id="ep1", inlines=[TextInline(text="미주 텍스트")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        en_blocks = [b for b in result.blocks if isinstance(b, EndnoteBlock)]
        assert len(en_blocks) >= 1, "파싱 결과에 EndnoteBlock이 있어야 함"
        assert en_blocks[0].ref == "2"
        assert "미주 텍스트" in en_blocks[0].text_content()
        assert loss is None

    def test_image_block_with_data(self, seed: str, tmp_path) -> None:
        """실제 이미지 데이터가 있으면 네이티브 이미지로 생성."""
        import base64
        # 최소 1x1 PNG
        png_1x1 = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )
        img_path = str(tmp_path / "test.png")
        with open(img_path, "wb") as f:
            f.write(png_1x1)

        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            ImageBlock(type="image", id="img1", src=img_path, width=100.0, height=80.0),
            ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="after")]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "before" in full
        assert loss is None


    def test_image_in_table_cell(self, seed: str, tmp_path) -> None:
        """BUG-058: ImageBlock inside table cell renders in-cell, not extracted to top level."""
        import base64
        png_1x1 = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )
        img_path = str(tmp_path / "cell_img.png")
        with open(img_path, "wb") as f:
            f.write(png_1x1)

        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before table")]),
            TableBlock(type="table", id="t1", rows=[
                TableRow(cells=[
                    TableCell(id="c1", content=[
                        ParagraphBlock(type="paragraph", id="cp1", inlines=[TextInline(text="cell text")]),
                        ImageBlock(type="image", id="img_cell", src=img_path, width=50.0, height=40.0),
                    ]),
                    TableCell(id="c2", content=[
                        ParagraphBlock(type="paragraph", id="cp2", inlines=[TextInline(text="no image")]),
                    ]),
                ]),
            ]),
            ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="after table")]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "before table" in full
        assert "after table" in full
        assert "cell text" in full
        assert "no image" in full
        # Verify file is valid (no loss reported for image)
        assert loss is None

    def test_image_inline_in_table_cell(self, seed: str, tmp_path) -> None:
        """BUG-058: ImageInline inside table cell paragraph renders in-cell."""
        import base64
        png_1x1 = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )
        img_path = str(tmp_path / "inline_cell_img.png")
        with open(img_path, "wb") as f:
            f.write(png_1x1)

        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="intro")]),
            TableBlock(type="table", id="t1", rows=[
                TableRow(cells=[
                    TableCell(id="c1", content=[
                        ParagraphBlock(type="paragraph", id="cp1", inlines=[
                            TextInline(text="text with "),
                            ImageInline(src=img_path, width=30.0, height=20.0),
                        ]),
                    ]),
                ]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "intro" in full
        assert "text with" in full
        assert loss is None


class TestPackCharShapeExpanded:
    """Phase 15a: CharShapeSpec 확장 필드 바이너리 직렬화 검증."""

    def test_default_spec_backward_compat(self) -> None:
        """기본값 CharShapeSpec은 기존 하드코딩과 동일한 74바이트 생성."""
        import struct
        buf = pack_char_shape(CharShapeSpec())
        assert len(buf) == 74
        ratios = struct.unpack_from("<7B", buf, 14)
        assert ratios == (100,) * 7
        spacings = struct.unpack_from("<7b", buf, 21)
        assert spacings == (0,) * 7
        rel_sizes = struct.unpack_from("<7B", buf, 28)
        assert rel_sizes == (100,) * 7
        offsets = struct.unpack_from("<7b", buf, 35)
        assert offsets == (0,) * 7
        shade = struct.unpack_from("<I", buf, 60)[0]
        assert shade == 0x00FFFFFF

    def test_outline_bit(self) -> None:
        import struct
        buf = pack_char_shape(CharShapeSpec(outline=True))
        attr = struct.unpack_from("<I", buf, 46)[0]
        assert (attr >> 8) & 0x07 == 1

    def test_shadow_type(self) -> None:
        import struct
        buf = pack_char_shape(CharShapeSpec(shadow_type=2))
        attr = struct.unpack_from("<I", buf, 46)[0]
        assert (attr >> 11) & 0x03 == 2

    def test_emboss_engrave_bits(self) -> None:
        import struct
        buf = pack_char_shape(CharShapeSpec(emboss=True, engrave=True))
        attr = struct.unpack_from("<I", buf, 46)[0]
        assert bool(attr & (1 << 13))
        assert bool(attr & (1 << 14))

    def test_char_scale_ratio(self) -> None:
        import struct
        buf = pack_char_shape(CharShapeSpec(char_scale=150))
        ratios = struct.unpack_from("<7B", buf, 14)
        assert ratios == (150,) * 7

    def test_letter_spacing_signed(self) -> None:
        import struct
        buf = pack_char_shape(CharShapeSpec(letter_spacing=-10))
        spacings = struct.unpack_from("<7b", buf, 21)
        assert spacings == (-10,) * 7

    def test_superscript_synthesis(self) -> None:
        import struct
        buf = pack_char_shape(CharShapeSpec(superscript=True))
        rel_sizes = struct.unpack_from("<7B", buf, 28)
        assert rel_sizes == (70,) * 7
        offsets = struct.unpack_from("<7b", buf, 35)
        assert all(o > 0 for o in offsets)

    def test_subscript_synthesis(self) -> None:
        import struct
        buf = pack_char_shape(CharShapeSpec(subscript=True))
        rel_sizes = struct.unpack_from("<7B", buf, 28)
        assert rel_sizes == (70,) * 7
        offsets = struct.unpack_from("<7b", buf, 35)
        assert all(o < 0 for o in offsets)

    def test_underline_color(self) -> None:
        import struct
        buf = pack_char_shape(CharShapeSpec(underline_color_r=255, underline_color_g=0, underline_color_b=128))
        raw = struct.unpack_from("<I", buf, 56)[0]
        assert raw & 0xFF == 255
        assert (raw >> 8) & 0xFF == 0
        assert (raw >> 16) & 0xFF == 128

    def test_bg_color(self) -> None:
        import struct
        buf = pack_char_shape(CharShapeSpec(bg_color_r=200, bg_color_g=200, bg_color_b=200))
        raw = struct.unpack_from("<I", buf, 60)[0]
        assert raw == (200 | (200 << 8) | (200 << 16))

    def test_strike_color(self) -> None:
        import struct
        buf = pack_char_shape(CharShapeSpec(strike_color_r=255, strike_color_g=0, strike_color_b=0))
        raw = struct.unpack_from("<I", buf, 70)[0]
        assert raw == 255


class TestCharShapeFromInlineExpanded:
    """Phase 15a: TextInline → CharShapeSpec 확장 매핑 검증."""

    def test_outline_shadow(self) -> None:
        il = TextInline(text="x", outline=True, shadow=True)
        cs = _charshape_from_inline(il)
        assert cs.outline is True
        assert cs.shadow_type == 1

    def test_emboss_engrave(self) -> None:
        il = TextInline(text="x", emboss=True, engrave=True)
        cs = _charshape_from_inline(il)
        assert cs.emboss is True
        assert cs.engrave is True

    def test_superscript_subscript(self) -> None:
        il_sup = TextInline(text="x", superscript=True)
        il_sub = TextInline(text="x", subscript=True)
        assert _charshape_from_inline(il_sup).superscript is True
        assert _charshape_from_inline(il_sub).subscript is True

    def test_char_scale_from_ratio(self) -> None:
        from udf.schema.types import Ratio
        il = TextInline(text="x", char_scale=Ratio(percent=150))
        cs = _charshape_from_inline(il)
        assert cs.char_scale == 150

    def test_letter_spacing(self) -> None:
        il = TextInline(text="x", letter_spacing=-5.0)
        cs = _charshape_from_inline(il)
        assert cs.letter_spacing == -5

    def test_colors_mapped(self) -> None:
        il = TextInline(
            text="x",
            underline_color="#ff0000",
            background_color="#00ff00",
            strikeout_color="#0000ff",
        )
        cs = _charshape_from_inline(il)
        assert (cs.underline_color_r, cs.underline_color_g, cs.underline_color_b) == (255, 0, 0)
        assert (cs.bg_color_r, cs.bg_color_g, cs.bg_color_b) == (0, 255, 0)
        assert (cs.strike_color_r, cs.strike_color_g, cs.strike_color_b) == (0, 0, 255)


class TestCharShapeKeyExpanded:
    """Phase 15a: 확장 필드가 dedup 키에 포함되는지 검증."""

    def test_distinct_outline_creates_distinct_key(self) -> None:
        a = CharShapeSpec()
        b = CharShapeSpec(outline=True)
        assert _charshape_key(a) != _charshape_key(b)

    def test_distinct_char_scale_creates_distinct_key(self) -> None:
        a = CharShapeSpec()
        b = CharShapeSpec(char_scale=80)
        assert _charshape_key(a) != _charshape_key(b)

    def test_same_spec_same_key(self) -> None:
        a = CharShapeSpec(outline=True, char_scale=120, letter_spacing=-3)
        b = CharShapeSpec(outline=True, char_scale=120, letter_spacing=-3)
        assert _charshape_key(a) == _charshape_key(b)


class TestPackParaShapeExpanded:
    """Phase 15b: ParaShapeSpec 확장 필드 바이너리 직렬화 검증."""

    def test_default_spec_58_bytes(self) -> None:
        buf = pack_para_shape(ParaShapeSpec())
        assert len(buf) == 58

    def test_line_spacing_type_bits(self) -> None:
        import struct
        buf = pack_para_shape(ParaShapeSpec(line_spacing_type=1))
        attr = struct.unpack_from("<I", buf, 0)[0]
        assert (attr & 0x03) == 1

    def test_widow_orphan_bit(self) -> None:
        import struct
        buf = pack_para_shape(ParaShapeSpec(widow_orphan=True))
        attr = struct.unpack_from("<I", buf, 0)[0]
        assert bool(attr & (1 << 5))

    def test_page_break_before_bit(self) -> None:
        import struct
        buf = pack_para_shape(ParaShapeSpec(page_break_before=True))
        attr = struct.unpack_from("<I", buf, 0)[0]
        assert bool(attr & (1 << 6))

    def test_break_word_default_bits(self) -> None:
        import struct
        buf = pack_para_shape(ParaShapeSpec())
        attr = struct.unpack_from("<I", buf, 0)[0]
        assert bool(attr & (1 << 7)), "bit 7 (breakNonLatinWord=KEEP_WORD) should be set"
        assert bool(attr & (1 << 8)), "bit 8 (breakLatinWord=KEEP_WORD) should be set"

    def test_indent_spacing_values(self) -> None:
        import struct
        buf = pack_para_shape(ParaShapeSpec(
            indent_left=1000, indent_right=500,
            space_before=200, space_after=300, indent_first=400,
        ))
        left, right = struct.unpack_from("<II", buf, 4)
        first = struct.unpack_from("<i", buf, 12)[0]
        s_before, s_after, ls = struct.unpack_from("<III", buf, 16)
        assert (left, right, first, s_before, s_after, ls) == (1000, 500, 400, 200, 300, 160)


class TestParaShapeFromBlockExpanded:
    """Phase 15b: BlockFormat → ParaShapeSpec 확장 매핑 검증."""

    def test_indent_mapped_pt_to_hwpunit(self) -> None:
        from udf.schema.formats import BlockFormat
        blk = ParagraphBlock(
            type="paragraph", id="p1",
            inlines=[TextInline(text="x")],
            format=BlockFormat(indent_left=10.0, indent_right=5.0),
        )
        ps = _parashape_from_block(blk)
        assert ps.indent_left == 1000  # 10pt * 100
        assert ps.indent_right == 500

    def test_space_before_after(self) -> None:
        from udf.schema.formats import BlockFormat
        blk = ParagraphBlock(
            type="paragraph", id="p1",
            inlines=[TextInline(text="x")],
            format=BlockFormat(space_before=6.0, space_after=12.0),
        )
        ps = _parashape_from_block(blk)
        assert ps.space_before == 600
        assert ps.space_after == 1200

    def test_page_break_before(self) -> None:
        from udf.schema.formats import BlockFormat
        blk = ParagraphBlock(
            type="paragraph", id="p1",
            inlines=[TextInline(text="x")],
            format=BlockFormat(page_break_before=True),
        )
        ps = _parashape_from_block(blk)
        assert ps.page_break_before is True

    def test_default_format_unchanged(self) -> None:
        blk = ParagraphBlock(
            type="paragraph", id="p1",
            inlines=[TextInline(text="x")],
        )
        ps = _parashape_from_block(blk)
        assert ps.indent_left == 0


class TestParaShapeKeyExpanded:
    """Phase 15b: 확장 필드가 dedup 키에 포함되는지 검증."""

    def test_distinct_page_break(self) -> None:
        a = ParaShapeSpec()
        b = ParaShapeSpec(page_break_before=True)
        assert _parashape_key(a) != _parashape_key(b)

    def test_same_spec_same_key(self) -> None:
        a = ParaShapeSpec(alignment="center", widow_orphan=True)
        b = ParaShapeSpec(alignment="center", widow_orphan=True)
        assert _parashape_key(a) == _parashape_key(b)


class TestNativeNumbering:
    """Phase 15e: ListBlock 네이티브 번호 매기기 검증."""

    @pytest.fixture
    def seed(self) -> str:
        assert SEED.exists()
        return str(SEED)

    def test_ordered_list_creates_numbering_record(self, seed: str, tmp_path) -> None:
        from udf.parsers.hwp.records import HWPTAG_NUMBERING, iter_records
        from udf.parsers.hwp.ole import OleReader

        doc = UdfDocument(source_format="udf", blocks=[
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="intro")]),
            ListBlock(type="list", id="l1", ordered=True, items=[
                ListItem(id="li1", inlines=[TextInline(text="item1")]),
                ListItem(id="li2", inlines=[TextInline(text="item2")]),
            ]),
        ])
        out = str(tmp_path / "out.hwp")
        generate_hwp_scratch(doc, out, seed)

        with OleReader.open(out) as ole:
            di = ole.read_stream(["DocInfo"])
        num_count = sum(1 for r in iter_records(di) if r.tag_id == HWPTAG_NUMBERING)
        with OleReader.open(seed) as ole:
            seed_di = ole.read_stream(["DocInfo"])
        seed_num_count = sum(1 for r in iter_records(seed_di) if r.tag_id == HWPTAG_NUMBERING)
        assert num_count > seed_num_count

    def test_unordered_list_creates_numbering_record(self, seed: str, tmp_path) -> None:
        from udf.parsers.hwp.records import HWPTAG_NUMBERING, iter_records
        from udf.parsers.hwp.ole import OleReader

        doc = UdfDocument(source_format="udf", blocks=[
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="intro")]),
            ListBlock(type="list", id="l1", ordered=False, items=[
                ListItem(id="li1", inlines=[TextInline(text="bullet1")]),
            ]),
        ])
        out = str(tmp_path / "out.hwp")
        generate_hwp_scratch(doc, out, seed)

        with OleReader.open(out) as ole:
            di = ole.read_stream(["DocInfo"])
        num_count = sum(1 for r in iter_records(di) if r.tag_id == HWPTAG_NUMBERING)
        with OleReader.open(seed) as ole:
            seed_di = ole.read_stream(["DocInfo"])
        seed_num_count = sum(1 for r in iter_records(seed_di) if r.tag_id == HWPTAG_NUMBERING)
        assert num_count > seed_num_count

    def test_list_items_preserve_text(self, seed: str, tmp_path) -> None:
        doc = UdfDocument(source_format="udf", blocks=[
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="intro")]),
            ListBlock(type="list", id="l1", ordered=True, items=[
                ListItem(id="li1", inlines=[TextInline(text="항목A")]),
                ListItem(id="li2", inlines=[TextInline(text="항목B")]),
            ]),
        ])
        out = str(tmp_path / "out.hwp")
        generate_hwp_scratch(doc, out, seed)
        result = parse_hwp(out)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "항목A" in full and "항목B" in full


class TestClickhereField:
    """Phase 15f: FieldBlock clickhere 서식 검증."""

    @pytest.fixture
    def seed(self) -> str:
        assert SEED.exists()
        return str(SEED)

    def test_clickhere_field_renders(self, seed: str, tmp_path) -> None:
        doc = UdfDocument(source_format="udf", blocks=[
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            FieldBlock(type="field", id="f1", field_type="clickhere",
                       inlines=[TextInline(text="여기를 클릭")]),
        ])
        out = str(tmp_path / "out.hwp")
        generate_hwp_scratch(doc, out, seed)
        result = parse_hwp(out)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "여기를 클릭" in full

    def test_clickhere_with_value(self, seed: str, tmp_path) -> None:
        doc = UdfDocument(source_format="udf", blocks=[
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            FieldBlock(type="field", id="f1", field_type="clickhere", value="입력값"),
        ])
        out = str(tmp_path / "out.hwp")
        generate_hwp_scratch(doc, out, seed)
        result = parse_hwp(out)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "입력값" in full


class TestFloatingTextbox:
    """floating textbox의 CTRL_HEADER attr이 올바르게 설정되는지."""

    def test_floating_attr(self):
        from udf.renderers.hwp.body_builder import build_textbox_shape
        import struct
        from udf.parsers.hwp.records import iter_records, HWPTAG_CTRL_HEADER

        content = b""  # empty content
        rec, h = build_textbox_shape(content, 15000, 3000, 0,
                                     x_offset=22500, y_offset=4100, floating=True)
        # Find CTRL_HEADER in the output
        for r in iter_records(rec):
            if r.tag_id == HWPTAG_CTRL_HEADER:
                attr = struct.unpack_from("<I", r.payload, 4)[0]
                flow = (attr >> 21) & 7
                hrelto = (attr >> 8) & 3
                vrelto = (attr >> 3) & 3
                assert flow == 3, f"Expected flow=3(front), got {flow}"
                assert hrelto == 0, f"Expected hrelto=0(paper), got {hrelto}"
                assert vrelto == 0, f"Expected vrelto=0(paper), got {vrelto}"
                # Check x/y offset
                y = struct.unpack_from("<i", r.payload, 8)[0]
                x = struct.unpack_from("<i", r.payload, 12)[0]
                assert x == 22500, f"Expected x=22500, got {x}"
                assert y == 4100, f"Expected y=4100, got {y}"
                break
        else:
            assert False, "No CTRL_HEADER found"
