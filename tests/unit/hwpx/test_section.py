"""HWPX section.py 파서 단위 테스트 — 이미지, 수식, 각주, 하이퍼링크, 페이지 브레이크."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from udf.schema import (
    EndnoteBlock,
    EquationInline,
    FooterBlock,
    FootnoteBlock,
    FootnoteRefInline,
    HeaderBlock,
    ImageInline,
    LinkInline,
    PageBreakBlock,
    ParagraphBlock,
    TextBoxBlock,
    TextInline,
)
from udf.pipeline.verbatim import GlobalResources
from udf.parsers.hwpx.section import parse_section_xml

# ---------------------------------------------------------------------------
# HWPX 네임스페이스 선언 (테스트 XML에서 사용)
# ---------------------------------------------------------------------------

_NS_DECL = (
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core"'
)


def _wrap_section(inner_xml: str) -> bytes:
    """단락 XML을 hs:sec 루트로 감싼다."""
    return f'<hs:sec {_NS_DECL}>{inner_xml}</hs:sec>'.encode("utf-8")


def _wrap_para(inner_xml: str, para_pr="0", style="0", page_break: str = "") -> str:
    """hp:p 요소를 생성한다."""
    pb_attr = f' pageBreak="{page_break}"' if page_break else ""
    return (
        f'<hp:p paraPrIDRef="{para_pr}" styleIDRef="{style}"{pb_attr}>'
        f"{inner_xml}"
        f"</hp:p>"
    )


def _wrap_run(inner_xml: str, char_pr="0") -> str:
    """hp:run 요소를 생성한다."""
    return f'<hp:run charPrIDRef="{char_pr}">{inner_xml}</hp:run>'


# ---------------------------------------------------------------------------
# 최소 DocInfoResult 모의 객체
# ---------------------------------------------------------------------------

# DocInfoResult는 dataclass이므로 직접 import하여 사용
from udf.parsers.hwp.doc_info import DocInfoResult


def _make_info(
    char_shapes: list[dict[str, Any]] | None = None,
    para_shapes: list[dict[str, Any]] | None = None,
    style_names: list[str] | None = None,
) -> DocInfoResult:
    """테스트용 최소 DocInfoResult를 생성한다."""
    return DocInfoResult(
        global_resources=GlobalResources(),
        char_shapes=char_shapes or [{"font_size_pt": 10.0}],
        para_shapes=para_shapes or [{"alignment": "left"}],
        style_names=style_names or ["본문"],
    )


# ===========================================================================
# Phase 1: 이미지 파싱
# ===========================================================================


class TestImageParsing:
    """hp:pic 요소가 ImageInline으로 변환되는지 테스트."""

    def test_pic_with_binary_item_id(self):
        """hp:pic > hp:img[binaryItemIDRef] → ImageInline."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:pic>'
                    '  <hp:sz width="5000" height="3000" />'
                    '  <hp:img binaryItemIDRef="image1.jpg" />'
                    '</hp:pic>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        assert len(blocks) == 1
        para = blocks[0]
        assert isinstance(para, ParagraphBlock)
        assert len(para.inlines) == 1
        img = para.inlines[0]
        assert isinstance(img, ImageInline)
        assert img.src == "bindata:image1.jpg"
        assert img.width == 50.0
        assert img.height == 30.0

    def test_pic_nested_img(self):
        """hp:pic > hp:imgRect > hp:img 패턴도 처리."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:pic>'
                    '  <hp:imgRect><hp:img binaryItemIDRef="nested.png" /></hp:imgRect>'
                    '</hp:pic>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        para = blocks[0]
        assert len(para.inlines) == 1
        assert isinstance(para.inlines[0], ImageInline)
        assert para.inlines[0].src == "bindata:nested.png"

    def test_pic_no_img_returns_no_inline(self):
        """hp:pic에 hp:img가 없으면 인라인을 생성하지 않는다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:pic><hp:sz width="100" height="100" /></hp:pic>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        para = blocks[0]
        assert len(para.inlines) == 0

    def test_pic_no_binary_id_returns_no_inline(self):
        """binaryItemIDRef가 빈 문자열이면 인라인을 생성하지 않는다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:pic><hp:img binaryItemIDRef="" /></hp:pic>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        para = blocks[0]
        assert len(para.inlines) == 0

    def test_pic_alongside_text(self):
        """텍스트와 이미지가 같은 run에 있을 때 모두 수집된다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:t>Before</hp:t>'
                    '<hp:pic><hp:img binaryItemIDRef="mid.png" /></hp:pic>'
                    '<hp:t>After</hp:t>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        para = blocks[0]
        assert len(para.inlines) == 3
        assert isinstance(para.inlines[0], TextInline)
        assert para.inlines[0].text == "Before"
        assert isinstance(para.inlines[1], ImageInline)
        assert isinstance(para.inlines[2], TextInline)
        assert para.inlines[2].text == "After"


