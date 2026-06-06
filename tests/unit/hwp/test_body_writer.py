"""body_writer 단위 테스트 — 인라인 컨트롤 보존 검증."""

import struct

from udf.renderers.hwp.body_writer import (
    _rebuild_pt_with_new_text,
    _split_pt_segments,
    apply_paragraph_patches,
)
from udf.parsers.hwp.records import (
    HWPTAG_PARA_CHAR_SHAPE,
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_LINE_SEG,
    HWPTAG_PARA_TEXT,
)


def _utf16(text: str) -> bytes:
    return text.encode("utf-16-le")


def _ctrl16(code: int) -> bytes:
    """16바이트 인라인 컨트롤 오브젝트 생성."""
    buf = bytearray(16)
    struct.pack_into("<H", buf, 0, code)
    return bytes(buf)


def _make_pt(*parts: bytes, cr: bool = True) -> bytes:
    """PT 바이트 조립. parts: text bytes 또는 ctrl bytes."""
    result = b"".join(parts)
    if cr:
        result += b"\x0d\x00"
    return result


class TestSplitPtSegments:
    def test_plain_text(self) -> None:
        pt = _make_pt(_utf16("hello"))
        segs = _split_pt_segments(pt)
        assert len(segs) == 1
        assert segs[0][0] == "text"
        assert segs[0][1] == _utf16("hello")

    def test_ctrl_only(self) -> None:
        ctrl = _ctrl16(0x000B)
        pt = _make_pt(ctrl)
        segs = _split_pt_segments(pt)
        assert len(segs) == 1
        assert segs[0][0] == "ctrl"
        assert segs[0][1] == ctrl

    def test_text_ctrl_text(self) -> None:
        ctrl = _ctrl16(0x000B)
        pt = _make_pt(_utf16("AB"), ctrl, _utf16("CD"))
        segs = _split_pt_segments(pt)
        assert len(segs) == 3
        assert segs[0] == ("text", _utf16("AB"))
        assert segs[1] == ("ctrl", ctrl)
        assert segs[2] == ("text", _utf16("CD"))

    def test_prefix_ctrl_then_text(self) -> None:
        """secd/cold 같은 앞쪽 컨트롤 + 텍스트."""
        ctrl = _ctrl16(0x0002)
        pt = _make_pt(ctrl, _utf16("body"))
        segs = _split_pt_segments(pt)
        assert len(segs) == 2
        assert segs[0] == ("ctrl", ctrl)
        assert segs[1] == ("text", _utf16("body"))

    def test_multiple_ctrls(self) -> None:
        c1 = _ctrl16(0x000B)
        c2 = _ctrl16(0x0011)
        pt = _make_pt(_utf16("A"), c1, _utf16("B"), c2, _utf16("C"))
        segs = _split_pt_segments(pt)
        assert len(segs) == 5
        assert segs[0] == ("text", _utf16("A"))
        assert segs[1] == ("ctrl", c1)
        assert segs[2] == ("text", _utf16("B"))
        assert segs[3] == ("ctrl", c2)
        assert segs[4] == ("text", _utf16("C"))

    def test_tab_in_text(self) -> None:
        """탭(0x0009)은 2바이트 제어코드 → 텍스트 세그먼트에 포함."""
        pt = _make_pt(_utf16("A"), b"\x09\x00", _utf16("B"))
        segs = _split_pt_segments(pt)
        assert len(segs) == 1
        assert segs[0][0] == "text"

    def test_empty_payload(self) -> None:
        segs = _split_pt_segments(b"")
        assert segs == []


