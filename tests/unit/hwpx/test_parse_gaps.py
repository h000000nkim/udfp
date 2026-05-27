"""HWPX 파서 갭 보강 테스트 — Wave 1-2.

header.py charPr 강화 (emboss, engrave, strikeout_type, outline, shadow, underline),
section.py _build_para_format 강화 (keep_with_next, page_break_before, widow_orphan),
section.py _extract_from_page_pr 강화 (gutter, columns),
parse.py 메타데이터 강화 (author, created_at, modified_at).
"""

from __future__ import annotations

from typing import Any

from udf.schema import ListBlock, ParagraphBlock, TextInline
from udf.schema.types import Color
from udf.pipeline.verbatim import GlobalResources
from udf.parsers.hwp.doc_info import DocInfoResult
from udf.parsers.hwpx.header import _parse_single_char_pr, NS
from udf.parsers.hwpx.section import (
    _build_para_format,
    _extract_from_page_pr,
    parse_section_xml,
)

from lxml import etree

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_NS_DECL = (
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core"'
)


def _make_char_pr_xml(inner: str) -> etree._Element:
    xml = f'<hh:charPr {_NS_DECL} height="1000" textColor="#000000">{inner}</hh:charPr>'
    return etree.fromstring(xml.encode())


def _make_info(
    char_shapes: list[dict[str, Any]] | None = None,
    para_shapes: list[dict[str, Any]] | None = None,
    style_names: list[str] | None = None,
) -> DocInfoResult:
    return DocInfoResult(
        global_resources=GlobalResources(),
        char_shapes=char_shapes or [{"font_size_pt": 10.0}],
        para_shapes=para_shapes or [{"alignment": "left"}],
        style_names=style_names or ["본문"],
    )


def _wrap_section(inner_xml: str) -> bytes:
    return f'<hs:sec {_NS_DECL}>{inner_xml}</hs:sec>'.encode("utf-8")


def _wrap_para(inner_xml: str, para_pr: str = "0", style: str = "0") -> str:
    return (
        f'<hp:p paraPrIDRef="{para_pr}" styleIDRef="{style}">'
        f"{inner_xml}"
        f"</hp:p>"
    )


def _wrap_run(inner_xml: str, char_pr: str = "0") -> str:
    return f'<hp:run charPrIDRef="{char_pr}">{inner_xml}</hp:run>'


# ===========================================================================
# charPr: emboss, engrave
# ===========================================================================


class TestCharPrEmbossEngrave:
    def test_emboss(self):
        el = _make_char_pr_xml('<hh:emboss />')
        cs = _parse_single_char_pr(el)
        assert cs["emboss"] is True

    def test_engrave(self):
        el = _make_char_pr_xml('<hh:engrave />')
        cs = _parse_single_char_pr(el)
        assert cs["engrave"] is True

    def test_no_emboss_engrave(self):
        el = _make_char_pr_xml('')
        cs = _parse_single_char_pr(el)
        assert cs["emboss"] is None
        assert cs["engrave"] is None


# ===========================================================================
# charPr: strikeout_type, strikeout_color
# ===========================================================================


class TestCharPrStrikeout:
    def test_strikeout_solid(self):
        el = _make_char_pr_xml('<hh:strikeout shape="SOLID" color="#FF0000" />')
        cs = _parse_single_char_pr(el)
        assert cs["strikethrough"] is True
        assert cs["strikeout_type"] == "solid"
        assert cs["strikeout_color"] == "#FF0000"

    def test_strikeout_none(self):
        el = _make_char_pr_xml('<hh:strikeout shape="NONE" />')
        cs = _parse_single_char_pr(el)
        assert cs["strikethrough"] is None
        assert cs["strikeout_type"] is None


# ===========================================================================
# charPr: underline_type, underline_color
# ===========================================================================


class TestCharPrUnderline:
    def test_underline_bottom(self):
        el = _make_char_pr_xml('<hh:underline type="BOTTOM" color="#0000FF" />')
        cs = _parse_single_char_pr(el)
        assert cs["underline"] is True
        assert cs["underline_type"] == "solid"
        assert cs["underline_color"] == "#0000FF"

    def test_underline_none(self):
        el = _make_char_pr_xml('<hh:underline type="NONE" />')
        cs = _parse_single_char_pr(el)
        assert cs["underline"] is None
        assert cs["underline_type"] is None


