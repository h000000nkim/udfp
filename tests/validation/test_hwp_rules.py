"""HWP R-rule validation tests.

Tests that R1-R4 structural integrity rules correctly pass on known-good
fixtures, and correctly detect violations when binary data is corrupted.

HWP R-규칙 검증 테스트. 정상 fixture에서 통과 확인 + 인위적 corruption 시 탐지 확인.
"""

from __future__ import annotations

import pathlib

import pytest

from udf.parsers.hwp.parse import parse_hwp
from udf.validation.hwp.integrity import (
    check_i7_section_count,
    check_i8_border_fill_ref,
    check_i9_table_nrows,
    check_i10_bindata_streams,
    check_i11_docinfo_order,
    check_i12_pls_tpos_bounds,
    check_r5,
    check_r6,
    check_r7,
    validate_hwp_file,
)
from udf.validation.hwp.rules import (
    ValidationReport,
    check_r1,
    check_r2,
    check_r3,
    check_r4,
    validate_hwp,
)

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwp"


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


# ---------------------------------------------------------------------------
# R1: charCnt == len(PT) // 2
# ---------------------------------------------------------------------------


class TestR1CharCnt:
    """Verify R1 passes on well-formed fixtures.

    R1 checks that PARA_HEADER.charCnt equals len(PARA_TEXT) // 2.
    정상 파일에서 charCnt가 PARA_TEXT 길이와 일치하는지 확인.
    """

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f02_char_format.hwp",
            "f03_para_align.hwp",
            "f06_multiline.hwp",
            "f07_hangul_latin.hwp",
            "f08_empty_paras.hwp",
        ],
    )
    def test_charcnt_matches_pt_length(self, filename: str) -> None:
        """Assert PARA_HEADER.charCnt == len(PARA_TEXT) // 2 for every paragraph.

        Parameters
        ----------
        filename : str
            HWP fixture file to validate.
        """
        doc = parse_hwp(_fixture(filename))
        violations = check_r1(doc)
        assert not violations, "R1 위반:\n" + "\n".join(v.message for v in violations)


# ---------------------------------------------------------------------------
# R2: csCount == len(PCS)//8 && lsCount == len(PLS)//36
# ---------------------------------------------------------------------------


class TestR2Counts:
    """Verify R2 passes: charshape count and lineseg count match their payloads.

    R2는 PH.csCount == len(PCS)//8, PH.lsCount == len(PLS)//36 확인.
    """

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f02_char_format.hwp",
            "f06_multiline.hwp",
        ],
    )
    def test_cs_count_matches(self, filename: str) -> None:
        """Assert csCount field equals actual PCS entry count.

        Parameters
        ----------
        filename : str
            HWP fixture file to validate.
        """
        doc = parse_hwp(_fixture(filename))
        violations = [v for v in check_r2(doc) if "csCount" in v.message]
        assert not violations, "R2 CS 위반:\n" + "\n".join(
            v.message for v in violations
        )

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f06_multiline.hwp",
        ],
    )
    def test_ls_count_matches(self, filename: str) -> None:
        """Assert lsCount field equals actual PLS entry count.

        Parameters
        ----------
        filename : str
            HWP fixture file to validate.
        """
        doc = parse_hwp(_fixture(filename))
        violations = [v for v in check_r2(doc) if "lsCount" in v.message]
        assert not violations, "R2 LS 위반:\n" + "\n".join(
            v.message for v in violations
        )


# ---------------------------------------------------------------------------
# R3: PLS 비어있지 않음 (텍스트 있는 단락)
# ---------------------------------------------------------------------------


class TestR3LineSeg:
    """Verify R3 passes: paragraphs with text have at least one PLS entry.

    R3는 텍스트 있는 단락에 PLS(줄 세그먼트) 엔트리가 1개 이상인지 확인.
    """

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f06_multiline.hwp",
            "f07_hangul_latin.hwp",
        ],
    )
    def test_pls_non_empty_for_text_paras(self, filename: str) -> None:
        """Assert every text-bearing paragraph has a non-empty PLS record.

        Parameters
        ----------
        filename : str
            HWP fixture file to validate.
        """
        doc = parse_hwp(_fixture(filename))
        violations = check_r3(doc)
        assert not violations, "R3 위반:\n" + "\n".join(v.message for v in violations)


# ---------------------------------------------------------------------------
# R4: PCS pos < len(PT) // 2
# ---------------------------------------------------------------------------


