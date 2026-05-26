#!/usr/bin/env python3
"""
VS Code 익스텐션 + macOS screencapture를 이용한 문서 스크린샷 배치 캡처.

출력 구조 (output/files/와 1:1 대응):
    output/screenshots/originals/{hwp,hwpx,docx}/
    output/screenshots/converted/{hwp2docx,hwp2hwp,...}/
    output/screenshots/modified/{hwp,docx,hwpx}/

사용법:
    python sandbox/capture_screenshots.py converted/md2hwp  # 특정 서브디렉토리만
    python sandbox/capture_screenshots.py originals          # originals 전체
    python sandbox/capture_screenshots.py converted          # converted 전체
    python sandbox/capture_screenshots.py modified           # modified 전체
    python sandbox/capture_screenshots.py all                # 전체 캡처
    python sandbox/capture_screenshots.py verify             # files↔screenshots 대조
    python sandbox/capture_screenshots.py file <path> <category/sub>

옵션:
    --force    이미 존재하는 스크린샷도 재캡처

필요 익스텐션:
    - cweijan.vscode-office (DOCX 뷰어)
    - edwardkim.rhwp-vscode (HWP 뷰어)

안전장치:
    - .capture_lock 파일로 동시 실행 방지
    - 탭 닫기 전 front window 제목이 방금 연 파일명과 일치하는지 확인
"""
from __future__ import annotations

import atexit
import os
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

FILES = Path("output/files")
SCREENSHOTS = Path("output/screenshots")
LOCK = Path(".capture_lock")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def acquire_lock() -> bool:
    """Lock 획득. 다른 캡처가 진행 중이면 False."""
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip())
            os.kill(pid, 0)  # 프로세스 생존 확인
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # stale lock
    LOCK.write_text(str(os.getpid()))
    atexit.register(release_lock)
    return True


def release_lock() -> None:
    LOCK.unlink(missing_ok=True)


def get_vscode_wid() -> int | None:
    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGNullWindowID,
            kCGWindowListOptionOnScreenOnly,
        )

        windows = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID
        )
        for w in windows:
            owner = w.get("kCGWindowOwnerName", "")
            name = w.get("kCGWindowName", "")
            if "Code" in owner and name:
                return w.get("kCGWindowNumber", 0)
    except ImportError:
        pass
    return None


def capture_file(filepath: Path, dst_png: Path, wait: float = 2.5, force: bool = False) -> str:
    if dst_png.exists() and not force:
        return "SKIP"

    dst_png.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["code", str(filepath)], capture_output=True)
    time.sleep(wait)

    wid = get_vscode_wid()
    if not wid:
        return "NO_WID"

    subprocess.run(
        ["screencapture", "-l", str(wid), str(dst_png)],
        capture_output=True,
        timeout=10,
    )

    # 탭 닫기 — 방금 연 파일명이 front window 제목에 포함된 경우에만
    result = subprocess.run(
        ["osascript", "-e",
         'tell application "System Events"\n'
         '  tell process "Code"\n'
         '    return name of front window\n'
         '  end tell\n'
         'end tell'],
        capture_output=True, text=True,
    )
    win_title = nfc(result.stdout.strip())
    opened_name = nfc(filepath.name)

    is_our_file = opened_name in win_title
    if is_our_file:
        subprocess.run(
            ["osascript", "-e",
             'tell application "Visual Studio Code" to activate\n'
             'delay 0.3\n'
             'tell application "System Events" to key code 13 using command down'],
            capture_output=True,
        )
        time.sleep(0.5)
    else:
        print(f"    SKIP close: title={win_title[:40]}... != {opened_name[:30]}")

    if dst_png.exists() and dst_png.stat().st_size > 10000:
        return "OK"
    return "FAIL"


