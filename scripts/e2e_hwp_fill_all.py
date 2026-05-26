#!/usr/bin/env python3
"""E2E test: 모든 codex_cases에 대해 HWP 양식 채우기를 실행한다.

Usage:
    python scripts/e2e_hwp_fill_all.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from scripts.e2e_hwp_fill import run_e2e

CASES_DIR = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "codex_cases"
OUTPUT_DIR = pathlib.Path("/tmp/udf_e2e_results")

CASE_CONFIGS = [
    {
        "name": "AFE실험_임운택",
        "hwp": "attachments/TalkFile_[실험] AFE 실험보고서(양식, 2026).hwp",
        "md": "draft_report.md",
    },
    {
        "name": "미적분1_김도현",
        "hwp": "outputs/미적분1_김도현/미적분Ⅰ의 원리와 응용에 관한 심층 탐구 보고서.hwp",
        "md": "outputs/미적분1_김도현/미적분1_김도현_최종초안.md",
    },
    {
        "name": "자율활동_이수민",
        "hwp": "jiyeogmunjeyeongye-peurojegteu-sinceongseo.hwp",
        "md": "outputs/자율활동_이수민/final_application.md",
    },
    {
        "name": "기하_김주원",
        "hwp": "output/report_template.hwp",
        "md": None,  # MD 없음 — 템플릿 파싱+렌더 only
    },
    {
        "name": "메디랩토론_이경원",
        "hwp": "메디랩_토론_보고서.hwp",
        "md": None,  # MD 없음 — 템플릿 파싱+렌더 only
    },
]


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for cfg in CASE_CONFIGS:
        case_dir = CASES_DIR / cfg["name"]
        hwp_path = case_dir / cfg["hwp"]
        md_path = case_dir / cfg["md"] if cfg["md"] else None

        if not hwp_path.exists():
            print(f"\n{'='*60}")
            print(f"SKIP: {cfg['name']} — HWP 없음: {hwp_path}")
            print(f"{'='*60}")
            results.append({"name": cfg["name"], "status": "SKIP", "reason": "HWP 없음"})
            continue

        if md_path and not md_path.exists():
            print(f"\n{'='*60}")
            print(f"SKIP: {cfg['name']} — MD 없음: {md_path}")
            print(f"{'='*60}")
            results.append({"name": cfg["name"], "status": "SKIP", "reason": "MD 없음"})
            continue

        # MD가 없는 케이스는 파싱→렌더→재파싱만 검증
        if md_path is None:
            print(f"\n{'='*60}")
            print(f"CASE: {cfg['name']} (파싱→렌더→재파싱만)")
            print(f"{'='*60}")
            result = _run_parse_render_only(cfg["name"], hwp_path)
            results.append(result)
            continue

        # 임시로 case_dir 구조를 맞추기 위해 심볼릭 구조 생성 대신 직접 호출
        print(f"\n{'='*60}")
        print(f"CASE: {cfg['name']}")
        print(f"{'='*60}")

        output_path = OUTPUT_DIR / f"{cfg['name']}_filled.hwp"
        result = _run_fill(cfg["name"], hwp_path, md_path, output_path)
        results.append(result)

    # 전체 요약
    print(f"\n\n{'='*60}")
    print("전체 요약")
    print(f"{'='*60}")
    for r in results:
        status = r["status"]
        name = r["name"]
        detail = r.get("detail", "")
        icon = {"PASS": "OK", "PARTIAL": "!!", "FAIL": "XX", "SKIP": "--"}.get(status, "??")
        print(f"  [{icon}] {name}: {status} {detail}")

    pass_count = sum(1 for r in results if r["status"] == "PASS")
    total = len(results)
    print(f"\n{pass_count}/{total} PASS")


def _run_fill(name, hwp_path, md_path, output_path):
    import udf
    from udf.core.schema import (
        FooterBlock, HeaderBlock, HeadingBlock,
        ParagraphBlock, TableBlock, TextBoxBlock, TextInline,
    )

    try:
        tmpl = udf.parse(str(hwp_path))
    except Exception as e:
        print(f"  [실패] 템플릿 파싱 에러: {e}")
        return {"name": name, "status": "FAIL", "detail": f"파싱 에러: {e}"}

    print(f"  템플릿: {len(tmpl.blocks)} 블록, verbatim={tmpl.verbatim is not None}")

    try:
        md_doc = udf.parse(str(md_path))
    except Exception as e:
        print(f"  [실패] MD 파싱 에러: {e}")
        return {"name": name, "status": "FAIL", "detail": f"MD 파싱 에러: {e}"}

    def iter_paras(blocks, depth=0):
        for b in blocks:
            if isinstance(b, (HeaderBlock, FooterBlock)):
                continue
            if isinstance(b, ParagraphBlock):
                yield b, depth
            elif isinstance(b, HeadingBlock):
                yield b, depth
            elif isinstance(b, TextBoxBlock):
                yield from iter_paras(b.content, depth + 1)
            elif isinstance(b, TableBlock):
                for row in b.rows:
                    for cell in row.cells:
                        yield from iter_paras(cell.content, depth + 1)
            elif hasattr(b, "content") and isinstance(getattr(b, "content", None), list):
                yield from iter_paras(b.content, depth + 1)

    def get_text(b):
        if isinstance(b, HeadingBlock):
            return b.text
        if isinstance(b, ParagraphBlock):
            return "".join(i.text for i in b.inlines if isinstance(i, TextInline))
        return ""

    # MD 텍스트 수집
    draft_texts = [get_text(b) for b, _ in iter_paras(md_doc.blocks) if get_text(b).strip()]
    print(f"  드래프트: {len(draft_texts)} 텍스트")

    # 빈 단락 우선, 부족하면 콘텐츠 단락 덮어쓰기
    targets = []
    for b, depth in iter_paras(tmpl.blocks):
        if isinstance(b, ParagraphBlock) and depth > 0 and not get_text(b).strip():
            targets.append(b)

    if not targets:
        for b, depth in iter_paras(tmpl.blocks):
            if isinstance(b, ParagraphBlock) and depth > 0 and get_text(b).strip():
                targets.append(b)

    n = min(len(targets), len(draft_texts))
    print(f"  주입: {n}개 단락")

    injected = []
    for i in range(n):
        b = targets[i]
        txt = draft_texts[i]
        if b.inlines:
            b.inlines[0] = TextInline(text=txt)
        else:
            b.inlines = [TextInline(text=txt)]
        injected.append((b.id, txt[:40]))

    # 렌더
    try:
        udf.render(tmpl, "hwp", output_path=str(output_path))
    except Exception as e:
        print(f"  [실패] 렌더 에러: {e}")
        return {"name": name, "status": "FAIL", "detail": f"렌더 에러: {e}"}

    fsize = output_path.stat().st_size
    print(f"  출력: {fsize:,} bytes")

    # 재파싱 검증
    try:
        rt = udf.parse(str(output_path))
    except Exception as e:
        print(f"  [실패] 재파싱 에러: {e}")
        return {"name": name, "status": "FAIL", "detail": f"재파싱 에러: {e}"}

    print(f"  블록: {len(tmpl.blocks)} → {len(rt.blocks)}")

    rt_texts = [get_text(b) for b, _ in iter_paras(rt.blocks)]
    found = 0
    missing = []
    for bid, txt in injected:
        if any(txt[:30] in t for t in rt_texts):
            found += 1
        else:
            missing.append((bid, txt[:30]))

    print(f"  텍스트 보존: {found}/{n}")
    if missing:
        for bid, txt in missing[:3]:
            print(f"    소실: {bid}: {txt}...")

    if n == 0:
        return {"name": name, "status": "PASS", "detail": "주입 대상 0개 (파싱+렌더 성공)"}
    elif len(missing) == 0:
        return {"name": name, "status": "PASS", "detail": f"{found}/{n} 보존"}
    else:
        return {"name": name, "status": "PARTIAL", "detail": f"{found}/{n} 보존, {len(missing)} 소실"}


def _run_parse_render_only(name, hwp_path):
    import udf

    try:
        doc = udf.parse(str(hwp_path))
    except Exception as e:
        print(f"  [실패] 파싱 에러: {e}")
        return {"name": name, "status": "FAIL", "detail": f"파싱 에러: {e}"}

    print(f"  블록: {len(doc.blocks)}, verbatim={doc.verbatim is not None}")

    output_path = OUTPUT_DIR / f"{name}_rt.hwp"
    try:
        udf.render(doc, "hwp", output_path=str(output_path))
    except Exception as e:
        print(f"  [실패] 렌더 에러: {e}")
        return {"name": name, "status": "FAIL", "detail": f"렌더 에러: {e}"}

    fsize = output_path.stat().st_size
    print(f"  출력: {fsize:,} bytes")

    try:
        rt = udf.parse(str(output_path))
    except Exception as e:
        print(f"  [실패] 재파싱 에러: {e}")
        return {"name": name, "status": "FAIL", "detail": f"재파싱 에러: {e}"}

    print(f"  블록: {len(doc.blocks)} → {len(rt.blocks)}")
    return {"name": name, "status": "PASS", "detail": f"블록 {len(doc.blocks)}→{len(rt.blocks)}, {fsize:,}B"}


if __name__ == "__main__":
    main()