class TestR4OobCharShape:
    """Verify R4 passes: no charshape position exceeds paragraph text length.

    R4는 PCS의 모든 pos 값이 PT 길이 미만인지 확인.
    """

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f02_char_format.hwp",
            "f06_multiline.hwp",
        ],
    )
    def test_no_oob_charshape(self, filename: str) -> None:
        """Assert all PCS position values are within PARA_TEXT bounds.

        Parameters
        ----------
        filename : str
            HWP fixture file to validate.
        """
        doc = parse_hwp(_fixture(filename))
        violations = check_r4(doc)
        assert not violations, "R4 위반:\n" + "\n".join(v.message for v in violations)


# ---------------------------------------------------------------------------
# 통합 ValidationReport
# ---------------------------------------------------------------------------


class TestValidateHwp:
    """Verify full validate_hwp() passes on all standard fixtures.

    전체 R1-R4를 통합 실행하여 ValidationReport.is_passing() 확인.
    """

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f02_char_format.hwp",
            "f03_para_align.hwp",
            "f04_simple_table.hwp",
            "f05_table_cell_text.hwp",
            "f06_multiline.hwp",
            "f07_hangul_latin.hwp",
            "f08_empty_paras.hwp",
        ],
    )
    def test_all_rules_pass(self, filename: str) -> None:
        """Assert ValidationReport.is_passing() on a well-formed HWP.

        Parameters
        ----------
        filename : str
            HWP fixture file to validate.
        """
        doc = parse_hwp(_fixture(filename))
        report: ValidationReport = validate_hwp(doc)
        assert report.is_passing(), f"검증 실패 ({filename}): " + ", ".join(
            f"{v.rule_id}:{v.message}" for v in report.all_violations
        )


# ---------------------------------------------------------------------------
# Negative tests — verify rules actually detect violations
# 규칙이 실제로 위반을 감지하는지 검증 (falsifiability)
# ---------------------------------------------------------------------------


class TestR1DetectsCorruption:
    """Verify R1 detects charCnt/PT length mismatch when data is corrupted.

    PARA_HEADER의 charCnt를 인위적으로 변조하여 R1이 탐지하는지 확인.
    이 테스트가 없으면 check_r1이 항상 빈 리스트를 반환해도 모를 수 있음.
    """

    def test_inflated_charcnt_detected(self) -> None:
        """Inject charCnt=99999 into first paragraph, assert R1 violation raised.

        Verifies R1 doesn't silently pass when charCnt exceeds actual PT length.
        charCnt를 99999로 부풀려서 R1이 위반을 보고하는지 확인.
        """
        import base64
        import copy
        import struct

        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        doc = copy.deepcopy(doc)
        for vb in doc.verbatim.blocks.values():
            if vb.raw_tag_id == 66 and vb.decoded and vb.decoded.get("pt_bytes"):
                ph = bytearray(base64.b64decode(vb.raw_bytes))
                if len(ph) >= 4:
                    old = struct.unpack_from("<I", ph, 0)[0]
                    msb = old & 0x80000000
                    struct.pack_into("<I", ph, 0, msb | 99999)
                    vb.raw_bytes = base64.b64encode(bytes(ph)).decode()
                    break
        violations = check_r1(doc)
        assert len(violations) > 0
        assert violations[0].rule_id == "R1"

    def test_zero_charcnt_detected(self) -> None:
        """Inject charCnt=0 into a paragraph with text, assert R1 violation.

        Verifies R1 catches charCnt being too small (not just too large).
        charCnt를 0으로 만들어 R1이 탐지하는지 확인.
        """
        import base64
        import copy
        import struct

        doc = parse_hwp(_fixture("f06_multiline.hwp"))
        doc = copy.deepcopy(doc)
        for vb in doc.verbatim.blocks.values():
            if vb.raw_tag_id == 66 and vb.decoded and vb.decoded.get("pt_bytes"):
                ph = bytearray(base64.b64decode(vb.raw_bytes))
                if len(ph) >= 4:
                    msb = struct.unpack_from("<I", ph, 0)[0] & 0x80000000
                    struct.pack_into("<I", ph, 0, msb | 0)
                    vb.raw_bytes = base64.b64encode(bytes(ph)).decode()
                    break
        violations = check_r1(doc)
        assert len(violations) > 0


class TestR4DetectsOobCharShape:
    """Verify R4 detects out-of-bounds PCS positions when injected.

    PCS 엔트리의 pos 필드를 0xFFFF로 변조하여 R4가 탐지하는지 확인.
    """

    def test_oob_pos_detected(self) -> None:
        """Inject pos=0xFFFF into last PCS entry, assert R4 violation raised.

        Verifies the rule catches charshape offsets beyond text length.
        마지막 PCS 엔트리의 pos를 0xFFFF로 설정하여 R4 위반 탐지 확인.
        """
        import base64
        import copy
        import struct

        doc = parse_hwp(_fixture("f02_char_format.hwp"))
        doc = copy.deepcopy(doc)
        for vb in doc.verbatim.blocks.values():
            if vb.raw_tag_id == 66 and vb.decoded:
                pcs_b64 = vb.decoded.get("pcs_bytes")
                if pcs_b64:
                    pcs = bytearray(base64.b64decode(pcs_b64))
                    if len(pcs) >= 8:
                        struct.pack_into("<I", pcs, len(pcs) - 8, 0xFFFF)
                        vb.decoded["pcs_bytes"] = base64.b64encode(bytes(pcs)).decode()
                        break
        violations = check_r4(doc)
        assert len(violations) > 0
        assert violations[0].rule_id == "R4"


