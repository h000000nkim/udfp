"""M4: DOCX → HWP 변환 E2E 테스트."""

from __future__ import annotations

import pathlib

import pytest

import udf
from udf.core.schema import ParagraphBlock

DOCX_FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "docx"

pytestmark = pytest.mark.skipif(
    not DOCX_FIXTURES.exists(), reason="DOCX fixtures not available"
)


class TestDocxToHwpConversion:
    def test_basic_document_converts(self, tmp_path: pathlib.Path):
        src = DOCX_FIXTURES / "basic_document.docx"
        if not src.exists():
            pytest.skip("basic_document.docx not found")
        out = str(tmp_path / "output.hwp")
        udf.convert(str(src), out)
        assert pathlib.Path(out).exists()
        assert pathlib.Path(out).stat().st_size > 0

    def test_roundtrip_preserves_text(self, tmp_path: pathlib.Path):
        src = DOCX_FIXTURES / "basic_document.docx"
        if not src.exists():
            pytest.skip("basic_document.docx not found")

        docx_doc = udf.parse(str(src))
        orig_texts = []
        for b in docx_doc.blocks:
            if isinstance(b, ParagraphBlock):
                t = "".join(
                    i.text for i in b.inlines if hasattr(i, "text")
                )
                if t.strip():
                    orig_texts.append(t.strip())
        if not orig_texts:
            pytest.skip("DOCX fixture has no text")

        out = str(tmp_path / "output.hwp")
        udf.convert(str(src), out)
        hwp_doc = udf.parse(out)
        hwp_texts = []
        for b in hwp_doc.blocks:
            if isinstance(b, ParagraphBlock):
                t = "".join(
                    i.text for i in b.inlines if hasattr(i, "text")
                )
                if t.strip():
                    hwp_texts.append(t.strip())

        matched = sum(1 for t in orig_texts if t in hwp_texts)
        ratio = matched / len(orig_texts) if orig_texts else 0
        assert ratio >= 0.5, (
            f"Text preservation {ratio:.0%} — expected ≥50%. "
            f"Missing: {[t for t in orig_texts if t not in hwp_texts][:5]}"
        )

    def test_output_is_valid_hwp(self, tmp_path: pathlib.Path):
        src = DOCX_FIXTURES / "basic_document.docx"
        if not src.exists():
            pytest.skip("basic_document.docx not found")
        out = str(tmp_path / "output.hwp")
        udf.convert(str(src), out)
        doc = udf.parse(out)
        assert len(doc.blocks) > 0
        assert doc.source_format == "hwp"
