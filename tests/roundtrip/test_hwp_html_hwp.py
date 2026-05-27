"""HWP → HTML → HWP 엔드투엔드 라운드트립 테스트.

P0 경로:
  1. parse_hwp → UdfDocument
  2. render_html(embed_ids=True) → HTML 문자열
  3. parse_html → UdfDocument (텍스트 보존 검증)
  4. 사용자가 HTML 편집 (시뮬레이션)
  5. patch_hwp_from_html → 텍스트 변경 패치된 HWP
  6. parse_hwp 재파싱 → 텍스트 검증
"""

from __future__ import annotations

import pathlib

import pytest

from udf.renderers.hwp import patch_hwp_from_html
from udf.parsers.hwp.parse import parse_hwp
from udf.parsers.html.parse import parse_html
from udf.renderers.md import render_html
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


class TestHwpHtmlRoundtrip:
    """HWP → HTML → parse_html: 텍스트 보존 검증."""

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f02_char_format.hwp",
            "f03_para_align.hwp",
            "f06_multiline.hwp",
            "f07_hangul_latin.hwp",
            "f08_empty_paras.hwp",
            "f13_pure_hangul.hwp",
        ],
    )
    def test_text_preserved(self, filename: str) -> None:
        """HTML 렌더링 후 parse_html 시 단락 텍스트가 ID 기반으로 보존."""
        doc_orig = parse_hwp(_fixture(filename))
        html = render_html(doc_orig, embed_images=True, embed_ids=True)
        doc_html = parse_html(html)

        orig_by_id = {}
        for b in doc_orig.blocks:
            if isinstance(b, ParagraphBlock):
                t = "".join(i.text for i in b.inlines if isinstance(i, TextInline))
                if t.strip():
                    orig_by_id[b.id] = t

        html_by_id = {}
        for b in doc_html.blocks:
            if isinstance(b, ParagraphBlock):
                t = "".join(i.text for i in b.inlines if isinstance(i, TextInline))
                if t.strip():
                    html_by_id[b.id] = t

        for bid, text in orig_by_id.items():
            assert bid in html_by_id, f"블록 {bid} 누락"
            assert html_by_id[bid].strip() == text.strip(), (
                f"블록 {bid} 텍스트 불일치: {text!r} != {html_by_id[bid]!r}"
            )

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f06_multiline.hwp",
            "f07_hangul_latin.hwp",
        ],
    )
    def test_block_count_preserved(self, filename: str) -> None:
        """HTML 파싱 후 블록 수가 원본과 일치해야 한다."""
        doc_orig = parse_hwp(_fixture(filename))
        html = render_html(doc_orig, embed_images=True, embed_ids=True)
        doc_html = parse_html(html)

        assert len(doc_html.blocks) == len(doc_orig.blocks), (
            f"{filename}: {len(doc_orig.blocks)} → {len(doc_html.blocks)} blocks"
        )


class TestHwpHtmlTextEdit:
    """HWP → HTML 편집 → HWP: 텍스트 변경 반영 테스트."""

    def test_single_para_edit(self, tmp_path: pathlib.Path) -> None:
        """단락 텍스트 변경이 출력 HWP에 반영되어야 한다."""
        orig_path = _fixture("f01_plain_text.hwp")
        doc_orig = parse_hwp(orig_path)
        html = render_html(doc_orig, embed_images=True, embed_ids=True)

        orig_texts = _all_texts(doc_orig)
        assert orig_texts, "f01은 비어있지 않아야 함"

        first_text = orig_texts[0]
        new_text = "HTML에서 수정된 첫 번째 단락"
        edited_html = html.replace(first_text, new_text)

        out = str(tmp_path / "edited_f01.hwp")
        patch_hwp_from_html(orig_path, edited_html, out)

        doc_rt = parse_hwp(out)
        rt_texts = _all_texts(doc_rt)
        assert new_text in rt_texts, f"수정 텍스트를 찾을 수 없음: {rt_texts!r}"
        for t in orig_texts[1:]:
            assert t in rt_texts, f"기존 텍스트 손실: {t!r}"

    def test_unchanged_paras_preserved(self, tmp_path: pathlib.Path) -> None:
        """편집하지 않은 단락은 원본 그대로 보존된다."""
        orig_path = _fixture("f06_multiline.hwp")
        doc_orig = parse_hwp(orig_path)
        html = render_html(doc_orig, embed_images=True, embed_ids=True)

        orig_texts = _all_texts(doc_orig)
        if len(orig_texts) < 2:
            pytest.skip("단락이 2개 미만")

        first_text = orig_texts[0]
        edited_html = html.replace(first_text, "변경된텍스트")

        out = str(tmp_path / "edited_f06.hwp")
        patch_hwp_from_html(orig_path, edited_html, out)

        doc_rt = parse_hwp(out)
        rt_texts = _all_texts(doc_rt)
        for t in orig_texts[1:]:
            assert t in rt_texts, f"미편집 단락 손실: {t!r}"

    def test_no_edit_roundtrip(self, tmp_path: pathlib.Path) -> None:
        """편집 없이 HWP → HTML → HWP 시 모든 텍스트 보존."""
        orig_path = _fixture("f01_plain_text.hwp")
        doc_orig = parse_hwp(orig_path)
        html = render_html(doc_orig, embed_images=True, embed_ids=True)

        out = str(tmp_path / "noedit_f01.hwp")
        report = patch_hwp_from_html(orig_path, html, out)
        assert report.is_roundtrip_safe, "LossReport not safe"

        doc_rt = parse_hwp(out)
        assert _all_texts(doc_orig) == _all_texts(doc_rt)


class TestHwpHtmlTableRoundtrip:
    """HWP → HTML → HWP 테이블 셀 텍스트 라운드트립."""

    def _table_cell_texts(self, doc) -> list[str]:
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
        """테이블 셀 텍스트가 편집 없이 라운드트립 후 보존."""
        doc_orig = parse_hwp(_fixture(filename))
        html = render_html(doc_orig, embed_images=True, embed_ids=True)

        out = str(tmp_path / filename)
        patch_hwp_from_html(_fixture(filename), html, out)

        doc_rt = parse_hwp(out)
        assert self._table_cell_texts(doc_orig) == self._table_cell_texts(doc_rt)


class TestHwpHtmlValidation:
    """HTML 라운드트립 후 R-규칙 통과 검증."""

    def test_r1_preserved(self, tmp_path: pathlib.Path) -> None:
        """패치 후 R1 규칙 통과."""
        from udf.validation.hwp.rules import check_r1

        orig_path = _fixture("f01_plain_text.hwp")
        doc_orig = parse_hwp(orig_path)
        html = render_html(doc_orig, embed_images=True, embed_ids=True)

        orig_texts = _all_texts(doc_orig)
        assert orig_texts
        edited_html = html.replace(orig_texts[0], "R1검증텍스트")

        out = str(tmp_path / "r1_test.hwp")
        patch_hwp_from_html(orig_path, edited_html, out)

        doc_rt = parse_hwp(out)
        violations = check_r1(doc_rt)
        assert not violations, f"R1 위반: {violations}"
