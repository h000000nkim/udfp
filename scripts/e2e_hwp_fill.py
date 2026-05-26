#!/usr/bin/env python3
"""E2E test: HWP 양식 템플릿에 MD 드래프트를 주입하고 결과를 검증한다.

Usage:
    python scripts/e2e_hwp_fill.py [case_dir] [--output /tmp/filled.hwp]

case_dir 기본값: tests/fixtures/codex_cases/AFE실험_임운택
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import udf
from udf.core.schema import (
    FooterBlock,
    HeaderBlock,
    HeadingBlock,
    ParagraphBlock,
    TableBlock,
    TextBoxBlock,
    TextInline,
)


def _find_hwp_template(case_dir: pathlib.Path) -> pathlib.Path:
    candidates = list(case_dir.glob("attachments/*.hwp"))
    if not candidates:
        raise FileNotFoundError(f"HWP 템플릿 없음: {case_dir}/attachments/")
    return candidates[0]


def _find_md_draft(case_dir: pathlib.Path) -> pathlib.Path:
    for name in ("draft_report.md", "draft.md"):
        p = case_dir / name
        if p.exists():
            return p
    raise FileNotFoundError(f"MD 드래프트 없음: {case_dir}")


def _iter_content_paragraphs(blocks, depth=0, skip_header_footer=True):
    """모든 깊이의 ParagraphBlock을 재귀적으로 수집한다.

    Header/Footer 블록은 양식 콘텐츠가 아니므로 기본적으로 건너뜀.
    """
    for block in blocks:
        if skip_header_footer and isinstance(block, (HeaderBlock, FooterBlock)):
            continue
        if isinstance(block, ParagraphBlock):
            yield block, depth
        elif isinstance(block, HeadingBlock):
            yield block, depth
        elif isinstance(block, TextBoxBlock):
            yield from _iter_content_paragraphs(block.content, depth + 1, skip_header_footer)
        elif isinstance(block, TableBlock):
            for row in block.rows:
                for cell in row.cells:
                    yield from _iter_content_paragraphs(cell.content, depth + 1, skip_header_footer)
        elif hasattr(block, "content") and isinstance(
            getattr(block, "content", None), list
        ):
            yield from _iter_content_paragraphs(block.content, depth + 1, skip_header_footer)


def _get_block_text(block) -> str:
    if isinstance(block, HeadingBlock):
        return block.text
    if isinstance(block, ParagraphBlock):
        return "".join(
            i.text for i in block.inlines if isinstance(i, TextInline)
        )
    return ""


def _get_md_texts(md_doc) -> list[str]:
    """MD 파싱 결과에서 비어있지 않은 텍스트 단락을 추출한다."""
    texts = []
    for block, _ in _iter_content_paragraphs(md_doc.blocks):
        text = _get_block_text(block)
        if text.strip():
            texts.append(text)
    return texts


def run_e2e(case_dir: pathlib.Path, output_path: pathlib.Path) -> dict:
    result = {}

    # 1. 템플릿 파싱
    hwp_path = _find_hwp_template(case_dir)
    print(f"[1] 템플릿 파싱: {hwp_path.name}")
    tmpl = udf.parse(str(hwp_path))
    result["template_blocks"] = len(tmpl.blocks)
    result["has_verbatim"] = tmpl.verbatim is not None
    result["has_container"] = tmpl.original_container is not None

    # 2. 템플릿 구조 분석
    content_paras = list(_iter_content_paragraphs(tmpl.blocks))
    textbox_paras = [(b, d) for b, d in content_paras if d > 0]
    toplevel_paras = [(b, d) for b, d in content_paras if d == 0]
    print(f"    전체 단락: {len(content_paras)} (top-level: {len(toplevel_paras)}, nested: {len(textbox_paras)})")

    # 3. MD 드래프트 파싱
    md_path = _find_md_draft(case_dir)
    print(f"[2] MD 드래프트 파싱: {md_path.name}")
    md_doc = udf.parse(str(md_path))
    draft_texts = _get_md_texts(md_doc)
    print(f"    드래프트 텍스트 {len(draft_texts)}개")

    # 4. 빈 단락 식별 (주입 대상)
    writable_paras = []
    for block, depth in content_paras:
        text = _get_block_text(block)
        if isinstance(block, ParagraphBlock) and not text.strip() and depth > 0:
            writable_paras.append(block)

    print(f"[3] 주입 대상 빈 단락: {len(writable_paras)}개")

    # 5. 콘텐츠 단락에 드래프트 주입 (빈 단락 우선, 부족하면 기존 단락 덮어쓰기)
    inject_targets = []
    for block, depth in content_paras:
        if isinstance(block, ParagraphBlock) and depth > 0:
            text = _get_block_text(block)
            if not text.strip():
                inject_targets.append(block)

    n_inject = min(len(inject_targets), len(draft_texts))
    if n_inject == 0:
        # 빈 단락이 없으면 기존 콘텐츠 단락에 덮어쓰기
        for block, depth in content_paras:
            if isinstance(block, ParagraphBlock) and depth > 0:
                text = _get_block_text(block)
                if text.strip():
                    inject_targets.append(block)
        n_inject = min(len(inject_targets), len(draft_texts))

    print(f"[4] 텍스트 주입: {n_inject}개 단락")
    injected_ids = []
    for i in range(n_inject):
        block = inject_targets[i]
        new_text = draft_texts[i]
        if block.inlines:
            block.inlines[0] = TextInline(text=new_text)
        else:
            block.inlines = [TextInline(text=new_text)]
        injected_ids.append((block.id, new_text[:40]))

    for bid, txt in injected_ids[:5]:
        print(f"    {bid}: {txt}...")
    if len(injected_ids) > 5:
        print(f"    ... 외 {len(injected_ids) - 5}개")

    result["injected_count"] = n_inject

    # 6. Seed Patch 렌더링
    print(f"[5] HWP 렌더링 → {output_path}")
    try:
        udf.render(tmpl, "hwp", output_path=str(output_path))
        result["render_ok"] = True
        result["output_size"] = output_path.stat().st_size
        print(f"    성공: {result['output_size']:,} bytes")
    except Exception as e:
        result["render_ok"] = False
        result["render_error"] = str(e)
        print(f"    실패: {e}")
        return result

    # 7. 재파싱 검증
    print("[6] 재파싱 검증")
    rt = udf.parse(str(output_path))
    result["rt_blocks"] = len(rt.blocks)
    print(f"    블록 수: {result['template_blocks']} → {result['rt_blocks']}")

    rt_paras = list(_iter_content_paragraphs(rt.blocks))
    rt_texts_all = [_get_block_text(b) for b, _ in rt_paras if isinstance(b, ParagraphBlock)]

    # 주입한 텍스트가 결과물에 존재하는지 확인
    found = 0
    missing = []
    for bid, txt in injected_ids:
        search = txt[:30]
        if any(search in t for t in rt_texts_all):
            found += 1
        else:
            missing.append((bid, search))

    result["text_found"] = found
    result["text_missing"] = len(missing)
    print(f"    텍스트 보존: {found}/{n_inject}")

    if missing:
        print(f"    [경고] 소실된 텍스트 {len(missing)}건:")
        for bid, txt in missing[:5]:
            print(f"      {bid}: {txt}...")
        if len(missing) > 5:
            print(f"      ... 외 {len(missing) - 5}건")

    # 8. 결과 요약
    print()
    print("=" * 60)
    if result["text_missing"] == 0 and result["render_ok"]:
        print("결과: PASS — 모든 텍스트가 보존됨")
    elif result["render_ok"] and result["text_missing"] > 0:
        print(f"결과: PARTIAL — 렌더 성공, 텍스트 {result['text_missing']}건 소실")
        print("원인: Seed Patch가 TextBox 내부 단락 변경을 감지하지 못함")
        print("      _iter_all_blocks()와 _iter_text_blocks()가 TableBlock만 재귀하고")
        print("      TextBoxBlock 등 컨테이너 블록은 건너뜀")
    else:
        print(f"결과: FAIL — {result.get('render_error', '알 수 없는 오류')}")
    print("=" * 60)

    return result


def main():
    parser = argparse.ArgumentParser(description="E2E HWP 양식 채우기 테스트")
    parser.add_argument(
        "case_dir",
        nargs="?",
        default="tests/fixtures/codex_cases/AFE실험_임운택",
        help="케이스 디렉토리 경로",
    )
    parser.add_argument(
        "--output",
        default="/tmp/udf_e2e_filled.hwp",
        help="출력 HWP 경로",
    )
    args = parser.parse_args()

    case_dir = pathlib.Path(args.case_dir)
    if not case_dir.is_absolute():
        case_dir = pathlib.Path(__file__).resolve().parent.parent / case_dir
    output_path = pathlib.Path(args.output)

    run_e2e(case_dir, output_path)


if __name__ == "__main__":
    main()