class TestR2DetectsCorruption:
    """Verify R2 detects csCount/PCS length mismatch when data is corrupted.

    PH offset 12의 csCount를 변조하여 R2가 탐지하는지 확인.
    """

    def test_wrong_cscount_detected(self) -> None:
        import base64
        import copy
        import struct

        doc = parse_hwp(_fixture("f02_char_format.hwp"))
        doc = copy.deepcopy(doc)
        for vb in doc.verbatim.blocks.values():
            if vb.raw_tag_id == 66 and vb.decoded and vb.decoded.get("pcs_bytes"):
                ph = bytearray(base64.b64decode(vb.raw_bytes))
                if len(ph) >= 14:
                    struct.pack_into("<H", ph, 12, 9999)
                    vb.raw_bytes = base64.b64encode(bytes(ph)).decode()
                    break
        violations = check_r2(doc)
        assert len(violations) > 0, "R2 should detect csCount mismatch"
        assert violations[0].rule_id == "R2"
        assert "csCount" in violations[0].message


class TestR3DetectsCorruption:
    """Verify R3 detects missing PLS for paragraphs with text.

    텍스트가 있는 단락에서 pls_bytes를 제거하여 R3가 탐지하는지 확인.
    """

    def test_missing_pls_detected(self) -> None:
        import copy

        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        doc = copy.deepcopy(doc)
        for vb in doc.verbatim.blocks.values():
            if vb.raw_tag_id == 66 and vb.decoded and vb.decoded.get("pls_bytes"):
                vb.decoded["pls_bytes"] = None
                break
        violations = check_r3(doc)
        assert len(violations) > 0, "R3 should detect missing PLS"
        assert violations[0].rule_id == "R3"


# ---------------------------------------------------------------------------
# R5: FileHeader 검증
# ---------------------------------------------------------------------------

ALL_HWP_FIXTURES = sorted(p.name for p in FIXTURES.glob("*.hwp"))