class TestRebuildPtWithNewText:
    def test_no_ctrl_plain_replace(self) -> None:
        segs = [("text", _utf16("hello"))]
        result = _rebuild_pt_with_new_text(segs, "world", True)
        assert result == _utf16("world") + b"\x0d\x00"

    def test_preserve_single_ctrl(self) -> None:
        """텍스트 앞의 ctrl 보존."""
        ctrl = _ctrl16(0x0002)
        segs = [("ctrl", ctrl), ("text", _utf16("body"))]
        result = _rebuild_pt_with_new_text(segs, "new", True)
        assert result.startswith(ctrl)
        assert result.endswith(b"\x0d\x00")
        text_part = result[16:-2]
        assert text_part == _utf16("new")

    def test_preserve_middle_ctrl(self) -> None:
        """텍스트 사이의 ctrl 보존."""
        ctrl = _ctrl16(0x000B)
        segs = [("text", _utf16("AB")), ("ctrl", ctrl), ("text", _utf16("CD"))]
        result = _rebuild_pt_with_new_text(segs, "ABCD", True)
        assert ctrl in result
        assert result.endswith(b"\x0d\x00")

    def test_preserve_footnote_ref(self) -> None:
        """각주참조(0x0011) 인라인 컨트롤 보존."""
        fn_ctrl = _ctrl16(0x0011)
        segs = [("text", _utf16("text")), ("ctrl", fn_ctrl), ("text", _utf16("more"))]
        result = _rebuild_pt_with_new_text(segs, "textmore", True)
        assert fn_ctrl in result

    def test_multiple_ctrls_preserved(self) -> None:
        c1 = _ctrl16(0x000B)
        c2 = _ctrl16(0x0011)
        segs = [
            ("text", _utf16("A")),
            ("ctrl", c1),
            ("text", _utf16("B")),
            ("ctrl", c2),
            ("text", _utf16("C")),
        ]
        result = _rebuild_pt_with_new_text(segs, "ABC", True)
        assert c1 in result
        assert c2 in result
        assert result.endswith(b"\x0d\x00")

    def test_no_trailing_cr(self) -> None:
        segs = [("text", _utf16("hello"))]
        result = _rebuild_pt_with_new_text(segs, "world", False)
        assert result == _utf16("world")
        assert not result.endswith(b"\x0d\x00")

    def test_empty_segments_with_ctrl(self) -> None:
        """텍스트 없이 ctrl만 있을 때."""
        ctrl = _ctrl16(0x0002)
        segs = [("ctrl", ctrl)]
        result = _rebuild_pt_with_new_text(segs, "added", True)
        assert result.startswith(ctrl)
        assert _utf16("added") in result


def _make_record(tag_id: int, level: int, payload: bytes, offset: int = 0) -> bytes:
    size = len(payload)
    header = (tag_id & 0x3FF) | ((level & 0x3FF) << 10) | (min(size, 0xFFE) << 20)
    return struct.pack("<I", header) + payload


def _make_section_stream(text: str, char_cnt: int | None = None, offset: int = 0) -> bytes:
    """단순 섹션 스트림 (PH + PT + PCS + PLS) 생성."""
    pt = _utf16(text) + b"\x0d\x00"
    cc = char_cnt if char_cnt is not None else len(pt) // 2
    ph = bytearray(22)
    struct.pack_into("<I", ph, 0, cc)
    struct.pack_into("<H", ph, 12, 1)  # csCount=1
    pcs = struct.pack("<II", 0, 0)  # pos=0, csId=0
    pls = bytes(36)  # 1 line seg
    return (
        _make_record(HWPTAG_PARA_HEADER, 0, bytes(ph))
        + _make_record(HWPTAG_PARA_TEXT, 1, pt)
        + _make_record(HWPTAG_PARA_CHAR_SHAPE, 1, pcs)
        + _make_record(HWPTAG_PARA_LINE_SEG, 1, pls)
    )


def _make_section_stream_with_ctrl(
    text_before: str, ctrl_code: int, text_after: str
) -> bytes:
    """인라인 컨트롤 포함 섹션 스트림."""
    ctrl = _ctrl16(ctrl_code)
    pt = _utf16(text_before) + ctrl + _utf16(text_after) + b"\x0d\x00"
    cc = len(pt) // 2
    ph = bytearray(22)
    struct.pack_into("<I", ph, 0, cc)
    struct.pack_into("<H", ph, 12, 1)
    pcs = struct.pack("<II", 0, 0)
    pls = bytes(36)
    return (
        _make_record(HWPTAG_PARA_HEADER, 0, bytes(ph))
        + _make_record(HWPTAG_PARA_TEXT, 1, pt)
        + _make_record(HWPTAG_PARA_CHAR_SHAPE, 1, pcs)
        + _make_record(HWPTAG_PARA_LINE_SEG, 1, pls)
    )


