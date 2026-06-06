"""P0 E2E 검증: HWP → IR → MD → IR → HWP → IR 전체 경로.

모든 fixture에 대해:
  1. parse → validate = 통과
  2. render_md → parse_md → 텍스트 보존
  3. generate_hwp → re-parse → validate = 통과
  4. 시맨틱 diff = 빈 lossy (편집 없음)
  5. 블록 수 보존
"""

from __future__ import annotations

import pathlib

import pytest

from udf.core.loss import diff_documents
from udf.renderers.hwp import generate_hwp
from udf.parsers.hwp.parse import parse_hwp
from udf.parsers.md.parse import parse_md
from udf.renderers.md import render_md
from udf.validation.hwp.rules import validate_hwp

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwp"

ALL_FIXTURES = [
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
]


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


from tests.helpers import all_texts as _all_texts


class TestP0Roundtrip:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_parse_validate_pass(self, filename: str) -> None:
        """1단계: 파싱 후 R-규칙 검증 ��과."""
        doc = parse_hwp(_fixture(filename))
        report = validate_hwp(doc)
        assert report.is_passing(), f"검증 실패 ({filename}): " + ", ".join(
            f"{v.rule_id}:{v.message}" for v in report.all_violations
        )

    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_generate_reparse_validate(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        """2단계: generate → re-parse → validate 통과."""
        doc = parse_hwp(_fixture(filename))
        out = str(tmp_path / filename)
        generate_hwp(doc, out)
        doc_rt = parse_hwp(out)
        report = validate_hwp(doc_rt)
        assert report.is_passing(), f"재생성 후 검증 실패 ({filename}): " + ", ".join(
            f"{v.rule_id}:{v.message}" for v in report.all_violations
        )

    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_text_preserved_after_roundtrip(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        """3단계: 텍스트 내용 보존 확인."""
        doc = parse_hwp(_fixture(filename))
        out = str(tmp_path / filename)
        generate_hwp(doc, out)
        doc_rt = parse_hwp(out)
        assert _all_texts(doc) == _all_texts(doc_rt), (
            f"텍스트 불일치 ({filename})"
        )

    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_block_ids_preserved(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        """4단계: 블록 ID 집합 보존 확인."""
        doc = parse_hwp(_fixture(filename))
        out = str(tmp_path / filename)
        generate_hwp(doc, out)
        doc_rt = parse_hwp(out)
        orig_ids = {b.id for b in doc.blocks if hasattr(b, "id")}
        rt_ids = {b.id for b in doc_rt.blocks if hasattr(b, "id")}
        assert orig_ids == rt_ids, (
            f"블록 ID 불일치 ({filename}): 소실={orig_ids - rt_ids}, 추가={rt_ids - orig_ids}"
        )

    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_semantic_diff_zero(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        """5단계: 시맨틱 diff = 0 (편집 없이 라운드트립)."""
        doc = parse_hwp(_fixture(filename))
        out = str(tmp_path / filename)
        generate_hwp(doc, out)
        doc_rt = parse_hwp(out)
        report = diff_documents(doc, doc_rt)
        assert not report.lossy_blocks, (
            f"시맨틱 diff 비어있지 않음 ({filename}): "
            + ", ".join(f"[{b.loss_type.value}] {b.description}" for b in report.lossy_blocks)
        )


class TestP0MdRoundtrip:
    """HWP → MD → (파싱) 텍스트 보존."""

    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_md_text_preserved(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        md = render_md(doc, embed_ids=True)
        doc_md = parse_md(md)
        # MD는 trailing whitespace를 자연적으로 strip — 포맷 특성이므로 rstrip 비교
        orig_texts = [t.rstrip() for t in _all_texts(doc)]
        md_texts = [t.rstrip() for t in _all_texts(doc_md)]
        assert orig_texts == md_texts, f"MD 텍스트 불일치 ({filename})"


class TestFormattingRoundtrip:
    """HWP → generate → reparse: 포맷팅(bold/italic/color 등) 보존 확인."""

    @pytest.mark.parametrize("filename", ["f02_char_format.hwp"])
    def test_formatting_diff_zero(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        """diff_documents()의 포맷팅 비교가 0개 lossy를 반환해야 함."""
        doc = parse_hwp(_fixture(filename))
        out = str(tmp_path / filename)
        generate_hwp(doc, out)
        doc_rt = parse_hwp(out)
        report = diff_documents(doc, doc_rt)
        formatting_losses = [
            b for b in report.lossy_blocks if b.description.startswith("포매팅 변경:")
        ]
        assert not formatting_losses, (
            f"포맷팅 손실 ({filename}): "
            + ", ".join(b.description for b in formatting_losses)
        )
