"""HWP R-rule validation tests.

Tests that R1-R4 structural integrity rules correctly pass on known-good
fixtures, and correctly detect violations when binary data is corrupted.

HWP R-규칙 검증 테스트. 정상 fixture에서 통과 확인 + 인위적 corruption 시 탐지 확인.
"""

from __future__ import annotations

import pathlib

import pytest

from udf.parsers.hwp.parse import parse_hwp
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
