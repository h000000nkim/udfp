"""DocInfo 파서 단위 테스트"""

import struct

from udf.parsers.hwp.doc_info import (
    _parse_border_fill,
    _parse_char_shape,
    _parse_face_name,
    _parse_face_name_detail,
    _parse_numbering,
    _parse_para_shape,
    parse_doc_info,
)
from udf.parsers.hwp.records import (
    HWPTAG_CHAR_SHAPE,
    HWPTAG_FACE_NAME,
    HWPTAG_ID_MAPPINGS,
    HWPTAG_PARA_SHAPE,
    HWPTAG_STYLE,
)


def _make_record(tag_id: int, level: int, payload: bytes) -> bytes:
    size = len(payload)
    header = (tag_id & 0x3FF) | ((level & 0x3FF) << 10) | (min(size, 0xFFE) << 20)
    return struct.pack("<I", header) + payload


class TestParseCharShape:
    def _make_payload(
        self,
        *,
        bold: bool = False,
        italic: bool = False,
        base_size: int = 1000,  # 10pt in HWPUNIT (1pt = 100)
        color: int = 0,
        underline_color: int = 0,
        ratio_hangul: int = 100,
        spacing_hangul: int = 0,
        rel_size_hangul: int = 100,
        offset_hangul: int = 0,
        strikethrough: bool = False,
    ) -> bytes:
        buf = bytearray(74)
        buf[14] = ratio_hangul & 0xFF
        struct.pack_into("<b", buf, 21, spacing_hangul)
        buf[28] = rel_size_hangul & 0xFF
        struct.pack_into("<b", buf, 35, offset_hangul)
        struct.pack_into("<i", buf, 42, base_size)
        attr = (0x01 if italic else 0) | (0x02 if bold else 0)
        if strikethrough:
            attr |= 2 << 18
        struct.pack_into("<I", buf, 46, attr)
        struct.pack_into("<I", buf, 52, color)
        struct.pack_into("<I", buf, 56, underline_color)
        return bytes(buf)

    def test_bold(self) -> None:
        cs = _parse_char_shape(self._make_payload(bold=True))
        assert cs["bold"] is True

    def test_italic(self) -> None:
        cs = _parse_char_shape(self._make_payload(italic=True))
        assert cs["italic"] is True

    def test_bold_italic_independent(self) -> None:
        cs = _parse_char_shape(self._make_payload(bold=True, italic=False))
        assert cs["bold"] is True
        assert cs["italic"] is None

    def test_font_size(self) -> None:
        cs = _parse_char_shape(self._make_payload(base_size=1000))
        assert cs["font_size_pt"] == 10.0

    def test_color(self) -> None:
        cs = _parse_char_shape(self._make_payload(color=0x000000FF))
        assert cs["color"] == "#ff0000"

    def test_color_blue(self) -> None:
        cs = _parse_char_shape(self._make_payload(color=0x00FF0000))
        assert cs["color"] == "#0000ff"

    def test_underline_color(self) -> None:
        cs = _parse_char_shape(self._make_payload(underline_color=0x0000FF00))
        assert cs["underline_color"] == "#00ff00"

    def test_char_scale(self) -> None:
        cs = _parse_char_shape(self._make_payload(ratio_hangul=80))
        assert cs["char_scale"] == 80

    def test_char_scale_default(self) -> None:
        cs = _parse_char_shape(self._make_payload(ratio_hangul=100))
        assert cs["char_scale"] is None

    def test_letter_spacing(self) -> None:
        cs = _parse_char_shape(self._make_payload(spacing_hangul=-5))
        assert cs["letter_spacing"] == "-5%"

    def test_char_offset(self) -> None:
        cs = _parse_char_shape(self._make_payload(offset_hangul=10))
        assert cs["char_offset"] == "10%"

    def test_strikethrough(self) -> None:
        cs = _parse_char_shape(self._make_payload(strikethrough=True))
        assert cs["strikethrough"] is True

    def test_color_black(self) -> None:
        cs = _parse_char_shape(self._make_payload(color=0x00000000))
        assert cs["color"] == "#000000"

    def test_underline_color_black(self) -> None:
        cs = _parse_char_shape(self._make_payload(underline_color=0x00000000))
        assert cs["underline_color"] == "#000000"

    def test_font_size_zero(self) -> None:
        cs = _parse_char_shape(self._make_payload(base_size=0))
        assert cs["font_size_pt"] == 0.0

    def test_pack_parse_color_roundtrip(self) -> None:
        from udf.renderers.hwp.docinfo_builder import CharShapeSpec, pack_char_shape
        spec = CharShapeSpec(color_r=255, color_g=0, color_b=0)
        payload = pack_char_shape(spec)
        cs = _parse_char_shape(payload)
        assert cs["color"] == "#ff0000"

    def test_pack_parse_color_blue_roundtrip(self) -> None:
        from udf.renderers.hwp.docinfo_builder import CharShapeSpec, pack_char_shape
        spec = CharShapeSpec(color_r=0, color_g=0, color_b=255)
        payload = pack_char_shape(spec)
        cs = _parse_char_shape(payload)
        assert cs["color"] == "#0000ff"

    def test_too_short_returns_empty(self) -> None:
        assert _parse_char_shape(b"\x00" * 10) == {}

    def test_emboss_from_attr(self) -> None:
        buf = bytearray(74)
        struct.pack_into("<i", buf, 42, 1000)
        struct.pack_into("<I", buf, 46, 1 << 13)  # emboss bit
        cs = _parse_char_shape(bytes(buf))
        assert cs["emboss"] is True
        assert cs["engrave"] is None

    def test_engrave_from_attr(self) -> None:
        buf = bytearray(74)
        struct.pack_into("<i", buf, 42, 1000)
        struct.pack_into("<I", buf, 46, 1 << 14)  # engrave bit
        cs = _parse_char_shape(bytes(buf))
        assert cs["engrave"] is True
        assert cs["emboss"] is None

    def test_superscript_synthesized(self) -> None:
        """rel_size < 100 + positive offset → superscript."""
        cs = _parse_char_shape(self._make_payload(rel_size_hangul=70, offset_hangul=30))
        assert cs["superscript"] is True
        assert cs["subscript"] is None

    def test_subscript_synthesized(self) -> None:
        """rel_size < 100 + negative offset → subscript."""
        cs = _parse_char_shape(self._make_payload(rel_size_hangul=70, offset_hangul=-30))
        assert cs["subscript"] is True
        assert cs["superscript"] is None

    def test_normal_text_no_super_sub(self) -> None:
        """rel_size=100 → no superscript/subscript regardless of offset."""
        cs = _parse_char_shape(self._make_payload(rel_size_hangul=100, offset_hangul=10))
        assert cs["superscript"] is None
        assert cs["subscript"] is None

    def test_small_rel_size_no_offset(self) -> None:
        """rel_size < 100 but offset=0 → neither super nor sub."""
        cs = _parse_char_shape(self._make_payload(rel_size_hangul=70, offset_hangul=0))
        assert cs["superscript"] is None
        assert cs["subscript"] is None