# ===========================================================================
# charPr: outline, shadow
# ===========================================================================


class TestCharPrOutlineShadow:
    def test_outline_with_type(self):
        el = _make_char_pr_xml('<hh:outline type="SOLID" />')
        cs = _parse_single_char_pr(el)
        assert cs["outline"] is True

    def test_outline_none(self):
        el = _make_char_pr_xml('<hh:outline type="NONE" />')
        cs = _parse_single_char_pr(el)
        assert cs["outline"] is None

    def test_shadow_with_type(self):
        el = _make_char_pr_xml('<hh:shadow type="DROP" />')
        cs = _parse_single_char_pr(el)
        assert cs["shadow"] is True

    def test_shadow_none(self):
        el = _make_char_pr_xml('<hh:shadow type="NONE" />')
        cs = _parse_single_char_pr(el)
        assert cs["shadow"] is None


# ===========================================================================
# _build_para_format: keep_with_next, page_break_before, widow_orphan
# ===========================================================================


class TestParaFormatProperties:
    def test_keep_with_next(self):
        info = _make_info(para_shapes=[{"alignment": "left", "with_next_paragraph": True}])
        fmt = _build_para_format(0, info)
        assert fmt is not None
        assert fmt.keep_with_next is True

    def test_page_break_before(self):
        info = _make_info(para_shapes=[{"alignment": "left", "start_new_page": True}])
        fmt = _build_para_format(0, info)
        assert fmt is not None
        assert fmt.page_break_before is True

    def test_widow_orphan(self):
        info = _make_info(para_shapes=[{"alignment": "left", "protect": True}])
        fmt = _build_para_format(0, info)
        assert fmt is not None
        assert fmt.widow_orphan is True

    def test_no_flags_all_none(self):
        info = _make_info(para_shapes=[{"alignment": "left"}])
        fmt = _build_para_format(0, info)
        assert fmt is not None
        assert fmt.keep_with_next is None
        assert fmt.page_break_before is None
        assert fmt.widow_orphan is None


# ===========================================================================
# charPr propagation to TextInline
# ===========================================================================


class TestCharPrPropagation:
    """charPr → TextInline까지 전달되는지 검증."""

    def test_emboss_in_text_inline(self):
        cs = {"font_size_pt": 10.0, "emboss": True, "engrave": None}
        info = _make_info(char_shapes=[cs])
        xml = _wrap_section(
            _wrap_para(_wrap_run('<hp:t>텍스트</hp:t>', char_pr="0"))
        )
        blocks, _ = parse_section_xml(xml, info, "section0.xml")
        assert len(blocks) > 0
        para = blocks[0]
        assert isinstance(para, ParagraphBlock)
        il = para.inlines[0]
        assert isinstance(il, TextInline)
        assert il.emboss is True
        assert il.engrave is None

    def test_strikeout_type_in_text_inline(self):
        cs = {
            "font_size_pt": 10.0,
            "strikethrough": True,
            "strikeout_type": "solid",
            "strikeout_color": "#FF0000",
        }
        info = _make_info(char_shapes=[cs])
        xml = _wrap_section(
            _wrap_para(_wrap_run('<hp:t>취소선</hp:t>', char_pr="0"))
        )
        blocks, _ = parse_section_xml(xml, info, "section0.xml")
        il = blocks[0].inlines[0]
        assert isinstance(il, TextInline)
        assert il.strikeout_type == "solid"
        assert il.strikeout_color == Color.from_hex("#FF0000")

    def test_underline_type_in_text_inline(self):
        cs = {
            "font_size_pt": 10.0,
            "underline": True,
            "underline_type": "solid",
            "underline_color": "#0000FF",
        }
        info = _make_info(char_shapes=[cs])
        xml = _wrap_section(
            _wrap_para(_wrap_run('<hp:t>밑줄</hp:t>', char_pr="0"))
        )
        blocks, _ = parse_section_xml(xml, info, "section0.xml")
        il = blocks[0].inlines[0]
        assert isinstance(il, TextInline)
        assert il.underline_type == "solid"
        assert il.underline_color == Color.from_hex("#0000FF")


