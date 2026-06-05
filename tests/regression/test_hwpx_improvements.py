"""HWPX parser improvements regression tests."""
import pytest
import udf
import os

HWPX_DIR = "dev/fixtures/external/polaris_hwp2hwpx"
HWP_DIR = "tests/fixtures/external/downloads"

pytestmark = pytest.mark.skipif(
    not os.path.isdir(HWPX_DIR), reason="dev/fixtures not available (public repo)"
)


def _common_pairs():
    if not os.path.isdir(HWPX_DIR) or not os.path.isdir(HWP_DIR):
        return []
    hwpx = {os.path.splitext(f)[0] for f in os.listdir(HWPX_DIR) if f.endswith(".hwpx")}
    hwp = {os.path.splitext(f)[0] for f in os.listdir(HWP_DIR) if f.endswith(".hwp")}
    return sorted(hwpx & hwp)


def _skip_if_missing(path):
    if not os.path.exists(path):
        pytest.skip(f"fixture not found: {path}")


class TestHwpxEquationPromotion:
    """<hp:equation> GSO가 standalone일 때 EquationBlock으로 승격."""

    def test_standalone_equation_promoted(self):
        p = f"{HWPX_DIR}/감염병확산지수미분_하윤중.hwpx"
        _skip_if_missing(p)
        dx = udf.parse(p)
        eq_blocks = [b for b in dx.document.blocks if b.type == "equation"]
        assert len(eq_blocks) >= 9


class TestHwpxImagePromotion:
    """standalone 이미지 단락이 ImageBlock으로 승격."""

    def test_standalone_image_promoted(self):
        p = f"{HWPX_DIR}/과학과제연구 보고서.hwpx"
        _skip_if_missing(p)
        dx = udf.parse(p)
        img_blocks = [b for b in dx.document.blocks if b.type == "image"]
        assert len(img_blocks) >= 5


class TestHwpxSuperscript:
    """HWPX charPr의 <supscript> 추출."""

    def test_superscript_creates_separate_inline(self):
        p = f"{HWPX_DIR}/BRHS-오승훈,장예준,우송윤.hwpx"
        _skip_if_missing(p)
        dx = udf.parse(p)
        b2 = dx.document.blocks[2]
        sup_inlines = [il for il in b2.inlines if hasattr(il, "superscript") and il.superscript]
        assert len(sup_inlines) >= 1


class TestHwpxTableTextSplit:
    """테이블+텍스트 혼합 단락에서 텍스트 분리."""

    @pytest.mark.parametrize("name", [
        "[양식①] 진로 탐구 보고서 세특 양식",
        "[양식②] 진로주제탐구활동 보고서 양식",
    ])
    def test_table_text_split(self, name):
        px = f"{HWPX_DIR}/{name}.hwpx"
        ph = f"{HWP_DIR}/{name}.hwp"
        _skip_if_missing(px)
        _skip_if_missing(ph)
        dx = udf.parse(px)
        dh = udf.parse(ph)
        bx_count = len(dx.document.blocks)
        bh_count = len(dh.document.blocks)
        # HWP 바이너리에 명시적 header/footer 레코드가 있어 HWP 파서가
        # 더 많은 블록을 추출할 수 있음. HWPX는 별도 파일(header.xml 등)이라
        # 현재 미추출 → BUG-236에서 HWPX 파서에 추가 예정.
        assert bx_count <= bh_count, (
            f"HWPX blocks ({bx_count}) > HWP blocks ({bh_count})"
        )
