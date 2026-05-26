#!/usr/bin/env python3
"""
realworld fixture 파일 탐색 스크립트.

사용법:
    # 1) 파일 목록 보기
    python sandbox/explore_realworld.py list

    # 2) 특정 파일 파싱해서 내용 확인
    python sandbox/explore_realworld.py parse 0        # 인덱스로
    python sandbox/explore_realworld.py parse 신문      # 이름 일부로 검색

    # 3) 포맷 변환 → output/realworld/ 에 저장
    python sandbox/explore_realworld.py convert 0 md
    python sandbox/explore_realworld.py convert 신문 md
    python sandbox/explore_realworld.py convert 0 docx

    # 4) 라운드트립 + diff (HWP→MD→비교)
    python sandbox/explore_realworld.py roundtrip 0
    python sandbox/explore_realworld.py roundtrip 신문

    # 5) 전체 일괄 테스트 (파싱 성공/실패 요약)
    python sandbox/explore_realworld.py batch
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

import udf

REALWORLD = Path("tests/fixtures/realworld")
OUTPUT = Path("output/realworld")


def collect_files() -> list[Path]:
    exts = {".hwp", ".hwpx", ".docx", ".pdf", ".md"}
    files = sorted(
        f for f in REALWORLD.rglob("*") if f.suffix.lower() in exts and f.is_file()
    )
    return files


def resolve_target(files: list[Path], query: str) -> Path:
    if query.isdigit():
        idx = int(query)
        if 0 <= idx < len(files):
            return files[idx]
        print(f"인덱스 범위 초과: 0~{len(files)-1}")
        sys.exit(1)
    matches = [f for f in files if query in f.name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        print(f"'{query}'에 해당하는 파일 없음")
        sys.exit(1)
    print(f"'{query}'에 해당하는 파일이 {len(matches)}개:")
    for i, m in enumerate(matches):
        print(f"  [{i}] {m.name}")
    sys.exit(1)


def cmd_list(files: list[Path]) -> None:
    print(f"총 {len(files)}개 파일\n")
    for i, f in enumerate(files):
        rel = f.relative_to(REALWORLD)
        size_kb = f.stat().st_size / 1024
        print(f"  [{i:3d}] {rel}  ({size_kb:.0f}KB)")


def cmd_parse(files: list[Path], query: str) -> None:
    path = resolve_target(files, query)
    print(f"파싱: {path.name}\n")

    doc = udf.parse(str(path))
    print(f"포맷: {doc.source_format}")
    print(f"블록 수: {len(doc.blocks)}")

    if doc.metadata:
        print(f"메타데이터: {doc.metadata}")

    print("\n--- 블록 목록 ---")
    for i, block in enumerate(doc.blocks):
        btype = block.type if hasattr(block, "type") else type(block).__name__
        text = ""
        if hasattr(block, "inlines") and block.inlines:
            text = "".join(
                il.text for il in block.inlines if hasattr(il, "text") and il.text
            )
        if hasattr(block, "cells"):
            text = f"[테이블 {len(block.rows)}x{len(block.cells[0]) if block.cells else 0}]" if hasattr(block, "rows") else "[테이블]"

        preview = text[:80] + ("..." if len(text) > 80 else "") if text else ""
        print(f"  [{i:3d}] {btype:12s} {preview}")

        if i >= 49:
            print(f"  ... ({len(doc.blocks) - 50}개 더)")
            break


def cmd_convert(files: list[Path], query: str, target_fmt: str) -> None:
    path = resolve_target(files, query)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    src_fmt = path.suffix.lstrip(".").lower()
    out_name = f"{path.stem}_{src_fmt}2{target_fmt}.{target_fmt}"
    out_path = OUTPUT / out_name

    print(f"변환: {path.name} → {out_name}")
    udf.convert(str(path), str(out_path))
    print(f"저장: {out_path}")
    print(f"크기: {out_path.stat().st_size / 1024:.1f}KB")

    if target_fmt == "md":
        content = out_path.read_text()
        print(f"\n--- 내용 미리보기 (처음 2000자) ---\n")
        print(content[:2000])
        if len(content) > 2000:
            print(f"\n... ({len(content) - 2000}자 더)")


def cmd_roundtrip(files: list[Path], query: str) -> None:
    path = resolve_target(files, query)
    fmt = path.suffix.lstrip(".").lower()

    print(f"라운드트립: {path.name}")
    print(f"경로: {fmt} → md → {fmt} 비교\n")

    doc_orig = udf.parse(str(path))
    print(f"원본 블록 수: {len(doc_orig.blocks)}")

    md_text = udf.render(doc_orig, "md")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    md_path = OUTPUT / f"{path.stem}_{fmt}2md_rt.md"
    md_path.write_text(md_text)
    print(f"MD 저장: {md_path}")

    doc_md = udf.parse(str(md_path))
    print(f"MD 블록 수: {len(doc_md.blocks)}")

    lr = udf.diff(doc_orig, doc_md)
    print(f"\n--- Loss Report ---")
    print(f"전체 블록: {lr.total_blocks}")
    print(f"무손실 블록: {lr.lossless_blocks}")
    print(f"라운드트립 안전: {lr.is_roundtrip_safe}")

    if lr.lossy_blocks:
        print(f"\n손실 항목 ({len(lr.lossy_blocks)}건):")
        for loss in lr.lossy_blocks[:20]:
            print(f"  - [{loss.block_id}] {loss.loss_type.value}: {loss.description}")
        if len(lr.lossy_blocks) > 20:
            print(f"  ... ({len(lr.lossy_blocks) - 20}건 더)")

    if lr.dropped_features:
        print(f"\n누락 기능: {lr.dropped_features}")


def cmd_batch(files: list[Path]) -> None:
    print(f"전체 {len(files)}개 파일 일괄 파싱 테스트\n")
    ok, fail = [], []

    for f in files:
        try:
            doc = udf.parse(str(f))
            ok.append((f, len(doc.blocks)))
        except Exception as e:
            fail.append((f, str(e)))

    print(f"성공: {len(ok)}개")
    for f, n in ok:
        print(f"  ✓ {f.relative_to(REALWORLD)} ({n} blocks)")

    if fail:
        print(f"\n실패: {len(fail)}개")
        for f, e in fail:
            print(f"  ✗ {f.relative_to(REALWORLD)}")
            print(f"    {e}")


def main() -> None:
    files = collect_files()
    if not files:
        print("realworld 파일 없음")
        sys.exit(1)

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "list":
        cmd_list(files)
    elif cmd == "parse":
        cmd_parse(files, sys.argv[2] if len(sys.argv) > 2 else "0")
    elif cmd == "convert":
        target_fmt = sys.argv[3] if len(sys.argv) > 3 else "md"
        cmd_convert(files, sys.argv[2] if len(sys.argv) > 2 else "0", target_fmt)
    elif cmd == "roundtrip":
        cmd_roundtrip(files, sys.argv[2] if len(sys.argv) > 2 else "0")
    elif cmd == "batch":
        cmd_batch(files)
    else:
        print(f"알 수 없는 명령: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
