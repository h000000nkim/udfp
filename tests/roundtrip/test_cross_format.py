"""E2E 크로스포맷 변환 검증.

HWP ↔ DOCX ↔ HWPX 간 변환 파이프라인에서 텍스트와 블록 구조가 보존되는지 검증.
크로스포맷은 From Scratch 모드로 동작하므로 verbatim/포맷 고유 속성 손실은 허용.
시맨틱 텍스트 보존이 핵심 검증 대상.
"""

from __future__ import annotations

import pathlib

import pytest

from udf.core.schema import (
    HeadingBlock,
    ParagraphBlock,
    TableBlock,
    TextInline,
    UdfDocument,
)

HWP_FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwp"
HWPX_FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwpx"

HWP_SIMPLE = [
    "f01_plain_text.hwp",
    "f03_para_align.hwp",
    "f06_multiline.hwp",
    "f07_hangul_latin.hwp",
    "f09_heading_h1h2.hwp",
    "f13_pure_hangul.hwp",
]

HWP_TABLE = [
    "f04_simple_table.hwp",
    "f05_table_cell_text.hwp",
]

HWPX_ALL = [
    "table_text.hwpx",
    "report_form.hwpx",
    "reading_log.hwpx",
]

HWPX_SIMPLE = [
    "table_text.hwpx",
    "report_form.hwpx",
]


def _all_texts(doc: UdfDocument) -> list[str]:
    texts: list[str] = []
    for block in doc.blocks:
        if isinstance(block, ParagraphBlock):
            t = "".join(i.text for i in block.inlines if isinstance(i, TextInline))
            if t.strip():
                texts.append(t.strip())
        elif isinstance(block, HeadingBlock):
            if block.text.strip():
                texts.append(block.text.strip())
        elif isinstance(block, TableBlock):
            for row in block.rows:
                for cell in row.cells:
                    for b in cell.content:
                        if isinstance(b, ParagraphBlock):
                            ct = "".join(
                                i.text for i in b.inlines if isinstance(i, TextInline)
                            )
                            if ct.strip():
                                texts.append(ct.strip())
    return texts


