"""P0 편집 시나리오 검증 + 역검증(falsifiability).

1. 단락 1개 편집 → 편집된 단락만 변경, 나머지 원본 유지
2. LossReport: user_edited 1개, unintended 0개
3. 역검증: 고의 파손 데이터에서 검증 실패, 텍스트 변경 시 diff가 감지
"""

from __future__ import annotations

import pathlib

import pytest

from udf.core.loss import diff_documents
from udf.core.schema import (
    HeadingBlock,
    LossCategory,
    ParagraphBlock,
    TextInline,
)
from udf.renderers.hwp import patch_hwp_from_md
from udf.parsers.hwp.parse import parse_hwp
from udf.renderers.md import render_md, _escape_md
from udf.validation.hwp.rules import validate_hwp

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
        elif isinstance(block, HeadingBlock):
            if block.text.strip():
                texts.append(block.text)
    return texts


class TestP0SingleEdit:
    """단락 1개 편집 → HWP 출력 검증."""

    @pytest.mark.parametrize(
        "filename",
        ["f01_plain_text.hwp", "f06_multiline.hwp", "f07_hangul_latin.hwp"],
    )
    def test_single_para_edit_reflected(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        """편집된 단락이 출력 HWP에 반영된다."""
        orig_path = _fixture(filename)
        doc_orig = parse_hwp(orig_path)
        md = render_md(doc_orig, embed_ids=True)

        orig_texts = _all_texts(doc_orig)
        assert orig_texts, f"{filename}: 비어있는 fixture"

        first_text = orig_texts[0]
        new_text = "편집된 첫 단락 텍스트"
        edited_md = md.replace(_escape_md(first_text), new_text)

        out = str(tmp_path / filename)
        patch_hwp_from_md(orig_path, edited_md, out)

        doc_rt = parse_hwp(out)
        rt_texts = _all_texts(doc_rt)
        assert new_text in rt_texts, f"편집 텍스트 미반영: {rt_texts!r}"

    @pytest.mark.parametrize(
        "filename",
        ["f01_plain_text.hwp", "f06_multiline.hwp", "f07_hangul_latin.hwp"],
    )
    def test_unedited_paras_preserved(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        """편집하지 않은 단락은 원본과 동일해야 한다."""
        orig_path = _fixture(filename)
        doc_orig = parse_hwp(orig_path)
        md = render_md(doc_orig, embed_ids=True)

        orig_texts = _all_texts(doc_orig)
        if len(orig_texts) < 2:
            pytest.skip("단락이 2개 미만")

        first_text = orig_texts[0]
        edited_md = md.replace(_escape_md(first_text), "수정됨")

        out = str(tmp_path / filename)
        patch_hwp_from_md(orig_path, edited_md, out)

        doc_rt = parse_hwp(out)
        rt_texts = _all_texts(doc_rt)
        for t in orig_texts[1:]:
            assert t in rt_texts, f"미편집 단락 손실: {t!r}"


class TestP0LossReport:
    """LossReport 검증: user_edited / unintended 정확도."""

    def test_edit_produces_user_edited_loss(self, tmp_path: pathlib.Path) -> None:
        """단락 편집 → LossReport에 user_edited 1개."""
        orig_path = _fixture("f01_plain_text.hwp")
        doc_orig = parse_hwp(orig_path)
        md = render_md(doc_orig, embed_ids=True)

        orig_texts = _all_texts(doc_orig)
        assert orig_texts

        edited_md = md.replace(_escape_md(orig_texts[0]), "수정 텍스트")
        out = str(tmp_path / "loss_test.hwp")
        report = patch_hwp_from_md(orig_path, edited_md, out)

        user_edits = [
            b
            for b in report.lossy_blocks
            if b.loss_type == LossCategory.USER_EDITED
        ]
        assert len(user_edits) >= 1, "user_edited 손실이 없음"

    def test_no_edit_no_unintended(self, tmp_path: pathlib.Path) -> None:
        """편집 없이 라운드트립 → unintended 손실 0개."""
        orig_path = _fixture("f01_plain_text.hwp")
        doc_orig = parse_hwp(orig_path)
        md = render_md(doc_orig, embed_ids=True)

        out = str(tmp_path / "noedit.hwp")
        report = patch_hwp_from_md(orig_path, md, out)

        unintended = [
            b
            for b in report.lossy_blocks
            if b.loss_type == LossCategory.UNINTENDED
        ]
        assert not unintended, (
            f"비의도 손실 발생: {[b.description for b in unintended]}"
        )

    def test_edit_roundtrip_safe(self, tmp_path: pathlib.Path) -> None:
        """단락 편집 후에도 is_roundtrip_safe == True (unintended 없음)."""
        orig_path = _fixture("f01_plain_text.hwp")
        doc_orig = parse_hwp(orig_path)
        md = render_md(doc_orig, embed_ids=True)

        orig_texts = _all_texts(doc_orig)
        edited_md = md.replace(_escape_md(orig_texts[0]), "안전한 편집")
        out = str(tmp_path / "safe.hwp")
        report = patch_hwp_from_md(orig_path, edited_md, out)

        assert report.is_roundtrip_safe, (
            f"roundtrip unsafe: {[b.description for b in report.lossy_blocks if b.loss_type == LossCategory.UNINTENDED]}"
        )


class TestP0EditValidation:
    """편집 후 R-규칙 검증 통과."""

    @pytest.mark.parametrize(
        "filename",
        ["f01_plain_text.hwp", "f06_multiline.hwp", "f07_hangul_latin.hwp"],
    )
    def test_edited_hwp_passes_r_rules(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        orig_path = _fixture(filename)
        doc_orig = parse_hwp(orig_path)
        md = render_md(doc_orig, embed_ids=True)

        orig_texts = _all_texts(doc_orig)
        assert orig_texts
        edited_md = md.replace(_escape_md(orig_texts[0]), "R-규칙 검증 텍스트")

        out = str(tmp_path / filename)
        patch_hwp_from_md(orig_path, edited_md, out)

        doc_rt = parse_hwp(out)
        report = validate_hwp(doc_rt)
        assert report.is_passing(), (
            f"R-규칙 위반 ({filename}): "
            + ", ".join(f"{v.rule_id}:{v.message}" for v in report.all_violations)
        )


class TestFalsifiability:
    """역검증: 검증 수단이 실제 실패를 감지하는지 확인."""

    def test_diff_detects_text_change(self) -> None:
        """텍스트를 변경하면 diff_documents가 변경을 감지한다."""
        from udf.core.schema import DocumentMetadata, UdfDocument

        p1 = ParagraphBlock(
            type="paragraph",
            id="blk-1",
            inlines=[TextInline(text="원본 텍스트")],
        )
        p2 = ParagraphBlock(
            type="paragraph",
            id="blk-1",
            inlines=[TextInline(text="변경된 텍스트")],
        )
        doc_a = UdfDocument(
            source_format="hwp",
            metadata=DocumentMetadata(),
            blocks=[p1],
        )
        doc_b = UdfDocument(
            source_format="hwp",
            metadata=DocumentMetadata(),
            blocks=[p2],
        )
        report = diff_documents(doc_a, doc_b)
        assert len(report.lossy_blocks) > 0, "diff가 텍스트 변경을 감지하지 못함"
        assert any(
            b.loss_type == LossCategory.USER_EDITED for b in report.lossy_blocks
        )

    def test_diff_detects_block_loss(self) -> None:
        """블록이 소실되면 diff_documents가 감지한다."""
        from udf.core.schema import DocumentMetadata, UdfDocument

        p1 = ParagraphBlock(
            type="paragraph",
            id="blk-1",
            inlines=[TextInline(text="살아있는 단락")],
        )
        doc_a = UdfDocument(
            source_format="hwp",
            metadata=DocumentMetadata(),
            blocks=[p1],
        )
        doc_b = UdfDocument(
            source_format="hwp",
            metadata=DocumentMetadata(),
            blocks=[],
        )
        report = diff_documents(doc_a, doc_b)
        unintended = [
            b for b in report.lossy_blocks if b.loss_type == LossCategory.UNINTENDED
        ]
        assert len(unintended) > 0, "diff가 블록 소실을 감지하지 못함"

    def test_validate_detects_corrupted_charCnt(self) -> None:
        """charCnt를 고의로 파손하면 R1 위반이 발생해야 한다."""
        import base64
        import struct

        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        assert doc.verbatim is not None

        for sec_name, b64 in doc.verbatim.section_streams.items():
            raw = bytearray(base64.b64decode(b64))
            # 첫 번째 PARA_HEADER의 charCnt(offset 0)를 파손
            off = 0
            while off + 4 <= len(raw):
                hdr = struct.unpack_from("<I", raw, off)[0]
                tag_id = hdr & 0x3FF
                size_field = (hdr >> 20) & 0xFFF
                if size_field == 0xFFF:
                    ext_size = struct.unpack_from("<I", raw, off + 4)[0]
                    payload_off = off + 8
                    size = ext_size
                else:
                    payload_off = off + 4
                    size = size_field
                if tag_id == 66 and size >= 22:  # HWPTAG_PARA_HEADER
                    old_dw = struct.unpack_from("<I", raw, payload_off)[0]
                    msb = old_dw & 0x80000000
                    # charCnt를 고의로 잘못된 값으로 설정
                    struct.pack_into("<I", raw, payload_off, msb | 9999)
                    break
                off = payload_off + size

            doc.verbatim.section_streams[sec_name] = base64.b64encode(
                bytes(raw)
            ).decode()
            break

        # 파손된 스트림에서 재파싱
        from udf.validation.validation_loop import _reparse_from_streams

        doc_corrupted = _reparse_from_streams(doc)
        report = validate_hwp(doc_corrupted)
        assert not report.is_passing(), (
            "charCnt 파손 후에도 검증 통과 — 검증 수단이 실패를 감지하지 못함"
        )

    def test_semantic_diff_identity_is_zero(self) -> None:
        """동일 문서 비교 시 lossy_blocks = 0이어야 한다."""
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        report = diff_documents(doc, doc)
        assert len(report.lossy_blocks) == 0, (
            f"동일 문서인데 diff 발생: {[b.description for b in report.lossy_blocks]}"
        )

    def test_semantic_diff_detects_text_change(self) -> None:
        """대조군: 텍스트 변경 시 diff가 반드시 감지해야 한다."""
        import copy

        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        doc2 = copy.deepcopy(doc)
        for blk in doc2.blocks:
            if isinstance(blk, ParagraphBlock) and blk.inlines:
                for il in blk.inlines:
                    if isinstance(il, TextInline):
                        il.text = "CHANGED"
                        break
                break
        report = diff_documents(doc, doc2)
        assert len(report.lossy_blocks) > 0, "텍스트 변경을 감지하지 못함"
