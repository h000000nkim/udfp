"""HWP verbatim roundtrip tests — parse → generate → re-parse.

Verifies that the Seed Patch renderer produces valid HWP files that can be
re-parsed with identical block counts, text content, and table structure.

HWP verbatim 라운드트립 테스트. Seed Patch 렌더 결과가 재파싱 가능하고,
블록 수/텍스트/테이블 구조가 동일한지 검증.
"""

from __future__ import annotations

import pathlib

import pytest

from udf.renderers.hwp import generate_hwp
from udf.parsers.hwp.parse import parse_hwp
from udf.core.loss import diff_documents
from udf.core.schema import ParagraphBlock, TableBlock
from udf.validation.hwp.rules import validate_hwp

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwp"


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


def _all_text(doc) -> list[str]:
    texts = []
    for block in doc.blocks:
        if isinstance(block, ParagraphBlock):
            t = "".join(i.text for i in block.inlines if hasattr(i, "text"))
            texts.append(t)
    return texts


class TestVerbatimRoundtrip:
    """HWP parse → generate → re-parse roundtrip correctness.

    HWP 파싱 → 생성 → 재파싱 라운드트립 정확성 검증.
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
            "f09_heading_h1h2.hwp",
            "f10_inline_mixed.hwp",
            "f11_para_align_4.hwp",
            "f12_heading_h1h4.hwp",
            "f13_pure_hangul.hwp",
            "f14_multilang_format.hwp",
        ],
    )
    def test_generate_produces_reparseable_hwp(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        """Generate HWP from parsed doc, verify it re-parses with same block count.

        렌더 결과가 유효한 HWP이고, 재파싱 시 블록 수가 동일한지 확인.
        단순 "에러 없음"보다 강력: 블록 수 일치를 검증하여 데이터 소실 감지.

        Asserts
        -------
        - Output file exists and is non-empty.
        - Re-parsed block count equals original block count.
        """
        doc = parse_hwp(_fixture(filename))
        out = str(tmp_path / filename)
        generate_hwp(doc, out)
        assert pathlib.Path(out).exists()
        assert pathlib.Path(out).stat().st_size > 0
        doc_rt = parse_hwp(out)
        assert len(doc_rt.blocks) == len(doc.blocks), (
            f"블록 수 불일치: {len(doc.blocks)} → {len(doc_rt.blocks)}"
        )

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f06_multiline.hwp",
            "f07_hangul_latin.hwp",
            "f09_heading_h1h2.hwp",
            "f10_inline_mixed.hwp",
            "f11_para_align_4.hwp",
            "f12_heading_h1h4.hwp",
            "f13_pure_hangul.hwp",
            "f14_multilang_format.hwp",
        ],
    )
    def test_text_preserved(self, filename: str, tmp_path: pathlib.Path) -> None:
        """Assert exact text list equality between original and roundtripped doc.

        원본과 라운드트립 후 텍스트 리스트가 정확히 일치하는지 확인.
        공백만 있는 단락은 제외하고 비교.

        Asserts
        -------
        - Non-empty text list from original == non-empty text list from re-parse.
        """
        doc_orig = parse_hwp(_fixture(filename))
        out = str(tmp_path / filename)
        generate_hwp(doc_orig, out)

        doc_rt = parse_hwp(out)
        orig_texts = [t for t in _all_text(doc_orig) if t.strip()]
        rt_texts = [t for t in _all_text(doc_rt) if t.strip()]
        assert orig_texts == rt_texts, f"텍스트 불일치: {orig_texts!r} != {rt_texts!r}"

    def test_f04_table_preserved(self, tmp_path: pathlib.Path) -> None:
        """Assert table structure (2 rows x 3 cols) survives roundtrip.

        f04_simple_table.hwp의 테이블 구조(2행 3열)가 라운드트립 후 보존되는지 확인.

        Asserts
        -------
        - At least 1 TableBlock exists after re-parse.
        - First table has exactly 2 rows, each with 3 cells.
        """
        doc_orig = parse_hwp(_fixture("f04_simple_table.hwp"))
        out = str(tmp_path / "f04_rt.hwp")
        generate_hwp(doc_orig, out)

        doc_rt = parse_hwp(out)
        tables_rt = [b for b in doc_rt.blocks if isinstance(b, TableBlock)]
        assert len(tables_rt) >= 1
        tbl = tables_rt[0]
        assert len(tbl.rows) == 2
        assert all(len(r.cells) == 3 for r in tbl.rows)

    def test_f05_cell_text_preserved(self, tmp_path: pathlib.Path) -> None:
        """Assert specific cell texts ('이름', '홍길동') survive roundtrip.

        f05_table_cell_text.hwp의 셀 텍스트가 라운드트립 후 보존되는지 확인.

        Asserts
        -------
        - '이름' appears in at least one cell.
        - '홍길동' appears in at least one cell.
        """
        doc_orig = parse_hwp(_fixture("f05_table_cell_text.hwp"))
        out = str(tmp_path / "f05_rt.hwp")
        generate_hwp(doc_orig, out)

        doc_rt = parse_hwp(out)
        tables = [b for b in doc_rt.blocks if isinstance(b, TableBlock)]
        assert len(tables) >= 1
        all_cell_texts: list[str] = []
        for row in tables[0].rows:
            for cell in row.cells:
                for blk in cell.content:
                    if isinstance(blk, ParagraphBlock):
                        t = "".join(i.text for i in blk.inlines if hasattr(i, "text"))
                        all_cell_texts.append(t)
        assert any("이름" in t for t in all_cell_texts)
        assert any("홍길동" in t for t in all_cell_texts)


class TestVerbatimValidation:
    """Verbatim 라운드트립에 R-규칙 + 시맨틱 diff 검증 추가."""

    VALIDATE_FIXTURES = [
        "f01_plain_text.hwp",
        "f02_char_format.hwp",
        "f03_para_align.hwp",
    ]

    @pytest.mark.parametrize("filename", VALIDATE_FIXTURES)
    def test_r_rules_after_roundtrip(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        doc = parse_hwp(_fixture(filename))
        out = str(tmp_path / filename)
        generate_hwp(doc, out)
        doc_rt = parse_hwp(out)
        report = validate_hwp(doc_rt)
        assert report.is_passing(), (
            f"R-규칙 위반 ({filename}): "
            + ", ".join(f"{v.rule_id}:{v.message}" for v in report.all_violations)
        )

    @pytest.mark.parametrize("filename", VALIDATE_FIXTURES)
    def test_semantic_diff_zero(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        doc = parse_hwp(_fixture(filename))
        out = str(tmp_path / filename)
        generate_hwp(doc, out)
        doc_rt = parse_hwp(out)
        report = diff_documents(doc, doc_rt)
        assert not report.lossy_blocks, (
            f"시맨틱 diff 비어있지 않음 ({filename}): "
            + ", ".join(f"[{b.loss_type.value}] {b.description}" for b in report.lossy_blocks)
        )
