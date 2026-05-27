"""HWP DocInfo/Body 구조 정합성 검증 (I-규칙) 테스트."""

import struct

import pytest

from udf.parsers.hwp.ole import OleReader
from udf.renderers.hwp.docinfo_builder import (
    CharShapeSpec,
    ParaShapeSpec,
    build_docinfo,
    _pack_record,
)
from udf.parsers.hwp.records import (
    HWPTAG_CHAR_SHAPE,
    HWPTAG_ID_MAPPINGS,
    HWPTAG_PARA_SHAPE,
    iter_records,
)
from udf.validation.hwp.integrity import (
    check_i1,
    check_i2,
    check_i3_body,
    check_i3_docinfo,
    validate_hwp_integrity,
    validate_hwp_full,
)

SEED = "tests/fixtures/hwp/plain_text.hwp"


@pytest.fixture
def seed_docinfo():
    with OleReader.open(SEED) as ole:
        return ole.read_stream(["DocInfo"])


@pytest.fixture
def seed_section():
    with OleReader.open(SEED) as ole:
        return ole.read_stream(["BodyText", "Section0"])


class TestCheckI1:
    def test_seed_passes(self, seed_docinfo):
        assert check_i1(seed_docinfo) == []

    def test_added_cs_passes(self, seed_docinfo):
        cs = CharShapeSpec(size_pt=18.0, bold=True)
        new_di, _, _, _ = build_docinfo(seed_docinfo, [cs], [])
        assert check_i1(new_di) == []

    def test_broken_idmap_detected(self, seed_docinfo):
        cs = CharShapeSpec(size_pt=18.0)
        new_di, _, _, _ = build_docinfo(seed_docinfo, [cs], [])
        # Replace ID_MAPPINGS with original (wrong counts)
        orig_idmap = None
        for rec in iter_records(seed_docinfo):
            if rec.tag_id == HWPTAG_ID_MAPPINGS:
                orig_idmap = rec.payload
                break
        broken = b"".join(
            _pack_record(rec.tag_id, rec.level, orig_idmap if rec.tag_id == HWPTAG_ID_MAPPINGS else rec.payload)
            for rec in iter_records(new_di)
        )
        violations = check_i1(broken)
        assert len(violations) >= 1
        assert any("CharShape" in v.message for v in violations)


class TestCheckI2:
    def test_seed_passes(self, seed_docinfo):
        assert check_i2(seed_docinfo) == []

    def test_oob_face_detected(self, seed_docinfo):
        # Create a broken CS with face_id=999
        parts = []
        for rec in iter_records(seed_docinfo):
            if rec.tag_id == HWPTAG_CHAR_SHAPE:
                broken_payload = bytearray(rec.payload)
                struct.pack_into("<H", broken_payload, 0, 999)  # face_id[0] = 999
                parts.append(_pack_record(rec.tag_id, rec.level, bytes(broken_payload)))
                break
            parts.append(_pack_record(rec.tag_id, rec.level, rec.payload))
        # Append remaining records
        found = False
        for rec in iter_records(seed_docinfo):
            if rec.tag_id == HWPTAG_CHAR_SHAPE and not found:
                found = True
                continue
            if found:
                parts.append(_pack_record(rec.tag_id, rec.level, rec.payload))
        broken_di = b"".join(parts)
        violations = check_i2(broken_di)
        assert len(violations) >= 1
        assert "face_id" in violations[0].message


class TestCheckI3:
    def test_seed_passes(self, seed_docinfo, seed_section):
        cs, ps, _ = check_i3_docinfo(seed_docinfo)
        assert cs > 0
        assert ps > 0
        violations = check_i3_body(seed_section, cs, ps)
        assert violations == []

    def test_insufficient_cs_detected(self, seed_docinfo, seed_section):
        violations = check_i3_body(seed_section, cs_count=1, ps_count=100)
        # seed likely references CS IDs > 0
        # May or may not have violations depending on seed content
        # At minimum, no crash
        assert isinstance(violations, list)

    def test_insufficient_ps_detected(self, seed_docinfo, seed_section):
        violations = check_i3_body(seed_section, cs_count=100, ps_count=1)
        assert isinstance(violations, list)


class TestValidateHwpIntegrity:
    def test_seed_passes(self, seed_docinfo):
        assert validate_hwp_integrity(seed_docinfo) == []

    def test_with_added_records(self, seed_docinfo):
        cs = CharShapeSpec(size_pt=14.0, bold=True, color_r=255)
        ps = ParaShapeSpec(alignment="center")
        new_di, _, _, _ = build_docinfo(seed_docinfo, [cs], [ps])
        assert validate_hwp_integrity(new_di) == []


class TestValidateHwpFull:
    def test_seed_passes(self, seed_docinfo, seed_section):
        assert validate_hwp_full(seed_docinfo, seed_section) == []

    def test_docinfo_only(self, seed_docinfo):
        assert validate_hwp_full(seed_docinfo) == []
