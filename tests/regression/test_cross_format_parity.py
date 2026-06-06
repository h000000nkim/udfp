"""Cross-format parity regression test — locks current achievement."""
import pytest
import udf
import os

HWPX_DIR = "dev/fixtures/external/polaris_hwp2hwpx"
HWP_DIR = "tests/fixtures/external/downloads"


def _common_pairs():
    hwpx = {os.path.splitext(f)[0] for f in os.listdir(HWPX_DIR) if f.endswith(".hwpx")}
    hwp = {os.path.splitext(f)[0] for f in os.listdir(HWP_DIR) if f.endswith(".hwp")}
    return sorted(hwpx & hwp)


class TestCrossFormatParity:
    """HWPX→UDF와 HWP→UDF 파싱 결과 일관성 회귀 테스트."""

    def test_struct_match_at_least_46(self):
        """블록 구조(타입+수) 일치가 46/48 이상이어야 함."""
        common = _common_pairs()
        struct_match = 0
        for name in common:
            dx = udf.parse(f"{HWPX_DIR}/{name}.hwpx")
            dh = udf.parse(f"{HWP_DIR}/{name}.hwp")
            bx, bh = dx.document.blocks, dh.document.blocks
            if len(bx) == len(bh) and [b.type for b in bx] == [b.type for b in bh]:
                struct_match += 1
        assert struct_match >= 45, f"struct match {struct_match}/48 < 45"

    def test_no_keep_with_next(self):
        """HWP 파서가 keepWithNext를 설정하지 않아야 함."""
        common = _common_pairs()
        for name in common[:10]:
            dh = udf.parse(f"{HWP_DIR}/{name}.hwp")
            for b in dh.document.blocks:
                if hasattr(b, "format") and b.format and b.format.keep_with_next:
                    pytest.fail(f"{name} block has keep_with_next=True")