class TestParseParaShape:
    def _make_payload(self, *, align: int = 0, ls_type: int = 0) -> bytes:
        buf = bytearray(54)
        attr = (ls_type & 0x3) | ((align & 0x7) << 2)
        struct.pack_into("<I", buf, 0, attr)
        return bytes(buf)

    def test_justify_align_0(self) -> None:
        ps = _parse_para_shape(self._make_payload(align=0))
        assert ps["alignment"] == "justify"

    def test_left_align(self) -> None:
        ps = _parse_para_shape(self._make_payload(align=1))
        assert ps["alignment"] == "left"

    def test_right_align(self) -> None:
        ps = _parse_para_shape(self._make_payload(align=2))
        assert ps["alignment"] == "right"

    def test_center_align(self) -> None:
        ps = _parse_para_shape(self._make_payload(align=3))
        assert ps["alignment"] == "center"

    def test_line_spacing_type_ratio(self) -> None:
        ps = _parse_para_shape(self._make_payload(ls_type=0))
        assert ps["line_spacing_type"] == "ratio"

    def test_line_spacing_type_fixed(self) -> None:
        ps = _parse_para_shape(self._make_payload(ls_type=1))
        assert ps["line_spacing_type"] == "fixed"

    def test_line_spacing_type_minimum(self) -> None:
        ps = _parse_para_shape(self._make_payload(ls_type=3))
        assert ps["line_spacing_type"] == "minimum"

    def test_too_short_returns_empty(self) -> None:
        assert _parse_para_shape(b"\x00" * 2) == {}


class TestParseFaceName:
    def _make_payload(self, name: str) -> bytes:
        encoded = name.encode("utf-16-le")
        n = len(name)
        return bytes([0x01]) + struct.pack("<H", n) + encoded

    def test_normal_name(self) -> None:
        assert _parse_face_name(self._make_payload("나눔고딕")) == "나눔고딕"

    def test_empty_payload(self) -> None:
        assert _parse_face_name(b"") is None

    def test_no_name_flag(self) -> None:
        assert _parse_face_name(bytes([0x00])) is None


