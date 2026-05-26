#!/usr/bin/env python3
"""
전체 realworld fixture 파일 테스트 스크립트.

출력 구조:
    output/files/originals/{hwp,hwpx,docx}/     원본 복사
    output/files/converted/{hwp2docx,...}/        변환 결과물
    output/files/modified/{hwp,docx,hwpx}/        수정 결과물
    output/files/test_results.json                전체 테스트 결과

사용법:
    python sandbox/test_all_realworld.py batch      # 전체 변환 테스트
    python sandbox/test_all_realworld.py roundtrip   # 같은 포맷 라운드트립
    python sandbox/test_all_realworld.py modify      # 수정 후 라운드트립
    python sandbox/test_all_realworld.py all          # 전체 실행
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

import udf
from udf.schema.inlines import Color, TextInline

REALWORLD = Path("tests/fixtures/realworld")
FILES = Path("output/files")
PURPLE = Color(r=128, g=0, b=128)

CONVERT_TARGETS = {
    "hwp": ["docx", "hwp"],
    "hwpx": ["docx", "hwp"],
    "docx": ["hwp", "docx"],
}

CONVERT_DIR_MAP = {
    ("hwp", "docx"): "hwp2docx",
    ("hwp", "hwp"): "hwp2hwp",
    ("hwpx", "docx"): "hwpx2docx",
    ("hwpx", "hwp"): "hwpx2hwp",
    ("docx", "docx"): "docx2docx",
    ("docx", "hwp"): "docx2hwp",
}


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def canonical_name(stem: str, max_len: int = 50) -> str:
    name = stem.replace(" ", "_")
    for ch in ",'()[]\"·…":
        name = name.replace(ch, "")
    if len(name) > max_len:
        name = name[:max_len]
    return name


def collect_files() -> list[Path]:
    exts = {".hwp", ".hwpx", ".docx"}
    return sorted(
        f for f in REALWORLD.rglob("*") if f.suffix.lower() in exts and f.is_file()
    )


def copy_originals(files: list[Path]) -> None:
    for f in files:
        fmt = f.suffix.lstrip(".").lower()
        dst_dir = FILES / "originals" / fmt
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / (canonical_name(nfc(f.stem)) + f.suffix)
        if not dst.exists():
            shutil.copy2(str(f), str(dst))


def out_path_for(src: Path, tgt_fmt: str, category: str = "converted") -> Path:
    src_fmt = src.suffix.lstrip(".").lower()
    subdir = CONVERT_DIR_MAP.get((src_fmt, tgt_fmt), f"{src_fmt}2{tgt_fmt}")
    dst_dir = FILES / category / subdir
    dst_dir.mkdir(parents=True, exist_ok=True)
    return dst_dir / (canonical_name(nfc(src.stem)) + f".{tgt_fmt}")


def mod_path_for(src: Path) -> Path:
    fmt = src.suffix.lstrip(".").lower()
    dst_dir = FILES / "modified" / fmt
    dst_dir.mkdir(parents=True, exist_ok=True)
    return dst_dir / (canonical_name(nfc(src.stem)) + src.suffix)


def count_types(doc) -> dict[str, int]:
    t: dict[str, int] = {}
    for b in doc.blocks:
        btype = b.type if hasattr(b, "type") else type(b).__name__
        t[btype] = t.get(btype, 0) + 1
    return t


@dataclass
class ConvResult:
    source: str
    src_fmt: str
    tgt_fmt: str
    parse_ok: bool = False
    parse_err: str = ""
    src_blocks: int = 0
    src_types: dict = field(default_factory=dict)
    render_ok: bool = False
    render_err: str = ""
    output_path: str = ""
    output_size: int = 0
    reparse_ok: bool = False
    reparse_err: str = ""
    tgt_blocks: int = 0
    tgt_types: dict = field(default_factory=dict)
    type_changes: dict = field(default_factory=dict)
    align_mismatches: int = 0
    ls_mismatches: int = 0
    size_ratio: float = 0.0
    elapsed: float = 0.0


@dataclass
class ModifyResult:
    source: str
    src_fmt: str
    tgt_fmt: str
    marker: str = ""
    modify_ok: bool = False
    modify_err: str = ""
    render_ok: bool = False
    render_err: str = ""
    marker_found: bool = False
    color_preserved: bool = False
    output_path: str = ""
    filled_count: int = 0
    empty_filled: int = 0


def run_single_conversion(path: Path, tgt_fmt: str) -> ConvResult:
    src_fmt = path.suffix.lstrip(".").lower()
    op = out_path_for(path, tgt_fmt)

    r = ConvResult(source=path.name, src_fmt=src_fmt, tgt_fmt=tgt_fmt)
    t0 = time.time()

    try:
        doc = udf.parse(str(path))
        r.parse_ok = True
        r.src_blocks = len(doc.blocks)
        r.src_types = count_types(doc)
    except Exception as e:
        r.parse_err = str(e)[:200]
        r.elapsed = time.time() - t0
        return r

    try:
        udf.convert(str(path), str(op))
        r.render_ok = True
        r.output_path = str(op)
        r.output_size = op.stat().st_size
        src_size = path.stat().st_size
        r.size_ratio = r.output_size / src_size if src_size > 0 else 0
    except Exception as e:
        r.render_err = str(e)[:200]
        r.elapsed = time.time() - t0
        return r

    try:
        conv = udf.parse(str(op))
        r.reparse_ok = True
        r.tgt_blocks = len(conv.blocks)
        r.tgt_types = count_types(conv)

        for tp in set(list(r.src_types.keys()) + list(r.tgt_types.keys())):
            o = r.src_types.get(tp, 0)
            c = r.tgt_types.get(tp, 0)
            if o != c:
                r.type_changes[tp] = f"{o}→{c}"

        for i in range(min(len(doc.blocks), len(conv.blocks))):
            ob = doc.blocks[i]
            cb = conv.blocks[i]
            oa = getattr(getattr(ob, "format", None), "alignment", None)
            ca = getattr(getattr(cb, "format", None), "alignment", None)
            if oa != ca:
                r.align_mismatches += 1
            ols = getattr(getattr(ob, "format", None), "line_spacing", None)
            cls = getattr(getattr(cb, "format", None), "line_spacing", None)
            olsv = ols.percent if ols and hasattr(ols, "percent") else ols
            clsv = cls.percent if cls and hasattr(cls, "percent") else cls
            if olsv != clsv:
                r.ls_mismatches += 1
    except Exception as e:
        r.reparse_err = str(e)[:200]

    r.elapsed = time.time() - t0
    return r


def _is_fillable_para(b: object) -> bool:
    """Check if a paragraph block is fillable (empty or whitespace-only)."""
    if not hasattr(b, "inlines"):
        return False
    if getattr(b, "type", None) == "field":
        return False
    if not b.inlines:
        return True
    return all(
        hasattr(il, "text") and (not il.text or not il.text.strip())
        for il in b.inlines
    )


def _fill_all_blanks(doc: object, marker: str) -> int:
    """Fill ALL empty/blank paragraphs in tables and top-level blocks.

    Returns the number of paragraphs filled.
    """
    filled = 0
    fill_text = f"보라색_{marker}"

    for b in doc.blocks:
        if hasattr(b, "rows"):
            for ri, row in enumerate(b.rows):
                for ci, cell in enumerate(row.cells):
                    for cb in cell.content:
                        if not hasattr(cb, "id"):
                            continue
                        if _is_fillable_para(cb):
                            try:
                                doc.set_inline_text(cb.id, 0, fill_text)
                                doc.set_inline_format(cb.id, 0, color=PURPLE)
                                filled += 1
                            except Exception:
                                pass
        elif _is_fillable_para(b) and hasattr(b, "id"):
            try:
                doc.set_inline_text(b.id, 0, fill_text)
                doc.set_inline_format(b.id, 0, color=PURPLE)
                filled += 1
            except Exception:
                pass
    return filled


def run_modify_test(path: Path) -> ModifyResult:
    src_fmt = path.suffix.lstrip(".").lower()
    ts = int(time.time())
    marker = f"{ts}-test중입니다-{ts}"
    op = mod_path_for(path)

    mr = ModifyResult(
        source=path.name, src_fmt=src_fmt, tgt_fmt=src_fmt, marker=marker
    )

    try:
        doc = udf.parse(str(path))

        # Phase 1: Append marker to the first non-empty text inline
        modified = False
        for b in doc.blocks:
            if hasattr(b, "inlines") and b.inlines:
                for idx, il in enumerate(b.inlines):
                    if hasattr(il, "text") and il.text and il.text.strip():
                        doc.set_inline_text(b.id, idx, il.text + marker)
                        doc.set_inline_format(b.id, idx, color=PURPLE)
                        modified = True
                        mr.filled_count += 1
                        break
                if modified:
                    break

        if not modified:
            for b in doc.blocks:
                if hasattr(b, "rows"):
                    for row in b.rows:
                        for cell in row.cells:
                            for cb in cell.content:
                                if hasattr(cb, "inlines") and cb.inlines:
                                    for idx, il in enumerate(cb.inlines):
                                        if hasattr(il, "text") and il.text and il.text.strip():
                                            doc.set_inline_text(cb.id, idx, il.text + marker)
                                            doc.set_inline_format(cb.id, idx, color=PURPLE)
                                            modified = True
                                            mr.filled_count += 1
                                            break
                                    if modified:
                                        break
                            if modified:
                                break
                        if modified:
                            break
                if modified:
                    break

        # Phase 2: Fill ALL empty paragraphs (tables + top-level)
        empty_filled = _fill_all_blanks(doc, marker)
        mr.empty_filled = empty_filled
        mr.filled_count += empty_filled

        if not modified and empty_filled == 0:
            mr.modify_err = "No text inline found and no blanks to fill"
            return mr
        mr.modify_ok = True
    except Exception as e:
        mr.modify_err = str(e)[:200]
        return mr

    try:
        udf.render(doc, src_fmt, output_path=str(op))
        mr.render_ok = True
        mr.output_path = str(op)
    except Exception as e:
        mr.render_err = str(e)[:200]
        return mr

    try:
        reloaded = udf.parse(str(op))
        for b in reloaded.blocks:
            if hasattr(b, "inlines") and b.inlines:
                for il in b.inlines:
                    if hasattr(il, "text") and il.text and marker in il.text:
                        mr.marker_found = True
                        if il.color and str(il.color) == "#800080":
                            mr.color_preserved = True
                        break
                if mr.marker_found:
                    break
        if not mr.marker_found:
            for b in reloaded.blocks:
                if hasattr(b, "rows"):
                    for row in b.rows:
                        for cell in row.cells:
                            for cb in cell.content:
                                if hasattr(cb, "inlines"):
                                    for il in cb.inlines:
                                        if hasattr(il, "text") and il.text and marker in il.text:
                                            mr.marker_found = True
                                            if il.color and str(il.color) == "#800080":
                                                mr.color_preserved = True
                                            break
                                if mr.marker_found:
                                    break
                            if mr.marker_found:
                                break
                        if mr.marker_found:
                            break
                if mr.marker_found:
                    break
    except Exception:
        pass

    return mr


def cmd_batch(files: list[Path]) -> list[ConvResult]:
    results: list[ConvResult] = []
    total_ops = sum(len(CONVERT_TARGETS.get(f.suffix.lstrip(".").lower(), [])) for f in files)
    done = 0

    for f in files:
        src_fmt = f.suffix.lstrip(".").lower()
        for tgt in CONVERT_TARGETS.get(src_fmt, []):
            done += 1
            cn = canonical_name(nfc(f.stem))[:30]
            print(f"  [{done}/{total_ops}] {cn} {src_fmt}→{tgt} ... ", end="", flush=True)
            try:
                r = run_single_conversion(f, tgt)
                status = "OK" if r.render_ok and r.reparse_ok else "FAIL"
                issues = []
                if r.type_changes:
                    issues.append(f"types:{r.type_changes}")
                if r.align_mismatches:
                    issues.append(f"align:{r.align_mismatches}")
                if r.ls_mismatches:
                    issues.append(f"ls:{r.ls_mismatches}")
                if r.size_ratio < 0.3 and r.render_ok:
                    issues.append(f"size:{r.size_ratio:.0%}")
                extra = f" [{', '.join(issues)}]" if issues else ""
                print(f"{status} ({r.elapsed:.1f}s){extra}")
                results.append(r)
            except Exception as e:
                print(f"CRASH: {e}")
                results.append(ConvResult(source=f.name, src_fmt=src_fmt, tgt_fmt=tgt, parse_err=f"CRASH: {e}"))

    return results


def cmd_roundtrip(files: list[Path]) -> list[ConvResult]:
    results: list[ConvResult] = []

    hwp_files = [f for f in files if f.suffix.lower() == ".hwp"]
    print(f"\n=== HWP→HWP 라운드트립 ({len(hwp_files)}개) ===\n")
    for i, f in enumerate(hwp_files):
        cn = canonical_name(nfc(f.stem))[:30]
        print(f"  [{i+1}/{len(hwp_files)}] {cn} ... ", end="", flush=True)
        r = run_single_conversion(f, "hwp")
        status = "OK" if r.render_ok and r.reparse_ok else "FAIL"
        issues = []
        if r.src_blocks != r.tgt_blocks:
            issues.append(f"blocks:{r.src_blocks}→{r.tgt_blocks}")
        if r.type_changes:
            issues.append(f"types:{r.type_changes}")
        extra = f" [{', '.join(issues)}]" if issues else ""
        print(f"{status} ({r.elapsed:.1f}s){extra}")
        results.append(r)

    docx_files = [f for f in files if f.suffix.lower() == ".docx"]
    if docx_files:
        print(f"\n=== DOCX→DOCX 라운드트립 ({len(docx_files)}개) ===\n")
        for i, f in enumerate(docx_files):
            cn = canonical_name(nfc(f.stem))[:30]
            print(f"  [{i+1}/{len(docx_files)}] {cn} ... ", end="", flush=True)
            r = run_single_conversion(f, "docx")
            status = "OK" if r.render_ok and r.reparse_ok else "FAIL"
            print(f"{status} ({r.elapsed:.1f}s)")
            results.append(r)

    return results


def cmd_modify(files: list[Path]) -> list[ModifyResult]:
    results: list[ModifyResult] = []
    for i, f in enumerate(files):
        cn = canonical_name(nfc(f.stem))[:30]
        src_fmt = f.suffix.lstrip(".").lower()
        print(f"  [{i+1}/{len(files)}] {cn} ({src_fmt}) ... ", end="", flush=True)
        mr = run_modify_test(f)
        parts = []
        parts.append("mod:OK" if mr.modify_ok else f"mod:FAIL({mr.modify_err[:30]})")
        parts.append("save:OK" if mr.render_ok else f"save:FAIL({mr.render_err[:30]})")
        parts.append("marker:FOUND" if mr.marker_found else "marker:LOST")
        parts.append("color:OK" if mr.color_preserved else "color:LOST")
        parts.append(f"fill:{mr.filled_count}(empty:{mr.empty_filled})")
        print(" | ".join(parts))
        results.append(mr)
    return results


def print_summary(batch_results, rt_results, mod_results):
    print("\n" + "=" * 70)
    print("=== 전체 테스트 결과 요약 ===")
    print("=" * 70)

    if batch_results:
        total = len(batch_results)
        render_ok = sum(1 for r in batch_results if r.render_ok)
        reparse_ok = sum(1 for r in batch_results if r.reparse_ok)
        type_issues = sum(1 for r in batch_results if r.type_changes)
        ls_issues = sum(1 for r in batch_results if r.ls_mismatches > 0)
        size_issues = sum(1 for r in batch_results if r.size_ratio < 0.3 and r.render_ok)

        print(f"\n[Batch] {total}건")
        print(f"  변환 성공: {render_ok}/{total}")
        print(f"  재파싱 성공: {reparse_ok}/{total}")
        print(f"  블록 타입 변경: {type_issues}건")
        print(f"  줄간격 불일치: {ls_issues}건")
        print(f"  크기 급감(<30%): {size_issues}건")

        fails = [r for r in batch_results if not r.render_ok]
        if fails:
            print("\n  변환 실패:")
            for r in fails:
                print(f"    - {r.source} ({r.src_fmt}→{r.tgt_fmt}): {(r.render_err or r.parse_err)[:80]}")

    if rt_results:
        total = len(rt_results)
        ok = sum(1 for r in rt_results if r.render_ok and r.reparse_ok and not r.type_changes)
        print(f"\n[Roundtrip] {ok}/{total} 완전 통과")
        fails = [r for r in rt_results if not (r.render_ok and r.reparse_ok and not r.type_changes)]
        if fails:
            for r in fails[:10]:
                issues = []
                if not r.render_ok:
                    issues.append(f"render:{r.render_err[:40]}")
                if not r.reparse_ok:
                    issues.append(f"reparse:{r.reparse_err[:40]}")
                if r.type_changes:
                    issues.append(f"types:{r.type_changes}")
                print(f"    - {r.source}: {', '.join(issues)}")

    if mod_results:
        total = len(mod_results)
        full_ok = sum(1 for r in mod_results if r.marker_found and r.color_preserved)
        marker_ok = sum(1 for r in mod_results if r.marker_found)
        color_ok = sum(1 for r in mod_results if r.color_preserved)
        print(f"\n[Modify] {total}건")
        print(f"  마커 보존: {marker_ok}/{total}")
        print(f"  색상 보존: {color_ok}/{total}")
        print(f"  완전 통과: {full_ok}/{total}")


def save_results(batch_results, rt_results, mod_results):
    data = {
        "timestamp": int(time.time()),
        "batch": [asdict(r) for r in batch_results] if batch_results else [],
        "roundtrip": [asdict(r) for r in rt_results] if rt_results else [],
        "modify": [asdict(r) for r in mod_results] if mod_results else [],
    }
    out = FILES / "test_results.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n결과 저장: {out}")


def main():
    files = collect_files()
    if not files:
        print("realworld 파일 없음")
        sys.exit(1)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    # 원본 복사
    copy_originals(files)

    batch_results: list[ConvResult] = []
    rt_results: list[ConvResult] = []
    mod_results: list[ModifyResult] = []

    if cmd in ("batch", "all"):
        print(f"\n=== Batch 변환 테스트 ({len(files)}개 파일) ===\n")
        batch_results = cmd_batch(files)

    if cmd in ("roundtrip", "all"):
        rt_results = cmd_roundtrip(files)

    if cmd in ("modify", "all"):
        print(f"\n=== 수정 테스트 ({len(files)}개) ===\n")
        mod_results = cmd_modify(files)

    print_summary(batch_results, rt_results, mod_results)
    save_results(batch_results, rt_results, mod_results)


if __name__ == "__main__":
    import os
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    main()