def _block_type_counts(doc: UdfDocument) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in doc.blocks:
        name = type(block).__name__
        counts[name] = counts.get(name, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# HWP → DOCX
# ---------------------------------------------------------------------------
class TestHwpToDocx:
    @pytest.mark.parametrize("filename", HWP_SIMPLE + HWP_TABLE)
    def test_text_preserved(self, filename: str, tmp_path: pathlib.Path) -> None:
        from udf.parsers.docx.parse import parse_docx
        from udf.parsers.hwp.parse import parse_hwp
        from udf.renderers.docx import generate_docx

        hwp_doc = parse_hwp(str(HWP_FIXTURES / filename))
        out = str(tmp_path / filename.replace(".hwp", ".docx"))
        generate_docx(hwp_doc, out)
        docx_doc = parse_docx(out)

        orig_texts = _all_texts(hwp_doc)
        conv_texts = _all_texts(docx_doc)
        assert orig_texts, f"원본 텍스트 없음: {filename}"
        assert orig_texts == conv_texts, (
            f"HWP→DOCX 텍스트 불일치 ({filename})"
        )

    @pytest.mark.parametrize("filename", HWP_SIMPLE)
    def test_has_paragraph_blocks(self, filename: str, tmp_path: pathlib.Path) -> None:
        from udf.parsers.docx.parse import parse_docx
        from udf.parsers.hwp.parse import parse_hwp
        from udf.renderers.docx import generate_docx

        hwp_doc = parse_hwp(str(HWP_FIXTURES / filename))
        out = str(tmp_path / filename.replace(".hwp", ".docx"))
        generate_docx(hwp_doc, out)
        docx_doc = parse_docx(out)

        orig_para = sum(
            1 for b in hwp_doc.blocks if isinstance(b, (ParagraphBlock, HeadingBlock))
        )
        conv_para = sum(
            1 for b in docx_doc.blocks if isinstance(b, (ParagraphBlock, HeadingBlock))
        )
        assert conv_para >= orig_para, (
            f"단락 수 감소: {orig_para} → {conv_para} ({filename})"
        )

    @pytest.mark.parametrize("filename", HWP_TABLE)
    def test_table_preserved(self, filename: str, tmp_path: pathlib.Path) -> None:
        from udf.parsers.docx.parse import parse_docx
        from udf.parsers.hwp.parse import parse_hwp
        from udf.renderers.docx import generate_docx

        hwp_doc = parse_hwp(str(HWP_FIXTURES / filename))
        out = str(tmp_path / filename.replace(".hwp", ".docx"))
        generate_docx(hwp_doc, out)
        docx_doc = parse_docx(out)

        orig_tables = [b for b in hwp_doc.blocks if isinstance(b, TableBlock)]
        conv_tables = [b for b in docx_doc.blocks if isinstance(b, TableBlock)]
        assert len(conv_tables) == len(orig_tables), (
            f"테이블 수 불일치: {len(orig_tables)} → {len(conv_tables)} ({filename})"
        )


# ---------------------------------------------------------------------------
# HWP → HWPX
# ---------------------------------------------------------------------------
class TestHwpToHwpx:
    @pytest.mark.parametrize("filename", HWP_SIMPLE + HWP_TABLE)
    def test_text_preserved(self, filename: str, tmp_path: pathlib.Path) -> None:
        from udf.parsers.hwp.parse import parse_hwp
        from udf.parsers.hwpx.parse import parse_hwpx
        from udf.renderers.hwpx import generate_hwpx

        hwp_doc = parse_hwp(str(HWP_FIXTURES / filename))
        out = str(tmp_path / filename.replace(".hwp", ".hwpx"))
        generate_hwpx(hwp_doc, out)
        hwpx_doc = parse_hwpx(out)

        orig_texts = _all_texts(hwp_doc)
        conv_texts = _all_texts(hwpx_doc)
        assert orig_texts, f"원본 텍스트 없음: {filename}"
        assert orig_texts == conv_texts, (
            f"HWP→HWPX 텍스트 불일치 ({filename})"
        )


# ---------------------------------------------------------------------------
# HWPX → DOCX
# ---------------------------------------------------------------------------
class TestHwpxToDocx:
    @pytest.mark.parametrize("filename", HWPX_SIMPLE)
    def test_text_preserved(self, filename: str, tmp_path: pathlib.Path) -> None:
        from udf.parsers.docx.parse import parse_docx
        from udf.parsers.hwpx.parse import parse_hwpx
        from udf.renderers.docx import generate_docx

        hwpx_doc = parse_hwpx(str(HWPX_FIXTURES / filename))
        out = str(tmp_path / filename.replace(".hwpx", ".docx"))
        generate_docx(hwpx_doc, out)
        docx_doc = parse_docx(out)

        orig_texts = _all_texts(hwpx_doc)
        conv_texts = _all_texts(docx_doc)
        assert orig_texts, f"원본 텍스트 없음: {filename}"
        assert orig_texts == conv_texts, (
            f"HWPX→DOCX 텍스트 불일치 ({filename})"
        )

    def test_text_set_preserved_complex(self, tmp_path: pathlib.Path) -> None:
        """복잡한 문서는 테이블 셀 순서가 달라질 수 있으므로 집합 비교."""
        from udf.parsers.docx.parse import parse_docx
        from udf.parsers.hwpx.parse import parse_hwpx
        from udf.renderers.docx import generate_docx

        hwpx_doc = parse_hwpx(str(HWPX_FIXTURES / "reading_log.hwpx"))
        out = str(tmp_path / "reading_log.docx")
        generate_docx(hwpx_doc, out)
        docx_doc = parse_docx(out)

        orig_set = set(_all_texts(hwpx_doc))
        conv_set = set(_all_texts(docx_doc))
        missing = orig_set - conv_set
        assert len(missing) / len(orig_set) < 0.05, (
            f"HWPX→DOCX 텍스트 5% 이상 소실: {len(missing)}/{len(orig_set)}"
        )

    @pytest.mark.parametrize("filename", HWPX_ALL)
    def test_from_scratch_mode_used(self, filename: str, tmp_path: pathlib.Path) -> None:
        """HWPX→DOCX는 verbatim.format 불일치로 From Scratch 동작해야 함."""
        from udf.parsers.docx.parse import parse_docx
        from udf.parsers.hwpx.parse import parse_hwpx
        from udf.renderers.docx import generate_docx

        hwpx_doc = parse_hwpx(str(HWPX_FIXTURES / filename))
        assert hwpx_doc.verbatim is not None
        assert hwpx_doc.verbatim.format == "hwpx"

        out = str(tmp_path / filename.replace(".hwpx", ".docx"))
        generate_docx(hwpx_doc, out)
        docx_doc = parse_docx(out)
        assert docx_doc.source_format == "docx"


# ---------------------------------------------------------------------------
# HWPX → HWP (From Scratch with seed)
# ---------------------------------------------------------------------------
class TestHwpxToHwp:
    @pytest.mark.parametrize("filename", HWPX_ALL)
    def test_generates_valid_hwp(self, filename: str, tmp_path: pathlib.Path) -> None:
        """HWPX→HWP 변환이 파싱 가능한 HWP를 생성하는지 확인."""
        from udf.parsers.hwp.parse import parse_hwp
        from udf.parsers.hwpx.parse import parse_hwpx
        from udf.renderers.hwp import generate_hwp

        hwpx_doc = parse_hwpx(str(HWPX_FIXTURES / filename))
        seed = str(HWP_FIXTURES / "f01_plain_text.hwp")
        out = str(tmp_path / filename.replace(".hwpx", ".hwp"))
        generate_hwp(hwpx_doc, out, seed_path=seed, validate=False)
        hwp_doc = parse_hwp(out)
        assert hwp_doc.blocks, f"블록 없음: {filename}"

    @pytest.mark.xfail(
        reason="HWP From Scratch는 테이블/복잡 구조를 크로스포맷 IR에서 완전히 재현하지 못함",
        strict=False,
    )
    @pytest.mark.parametrize("filename", HWPX_ALL)
    def test_text_preserved(self, filename: str, tmp_path: pathlib.Path) -> None:
        from udf.parsers.hwp.parse import parse_hwp
        from udf.parsers.hwpx.parse import parse_hwpx
        from udf.renderers.hwp import generate_hwp

        hwpx_doc = parse_hwpx(str(HWPX_FIXTURES / filename))
        seed = str(HWP_FIXTURES / "f01_plain_text.hwp")
        out = str(tmp_path / filename.replace(".hwpx", ".hwp"))
        generate_hwp(hwpx_doc, out, seed_path=seed, validate=False)
        hwp_doc = parse_hwp(out)

        orig_texts = _all_texts(hwpx_doc)
        conv_texts = _all_texts(hwp_doc)
        assert orig_texts, f"원본 텍스트 없음: {filename}"
        assert orig_texts == conv_texts, (
            f"HWPX→HWP 텍스트 불일치 ({filename})"
        )


# ---------------------------------------------------------------------------
# Multi-hop: HWP → DOCX → HWPX
# ---------------------------------------------------------------------------
class TestMultiHop:
    @pytest.mark.parametrize("filename", ["f01_plain_text.hwp", "f06_multiline.hwp"])
    def test_hwp_docx_hwpx_text(self, filename: str, tmp_path: pathlib.Path) -> None:
        """HWP → DOCX → HWPX 2단 변환 후 텍스트 보존."""
        from udf.parsers.docx.parse import parse_docx
        from udf.parsers.hwp.parse import parse_hwp
        from udf.parsers.hwpx.parse import parse_hwpx
        from udf.renderers.docx import generate_docx
        from udf.renderers.hwpx import generate_hwpx

        hwp_doc = parse_hwp(str(HWP_FIXTURES / filename))
        orig_texts = _all_texts(hwp_doc)

        docx_path = str(tmp_path / "step1.docx")
        generate_docx(hwp_doc, docx_path)
        docx_doc = parse_docx(docx_path)

        hwpx_path = str(tmp_path / "step2.hwpx")
        generate_hwpx(docx_doc, hwpx_path)
        hwpx_doc = parse_hwpx(hwpx_path)

        final_texts = _all_texts(hwpx_doc)
        assert orig_texts, f"원본 텍스트 없음: {filename}"
        assert orig_texts == final_texts, (
            f"HWP→DOCX→HWPX 멀티홉 텍스트 불일치 ({filename})"
        )

    @pytest.mark.parametrize("filename", ["f01_plain_text.hwp", "f09_heading_h1h2.hwp"])
    def test_hwp_hwpx_docx_text(self, filename: str, tmp_path: pathlib.Path) -> None:
        """HWP → HWPX → DOCX 2단 변환 후 텍스트 보존."""
        from udf.parsers.docx.parse import parse_docx
        from udf.parsers.hwp.parse import parse_hwp
        from udf.parsers.hwpx.parse import parse_hwpx
        from udf.renderers.docx import generate_docx
        from udf.renderers.hwpx import generate_hwpx

        hwp_doc = parse_hwp(str(HWP_FIXTURES / filename))
        orig_texts = _all_texts(hwp_doc)

        hwpx_path = str(tmp_path / "step1.hwpx")
        generate_hwpx(hwp_doc, hwpx_path)
        hwpx_doc = parse_hwpx(hwpx_path)

        docx_path = str(tmp_path / "step2.docx")
        generate_docx(hwpx_doc, docx_path)
        docx_doc = parse_docx(docx_path)

        final_texts = _all_texts(docx_doc)
        assert orig_texts, f"원본 텍스트 없음: {filename}"
        assert orig_texts == final_texts, (
            f"HWP→HWPX→DOCX 멀티홉 텍스트 불일치 ({filename})"
        )

    def test_full_triangle_hwp_docx_hwpx_hwp(self, tmp_path: pathlib.Path) -> None:
        """HWP → DOCX → HWPX → HWP 삼각 변환 후 텍스트 보존."""
        from udf.parsers.docx.parse import parse_docx
        from udf.parsers.hwp.parse import parse_hwp
        from udf.parsers.hwpx.parse import parse_hwpx
        from udf.renderers.docx import generate_docx
        from udf.renderers.hwp import generate_hwp
        from udf.renderers.hwpx import generate_hwpx

        hwp_doc = parse_hwp(str(HWP_FIXTURES / "f01_plain_text.hwp"))
        orig_texts = _all_texts(hwp_doc)

        docx_path = str(tmp_path / "step1.docx")
        generate_docx(hwp_doc, docx_path)
        docx_doc = parse_docx(docx_path)

        hwpx_path = str(tmp_path / "step2.hwpx")
        generate_hwpx(docx_doc, hwpx_path)
        hwpx_doc = parse_hwpx(hwpx_path)

        seed = str(HWP_FIXTURES / "f01_plain_text.hwp")
        hwp_path = str(tmp_path / "step3.hwp")
        generate_hwp(hwpx_doc, hwp_path, seed_path=seed, validate=False)
        final_doc = parse_hwp(hwp_path)

        final_texts = _all_texts(final_doc)
        assert orig_texts, "원본 텍스트 없음"
        assert orig_texts == final_texts, "삼각 변환 텍스트 불일치"


# ---------------------------------------------------------------------------
# 크로스포맷 Seed Patch 방어 (DOCX↔HWPX 혼동 방지)
# ---------------------------------------------------------------------------
class TestCrossFormatSeedPatchGuard:
    def test_hwpx_doc_generates_docx_from_scratch(self, tmp_path: pathlib.Path) -> None:
        """HWPX 파싱 결과(verbatim.format=hwpx)를 DOCX로 생성 시 From Scratch."""
        from udf.parsers.hwpx.parse import parse_hwpx
        from udf.renderers.docx import generate_docx

        doc = parse_hwpx(str(HWPX_FIXTURES / "table_text.hwpx"))
        assert doc.original_container is not None
        assert doc.original_container.format == "zip"
        assert doc.verbatim is not None
        assert doc.verbatim.format == "hwpx"

        out = str(tmp_path / "out.docx")
        generate_docx(doc, out)

        import zipfile
        with zipfile.ZipFile(out) as zf:
            assert "word/document.xml" in zf.namelist()
            assert "mimetype" not in zf.namelist()

    def test_docx_ir_generates_hwpx_from_scratch(self, tmp_path: pathlib.Path) -> None:
        """DOCX에서 생성된 IR을 HWPX로 생성 시 From Scratch."""
        from udf.parsers.hwp.parse import parse_hwp
        from udf.parsers.docx.parse import parse_docx
        from udf.renderers.docx import generate_docx
        from udf.renderers.hwpx import generate_hwpx

        hwp_doc = parse_hwp(str(HWP_FIXTURES / "f01_plain_text.hwp"))
        docx_path = str(tmp_path / "step1.docx")
        generate_docx(hwp_doc, docx_path)
        docx_doc = parse_docx(docx_path)

        assert docx_doc.verbatim is not None
        assert docx_doc.verbatim.format == "docx"
        assert docx_doc.original_container is not None
        assert docx_doc.original_container.format == "zip"

        hwpx_path = str(tmp_path / "out.hwpx")
        generate_hwpx(docx_doc, hwpx_path)

        import zipfile
        with zipfile.ZipFile(hwpx_path) as zf:
            names = zf.namelist()
            assert "mimetype" in names
            assert "Contents/section0.xml" in names
            assert "word/document.xml" not in names
