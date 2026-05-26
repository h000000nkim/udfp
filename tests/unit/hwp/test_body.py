"""BodyText 파서 단위 테스트"""

import struct

from udf.parsers.hwp.body import _extract_text, _build_inlines, parse_section
from udf.parsers.hwp.doc_info import DocInfoResult
from udf.parsers.hwp.records import (
    HWPTAG_CTRL_HEADER,
    HWPTAG_LIST_HEADER,
    HWPTAG_PARA_CHAR_SHAPE,
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_LINE_SEG,
    HWPTAG_PARA_TEXT,
)
from udf.schema import (
    EndnoteBlock,
    FootnoteBlock,
    HeadingBlock,
    ParagraphBlock,
)
from udf.pipeline.verbatim import GlobalResources


def _make_record(tag_id: int, level: int, payload: bytes) -> bytes:
    size = len(payload)
    header = (tag_id & 0x3FF) | ((level & 0x3FF) << 10) | (min(size, 0xFFE) << 20)
    return struct.pack("<I", header) + payload


def _utf16le(text: str) -> bytes:
    return text.encode("utf-16-le")


def _para_header(para_shape_id: int = 0, style_id: int = 0) -> bytes:
    """최소 PARA_HEADER 페이로드 (22바이트)."""
    buf = bytearray(22)
    struct.pack_into("<H", buf, 8, para_shape_id)  # paraShapeId
    buf[10] = style_id & 0xFF  # styleId
    return bytes(buf)


def _make_pcs(entries: list[tuple[int, int]]) -> bytes:
    """(pos, cs_id) 목록 → PARA_CHAR_SHAPE 페이로드."""
    buf = bytearray(len(entries) * 8)
    for i, (pos, cs_id) in enumerate(entries):
        struct.pack_into("<II", buf, i * 8, pos, cs_id)
    return bytes(buf)


class TestExtractText:
    def test_simple_text(self) -> None:
        text = "안녕하세요"
        payload = _utf16le(text) + b"\x0d\x00"  # 단락 끝
        assert _extract_text(payload) == "안녕하세요"

    def test_tab_skipped(self) -> None:
        payload = _utf16le("A") + b"\x09\x00" + _utf16le("B") + b"\x0d\x00"
        assert _extract_text(payload) == "AB"

    def test_para_end_skipped(self) -> None:
        payload = _utf16le("X") + b"\x0d\x00"
        assert _extract_text(payload) == "X"

    def test_inline_object_skipped(self) -> None:
        # hwp.md §5.2: 제어 코드 0x0002는 인라인 오브젝트 (2+14=16바이트)
        ctrl = b"\x02\x00" + b"\x00" * 14  # 16바이트
        payload = _utf16le("A") + ctrl + _utf16le("B")
        result = _extract_text(payload)
        assert result == "AB"

    def test_empty_payload(self) -> None:
        assert _extract_text(b"") == ""


class TestBuildInlines:
    def _empty_info(self) -> DocInfoResult:
        return DocInfoResult(global_resources=GlobalResources())

    def test_no_pcs_single_inline(self) -> None:
        pt = _utf16le("hello") + b"\x0d\x00"
        inlines = _build_inlines(pt, b"", [])
        assert len(inlines) == 1
        assert inlines[0].text == "hello"

    def test_pcs_splits_into_runs(self) -> None:
        pt = _utf16le("AABB") + b"\x0d\x00"
        cs0: dict = {
            "bold": True,
            "italic": None,
            "underline": None,
            "underline_type": None,
            "strikethrough": None,
            "color": None,
            "font_size_pt": None,
        }
        cs1: dict = {
            "bold": None,
            "italic": True,
            "underline": None,
            "underline_type": None,
            "strikethrough": None,
            "color": None,
            "font_size_pt": None,
        }
        # pos=0 → cs0, pos=2 → cs1
        pcs = _make_pcs([(0, 0), (2, 1)])
        inlines = _build_inlines(pt, pcs, [cs0, cs1])
        assert len(inlines) == 2
        assert inlines[0].text == "AA"
        assert inlines[0].bold is True
        assert inlines[1].text == "BB"
        assert inlines[1].italic is True

    def test_empty_pt_returns_empty(self) -> None:
        inlines = _build_inlines(b"", b"", [])
        assert inlines == []

    def test_superscript_propagated(self) -> None:
        pt = _utf16le("H2O") + b"\x0d\x00"
        cs_normal: dict = {"font_size_pt": 10.0}
        cs_super: dict = {
            "font_size_pt": 7.0,
            "superscript": True,
            "subscript": None,
        }
        pcs = _make_pcs([(0, 0), (1, 1), (2, 0)])
        inlines = _build_inlines(pt, pcs, [cs_normal, cs_super])
        assert inlines[1].superscript is True
        assert inlines[0].superscript is None

    def test_subscript_propagated(self) -> None:
        pt = _utf16le("CO2") + b"\x0d\x00"
        cs_normal: dict = {"font_size_pt": 10.0}
        cs_sub: dict = {
            "font_size_pt": 7.0,
            "subscript": True,
            "superscript": None,
        }
        pcs = _make_pcs([(0, 0), (2, 1)])
        inlines = _build_inlines(pt, pcs, [cs_normal, cs_sub])
        assert inlines[1].subscript is True
        assert inlines[0].subscript is None

    def test_emboss_propagated(self) -> None:
        pt = _utf16le("em") + b"\x0d\x00"
        cs: dict = {"font_size_pt": 10.0, "emboss": True}
        pcs = _make_pcs([(0, 0)])
        inlines = _build_inlines(pt, pcs, [cs])
        assert inlines[0].emboss is True