# ===========================================================================
# Phase 1: 수식 파싱
# ===========================================================================


class TestEquationParsing:
    """hp:eqEdit 요소가 EquationInline으로 변환되는지 테스트."""

    def test_eqedit_with_script_attr(self):
        """script 속성에서 수식 스크립트를 가져온다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:eqEdit script="x^2 + y^2 = z^2" />'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        para = blocks[0]
        assert len(para.inlines) == 1
        eq = para.inlines[0]
        assert isinstance(eq, EquationInline)
        assert eq.hwp_script == "x^2 + y^2 = z^2"
        assert eq.latex is None

    def test_eqedit_with_text_content(self):
        """텍스트 콘텐츠에서 수식 스크립트를 가져온다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:eqEdit>a + b = c</hp:eqEdit>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        eq = blocks[0].inlines[0]
        assert isinstance(eq, EquationInline)
        assert eq.hwp_script == "a + b = c"

    def test_eqedit_with_script_child(self):
        """hp:script 자식 요소에서 수식 스크립트를 가져온다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:eqEdit><hp:script>int from 0 to 1</hp:script></hp:eqEdit>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        eq = blocks[0].inlines[0]
        assert isinstance(eq, EquationInline)
        assert eq.hwp_script == "int from 0 to 1"

    def test_eqedit_empty(self):
        """수식 스크립트가 없으면 hwp_script=None."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:eqEdit />'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        eq = blocks[0].inlines[0]
        assert isinstance(eq, EquationInline)
        assert eq.hwp_script is None


# ===========================================================================
# Phase 2: 각주/미주 파싱
# ===========================================================================