class TestR5FileHeader:
    @pytest.mark.parametrize("filename", ALL_HWP_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_r5(_fixture(filename))
        assert violations == [], f"R5 violations: {[v.message for v in violations]}"

    def test_detects_non_ole_file(self, tmp_path: pathlib.Path) -> None:
        bad = tmp_path / "not_ole.hwp"
        bad.write_bytes(b"not an OLE file at all")
        violations = check_r5(str(bad))
        assert any("OLE2" in v.message for v in violations)


# ---------------------------------------------------------------------------
# R6: 필수 스트림 존재
# ---------------------------------------------------------------------------


class TestR6RequiredStreams:
    @pytest.mark.parametrize("filename", ALL_HWP_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_r6(_fixture(filename))
        assert violations == [], f"R6 violations: {[v.message for v in violations]}"


# ---------------------------------------------------------------------------
# R7: 압축 모드 일관성
# ---------------------------------------------------------------------------


class TestR7Compression:
    @pytest.mark.parametrize("filename", ALL_HWP_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_r7(_fixture(filename))
        assert violations == [], f"R7 violations: {[v.message for v in violations]}"


# ---------------------------------------------------------------------------
# validate_hwp_file 통합
# ---------------------------------------------------------------------------


class TestValidateHwpFile:
    @pytest.mark.parametrize("filename", ALL_HWP_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = validate_hwp_file(_fixture(filename))
        assert violations == [], f"File-level violations: {[v.message for v in violations]}"


# ---------------------------------------------------------------------------
# Helpers for I-rule tests
# ---------------------------------------------------------------------------


def _read_streams(path: str) -> tuple[bytes, bytes]:
    """Read decompressed DocInfo and Section0 bytes from an HWP file."""
    import struct
    import zlib
    import olefile

    ole = olefile.OleFileIO(path)
    try:
        flags = ole.openstream("FileHeader").read()
        compressed = bool(struct.unpack_from("<I", flags, 36)[0] & 1)
        raw_di = ole.openstream("DocInfo").read()
        raw_s0 = ole.openstream("BodyText/Section0").read()
        if compressed:
            return zlib.decompress(raw_di, -15), zlib.decompress(raw_s0, -15)
        return raw_di, raw_s0
    finally:
        ole.close()


# ---------------------------------------------------------------------------
# I7: sectionCount == Section 스트림 수
# ---------------------------------------------------------------------------


class TestI7SectionCount:
    @pytest.mark.parametrize("filename", ALL_HWP_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_i7_section_count(_fixture(filename))
        assert violations == [], f"I7 violations: {[v.message for v in violations]}"


# ---------------------------------------------------------------------------
# I8: BorderFill 1-based 참조 범위
# ---------------------------------------------------------------------------


TABLE_FIXTURES = [f for f in ALL_HWP_FIXTURES if "table" in f.lower() or f.startswith("f04") or f.startswith("f05") or f.startswith("f19") or f.startswith("f20") or f.startswith("f21")]


class TestI8BorderFillRef:
    @pytest.mark.parametrize("filename", ALL_HWP_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        docinfo, section = _read_streams(_fixture(filename))
        violations = check_i8_border_fill_ref(docinfo, section)
        assert violations == [], f"I8 violations: {[v.message for v in violations]}"

    def test_detects_oob_bf(self) -> None:
        """Mutate borderFillCount to 1 so that refs > 1 become OOB."""
        if not TABLE_FIXTURES:
            pytest.skip("No table fixtures")
        docinfo, section = _read_streams(_fixture(TABLE_FIXTURES[0]))
        import struct
        from udf.parsers.hwp.records import HWPTAG_ID_MAPPINGS, iter_records

        mutated = bytearray(docinfo)
        mutated_id_mappings = False
        for rec in iter_records(docinfo):
            if rec.tag_id == HWPTAG_ID_MAPPINGS:
                struct.pack_into("<I", mutated, rec.offset + 4 + 32, 1)
                mutated_id_mappings = True
                break
        assert mutated_id_mappings, "ID_MAPPINGS 레코드를 찾지 못함"
        violations = check_i8_border_fill_ref(bytes(mutated), section)
        assert len(violations) > 0, (
            "borderFillCount=1로 변조했지만 OOB 참조가 검출되지 않음"
        )


# ---------------------------------------------------------------------------
# I9: TABLE nRows × nCols == LIST_HEADER count
# ---------------------------------------------------------------------------


class TestI9TableNrows:
    @pytest.mark.parametrize("filename", ALL_HWP_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        _, section = _read_streams(_fixture(filename))
        violations = check_i9_table_nrows(section)
        assert violations == [], f"I9 violations: {[v.message for v in violations]}"


# ---------------------------------------------------------------------------
# I10: BinData streams match BIN_DATA records
# ---------------------------------------------------------------------------


class TestI10BinDataStreams:
    @pytest.mark.parametrize("filename", ALL_HWP_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_i10_bindata_streams(_fixture(filename))
        assert violations == [], f"I10 violations: {[v.message for v in violations]}"


# ---------------------------------------------------------------------------
# I11: DocInfo record order
# ---------------------------------------------------------------------------


class TestI11DocInfoOrder:
    @pytest.mark.parametrize("filename", ALL_HWP_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        docinfo, _ = _read_streams(_fixture(filename))
        violations = check_i11_docinfo_order(docinfo)
        assert violations == [], f"I11 violations: {[v.message for v in violations]}"


# ---------------------------------------------------------------------------
# I12: PLS tpos < charCnt
# ---------------------------------------------------------------------------


class TestI12PlsTposBounds:
    @pytest.mark.parametrize("filename", ALL_HWP_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        _, section = _read_streams(_fixture(filename))
        violations = check_i12_pls_tpos_bounds(section)
        assert violations == [], f"I12 violations: {[v.message for v in violations]}"

    def test_detects_tpos_overflow(self) -> None:
        """Mutate a PLS entry to have tpos > charCnt and verify detection."""
        import struct
        from udf.parsers.hwp.records import (
            HWPTAG_PARA_HEADER, HWPTAG_PARA_LINE_SEG, iter_records,
        )

        _, section = _read_streams(_fixture("f01_plain_text.hwp"))
        mutated = bytearray(section)

        recs = list(iter_records(section))
        for i, rec in enumerate(recs):
            if rec.tag_id != HWPTAG_PARA_HEADER:
                continue
            char_cnt = struct.unpack_from("<I", rec.payload, 0)[0] & 0x7FFFFFFF
            if char_cnt == 0:
                continue
            for j in range(i + 1, len(recs)):
                if recs[j].tag_id == HWPTAG_PARA_LINE_SEG:
                    pls_offset = recs[j].offset + 4  # skip record header
                    struct.pack_into("<I", mutated, pls_offset, 9999)
                    break
            break

        violations = check_i12_pls_tpos_bounds(bytes(mutated))
        assert len(violations) > 0, "Should detect tpos overflow"
        assert violations[0].rule_id == "I12"