class TestParseDocInfo:
    def _stream(self, records: list[bytes]) -> bytes:
        return b"".join(records)

    def test_empty_stream(self) -> None:
        result = parse_doc_info(b"")
        assert result.char_shapes == []
        assert result.para_shapes == []

    def test_char_shape_collected(self) -> None:
        cs_payload = bytearray(74)
        struct.pack_into("<i", cs_payload, 42, 1000)  # 10pt
        stream = self._stream([_make_record(HWPTAG_CHAR_SHAPE, 0, bytes(cs_payload))])
        result = parse_doc_info(stream)
        assert len(result.char_shapes) == 1
        assert result.char_shapes[0]["font_size_pt"] == 10.0

    def test_para_shape_collected(self) -> None:
        ps_payload = bytearray(54)
        struct.pack_into("<I", ps_payload, 0, 3 << 2)  # center
        stream = self._stream([_make_record(HWPTAG_PARA_SHAPE, 0, bytes(ps_payload))])
        result = parse_doc_info(stream)
        assert len(result.para_shapes) == 1
        assert result.para_shapes[0]["alignment"] == "center"

    def test_style_links_format(self) -> None:
        cs_payload = bytearray(74)
        struct.pack_into("<i", cs_payload, 42, 1200)  # 12pt
        attr = 0x02  # bold
        struct.pack_into("<I", cs_payload, 46, attr)

        ps_payload = bytearray(54)
        struct.pack_into("<I", ps_payload, 0, 3 << 2)  # center

        style_name = "본문"
        encoded_name = style_name.encode("utf-16-le")
        style_payload = struct.pack("<H", len(style_name)) + encoded_name
        style_payload += struct.pack("<H", 0)  # english name (empty)
        style_payload += bytes([0, 0, 0, 0, 0, 0])  # type + next + lang + lock
        style_payload += struct.pack("<HH", 0, 0)  # para_shape_id=0, char_shape_id=0

        stream = self._stream([
            _make_record(HWPTAG_CHAR_SHAPE, 0, bytes(cs_payload)),
            _make_record(HWPTAG_PARA_SHAPE, 0, bytes(ps_payload)),
            _make_record(HWPTAG_STYLE, 0, style_payload),
        ])
        result = parse_doc_info(stream)
        sdef = result.global_resources.styles["0"]
        assert sdef.name == "본문"
        assert sdef.format is not None
        assert sdef.format.alignment == "center"
        assert sdef.format.bold is True
        assert sdef.format.font_size == 12.0

    def test_face_name_collected(self) -> None:
        name = "맑은고딕"
        encoded = name.encode("utf-16-le")
        payload = bytes([0x01]) + struct.pack("<H", len(name)) + encoded
        stream = self._stream([_make_record(HWPTAG_FACE_NAME, 0, payload)])
        result = parse_doc_info(stream)
        assert result.face_names == ["맑은고딕"]


class TestFaceName7Fallback:
    def _make_fn_payload(self, name: str) -> bytes:
        encoded = name.encode("utf-16-le")
        return bytes([0x01]) + struct.pack("<H", len(name)) + encoded

    def _make_id_mappings(self, counts: list[int]) -> bytes:
        buf = bytearray(len(counts) * 2)
        for i, cnt in enumerate(counts):
            struct.pack_into("<H", buf, i * 2, cnt)
        return bytes(buf)

    def test_7fallback_mapping(self) -> None:
        """ID_MAPPINGS으로 카테고리별 FaceName이 FontFallbacks 슬롯에 매핑된다."""
        # 카테고리별 1개씩: hangul=나눔고딕, latin=Arial, hanja=HCI, ...
        id_map = self._make_id_mappings([
            0,   # binary data
            1,   # hangul FaceName count
            1,   # latin FaceName count
            1,   # hanja FaceName count
            0, 0, 0, 0,  # japanese, other, symbol, user = 0
            0, 0, 0, 0, 0, 0, 0,  # BorderFill, CharShape, ...
        ])
        fn_hangul = self._make_fn_payload("나눔고딕")
        fn_latin = self._make_fn_payload("Arial")
        fn_hanja = self._make_fn_payload("바탕")

        stream = (
            _make_record(HWPTAG_ID_MAPPINGS, 0, id_map)
            + _make_record(HWPTAG_FACE_NAME, 0, fn_hangul)
            + _make_record(HWPTAG_FACE_NAME, 0, fn_latin)
            + _make_record(HWPTAG_FACE_NAME, 0, fn_hanja)
        )
        result = parse_doc_info(stream)
        ff = result.global_resources.face_names.get("0")
        assert ff is not None
        assert ff.hangul == "나눔고딕"
        assert ff.latin == "Arial"
        assert ff.hanja == "바탕"

    def test_face_name_detail_with_substitute(self) -> None:
        name = "나눔고딕"
        encoded = name.encode("utf-16-le")
        sub_name = "굴림"
        sub_encoded = sub_name.encode("utf-16-le")
        payload = (
            bytes([0x03])  # flags: has_name + has_substitute
            + struct.pack("<H", len(name)) + encoded
            + bytes([0x01])  # substitute type
            + struct.pack("<H", len(sub_name)) + sub_encoded
        )
        detail = _parse_face_name_detail(payload)
        assert detail["name"] == "나눔고딕"
        assert detail["substitute_name"] == "굴림"


