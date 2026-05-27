"""HWP → MD → HWP 엔드투엔드 라운드트립 테스트.

P0 핵심 경로:
  1. parse_hwp → UdfDocument
  2. render_md(embed_ids=True) → MD 문자열
  3. 사용자가 MD 편집 (시뮬레이션)
  4. patch_hwp_from_md → 텍스트 변경 패치된 HWP
  5. parse_hwp 재파싱 → 텍스트 검증
"""

from __future__ import annotations

import pathlib

import pytest

from udf.renderers.hwp import patch_hwp_from_md
from udf.parsers.hwp.parse import parse_hwp
from udf.renderers.md import render_md, _escape_md
from udf.core.schema import ParagraphBlock, TableBlock, TextInline

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwp"


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


def _all_texts(doc) -> list[str]:
    texts = []
    for block in doc.blocks:
        if isinstance(block, ParagraphBlock):
            t = "".join(i.text for i in block.inlines if isinstance(i, TextInline))
            if t.strip():
                texts.append(t)
    return texts


class TestHwpMdRoundtrip:
    """HWP → MD → HWP verbatim 라운드트립 (편집 없음)."""

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f06_multiline.hwp",
            "f07_hangul_latin.hwp",
        ],
    )
    def test_verbatim_passthrough(self, filename: str, tmp_path: pathlib.Path) -> None:
        """MD 렌더링 후 편집 없이 그대로 다시 HWP 생성 — 텍스트 보존."""
        doc_orig = parse_hwp(_fixture(filename))
        md = render_md(doc_orig, embed_ids=True)

        out = str(tmp_path / filename)
        patch_hwp_from_md(_fixture(filename), md, out)

        doc_rt = parse_hwp(out)
        assert _all_texts(doc_orig) == _all_texts(doc_rt), (
            f"텍스트 불일치: {_all_texts(doc_orig)!r} != {_all_texts(doc_rt)!r}"
        )


class TestHwpMdTextEdit:
    """HWP → MD 편집 → HWP — 텍스트 변경 반영 테스트."""

    def test_single_para_edit(self, tmp_path: pathlib.Path) -> None:
        """단락 텍스트 변경이 출력 HWP에 반영되어야 한다."""
        orig_path = _fixture("f01_plain_text.hwp")
        doc_orig = parse_hwp(orig_path)
        md = render_md(doc_orig, embed_ids=True)

        # 첫 번째 단락 텍스트 교체 (MD 이스케이프 고려)
        orig_texts = _all_texts(doc_orig)
        assert orig_texts, "f01은 비어있지 않아야 함"

        first_text = orig_texts[0]
        new_text = "수정된 첫 번째 단락"
        edited_md = md.replace(_escape_md(first_text), new_text)

        out = str(tmp_path / "edited_f01.hwp")
        patch_hwp_from_md(orig_path, edited_md, out)

        doc_rt = parse_hwp(out)
        rt_texts = _all_texts(doc_rt)
        assert new_text in rt_texts, f"수정 텍스트를 찾을 수 없음: {rt_texts!r}"
        # 나머지 단락은 보존
        for t in orig_texts[1:]:
            assert t in rt_texts, f"기존 텍스트 손실: {t!r}"

    def test_unchanged_paras_preserved(self, tmp_path: pathlib.Path) -> None:
        """편집하지 않은 단락은 원본 bytes 그대로 보존된다."""
        orig_path = _fixture("f06_multiline.hwp")
        doc_orig = parse_hwp(orig_path)
        md = render_md(doc_orig, embed_ids=True)

        orig_texts = _all_texts(doc_orig)
        if len(orig_texts) < 2:
            pytest.skip("단락이 2개 미만인 fixture")

        # 첫 단락만 편집 (MD 이스케이프 고려)
        first_text = orig_texts[0]
        edited_md = md.replace(_escape_md(first_text), "변경된텍스트")

        out = str(tmp_path / "edited_f06.hwp")
        patch_hwp_from_md(orig_path, edited_md, out)

        doc_rt = parse_hwp(out)
        rt_texts = _all_texts(doc_rt)
        # 두 번째 이후 단락 보존
        for t in orig_texts[1:]:
            assert t in rt_texts, f"미편집 단락 손실: {t!r}"