# ===========================================================================
# _extract_from_page_pr: gutter
# ===========================================================================


class TestPagePrGutter:
    def test_gutter_extracted(self):
        xml = (
            f'<hp:pagePr {_NS_DECL} width="59528" height="84188">'
            f'  <hp:margin left="8504" right="8504" top="5668" bottom="4252" header="4252" footer="4252" />'
            f'  <hp:gutter value="500" />'
            f'</hp:pagePr>'
        )
        el = etree.fromstring(xml.encode())
        result = _extract_from_page_pr(el)
        assert result["gutter"] == 5.0

    def test_no_gutter(self):
        xml = (
            f'<hp:pagePr {_NS_DECL} width="59528" height="84188">'
            f'  <hp:margin left="8504" right="8504" top="5668" bottom="4252" header="4252" footer="4252" />'
            f'</hp:pagePr>'
        )
        el = etree.fromstring(xml.encode())
        result = _extract_from_page_pr(el)
        assert "gutter" not in result


# ===========================================================================
# _extract_from_page_pr: columns
# ===========================================================================


class TestPagePrColumns:
    def test_multi_column(self):
        xml = (
            f'<hp:pagePr {_NS_DECL} width="59528" height="84188">'
            f'  <hp:margin left="8504" right="8504" top="5668" bottom="4252" header="4252" footer="4252" />'
            f'  <hp:multiColumn count="2" gap="1200" sameWidth="1" />'
            f'</hp:pagePr>'
        )
        el = etree.fromstring(xml.encode())
        result = _extract_from_page_pr(el)
        assert result["column_count"] == 2
        assert result["column_gap"] == 12.0
        assert result["column_same_width"] is True

    def test_single_column_not_stored(self):
        xml = (
            f'<hp:pagePr {_NS_DECL} width="59528" height="84188">'
            f'  <hp:margin left="8504" right="8504" top="5668" bottom="4252" header="4252" footer="4252" />'
            f'  <hp:multiColumn count="1" />'
            f'</hp:pagePr>'
        )
        el = etree.fromstring(xml.encode())
        result = _extract_from_page_pr(el)
        assert "column_count" not in result

    def test_column_def_alternative_tag(self):
        xml = (
            f'<hp:pagePr {_NS_DECL} width="59528" height="84188">'
            f'  <hp:margin left="8504" right="8504" top="5668" bottom="4252" header="4252" footer="4252" />'
            f'  <hp:columnDef count="3" gap="800" sameWidth="0" />'
            f'</hp:pagePr>'
        )
        el = etree.fromstring(xml.encode())
        result = _extract_from_page_pr(el)
        assert result["column_count"] == 3
        assert result["column_same_width"] is False


# ===========================================================================
# header.py: breakSetting in paraPr
# ===========================================================================


