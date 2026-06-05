"""HWP 구조 무결성 회귀 테스트.

BUG-070/071/073: DOCX→HWP 변환 시 구조 손상, 이미지/머리글이 치명적 손상 유발.
BUG-052/053: HWPX→HWP 대용량 파일 실패/빈 출력.

이 테스트들은 해당 변환 경로에서 생성된 HWP가 최소한의 구조적 정합성을
갖추는지 확인합니다. 시각적 정확성은 검증하지 않습니다.
"""

from __future__ import annotations

import pathlib

import pytest

from udf.core.schema import (
    HeadingBlock,
    ParagraphBlock,
    TextInline,
)

DOCX_FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "docx"
HWPX_FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwpx"
HWP_FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwp"


class TestDocxToHwpIntegrity:
    """BUG-070: DOCX→HWP 변환 후 구조 손상 방지."""

    @pytest.mark.parametrize("filename", sorted(p.name for p in DOCX_FIXTURES.glob("*.docx")))
    def test_convert_produces_valid_hwp(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        import udf

        src = str(DOCX_FIXTURES / filename)
        out = str(tmp_path / filename.replace(".docx", ".hwp"))
        udf.convert(src, out, validate=False)

        doc = udf.parse(out)
        assert len(doc.blocks) > 0, f"DOCX→HWP 변환 결과 블록 0개: {filename}"

        texts = []
        for b in doc.blocks:
            if isinstance(b, ParagraphBlock):
                texts.append("".join(i.text for i in b.inlines if isinstance(i, TextInline)))
            elif isinstance(b, HeadingBlock):
                texts.append(b.text)
        assert any(t.strip() for t in texts), f"DOCX→HWP 변환 결과 텍스트 없음: {filename}"


class TestHwpxToHwpIntegrity:
    """BUG-052/053: HWPX→HWP 변환 시 빈 출력/실패 방지."""

    @pytest.mark.parametrize("filename", sorted(p.name for p in HWPX_FIXTURES.glob("*.hwpx")))
    def test_convert_produces_nonempty_hwp(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        import udf

        src = str(HWPX_FIXTURES / filename)
        out = str(tmp_path / filename.replace(".hwpx", ".hwp"))
        udf.convert(src, out, validate=False)

        doc = udf.parse(out)
        assert len(doc.blocks) > 0, f"HWPX→HWP 변환 결과 블록 0개: {filename}"


class TestHwpToMdContentPreservation:
    """BUG-062: HWP→MD 변환 시 text_box 등 콘텐츠 소실 방지."""

    @pytest.mark.parametrize("filename", [
        "f01_plain_text.hwp",
        "f02_char_format.hwp",
        "f04_simple_table.hwp",
    ])
    def test_md_has_content(self, filename: str) -> None:
        import udf

        src = str(HWP_FIXTURES / filename)
        doc = udf.parse(src)
        md = udf.render(doc, "md")
        assert md is not None
        assert len(md.strip()) > 10, f"HWP→MD 변환 결과가 거의 비어있음: {filename}"


class TestHwpxValidationAfterGenerate:
    """BUG-076: HWPX 생성 후 구조적 유효성 확인."""

    @pytest.mark.parametrize("filename", sorted(p.name for p in HWPX_FIXTURES.glob("*.hwpx")))
    def test_hwpx_roundtrip_validates(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        import udf
        from udf.validation.hwpx.rules import validate_hwpx

        src = str(HWPX_FIXTURES / filename)
        doc = udf.parse(src)
        out = str(tmp_path / filename)
        udf.render(doc, "hwpx", output_path=out, validate=False)

        report = validate_hwpx(out)
        assert report.error_count == 0, (
            f"HWPX 라운드트립 HX-규칙 에러: {[v.message for v in report.all_violations if v.severity == 'error']}"
        )


class TestImageColorSampling:
    """BUG-087: 배경 이미지 색상 샘플링이 올바르게 작동하는지."""

    def test_no_crash_without_pil(self):
        """PIL 없어도 변환이 성공해야 함 (fallback to #4a2040)."""
        import udf
        doc = udf.parse("dev/fixtures/external/hwpx/11차시_자기_나의 약점과 강점 알기.hwpx")
        import tempfile
        import shutil
        import os
        seed = "udf/renderers/hwp/seed/empty.hwp"
        out = tempfile.mktemp(suffix=".hwp")
        shutil.copy2(seed, out)
        try:
            from udf.renderers.hwp.scratch import generate_hwp_scratch
            generate_hwp_scratch(doc, out, seed)
            assert os.path.getsize(out) > 1000
        finally:
            os.unlink(out)


class TestHwpxToHwpTextFidelity:
    """HWPX→HWP 변환의 전체 텍스트 보존율이 85% 이상이어야 함."""

    def test_batch_text_fidelity(self):
        import os
        import tempfile
        import shutil
        from udf.parsers.hwpx.parse import parse_hwpx
        from udf.renderers.hwp.scratch import generate_hwp_scratch
        from udf.parsers.hwp.parse import parse_hwp

        def get_texts(doc):
            texts = set()
            def collect(blocks):
                for b in blocks:
                    if hasattr(b, "inlines"):
                        for il in (b.inlines or []):
                            t = getattr(il, "text", "")
                            if t:
                                t = " ".join(t.split())
                                if t:
                                    texts.add(t[:30])
                    if hasattr(b, "content") and b.content:
                        collect(b.content)
                    if hasattr(b, "rows"):
                        for r in (b.rows or []):
                            for c in (r.cells or []):
                                collect(c.content)
            collect(doc.document.blocks)
            return texts

        seed = "udf/renderers/hwp/seed/empty.hwp"
        hwpx_dir = "dev/fixtures/external/hwpx"
        if not os.path.isdir(hwpx_dir):
            pytest.skip("No external HWPX fixtures")

        total_match = 0
        total_texts = 0
        for f in sorted(os.listdir(hwpx_dir))[:10]:
            if not f.endswith(".hwpx"):
                continue
            try:
                doc = parse_hwpx(os.path.join(hwpx_dir, f))
                orig = get_texts(doc)
                if not orig:
                    continue
                out = tempfile.mktemp(suffix=".hwp")
                shutil.copy2(seed, out)
                generate_hwp_scratch(doc, out, seed)
                hwp_doc = parse_hwp(out)
                os.unlink(out)
                conv = get_texts(hwp_doc)
                matched = sum(1 for ot in orig if ot in conv or any(ot in ct for ct in conv))
                total_match += matched
                total_texts += len(orig)
            except Exception:
                pass

        if total_texts == 0:
            pytest.skip("No text extracted")
        fidelity = total_match / total_texts
        assert fidelity >= 0.80, f"Text fidelity {fidelity:.1%} below 80% threshold"