class TestApplyParagraphPatches:
    def test_plain_text_patch(self) -> None:
        stream = _make_section_stream("hello")
        patched = apply_paragraph_patches(stream, [(0, "world")])
        assert _utf16("world") in patched
        assert _utf16("hello") not in patched

    def test_preserve_equation_inline(self) -> None:
        """수식(0x000B) 인라인 컨트롤이 패치 후에도 보존되어야 한다."""
        stream = _make_section_stream_with_ctrl("AB", 0x000B, "CD")
        patched = apply_paragraph_patches(stream, [(0, "ABCD")])
        ctrl = _ctrl16(0x000B)
        assert ctrl in patched

    def test_preserve_footnote_ref_inline(self) -> None:
        """각주참조(0x0011) 인라인 컨트롤이 패치 후에도 보존되어야 한다."""
        stream = _make_section_stream_with_ctrl("text", 0x0011, "more")
        patched = apply_paragraph_patches(stream, [(0, "textmore")])
        ctrl = _ctrl16(0x0011)
        assert ctrl in patched

    def test_preserve_secd_prefix(self) -> None:
        """secd(0x0002) 프리픽스가 패치 후에도 보존되어야 한다."""
        ctrl = _ctrl16(0x0002)
        pt = ctrl + _utf16("body") + b"\x0d\x00"
        cc = len(pt) // 2
        ph = bytearray(22)
        struct.pack_into("<I", ph, 0, cc)
        struct.pack_into("<H", ph, 12, 1)
        pcs = struct.pack("<II", 0, 0)
        pls = bytes(36)
        stream = (
            _make_record(HWPTAG_PARA_HEADER, 0, bytes(ph))
            + _make_record(HWPTAG_PARA_TEXT, 1, pt)
            + _make_record(HWPTAG_PARA_CHAR_SHAPE, 1, pcs)
            + _make_record(HWPTAG_PARA_LINE_SEG, 1, pls)
        )
        patched = apply_paragraph_patches(stream, [(0, "new")])
        assert ctrl in patched

    def test_no_patch_returns_original(self) -> None:
        stream = _make_section_stream("hello")
        assert apply_paragraph_patches(stream, []) is stream


class TestPcsMultiEdit:
    """BUG-215: PCS adjustment with multi-edit (text changed on both sides of ctrl)."""

    def test_ctrl_anchor_preserves_pcs_at_ctrl(self):
        """PCS entry at ctrl position maps to new ctrl position."""
        from udf.renderers.hwp.body_writer import _adjust_pcs_positions

        # Old: "AB" + [16B ctrl] + "CD" + CR = 2+8+2+1 = 13 chars
        ctrl = _ctrl16(0x000B)
        old_pt = _utf16("AB") + ctrl + _utf16("CD") + b"\x0d\x00"
        # New: "XYZ" + [16B ctrl] + "W" + CR = 3+8+1+1 = 13 chars
        new_pt = _utf16("XYZ") + ctrl + _utf16("W") + b"\x0d\x00"

        # PCS: pos=0 → cs0, pos=2 → cs1 (at ctrl start)
        pcs = [
            struct.pack("<II", 0, 10),
            struct.pack("<II", 2, 20),
        ]
        result = _adjust_pcs_positions(old_pt, new_pt, pcs)

        positions = [struct.unpack_from("<I", e, 0)[0] for e in result]
        cs_ids = [struct.unpack_from("<I", e, 4)[0] for e in result]
        assert positions[0] == 0
        assert positions[1] == 3  # ctrl moved from pos 2 to pos 3
        assert cs_ids == [10, 20]

    def test_both_sides_changed_different_lengths(self):
        """Text changes on both sides with different length deltas."""
        from udf.renderers.hwp.body_writer import _adjust_pcs_positions

        # Old: "AB" + [ctrl] + "CD" + CR = 2+8+2+1 = 13 chars (26 bytes)
        ctrl = _ctrl16(0x000B)
        old_pt = _utf16("AB") + ctrl + _utf16("CD") + b"\x0d\x00"
        # New: "XYZW" + [ctrl] + "V" + CR = 4+8+1+1 = 14 chars (28 bytes)
        new_pt = _utf16("XYZW") + ctrl + _utf16("V") + b"\x0d\x00"

        # PCS: pos=0→cs0, pos=2→cs1 (ctrl), pos=10→cs2 (after ctrl)
        pcs = [
            struct.pack("<II", 0, 10),
            struct.pack("<II", 2, 20),
            struct.pack("<II", 10, 30),
        ]
        result = _adjust_pcs_positions(old_pt, new_pt, pcs)
        positions = [struct.unpack_from("<I", e, 0)[0] for e in result]
        # pos 0 → 0 (start), pos 2 → 4 (ctrl), pos 10 → 12 (after ctrl)
        assert positions[0] == 0
        assert positions[1] == 4
        assert positions[2] == 12

    def test_no_ctrl_falls_back_to_prefix_suffix(self):
        """Without ctrls, use prefix/suffix matching (backwards compat)."""
        from udf.renderers.hwp.body_writer import _adjust_pcs_positions

        old_pt = _utf16("Hello world") + b"\x0d\x00"
        new_pt = _utf16("Hello earth") + b"\x0d\x00"

        pcs = [struct.pack("<II", 0, 10)]
        result = _adjust_pcs_positions(old_pt, new_pt, pcs)
        assert len(result) == 1
        assert struct.unpack_from("<I", result[0], 0)[0] == 0
