#!/usr/bin/env python3
"""Capture per-page screenshots from local HTML files using Safari WebDriver.

Usage:
    python scripts/capture_html_screenshots.py
    python scripts/capture_html_screenshots.py --single f01_plain_text.html
    python scripts/capture_html_screenshots.py --compare

Prerequisites:
    sudo safaridriver --enable   (one-time)
    pip install -e ".[screenshot]"
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
HTML_DIR = FIXTURES / "html_output"
OUT_DIR = FIXTURES / "html_screenshots"
GT_DIR = FIXTURES / "screenshots"

JS_ISOLATE_PAGE = """
var pages = document.querySelectorAll('.page');
for (var i = 0; i < pages.length; i++) {
    pages[i].style.display = (i === arguments[0]) ? 'block' : 'none';
}
var target = pages[arguments[0]];
target.style.margin = '0';
target.style.boxShadow = 'none';
document.body.style.margin = '0';
document.body.style.padding = '0';
document.body.style.background = '#fff';
var cmp = document.getElementById('cmp');
if (cmp) cmp.remove();
return [target.offsetWidth, target.offsetHeight];
"""


def capture_file(driver: webdriver.Safari, html_path: Path, out_dir: Path) -> int:
    doc_name = html_path.stem
    doc_dir = out_dir / doc_name
    if doc_dir.exists():
        shutil.rmtree(doc_dir)
    doc_dir.mkdir(parents=True)

    driver.get(f"file://{html_path}")
    time.sleep(0.5)

    pages = driver.find_elements(By.CSS_SELECTOR, ".page")
    n_pages = len(pages)
    if n_pages == 0:
        print(f"  SKIP {doc_name}: no .page elements")
        return 0

    for i in range(n_pages):
        dims = driver.execute_script(JS_ISOLATE_PAGE, i)
        if dims:
            driver.set_window_size(dims[0] + 40, dims[1] + 40)
            time.sleep(0.3)

        out_path = doc_dir / f"{doc_name}_p{i + 1}.png"
        target = driver.find_elements(By.CSS_SELECTOR, ".page")[i]
        target.screenshot(str(out_path))
        print(f"  {out_path.name}")

    return n_pages


def run(html_dir: Path, out_dir: Path, single: str | None, compare: bool) -> None:
    if single:
        html_files = [html_dir / single]
        if not html_files[0].exists():
            sys.exit(f"File not found: {html_files[0]}")
    else:
        html_files = sorted(html_dir.glob("*.html"))

    if not html_files:
        sys.exit(f"No HTML files in {html_dir}")

    print(f"Capturing {len(html_files)} file(s) with Safari WebDriver")
    driver = webdriver.Safari()
    try:
        for hf in html_files:
            n = capture_file(driver, hf, out_dir)
            print(f"  → {hf.stem}: {n} page(s)")
    finally:
        driver.quit()

    if compare:
        from _screenshot_utils import compare_page_dirs, print_comparison_table

        results: dict[str, dict[str, float]] = {}
        for hf in html_files:
            doc_name = hf.stem
            actual = out_dir / doc_name
            gt = GT_DIR / doc_name
            if actual.exists() and gt.exists():
                results[doc_name] = compare_page_dirs(actual, gt)
        if results:
            print_comparison_table(results)
        else:
            print("No matching GT directories found for comparison.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture HTML screenshots with Safari")
    parser.add_argument("--html-dir", type=Path, default=HTML_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--single", type=str, default=None, help="Capture a single file")
    parser.add_argument("--compare", action="store_true", help="Compare with GT after capture")
    args = parser.parse_args()
    run(args.html_dir, args.out_dir, args.single, args.compare)


if __name__ == "__main__":
    main()