class TestParseSection:
    def _empty_info(self) -> DocInfoResult:
        return DocInfoResult(global_resources=GlobalResources())

    def _simple_para_stream(self, text: str) -> bytes:
        pt = _utf16le(text) + b"\x0d\x00"
        pls = bytes(36)  # 1 line seg entry
        pcs = _make_pcs([(0, 0)])
        return (
            _make_record(HWPTAG_PARA_HEADER, 0, _para_header())
            + _make_record(HWPTAG_PARA_TEXT, 1, pt)
            + _make_record(HWPTAG_PARA_CHAR_SHAPE, 1, pcs)
            + _make_record(HWPTAG_PARA_LINE_SEG, 1, pls)
        )

    def test_single_paragraph(self) -> None:
        stream = self._simple_para_stream("테스트 텍스트")
        blocks, verb_map = parse_section(stream, self._empty_info())
        assert len(blocks) == 1
        block = blocks[0]
        assert block.type == "paragraph"
        assert block.verbatim_ref is not None
        assert block.verbatim_ref in verb_map

    def test_text_content(self) -> None:
        stream = self._simple_para_stream("hello world")
        blocks, _ = parse_section(stream, self._empty_info())
        assert blocks[0].inlines[0].text == "hello world"

    def test_multiple_paragraphs(self) -> None:
        stream = (
            self._simple_para_stream("첫번째")
            + self._simple_para_stream("두번째")
            + self._simple_para_stream("세번째")
        )
        blocks, _ = parse_section(stream, self._empty_info())
        assert len(blocks) == 3

    def test_verbatim_ref_all_connected(self) -> None:
        """모든 block.verbatim_ref이 verbatim_map에 존재해야 한다."""
        stream = self._simple_para_stream("검증")
        blocks, verb_map = parse_section(stream, self._empty_info())
        for block in blocks:
            if hasattr(block, "verbatim_ref") and block.verbatim_ref:
                assert block.verbatim_ref in verb_map, (
                    f"{block.verbatim_ref} not in verbatim_map"
                )

    def test_empty_stream(self) -> None:
        blocks, verb_map = parse_section(b"", self._empty_info())
        assert blocks == []
        assert verb_map == {}