class TestBorderFillParsing:
    def test_border_color_extracted(self) -> None:
        payload = bytearray(40)
        # attr (2B)
        # left border: type=1(solid), width=1, color=0x00FF0000 (red in BGR)
        payload[2] = 1  # type
        payload[3] = 1  # width
        struct.pack_into("<I", payload, 4, 0x000000FF)  # COLORREF 0x00BBGGRR: R=FF → #ff0000
        result = _parse_border_fill(bytes(payload))
        assert result.get("border_left_color") == "#ff0000"
        assert result.get("border_left_style") == "solid"

    def test_fill_color_extracted(self) -> None:
        payload = bytearray(50)
        # 4면 테두리 (4×6=24B) + 대각선 (6B) = 32B offset from byte 2
        off = 2 + 24 + 6  # = 32
        struct.pack_into("<I", payload, off, 0x01)  # fill_attr: 단색
        struct.pack_into("<I", payload, off + 4, 0x0000FF00)  # green in BGR
        result = _parse_border_fill(bytes(payload))
        assert result.get("fill_color") == "#00ff00"

    def test_fixture_border_fills(self) -> None:
        """실제 fixture에서 BorderFill 파싱 확인."""
        import pathlib
        from udf.parsers.hwp.parse import parse_hwp

        fixture = (
            pathlib.Path(__file__).parent.parent.parent
            / "fixtures" / "hwp" / "f04_simple_table.hwp"
        )
        if not fixture.exists():
            return
        doc = parse_hwp(str(fixture))
        bfs = doc.verbatim.global_resources.border_fills if doc.verbatim else {}
        # 테이블이 있는 fixture에는 보통 BorderFill이 있음
        if bfs:
            first_bf = next(iter(bfs.values()))
            # id는 항상 존재
            assert first_bf.id is not None


class TestNumberingParsing:
    def test_numbering_levels_extracted(self) -> None:
        """합성 Numbering 레코드에서 레벨 정보가 추출된다."""
        # 레벨별 구조: 12-byte header + uint16 str_len + utf16le string
        buf = bytearray()
        for i in range(7):
            pattern = f"^{i+1}."
            encoded = pattern.encode("utf-16-le")
            # 12-byte header: flags(2) + reserved(4) + num_format(2) + reserved(4)
            buf += struct.pack("<H", 0)  # flags
            buf += struct.pack("<I", 0)  # reserved
            buf += struct.pack("<H", 0)  # num_format = decimal
            buf += struct.pack("<I", 0xFFFFFFFF)  # reserved
            buf += struct.pack("<H", len(pattern)) + encoded
        # 7 start values (uint32 each)
        for _ in range(7):
            buf += struct.pack("<I", 1)
        result = _parse_numbering(bytes(buf))
        assert "levels" in result
        levels = result["levels"]
        assert len(levels) == 7
        assert levels[0]["format"] == "decimal"
        assert levels[0]["pattern"] == "^1."

    def test_fixture_numbering(self) -> None:
        """실제 fixture에서 Numbering 파싱 확인."""
        import pathlib
        from udf.parsers.hwp.parse import parse_hwp

        fixture = (
            pathlib.Path(__file__).parent.parent.parent
            / "fixtures" / "hwp" / "f01_plain_text.hwp"
        )
        if not fixture.exists():
            return
        doc = parse_hwp(str(fixture))
        nums = doc.verbatim.global_resources.numberings if doc.verbatim else {}
        for nid, ndef in nums.items():
            assert len(ndef.levels) > 0
            assert ndef.levels[0].level == 0