class TestFootnoteParsing:
    """hp:footNote / hp:endNote가 FootnoteRefInline + FootnoteBlock/EndnoteBlock로 변환되는지 테스트."""

    def test_footnote_creates_ref_and_block(self):
        """hp:footNote → FootnoteRefInline (인라인) + FootnoteBlock (추가 블록)."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:t>Main text</hp:t>'
                    '<hp:footNote number="1">'
                    '  <hp:subList>'
                    '    <hp:p paraPrIDRef="0" styleIDRef="0">'
                    '      <hp:run charPrIDRef="0"><hp:t>Footnote content</hp:t></hp:run>'
                    '    </hp:p>'
                    '  </hp:subList>'
                    '</hp:footNote>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        # 첫 번째: 본문 단락 (FootnoteRefInline 포함)
        # 두 번째: FootnoteBlock
        assert len(blocks) >= 2

        para = blocks[0]
        assert isinstance(para, ParagraphBlock)

        # 본문 텍스트 + 각주 참조
        text_inlines = [i for i in para.inlines if isinstance(i, TextInline)]
        ref_inlines = [i for i in para.inlines if isinstance(i, FootnoteRefInline)]
        assert len(text_inlines) >= 1
        assert text_inlines[0].text == "Main text"
        assert len(ref_inlines) == 1
        assert ref_inlines[0].number == 1

        # FootnoteBlock
        fn_block = blocks[1]
        assert isinstance(fn_block, FootnoteBlock)
        assert fn_block.ref == ref_inlines[0].ref_id
        assert len(fn_block.content) >= 1

        # 각주 내용 확인
        fn_para = fn_block.content[0]
        assert isinstance(fn_para, ParagraphBlock)
        fn_texts = [i for i in fn_para.inlines if isinstance(i, TextInline)]
        assert any("Footnote content" in t.text for t in fn_texts)

    def test_endnote_creates_ref_and_block(self):
        """hp:endNote → FootnoteRefInline + EndnoteBlock."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:t>Main</hp:t>'
                    '<hp:endNote number="2">'
                    '  <hp:subList>'
                    '    <hp:p paraPrIDRef="0" styleIDRef="0">'
                    '      <hp:run charPrIDRef="0"><hp:t>Endnote text</hp:t></hp:run>'
                    '    </hp:p>'
                    '  </hp:subList>'
                    '</hp:endNote>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        assert len(blocks) >= 2
        en_block = blocks[1]
        assert isinstance(en_block, EndnoteBlock)
        assert en_block.content[0].inlines[0].text == "Endnote text"

    def test_footnote_without_number(self):
        """number 속성이 없으면 number=None."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:footNote>'
                    '  <hp:subList>'
                    '    <hp:p paraPrIDRef="0" styleIDRef="0">'
                    '      <hp:run charPrIDRef="0"><hp:t>No num</hp:t></hp:run>'
                    '    </hp:p>'
                    '  </hp:subList>'
                    '</hp:footNote>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        para = blocks[0]
        ref = next(i for i in para.inlines if isinstance(i, FootnoteRefInline))
        assert ref.number is None


# ===========================================================================
# Phase 3: 하이퍼링크 파싱
# ===========================================================================


class TestHyperlinkParsing:
    """hp:ctrl[@ctrlID="hlnk"] 요소가 LinkInline으로 변환되는지 테스트."""

    def test_hyperlink_with_href(self):
        """href 속성에서 URL을 가져온다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:ctrl ctrlID="hlnk" href="https://example.com">'
                    '  <hp:t>Click here</hp:t>'
                    '</hp:ctrl>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        para = blocks[0]
        assert len(para.inlines) == 1
        link = para.inlines[0]
        assert isinstance(link, LinkInline)
        assert link.url == "https://example.com"
        assert link.text == "Click here"

    def test_hyperlink_url_from_child(self):
        """href가 없으면 자식 hp:url에서 URL을 가져온다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:ctrl ctrlID="hlnk">'
                    '  <hp:url>https://child-url.com</hp:url>'
                    '  <hp:t>Link</hp:t>'
                    '</hp:ctrl>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        link = para_inlines_of_type(blocks[0], LinkInline)[0]
        assert link.url == "https://child-url.com"
        assert link.text == "Link"

    def test_non_hlnk_ctrl_ignored(self):
        """ctrlID가 hlnk가 아닌 ctrl은 무시된다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:ctrl ctrlID="other">'
                    '  <hp:t>Not a link</hp:t>'
                    '</hp:ctrl>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        para = blocks[0]
        assert len(para.inlines) == 0


# ===========================================================================
# Phase 4: 페이지 브레이크
# ===========================================================================