class TestParaPrBreakSetting:
    """header.py _parse_single_para_pr: breakSetting 요소 파싱 검증."""

    def test_keep_with_next_from_header(self):
        from udf.parsers.hwpx.header import _parse_single_para_pr
        xml = (
            f'<hh:paraPr {_NS_DECL}>'
            f'  <hh:align horizontal="LEFT" />'
            f'  <hh:breakSetting keepWithNext="1" />'
            f'</hh:paraPr>'
        )
        el = etree.fromstring(xml.encode())
        ps = _parse_single_para_pr(el)
        assert ps.get("with_next_paragraph") is True

    def test_page_break_before_from_header(self):
        from udf.parsers.hwpx.header import _parse_single_para_pr
        xml = (
            f'<hh:paraPr {_NS_DECL}>'
            f'  <hh:align horizontal="LEFT" />'
            f'  <hh:breakSetting pageBreakBefore="1" />'
            f'</hh:paraPr>'
        )
        el = etree.fromstring(xml.encode())
        ps = _parse_single_para_pr(el)
        assert ps.get("start_new_page") is True

    def test_widow_orphan_from_header(self):
        from udf.parsers.hwpx.header import _parse_single_para_pr
        xml = (
            f'<hh:paraPr {_NS_DECL}>'
            f'  <hh:align horizontal="LEFT" />'
            f'  <hh:breakSetting widowOrphan="1" />'
            f'</hh:paraPr>'
        )
        el = etree.fromstring(xml.encode())
        ps = _parse_single_para_pr(el)
        assert ps.get("protect") is True

    def test_no_break_setting(self):
        from udf.parsers.hwpx.header import _parse_single_para_pr
        xml = (
            f'<hh:paraPr {_NS_DECL}>'
            f'  <hh:align horizontal="LEFT" />'
            f'</hh:paraPr>'
        )
        el = etree.fromstring(xml.encode())
        ps = _parse_single_para_pr(el)
        assert ps.get("with_next_paragraph") is None
        assert ps.get("start_new_page") is None
        assert ps.get("protect") is None


# ---------------------------------------------------------------------------
# Phase 4: 섹션 속성 — orientation + multi-section
# ---------------------------------------------------------------------------


class TestPageDefOrientation:
    def _make_page_pr(self, landscape: str | None = None,
                       width: int = 59528, height: int = 84188) -> str:
        orient = f' landscape="{landscape}"' if landscape else ""
        return (
            f'<hp:pagePr {_NS_DECL} width="{width}" height="{height}"{orient}>'
            f'  <hp:margin left="8504" right="8504" top="5668" bottom="4252"'
            f'   header="4252" footer="4252" />'
            f'</hp:pagePr>'
        )

    def test_portrait_default(self):
        xml = self._make_page_pr()
        el = etree.fromstring(xml.encode())
        result = _extract_from_page_pr(el)
        assert result.get("orientation") is None

    def test_landscape_true(self):
        xml = self._make_page_pr(landscape="true")
        el = etree.fromstring(xml.encode())
        result = _extract_from_page_pr(el)
        assert result["orientation"] == "landscape"

    def test_landscape_1(self):
        xml = self._make_page_pr(landscape="1")
        el = etree.fromstring(xml.encode())
        result = _extract_from_page_pr(el)
        assert result["orientation"] == "landscape"

    def test_landscape_false(self):
        xml = self._make_page_pr(landscape="false")
        el = etree.fromstring(xml.encode())
        result = _extract_from_page_pr(el)
        assert result.get("orientation") is None


class TestExtractPageDefColumns:
    def test_two_columns(self):
        xml = (
            f'<hp:pagePr {_NS_DECL} width="59528" height="84188">'
            f'  <hp:margin left="8504" right="8504" top="5668" bottom="4252"'
            f'   header="4252" footer="4252" />'
            f'  <hp:multiColumn count="2" gap="1200" sameWidth="1" />'
            f'</hp:pagePr>'
        )
        el = etree.fromstring(xml.encode())
        result = _extract_from_page_pr(el)
        assert result["column_count"] == 2
        assert result["column_gap"] == 12.0
        assert result["column_same_width"] is True

    def test_columnDef_fallback(self):
        xml = (
            f'<hp:pagePr {_NS_DECL} width="59528" height="84188">'
            f'  <hp:margin left="8504" right="8504" top="5668" bottom="4252"'
            f'   header="4252" footer="4252" />'
            f'  <hp:columnDef count="3" gap="800" sameWidth="0" />'
            f'</hp:pagePr>'
        )
        el = etree.fromstring(xml.encode())
        result = _extract_from_page_pr(el)
        assert result["column_count"] == 3
        assert result["column_same_width"] is False


# ===========================================================================
# ListBlock 감지
# ===========================================================================


