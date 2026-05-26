#!/usr/bin/env python3
"""workspace/ 에 HWP 기능별 데모 파일을 생성한다.

각 파일은 특정 HWP 기능을 실제 눈으로 확인할 수 있도록 의미 있는
한글 내용으로 구성됨. 사용법: python scripts/make_workspace.py

생성 방식:
  - Seed Patch: 기존 구조(표, 서식)를 재사용하는 경우
  - From Scratch: 인라인 서식(볼드/이탤릭), 헤딩, 정렬 등 IR로 완전 제어
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from udf.core.schema import (
    DocumentMetadata,
    HeadingBlock,
    ParagraphBlock,
    TextInline,
    UdfDocument,
)
from udf.renderers.hwp.generate import patch_hwp_from_md
from udf.renderers.hwp.scratch import generate_hwp_scratch
from udf.parsers.hwp.parse import parse_hwp
from udf.renderers.md.render import _escape_md, render_md

FIXTURES = ROOT / "tests" / "fixtures" / "hwp"
WORKSPACE = ROOT / "workspace"
SEED = str(WORKSPACE / "plain_text.hwp")


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _text_blocks(doc) -> list[tuple[object, str]]:
    """비어있지 않은 텍스트 블록과 원문 텍스트 쌍 반환."""
    result = []
    for block in doc.blocks:
        if isinstance(block, ParagraphBlock):
            t = "".join(i.text for i in block.inlines if isinstance(i, TextInline))
            if t.strip():
                result.append((block, t))
        elif isinstance(block, HeadingBlock):
            if block.text.strip():
                result.append((block, block.text))
    return result


def make_hwp(seed: str, new_texts: list[str], out_name: str) -> None:
    """seed 파일을 기반으로 텍스트를 교체하여 workspace 파일을 생성한다."""
    seed_path = str(FIXTURES / seed)
    out_path = str(WORKSPACE / out_name)

    doc = parse_hwp(seed_path)
    md = render_md(doc, embed_ids=True)
    edited = md

    pairs = _text_blocks(doc)
    for i, new_text in enumerate(new_texts):
        if i >= len(pairs):
            break
        _, orig = pairs[i]
        esc = _escape_md(orig)
        if esc in edited:
            edited = edited.replace(esc, _escape_md(new_text) if new_text else "", 1)

    patch_hwp_from_md(seed_path, edited, out_path)
    print(f"  ✓ {out_name}")


def copy_as(seed: str | Path, out_name: str) -> None:
    """기존 파일을 workspace에 그대로 복사한다 (구조 변경 없음)."""
    src = Path(seed) if isinstance(seed, Path) else FIXTURES / seed
    shutil.copy2(src, WORKSPACE / out_name)
    print(f"  ✓ {out_name}  (복사)")


# ---------------------------------------------------------------------------
# 파일 정의
# ---------------------------------------------------------------------------

MANIFEST: list[tuple[str, dict]] = [
    # ── 01. 순수 텍스트 ──────────────────────────────────────────────────────
    (
        "01_순수텍스트.hwp",
        dict(
            method="make",
            seed="f01_plain_text.hwp",
            texts=[
                "UDFP는 다양한 문서 포맷을 JSON AST로 변환하는 라이브러리입니다.",
                "HWP, HWPX, PDF, DOCX, XLSX 등을 지원 목표로 합니다.",
                "무손실 라운드트립이 절대 요건입니다.",
            ],
        ),
    ),
    # ── 02. 글자 서식 (볼드 / 이탤릭 / 밑줄) ──────────────────────────────
    (
        "02_글자서식_볼드이탤릭밑줄.hwp",
        dict(
            method="make",
            seed="f02_char_format.hwp",
            texts=[
                "진하게(Bold) — 중요한 내용을 강조할 때 사용합니다.",
                "기울임꼴(Italic) — 외래어나 특수 용어를 표기할 때 씁니다.",
                "밑줄(Underline) — 링크 또는 키워드를 표시합니다.",
                "볼드+이탤릭 혼합 — 복합 서식 예시입니다.",
            ],
        ),
    ),
    # ── 03. 단락 정렬 (왼쪽 / 가운데 / 오른쪽 / 양쪽) ─────────────────────
    # seed f03의 실제 정렬 순서: right / justify / center / left
    (
        "03_단락정렬.hwp",
        dict(
            method="make",
            seed="f03_para_align.hwp",
            texts=[
                "오른쪽 정렬(right): 날짜·서명 등 우측 배치 요소에 씁니다.",
                "양쪽 정렬(justify): 본문 텍스트 좌우 여백을 맞출 때 사용합니다.",
                "가운데 정렬(center): 제목이나 캡션에 자주 사용됩니다.",
                "왼쪽 정렬(left): 기본 문단 배치 방식입니다.",
            ],
        ),
    ),
    # ── 04. 표 기본 구조 (2행 3열, 앞뒤 단락 포함) ─────────────────────────
    (
        "04_표_기본구조.hwp",
        dict(
            method="make",
            seed="f04_simple_table.hwp",
            texts=[
                "아래 표는 UDFP 지원 포맷 목록입니다.",
                "표 내용은 verbatim 레이어에 보존됩니다.",
            ],
        ),
    ),
    # ── 05. 표 셀 내용 (셀 텍스트 직접 확인) ──────────────────────────────
    (
        "05_표_셀내용.hwp",
        dict(
            method="copy",
            seed="f05_table_cell_text.hwp",
        ),
    ),
    # ── 06. 긴 문서 (30개 단락) ────────────────────────────────────────────
    (
        "06_긴문서_30단락.hwp",
        dict(
            method="make",
            seed="f06_multiline.hwp",
            texts=[
                f"단락 {i:02d} — UDFP 라운드트립 검증용 텍스트. 한글과 영어가 혼재합니다 (paragraph {i})."
                for i in range(1, 31)
            ],
        ),
    ),
    # ── 07. 한글 + 영문 + 숫자 + 기호 혼합 ───────────────────────────────
    (
        "07_한글영문숫자혼합.hwp",
        dict(
            method="make",
            seed="f07_hangul_latin.hwp",
            texts=[
                "한글 텍스트: 가나다라마바사 아자차카타파하 — 자음 모음 검증.",
                "English text: The quick brown fox jumps over the lazy dog.",
                "숫자 및 기호: 0123456789  ₩ $ % & * ( ) [ ] { }",
                "혼합 Mixed: 안녕 Hello 1234 こんにちは — 다국어 샘플.",
            ],
        ),
    ),
    # ── 08. 빈 단락 / 단락 여백 ────────────────────────────────────────────
    (
        "08_빈단락_여백.hwp",
        dict(
            method="make",
            seed="f08_empty_paras.hwp",
            texts=[
                "첫 번째 내용 단락입니다. 아래에 빈 단락이 이어집니다.",
                "두 번째 내용 단락입니다. 빈 단락 두 개가 앞에 있습니다.",
                "세 번째 내용 단락입니다. 단락 여백 확인용입니다.",
            ],
        ),
    ),
    # ── 09. 개요/헤딩 (H1, H2) ────────────────────────────────────────────
    (
        "09_헤딩_H1H2.hwp",
        dict(
            method="scratch",
            blocks=[
                HeadingBlock(type="heading", id="h1", level=1, text="1장. UDFP 소개"),
                HeadingBlock(type="heading", id="h2", level=1, text="2장. 지원 포맷"),
                HeadingBlock(type="heading", id="h3", level=2, text="2.1 HWP 바이너리 포맷"),
                HeadingBlock(type="heading", id="h4", level=2, text="2.2 HWPX XML 포맷"),
            ],
        ),
    ),
    # ══ From Scratch 섹션 ════════════════════════════════════════════════════
    # ── 10. 인라인 혼합 서식 (볼드+이탤릭+밑줄 단락 내 혼재) ──────────────
    (
        "10_인라인혼합서식.hwp",
        dict(
            method="scratch",
            blocks=[
                HeadingBlock(type="heading", id="h1", level=1, text="인라인 서식 데모"),
                ParagraphBlock(
                    type="paragraph", id="p1",
                    inlines=[
                        TextInline(type="text", text="이 단락에는 "),
                        TextInline(type="text", text="볼드(굵게)", bold=True),
                        TextInline(type="text", text=", "),
                        TextInline(type="text", text="이탤릭(기울임)", italic=True),
                        TextInline(type="text", text=", "),
                        TextInline(type="text", text="밑줄", underline=True),
                        TextInline(type="text", text=", "),
                        TextInline(type="text", text="볼드+이탤릭", bold=True, italic=True),
                        TextInline(type="text", text=" 서식이 한 단락에 혼재합니다."),
                    ],
                ),
                ParagraphBlock(
                    type="paragraph", id="p2",
                    inlines=[
                        TextInline(type="text", text="취소선("),
                        TextInline(type="text", text="strikethrough", strikethrough=True),
                        TextInline(type="text", text=") 및 일반 텍스트 조합."),
                    ],
                ),
            ],
        ),
    ),
    # ── 11. 단락 정렬 4종 (From Scratch, 정렬값 정확 반영) ─────────────────
    (
        "11_단락정렬_4종.hwp",
        dict(
            method="scratch",
            blocks=[
                HeadingBlock(type="heading", id="h1", level=1, text="단락 정렬 데모"),
                ParagraphBlock(
                    type="paragraph", id="p1",
                    format={"alignment": "left"},
                    inlines=[TextInline(type="text", text="왼쪽 정렬(left): 기본 본문 배치. 가장 자주 쓰이는 정렬 방식입니다.")],
                ),
                ParagraphBlock(
                    type="paragraph", id="p2",
                    format={"alignment": "center"},
                    inlines=[TextInline(type="text", text="가운데 정렬(center): 제목·캡션·시 등에 사용합니다.")],
                ),
                ParagraphBlock(
                    type="paragraph", id="p3",
                    format={"alignment": "right"},
                    inlines=[TextInline(type="text", text="오른쪽 정렬(right): 날짜, 서명, 쪽 번호에 사용합니다.")],
                ),
                ParagraphBlock(
                    type="paragraph", id="p4",
                    format={"alignment": "justify"},
                    inlines=[TextInline(type="text", text="양쪽 정렬(justify): 좌우 여백을 동시에 맞추는 방식. 공문서·학술 문서 본문에 많이 사용됩니다.")],
                ),
            ],
        ),
    ),
    # ── 12. 헤딩 H1~H4 (From Scratch, 스타일 ID 직접 매핑) ─────────────────
    (
        "12_헤딩_H1H2H3H4.hwp",
        dict(
            method="scratch",
            blocks=[
                HeadingBlock(type="heading", id="h1", level=1, text="1장. UDFP 아키텍처"),
                ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(type="text", text="이 문서는 UDFP의 계층 구조를 설명합니다.")]),
                HeadingBlock(type="heading", id="h2", level=2, text="1.1 파서 레이어"),
                ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(type="text", text="HWP 파서는 OLE2 컨테이너를 읽어 DocInfo와 BodyText를 파싱합니다.")]),
                HeadingBlock(type="heading", id="h3", level=3, text="1.1.1 DocInfo 파싱"),
                ParagraphBlock(type="paragraph", id="p2", inlines=[TextInline(type="text", text="CharShape, ParaShape, Style 테이블을 읽어 전역 리소스로 저장합니다.")]),
                HeadingBlock(type="heading", id="h4", level=4, text="1.1.1.1 CharShape 디코딩"),
                ParagraphBlock(type="paragraph", id="p3", inlines=[TextInline(type="text", text="74바이트 고정 구조로 볼드·이탤릭·밑줄 등의 글자 속성을 저장합니다.")]),
            ],
        ),
    ),
    # ── 13. 서식 없는 순수 한글 텍스트 (From Scratch) ──────────────────────
    (
        "13_순수한글_서식없음.hwp",
        dict(
            method="scratch",
            blocks=[
                ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(type="text", text="UDFP는 다양한 문서 포맷을 JSON Document AST로 변환합니다.")]),
                ParagraphBlock(type="paragraph", id="p2", inlines=[TextInline(type="text", text="HWP, HWPX, PDF, DOCX, XLSX 포맷을 지원 목표로 합니다.")]),
                ParagraphBlock(type="paragraph", id="p3", inlines=[TextInline(type="text", text="무손실 라운드트립이 절대 요건이며, LossReport가 동반됩니다.")]),
                ParagraphBlock(type="paragraph", id="p4", inlines=[TextInline(type="text", text="Seed Patch 모드와 From Scratch 모드 두 가지로 동작합니다.")]),
            ],
        ),
    ),
    # ── 14. 혼합 언어 + 혼합 서식 (From Scratch) ───────────────────────────
    (
        "14_다국어_혼합서식.hwp",
        dict(
            method="scratch",
            blocks=[
                HeadingBlock(type="heading", id="h1", level=1, text="Multi-language & Formatting"),
                ParagraphBlock(
                    type="paragraph", id="p1",
                    inlines=[
                        TextInline(type="text", text="한글: "),
                        TextInline(type="text", text="가나다라마바사아자차카타파하", bold=True),
                    ],
                ),
                ParagraphBlock(
                    type="paragraph", id="p2",
                    inlines=[
                        TextInline(type="text", text="English: "),
                        TextInline(type="text", text="The quick brown fox jumps over the lazy dog.", italic=True),
                    ],
                ),
                ParagraphBlock(
                    type="paragraph", id="p3",
                    inlines=[
                        TextInline(type="text", text="숫자·기호: "),
                        TextInline(type="text", text="0123456789 ₩$%&*()[]{}", underline=True),
                    ],
                ),
                ParagraphBlock(
                    type="paragraph", id="p4",
                    inlines=[TextInline(type="text", text="혼합: 안녕 Hello 1234 こんにちは — 다국어 혼재 검증용.")],
                ),
            ],
        ),
    ),
]


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"workspace → {WORKSPACE}\n")
    ok = 0
    fail = 0

    for out_name, spec in MANIFEST:
        try:
            method = spec["method"]
            if method == "copy":
                copy_as(spec["seed"], out_name)
            elif method == "make":
                make_hwp(spec["seed"], spec["texts"], out_name)
            elif method == "make_ws":
                seed_path = str(WORKSPACE / spec["seed"])
                out_path = str(WORKSPACE / out_name)
                doc = parse_hwp(seed_path)
                md = render_md(doc, embed_ids=True)
                edited = md
                pairs = _text_blocks(doc)
                for i, new_text in enumerate(spec["texts"]):
                    if i >= len(pairs):
                        break
                    _, orig = pairs[i]
                    esc = _escape_md(orig)
                    if esc in edited:
                        edited = edited.replace(esc, _escape_md(new_text), 1)
                patch_hwp_from_md(seed_path, edited, out_path)
                print(f"  ✓ {out_name}")
            elif method == "scratch":
                out_path = str(WORKSPACE / out_name)
                blocks = spec["blocks"]
                # format dict → BlockFormat 변환
                from udf.core.schema import BlockFormat
                for b in blocks:
                    if isinstance(b, ParagraphBlock) and isinstance(b.format, dict):
                        b.format = BlockFormat(**b.format)
                doc = UdfDocument(
                    source_format="hwp",
                    metadata=DocumentMetadata(),
                    blocks=blocks,
                )
                generate_hwp_scratch(doc, out_path, SEED)
                print(f"  ✓ {out_name}  (from scratch)")
            ok += 1
        except Exception as e:
            import traceback
            print(f"  ✗ {out_name}: {e}")
            traceback.print_exc()
            fail += 1

    print(f"\n완료: {ok}개 생성, {fail}개 실패")

    # 결과 요약
    print("\n생성된 파일:")
    for f in sorted(WORKSPACE.glob("*.hwp")):
        size = f.stat().st_size
        print(f"  {f.name:45s}  {size:>7,} bytes")


if __name__ == "__main__":
    main()