class TestHwpMdTableRoundtrip:
    """HWP → MD → HWP 테이블 셀 텍스트 라운드트립."""

    def _table_cell_texts(self, doc) -> list[str]:
        """문서 내 모든 테이블 셀의 텍스트를 flat list로 반환."""
        texts = []
        for block in doc.blocks:
            if isinstance(block, TableBlock):
                for row in block.rows:
                    for cell in row.cells:
                        for b in cell.content:
                            if isinstance(b, ParagraphBlock):
                                t = "".join(
                                    i.text
                                    for i in b.inlines
                                    if isinstance(i, TextInline)
                                )
                                if t.strip():
                                    texts.append(t)
        return texts

    @pytest.mark.parametrize(
        "filename",
        [
            "f04_simple_table.hwp",
            "f05_table_cell_text.hwp",
        ],
    )
    def test_table_text_preserved(self, filename: str, tmp_path: pathlib.Path) -> None:
        """테이블 셀 텍스트가 편집 없이 라운드트립 후 보존되어야 한다."""
        doc_orig = parse_hwp(_fixture(filename))
        md = render_md(doc_orig, embed_ids=True)

        out = str(tmp_path / filename)
        patch_hwp_from_md(_fixture(filename), md, out)

        doc_rt = parse_hwp(out)
        assert self._table_cell_texts(doc_orig) == self._table_cell_texts(doc_rt), (
            f"테이블 셀 텍스트 불일치"
        )

    def test_table_cell_edit(self, tmp_path: pathlib.Path) -> None:
        """테이블 셀 텍스트 변경이 출력 HWP에 반영되어야 한다."""
        orig_path = _fixture("f05_table_cell_text.hwp")
        doc_orig = parse_hwp(orig_path)
        cell_texts = self._table_cell_texts(doc_orig)
        if not cell_texts:
            pytest.skip("테이블 셀 텍스트 없음")

        md = render_md(doc_orig, embed_ids=True)
        target = cell_texts[0]
        new_text = "수정된셀"
        edited_md = md.replace(target, new_text, 1)

        out = str(tmp_path / "edited_table.hwp")
        report = patch_hwp_from_md(orig_path, edited_md, out)

        doc_rt = parse_hwp(out)
        rt_cells = self._table_cell_texts(doc_rt)
        assert new_text in rt_cells, f"수정 텍스트 미반영: {rt_cells!r}"


class TestHwpMdBodyWriter:
    """apply_paragraph_patches 직접 테스트."""

    def test_patch_does_not_crash(self, tmp_path: pathlib.Path) -> None:
        """body_writer 패치 후 파일이 생성되고 파싱 가능해야 한다."""
        orig_path = _fixture("f01_plain_text.hwp")
        out = str(tmp_path / "patched.hwp")

        doc_orig = parse_hwp(orig_path)
        md = render_md(doc_orig, embed_ids=True)

        orig_texts = _all_texts(doc_orig)
        if not orig_texts:
            pytest.skip("텍스트 없는 fixture")

        edited_md = md.replace(_escape_md(orig_texts[0]), "패치된텍스트")
        patch_hwp_from_md(orig_path, edited_md, out)

        assert pathlib.Path(out).exists()
        assert pathlib.Path(out).stat().st_size > 0

        # 재파싱 가능 여부
        doc_rt = parse_hwp(out)
        assert doc_rt is not None
        rt_texts = _all_texts(doc_rt)
        assert "패치된텍스트" in rt_texts

    def test_r1_preserved(self, tmp_path: pathlib.Path) -> None:
        """패치 후 R1 규칙(charCnt == len(PT)//2) 통과."""
        from udf.validation.hwp.rules import check_r1

        orig_path = _fixture("f01_plain_text.hwp")
        doc_orig = parse_hwp(orig_path)
        md = render_md(doc_orig, embed_ids=True)

        orig_texts = _all_texts(doc_orig)
        if not orig_texts:
            pytest.skip("텍스트 없는 fixture")

        edited_md = md.replace(_escape_md(orig_texts[0]), "R1검증텍스트")
        out = str(tmp_path / "r1_test.hwp")
        patch_hwp_from_md(orig_path, edited_md, out)

        doc_rt = parse_hwp(out)
        violations = check_r1(doc_rt)
        assert not violations, f"R1 위반: {violations}"