class TestListBlockDetection:
    """리스트 스타일 단락이 ListBlock으로 변환되는지 검증."""

    def _make_list_info(self, style_names: list[str]) -> DocInfoResult:
        return _make_info(
            char_shapes=[{"font_size_pt": 10.0}],
            para_shapes=[{"alignment": "left"}] * len(style_names),
            style_names=style_names,
        )

    def test_mso_list_paragraph_detected(self):
        info = self._make_list_info(["본문", "MsoListParagraph"])
        xml = _wrap_section(
            _wrap_para(_wrap_run('<hp:t>Item 1</hp:t>'), style="1")
            + _wrap_para(_wrap_run('<hp:t>Item 2</hp:t>'), style="1")
        )
        blocks, _ = parse_section_xml(xml, info, "section0.xml")
        assert len(blocks) == 1
        lb = blocks[0]
        assert isinstance(lb, ListBlock)
        assert lb.ordered is False
        assert len(lb.items) == 2
        assert lb.list_style == "MsoListParagraph"

    def test_korean_numbering_style_ordered(self):
        info = self._make_list_info(["본문", "㉿3."])
        xml = _wrap_section(
            _wrap_para(_wrap_run('<hp:t>첫째</hp:t>'), style="1")
            + _wrap_para(_wrap_run('<hp:t>둘째</hp:t>'), style="1")
        )
        blocks, _ = parse_section_xml(xml, info, "section0.xml")
        assert len(blocks) == 1
        lb = blocks[0]
        assert isinstance(lb, ListBlock)
        assert lb.ordered is True
        assert len(lb.items) == 2

    def test_ga_style_ordered(self):
        info = self._make_list_info(["본문", "가."])
        xml = _wrap_section(
            _wrap_para(_wrap_run('<hp:t>항목</hp:t>'), style="1")
        )
        blocks, _ = parse_section_xml(xml, info, "section0.xml")
        assert len(blocks) == 1
        lb = blocks[0]
        assert isinstance(lb, ListBlock)
        assert lb.ordered is True

    def test_list_flush_on_normal_paragraph(self):
        info = self._make_list_info(["본문", "MsoListParagraph"])
        xml = _wrap_section(
            _wrap_para(_wrap_run('<hp:t>Item 1</hp:t>'), style="1")
            + _wrap_para(_wrap_run('<hp:t>Normal</hp:t>'), style="0")
            + _wrap_para(_wrap_run('<hp:t>Item 2</hp:t>'), style="1")
        )
        blocks, _ = parse_section_xml(xml, info, "section0.xml")
        assert len(blocks) == 3
        assert isinstance(blocks[0], ListBlock)
        assert isinstance(blocks[1], ParagraphBlock)
        assert isinstance(blocks[2], ListBlock)

    def test_empty_list_items_skipped(self):
        info = self._make_list_info(["본문", "MsoListParagraph"])
        xml = _wrap_section(
            _wrap_para(_wrap_run('<hp:t> </hp:t>'), style="1")
            + _wrap_para(_wrap_run('<hp:t>Actual item</hp:t>'), style="1")
        )
        blocks, _ = parse_section_xml(xml, info, "section0.xml")
        assert len(blocks) == 1
        lb = blocks[0]
        assert isinstance(lb, ListBlock)
        assert len(lb.items) == 1

    def test_non_list_style_not_detected(self):
        info = self._make_list_info(["본문", "Custom Style"])
        xml = _wrap_section(
            _wrap_para(_wrap_run('<hp:t>Not a list</hp:t>'), style="1")
        )
        blocks, _ = parse_section_xml(xml, info, "section0.xml")
        assert len(blocks) == 1
        assert isinstance(blocks[0], ParagraphBlock)

    def test_fixture_tac_img_has_list_blocks(self):
        """실제 HWPX fixture에서 ListBlock이 감지되는지 통합 검증."""
        from udf.parsers.hwpx.parse import parse_hwpx
        doc = parse_hwpx("tests/fixtures/hwpx/tac_img.hwpx")
        list_blocks = [b for b in doc.document.blocks if isinstance(b, ListBlock)]
        assert len(list_blocks) >= 2
        mso_lists = [lb for lb in list_blocks if lb.list_style == "MsoListParagraph"]
        assert len(mso_lists) >= 2
        for lb in mso_lists:
            assert lb.ordered is False
            assert len(lb.items) > 0