def collect_from_dir(category: str, sub_filter: str | None = None) -> list[tuple[Path, Path]]:
    """Collect (source_file, screenshot_dst) pairs from a files/ subdirectory.

    sub_filter: if set, only collect from this specific subdirectory name.
    """
    pairs = []
    cat_dir = FILES / category
    if not cat_dir.exists():
        return pairs

    for sub in sorted(cat_dir.iterdir()):
        if not sub.is_dir():
            continue
        if sub_filter and sub.name != sub_filter:
            continue
        ss_sub = SCREENSHOTS / category / sub.name
        for f in sorted(sub.iterdir()):
            if f.is_file() and f.suffix != ".json":
                dst = ss_sub / (f.stem + ".png")
                pairs.append((f, dst))
    return pairs


def run_batch(pairs: list[tuple[Path, Path]], force: bool = False) -> None:
    if not acquire_lock():
        print("ERROR: 다른 캡처가 진행 중 (.capture_lock). 완료 후 재시도.")
        sys.exit(1)

    todo = pairs if force else [(s, d) for s, d in pairs if not d.exists()]
    print(f"Total: {len(pairs)}, To capture: {len(todo)}")

    captured = 0
    failed = 0
    for i, (src, dst) in enumerate(todo):
        result = capture_file(src, dst, force=force)
        if result == "OK":
            captured += 1
        elif result == "SKIP":
            pass
        else:
            failed += 1
            print(f"  {result}: {nfc(src.name)[:50]}")

        if (i + 1) % 10 == 0:
            print(f"  Progress: {i+1}/{len(todo)} (captured={captured}, failed={failed})")

    release_lock()
    print(f"\nCaptured: {captured}, Failed: {failed}")


def cmd_verify() -> None:
    print("=== files ↔ screenshots 대조 ===\n")
    all_ok = True
    for category in ["originals", "converted", "modified"]:
        cat_dir = FILES / category
        if not cat_dir.exists():
            continue
        for sub in sorted(cat_dir.iterdir()):
            if not sub.is_dir():
                continue
            ss_sub = SCREENSHOTS / category / sub.name
            file_stems = {nfc(f.stem) for f in sub.iterdir() if f.is_file() and f.suffix != ".json"}
            ss_stems = {nfc(f.stem) for f in ss_sub.iterdir() if f.is_file()} if ss_sub.exists() else set()

            ok = file_stems == ss_stems
            status = "✓" if ok else "✗"
            if not ok:
                all_ok = False
            print(f"  {status} {category}/{sub.name}: files={len(file_stems)} ss={len(ss_stems)}")

            if not ok:
                missing_ss = file_stems - ss_stems
                extra_ss = ss_stems - file_stems
                if missing_ss:
                    print(f"      스크린샷 없음: {sorted(list(missing_ss))[:3]}")
                if extra_ss:
                    print(f"      파일 없음: {sorted(list(extra_ss))[:3]}")

    print(f"\n{'전부 일치 ✓' if all_ok else '불일치 있음 ✗'}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--force"]
    cmd = args[0] if args else ""

    if "/" in cmd:
        parts = cmd.split("/", 1)
        category, sub = parts[0], parts[1]
        print(f"=== {category}/{sub} ===")
        run_batch(collect_from_dir(category, sub_filter=sub), force=force)
    elif cmd == "originals":
        run_batch(collect_from_dir("originals"), force=force)
    elif cmd == "converted":
        run_batch(collect_from_dir("converted"), force=force)
    elif cmd == "modified":
        run_batch(collect_from_dir("modified"), force=force)
    elif cmd == "all":
        for cat in ["originals", "converted", "modified"]:
            print(f"\n=== {cat} ===")
            run_batch(collect_from_dir(cat), force=force)
    elif cmd == "verify":
        cmd_verify()
    elif cmd == "file":
        if len(args) < 3:
            print("Usage: capture_screenshots.py file <path> <category/sub>")
            sys.exit(1)
        filepath = Path(args[1])
        cat_sub = args[2]
        dst = SCREENSHOTS / cat_sub / (filepath.stem + ".png")
        if not acquire_lock():
            print("ERROR: 다른 캡처가 진행 중.")
            sys.exit(1)
        result = capture_file(filepath, dst, force=True)
        release_lock()
        print(f"{result}: {dst}")
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
