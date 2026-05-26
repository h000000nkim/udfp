#!/usr/bin/env python3
"""
HWP 파일을 Hancom HWP Viewer로 열어 모든 페이지 스크린샷을 캡처한다.
스크롤바를 조작하여 각 페이지가 전체 높이로 보이는 위치를 찾아 크롭 저장.

사용법:
    python scripts/capture_hwp_screenshots.py                         # 전체 캡처
    python scripts/capture_hwp_screenshots.py --src tests/data/hwp    # 소스 지정
    python scripts/capture_hwp_screenshots.py --pages 1               # 1페이지만

출력 구조:
    {dst}/{문서이름}/{문서이름}_p1.png
    {dst}/{문서이름}/{문서이름}_p2.png
    ...

요구사항:
    - macOS + Hancom Office HWP Viewer 설치
    - Pillow, numpy
    - 시스템 설정 → 손쉬운 사용에서 터미널 앱 권한 필요 (다페이지 스크롤용)
"""

import argparse
import glob
import os
import subprocess
import time
import unicodedata

import numpy as np
from PIL import Image

APP_DISPLAY_NAME = "Hancom Office HWP Viewer"
APP_PROCESS_NAME = "한컴오피스 한글 Viewer"
FULL_PAGE_THRESHOLD = 1500
SCAN_STEP = 0.005
SCAN_STEPS = 201  # 0.000 to 1.000


def _list_hancom_windows():
    """Return list of (wid, name, width, height, layer) for all Hancom windows."""
    script = """
import Quartz, json
wl = Quartz.CGWindowListCopyWindowInfo(
    Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
results = []
for w in wl:
    owner = w.get('kCGWindowOwnerName', '')
    if '한컴' in owner:
        b = w.get('kCGWindowBounds', {})
        results.append({
            'id': w['kCGWindowNumber'],
            'name': w.get('kCGWindowName', ''),
            'w': b.get('Width', 0),
            'h': b.get('Height', 0),
            'layer': w.get('kCGWindowLayer', 0),
        })
print(json.dumps(results))
"""
    result = subprocess.run(
        ["python3", "-c", script], capture_output=True, text=True, timeout=5
    )
    try:
        import json
        return json.loads(result.stdout.strip())
    except Exception:
        return []


def has_warning_dialog():
    """손상 경고 다이얼로그가 떠있는지 확인 (Layer > 0인 작은 창)."""
    for w in _list_hancom_windows():
        if w["layer"] > 0 and w["w"] < 500:
            return True
    return False


def dismiss_dialogs():
    """손상 경고 다이얼로그의 '확인' 버튼 클릭으로 닫기."""
    subprocess.run(
        [
            "osascript", "-e",
            f'tell application "System Events"\n'
            f'  tell process "{APP_PROCESS_NAME}"\n'
            f'    try\n'
            f'      click button "확인" of window "한컴오피스 한글"\n'
            f'    end try\n'
            f'  end tell\n'
            f'end tell',
        ],
        capture_output=True, timeout=5,
    )
    time.sleep(1)


def get_hancom_document_window(expected_filename):
    """파일명이 포함된 문서 창의 window ID를 반환. 없으면 None."""
    for w in _list_hancom_windows():
        name_nfc = unicodedata.normalize("NFC", w["name"])
        if w["layer"] == 0 and w["w"] > 400 and expected_filename in name_nfc:
            return str(w["id"])
    return None


def set_scroll(val):
    val = max(0.0, min(1.0, val))
    subprocess.run(
        [
            "osascript", "-e",
            f'tell application "System Events" to tell process "{APP_PROCESS_NAME}"'
            f" to set value of scroll bar 1 of scroll area 1 of window 1 to {val}",
        ],
        capture_output=True, timeout=5,
    )
    time.sleep(0.2)


def close_current_doc():
    subprocess.run(
        [
            "osascript", "-e",
            f'tell application "System Events" to tell process "{APP_PROCESS_NAME}"'
            f' to keystroke "w" using command down',
        ],
        capture_output=True, timeout=5,
    )
    time.sleep(1)


def _find_page_bounds(arr):
    """Return (page_left, page_right) column indices and page brightness arrays."""
    white = (arr[:, :, 0] > 240) & (arr[:, :, 1] > 240) & (arr[:, :, 2] > 240)
    col_ratio = np.mean(white, axis=0)
    page_cols = np.where(col_ratio > 0.3)[0]
    if len(page_cols) == 0:
        return None
    pl, pr = int(page_cols[0]), int(page_cols[-1])
    lb = np.mean(arr[:, pl + 15, :3], axis=1)
    rb = np.mean(arr[:, pr - 15, :3], axis=1)
    return pl, pr, lb, rb


def _find_segments(lb, rb, min_height=30):
    """Find contiguous page segments from margin brightness."""
    is_page = (lb > 100) | (rb > 100)
    segs = []
    in_s, start = False, 0
    for i in range(len(is_page)):
        if is_page[i] and not in_s:
            in_s, start = True, i
        elif not is_page[i] and in_s:
            in_s = False
            if i - start > min_height:
                segs.append((start, i - 1))
    if in_s and len(is_page) - start > min_height:
        segs.append((start, len(is_page) - 1))
    return segs


