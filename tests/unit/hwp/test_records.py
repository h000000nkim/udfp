"""HWPTAG 레코드 디코더 단위 테스트"""

import struct


from udf.parsers.hwp.records import (
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_TEXT,
    ctrl_id_from_payload,
    iter_records,
)


def _make_record(tag_id: int, level: int, payload: bytes) -> bytes:
    size = len(payload)
    if size < 0xFFF:
        header = (tag_id & 0x3FF) | ((level & 0x3FF) << 10) | (size << 20)
        return struct.pack("<I", header) + payload
    else:
        header = (tag_id & 0x3FF) | ((level & 0x3FF) << 10) | (0xFFF << 20)
        return struct.pack("<II", header, size) + payload


class TestIterRecords:
    def test_single_record(self) -> None:
        payload = b"hello"
        stream = _make_record(HWPTAG_PARA_TEXT, 0, payload)
        records = list(iter_records(stream))
        assert len(records) == 1
        assert records[0].tag_id == HWPTAG_PARA_TEXT
        assert records[0].level == 0
        assert records[0].payload == payload
        assert records[0].offset == 0

    def test_multiple_records(self) -> None:
        p1 = b"\x01\x02"
        p2 = b"\x03\x04\x05"
        stream = _make_record(HWPTAG_PARA_HEADER, 0, p1) + _make_record(
            HWPTAG_PARA_TEXT, 1, p2
        )
        records = list(iter_records(stream))
        assert len(records) == 2
        assert records[0].tag_id == HWPTAG_PARA_HEADER
        assert records[0].level == 0
        assert records[1].tag_id == HWPTAG_PARA_TEXT
        assert records[1].level == 1

    def test_extended_size(self) -> None:
        """size 필드 == 0xFFF 이면 다음 4바이트가 실제 크기."""
        payload = bytes(range(256)) * 20  # 5120 bytes > 0xFFF (4095)
        stream = _make_record(HWPTAG_PARA_TEXT, 0, payload)
        records = list(iter_records(stream))
        assert len(records) == 1
        assert len(records[0].payload) == len(payload)

    def test_empty_stream(self) -> None:
        assert list(iter_records(b"")) == []

    def test_truncated_stream_does_not_raise(self) -> None:
        # header encodes size=1 but no payload bytes follow → truncated
        truncated = b"\x42\x00\x10\x00"
        records = list(iter_records(truncated))
        assert len(records) == 0

    def test_level_extraction(self) -> None:
        payload = b"\xaa"
        for level in (0, 1, 5, 255):
            stream = _make_record(HWPTAG_PARA_HEADER, level, payload)
            rec = next(iter_records(stream))
            assert rec.level == level

    def test_offset_tracking(self) -> None:
        p1, p2 = b"AB", b"CD"
        stream = _make_record(10, 0, p1) + _make_record(11, 0, p2)
        records = list(iter_records(stream))
        assert records[0].offset == 0
        assert records[1].offset == 4 + len(p1)  # header(4) + payload(2)


class TestCtrlIdFromPayload:
    def test_normal(self) -> None:
        # HWP는 ctrlId를 little-endian으로 저장 → "tbl "의 실제 바이트는 역순
        payload = b" lbt\x00\x00"
        assert ctrl_id_from_payload(payload) == "tbl "

    def test_secd(self) -> None:
        # "secd" little-endian bytes
        payload = b"dces\x00\x00"
        assert ctrl_id_from_payload(payload) == "secd"

    def test_too_short(self) -> None:
        assert ctrl_id_from_payload(b"tb") == ""

    def test_empty(self) -> None:
        assert ctrl_id_from_payload(b"") == ""