class TestPageBreak:
    """hp:p[@pageBreak="true"]가 PageBreakBlock을 생성하는지 테스트."""

    def test_page_break_true(self):
        """pageBreak="true" → PageBreakBlock + ParagraphBlock."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run('<hp:t>After break</hp:t>'),
                page_break="true",
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        assert len(blocks) >= 2
        assert isinstance(blocks[0], PageBreakBlock)
        assert isinstance(blocks[1], ParagraphBlock)

    def test_no_page_break(self):
        """pageBreak 속성이 없으면 PageBreakBlock이 없다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run('<hp:t>Normal</hp:t>'),
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        assert len(blocks) == 1
        assert isinstance(blocks[0], ParagraphBlock)

    def test_page_break_false(self):
        """pageBreak="false"이면 PageBreakBlock이 없다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run('<hp:t>Normal</hp:t>'),
                page_break="false",
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        assert len(blocks) == 1
        assert isinstance(blocks[0], ParagraphBlock)


# ===========================================================================
# Phase 4: 텍스트박스
# ===========================================================================


class TestTextBoxParsing:
    """hp:container 요소가 TextBoxBlock으로 변환되는지 테스트."""

    def test_container_with_sublist(self):
        """hp:container > hp:drawText > hp:subList → TextBoxBlock."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:t>Before</hp:t>'
                    '<hp:container>'
                    '  <hp:drawText>'
                    '    <hp:subList>'
                    '      <hp:p paraPrIDRef="0" styleIDRef="0">'
                    '        <hp:run charPrIDRef="0"><hp:t>Box text</hp:t></hp:run>'
                    '      </hp:p>'
                    '    </hp:subList>'
                    '  </hp:drawText>'
                    '</hp:container>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        # ParagraphBlock (with "Before") + TextBoxBlock
        assert len(blocks) >= 2
        para = blocks[0]
        assert isinstance(para, ParagraphBlock)

        tb = blocks[1]
        assert isinstance(tb, TextBoxBlock)
        assert len(tb.content) >= 1
        inner_para = tb.content[0]
        assert isinstance(inner_para, ParagraphBlock)
        assert inner_para.inlines[0].text == "Box text"

    def test_container_empty_sublist_no_block(self):
        """subList에 단락이 없으면 TextBoxBlock을 생성하지 않는다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:container>'
                    '  <hp:drawText>'
                    '    <hp:subList />'
                    '  </hp:drawText>'
                    '</hp:container>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        # 빈 단락 하나만 생성
        assert len(blocks) == 1
        assert isinstance(blocks[0], ParagraphBlock)


# ===========================================================================
# Phase 3: 헤더/푸터
# ===========================================================================


class TestHeaderFooterParsing:
    """secPr > hp:headerFooter가 HeaderBlock/FooterBlock으로 변환되는지 테스트."""

    def test_header_from_sec_pr(self):
        """secPr 안의 headerFooter[HEADER] → HeaderBlock."""
        sec_pr_xml = (
            '<hp:secPr>'
            '  <hp:headerFooter type="BOTH" headerFooter="HEADER">'
            '    <hp:subList>'
            '      <hp:p paraPrIDRef="0" styleIDRef="0">'
            '        <hp:run charPrIDRef="0"><hp:t>Header text</hp:t></hp:run>'
            '      </hp:p>'
            '    </hp:subList>'
            '  </hp:headerFooter>'
            '</hp:secPr>'
        )
        xml = _wrap_section(
            _wrap_para(_wrap_run(sec_pr_xml))
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        header_blocks = [b for b in blocks if isinstance(b, HeaderBlock)]
        assert len(header_blocks) == 1
        hb = header_blocks[0]
        assert hb.apply_to == "all"
        assert len(hb.content) >= 1
        assert isinstance(hb.content[0], ParagraphBlock)

    def test_footer_from_sec_pr(self):
        """secPr 안의 headerFooter[FOOTER] → FooterBlock."""
        sec_pr_xml = (
            '<hp:secPr>'
            '  <hp:headerFooter type="ODD" headerFooter="FOOTER">'
            '    <hp:subList>'
            '      <hp:p paraPrIDRef="0" styleIDRef="0">'
            '        <hp:run charPrIDRef="0"><hp:t>Footer</hp:t></hp:run>'
            '      </hp:p>'
            '    </hp:subList>'
            '  </hp:headerFooter>'
            '</hp:secPr>'
        )
        xml = _wrap_section(
            _wrap_para(_wrap_run(sec_pr_xml))
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        footer_blocks = [b for b in blocks if isinstance(b, FooterBlock)]
        assert len(footer_blocks) == 1
        fb = footer_blocks[0]
        assert fb.apply_to == "odd"

    def test_both_header_and_footer(self):
        """하나의 secPr에 header와 footer가 모두 있을 수 있다."""
        sec_pr_xml = (
            '<hp:secPr>'
            '  <hp:headerFooter type="BOTH" headerFooter="HEADER">'
            '    <hp:subList>'
            '      <hp:p paraPrIDRef="0" styleIDRef="0">'
            '        <hp:run charPrIDRef="0"><hp:t>H</hp:t></hp:run>'
            '      </hp:p>'
            '    </hp:subList>'
            '  </hp:headerFooter>'
            '  <hp:headerFooter type="BOTH" headerFooter="FOOTER">'
            '    <hp:subList>'
            '      <hp:p paraPrIDRef="0" styleIDRef="0">'
            '        <hp:run charPrIDRef="0"><hp:t>F</hp:t></hp:run>'
            '      </hp:p>'
            '    </hp:subList>'
            '  </hp:headerFooter>'
            '</hp:secPr>'
        )
        xml = _wrap_section(
            _wrap_para(_wrap_run(sec_pr_xml))
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        headers = [b for b in blocks if isinstance(b, HeaderBlock)]
        footers = [b for b in blocks if isinstance(b, FooterBlock)]
        assert len(headers) == 1
        assert len(footers) == 1


# ===========================================================================
# 텍스트 하위 요소 (tab, lineBreak)
# ===========================================================================


class TestTextSubElements:
    """hp:t 안의 tab, lineBreak, tail 텍스트가 올바르게 수집되는지 테스트."""

    def test_tab_in_text(self):
        """hp:t 안의 hp:tab → TextInline(text="\\t")."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:t>Before<hp:tab/>After</hp:t>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        para = blocks[0]
        texts = [i.text for i in para.inlines if isinstance(i, TextInline)]
        assert "Before" in texts
        assert "\t" in texts
        assert "After" in texts

    def test_line_break(self):
        """hp:t 안의 hp:lineBreak → TextInline(text="\\n")."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:t>Line1<hp:lineBreak/>Line2</hp:t>'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        para = blocks[0]
        texts = [i.text for i in para.inlines if isinstance(i, TextInline)]
        assert "Line1" in texts
        assert "\n" in texts
        assert "Line2" in texts


# ===========================================================================
# 복합 시나리오
# ===========================================================================


class TestMixedContent:
    """여러 요소 타입이 혼합된 단락 테스트."""

    def test_text_image_equation_in_one_para(self):
        """텍스트, 이미지, 수식이 같은 단락에 있을 때 모두 수집."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run(
                    '<hp:t>Intro: </hp:t>'
                    '<hp:pic><hp:img binaryItemIDRef="fig1.png" /></hp:pic>'
                    '<hp:eqEdit script="E=mc^2" />'
                )
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        para = blocks[0]
        assert len(para.inlines) == 3
        assert isinstance(para.inlines[0], TextInline)
        assert isinstance(para.inlines[1], ImageInline)
        assert isinstance(para.inlines[2], EquationInline)

    def test_multiple_runs(self):
        """여러 run에 걸친 다양한 인라인이 순서대로 수집된다."""
        xml = _wrap_section(
            _wrap_para(
                _wrap_run('<hp:t>Run1</hp:t>')
                + _wrap_run(
                    '<hp:pic><hp:img binaryItemIDRef="r2.png" /></hp:pic>',
                    char_pr="0",
                )
                + _wrap_run('<hp:t>Run3</hp:t>')
            )
        )
        info = _make_info()
        blocks, _ = parse_section_xml(xml, info, "section0.xml")

        para = blocks[0]
        assert len(para.inlines) == 3
        assert para.inlines[0].text == "Run1"
        assert isinstance(para.inlines[1], ImageInline)
        assert para.inlines[2].text == "Run3"


# ===========================================================================
# 유틸리티
# ===========================================================================


def para_inlines_of_type(block, inline_type):
    """ParagraphBlock에서 특정 타입의 인라인을 추출한다."""
    return [i for i in block.inlines if isinstance(i, inline_type)]