def measure_main_page_height(wid):
    subprocess.run(
        ["screencapture", "-o", "-l", wid, "/tmp/_hwp_measure.png"], timeout=5
    )
    arr = np.array(Image.open("/tmp/_hwp_measure.png"))
    bounds = _find_page_bounds(arr)
    if bounds is None:
        return 0
    _, _, lb, rb = bounds
    segs = _find_segments(lb, rb)
    if not segs:
        return 0
    return max(e - s + 1 for s, e in segs)


def capture_and_crop_main_page(wid, dst_path):
    subprocess.run(
        ["screencapture", "-o", "-l", wid, "/tmp/_hwp_cap.png"], timeout=5
    )
    arr = np.array(Image.open("/tmp/_hwp_cap.png"))
    bounds = _find_page_bounds(arr)
    if bounds is None:
        return None
    pl, pr, lb, rb = bounds
    segs = _find_segments(lb, rb)
    if not segs:
        return None
    best = max(segs, key=lambda s: s[1] - s[0])
    t, b = best
    crop = arr[t : b + 1, pl : pr + 1]
    Image.fromarray(crop).save(dst_path)
    return crop.shape[1], crop.shape[0]


def find_page_scroll_positions(wid):
    """Scan scroll bar to find positions where each page is fully visible."""
    heights = []
    for vi in range(SCAN_STEPS):
        v = vi / (SCAN_STEPS - 1)
        set_scroll(v)
        h = measure_main_page_height(wid)
        heights.append((v, h))

    page_positions = []
    i = 0
    while i < len(heights):
        v, h = heights[i]
        if h >= FULL_PAGE_THRESHOLD:
            best_v, best_h = v, h
            while i < len(heights) and heights[i][1] >= FULL_PAGE_THRESHOLD:
                if heights[i][1] > best_h:
                    best_v, best_h = heights[i]
                i += 1
            page_positions.append(best_v)
        else:
            i += 1

    return page_positions


def capture_single_page(hwp_path, wid, folder, filename):
    """Capture only page 1 (no scroll needed)."""
    set_scroll(0.0)
    time.sleep(0.3)
    dst = os.path.join(folder, f"{filename}_p1.png")
    size = capture_and_crop_main_page(wid, dst)
    if size:
        print(f"    p1: {size[0]}x{size[1]}")
    return 1


def capture_all_pages(wid, folder, filename):
    """Scan and capture all pages via scroll bar."""
    print(f"    Scanning pages...")
    positions = find_page_scroll_positions(wid)
    total = len(positions)
    print(f"    Found {total} pages")

    for p, sv in enumerate(positions):
        dst = os.path.join(folder, f"{filename}_p{p + 1}.png")
        set_scroll(sv)
        time.sleep(0.3)
        size = capture_and_crop_main_page(wid, dst)
        if size:
            print(f"    p{p + 1}: {size[0]}x{size[1]} (scroll={sv:.3f})")

    return total


def capture_files(src_dir: str, dst_dir: str, max_pages: int = 0):
    hwp_files = sorted(glob.glob(os.path.join(src_dir, "*.hwp")))
    print(f"Found {len(hwp_files)} HWP files in {src_dir}")

    for hwp_path in hwp_files:
        filename = os.path.splitext(os.path.basename(hwp_path))[0]
        folder = os.path.join(dst_dir, filename)
        os.makedirs(folder, exist_ok=True)

        p1_file = os.path.join(folder, f"{filename}_p1.png")
        if os.path.exists(p1_file):
            print(f"  SKIP (exists): {filename}")
            continue

        print(f"  Opening: {filename}")
        subprocess.run(
            ["open", "-a", APP_DISPLAY_NAME, os.path.abspath(hwp_path)], timeout=10
        )
        time.sleep(4)

        # 손상 경고 다이얼로그 감지 → 닫고 스킵
        if has_warning_dialog():
            print(f"  SKIP (corrupted/warning dialog): {filename}")
            dismiss_dialogs()
            continue

        # 파일명이 포함된 문서 창 찾기
        hwp_basename = os.path.basename(hwp_path)
        wid = get_hancom_document_window(hwp_basename)
        if wid is None:
            print(f"  SKIP (document window not found): {filename}")
            close_current_doc()
            continue

        if max_pages == 1:
            capture_single_page(hwp_path, wid, folder, filename)
        else:
            capture_all_pages(wid, folder, filename)

        close_current_doc()

    subprocess.run(
        ["osascript", "-e", f'tell application "{APP_DISPLAY_NAME}" to quit'],
        capture_output=True, timeout=5,
    )
    print("\nDone!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HWP → 스크린샷 캡처 (전 페이지)")
    parser.add_argument("--src", default="tests/fixtures/hwp", help="HWP 파일 디렉토리")
    parser.add_argument("--dst", default="tests/fixtures/screenshots", help="출력 디렉토리")
    parser.add_argument(
        "--pages", type=int, default=0,
        help="캡처할 최대 페이지 수 (0=전체, 1=1페이지만)",
    )
    args = parser.parse_args()
    capture_files(args.src, args.dst, args.pages)