class TestHeadingBlock:
    """styleId → HeadingBlock 감지 테스트."""

    def _info_with_styles(self, style_names: list[str]) -> DocInfoResult:
        return DocInfoResult(
            global_resources=GlobalResources(),
            style_names=style_names,
        )

    def _heading_para_stream(self, text: str, style_id: int) -> bytes:
        pt = _utf16le(text) + b"\x0d\x00"
        pls = bytes(36)
        pcs = _make_pcs([(0, 0)])
        return (
            _make_record(HWPTAG_PARA_HEADER, 0, _para_header(style_id=style_id))
            + _make_record(HWPTAG_PARA_TEXT, 1, pt)
            + _make_record(HWPTAG_PARA_CHAR_SHAPE, 1, pcs)
            + _make_record(HWPTAG_PARA_LINE_SEG, 1, pls)
        )

    def test_outline_style_emits_heading(self) -> None:
        """'개요 1' 스타일 → HeadingBlock(level=1)."""
        info = self._info_with_styles(["바탕글", "개요 1", "개요 2"])
        stream = self._heading_para_stream("헤딩 텍스트", style_id=1)
        blocks, _ = parse_section(stream, info)
        assert len(blocks) == 1
        blk = blocks[0]
        assert isinstance(blk, HeadingBlock)
        assert blk.level == 1
        assert blk.text == "헤딩 텍스트"

    def test_outline_level2(self) -> None:
        """'개요 2' 스타일 → HeadingBlock(level=2)."""
        info = self._info_with_styles(["바탕글", "개요 1", "개요 2"])
        stream = self._heading_para_stream("소 헤딩", style_id=2)
        blocks, _ = parse_section(stream, info)
        blk = blocks[0]
        assert isinstance(blk, HeadingBlock)
        assert blk.level == 2

    def test_normal_style_emits_paragraph(self) -> None:
        """일반 스타일 → ParagraphBlock."""
        info = self._info_with_styles(["바탕글", "개요 1"])
        stream = self._heading_para_stream("보통 텍스트", style_id=0)
        blocks, _ = parse_section(stream, info)
        assert isinstance(blocks[0], ParagraphBlock)

    def test_paragraph_styles_fixture(self) -> None:
        """실제 paragraph_styles.hwp에서 HeadingBlock이 감지되어야 한다."""
        import pathlib
        from udf.parsers.hwp.parse import parse_hwp

        fixture = (
            pathlib.Path(__file__).parent.parent.parent
            / "fixtures"
            / "hwp"
            / "paragraph_styles.hwp"
        )
        if not fixture.exists():
            return
        doc = parse_hwp(str(fixture))
        heading_blocks = [b for b in doc.blocks if b.type == "heading"]
        assert len(heading_blocks) >= 1, "paragraph_styles.hwp에서 HeadingBlock이 없음"
        levels = {b.level for b in heading_blocks}
        assert 1 in levels, "level=1 HeadingBlock이 없음"


class TestFootnoteEndnote:
    """합성 fn/en CTRL_HEADER → FootnoteBlock/EndnoteBlock 파싱."""

    def _empty_info(self) -> DocInfoResult:
        return DocInfoResult(global_resources=GlobalResources())

    def _ctrl_header_payload(self, ctrl_id: str, fn_number: int = 1) -> bytes:
        """CTRL_HEADER 페이로드 (20B): ctrlId(4) + number(u32) + beforeDeco(u16) + afterDeco(u16) + numberShape(u32) + instanceId(u32)."""
        buf = bytearray(20)
        buf[0:4] = ctrl_id.encode("ascii")[::-1]
        struct.pack_into("<I", buf, 4, fn_number)
        struct.pack_into("<H", buf, 10, 0x0029)  # afterDeco = ')'
        return bytes(buf)

    def _list_header_payload(self) -> bytes:
        """최소 LIST_HEADER 페이로드 (32바이트)."""
        return bytes(32)

    def _fn_stream(self, ctrl_id: str = "fn  ", fn_number: int = 1) -> bytes:
        """CTRL_HEADER("fn  ") → LIST_HEADER → PARA_HEADER → PT 구조."""
        pt = _utf16le("각주 내용") + b"\x0d\x00"
        pls = bytes(36)
        pcs = _make_pcs([(0, 0)])
        return (
            _make_record(HWPTAG_CTRL_HEADER, 0, self._ctrl_header_payload(ctrl_id, fn_number))
            + _make_record(HWPTAG_LIST_HEADER, 1, self._list_header_payload())
            + _make_record(HWPTAG_PARA_HEADER, 1, _para_header())
            + _make_record(HWPTAG_PARA_TEXT, 2, pt)
            + _make_record(HWPTAG_PARA_CHAR_SHAPE, 2, pcs)
            + _make_record(HWPTAG_PARA_LINE_SEG, 2, pls)
        )

    def test_footnote_parsed(self) -> None:
        stream = self._fn_stream("fn  ", 1)
        blocks, verb_map = parse_section(stream, self._empty_info())
        assert len(blocks) == 1
        blk = blocks[0]
        assert isinstance(blk, FootnoteBlock)
        assert blk.ref == "1"
        assert len(blk.content) >= 1
        assert blk.verbatim_ref is not None

    def test_endnote_parsed(self) -> None:
        stream = self._fn_stream("en  ", 2)
        blocks, verb_map = parse_section(stream, self._empty_info())
        assert len(blocks) == 1
        blk = blocks[0]
        assert isinstance(blk, EndnoteBlock)
        assert blk.ref == "2"

    def test_footnote_content_is_paragraph(self) -> None:
        stream = self._fn_stream("fn  ", 1)
        blocks, _ = parse_section(stream, self._empty_info())
        fn = blocks[0]
        assert isinstance(fn, FootnoteBlock)
        assert any(isinstance(b, ParagraphBlock) for b in fn.content)
        para = [b for b in fn.content if isinstance(b, ParagraphBlock)][0]
        assert para.inlines[0].text == "각주 내용"
