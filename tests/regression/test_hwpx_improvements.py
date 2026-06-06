"""HWPX parser improvements regression tests."""
import pytest
import udf
import os
from collections import Counter

HWPX_DIR = "dev/fixtures/external/polaris_hwp2hwpx"
HWP_DIR = "tests/fixtures/external/downloads"


def _common_pairs():
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
        assert len(dx.document.blocks) == len(dh.document.blocks)
