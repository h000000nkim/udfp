#!/usr/bin/env python3
"""Capture GT screenshots from Hancom Docs mobile web using Playwright.

Usage:
    python scripts/capture_hancom_screenshots.py --login
    python scripts/capture_hancom_screenshots.py --url "https://docs.hancom.com/..."

Prerequisites:
    pip install -e ".[screenshot-gt]"
    playwright install webkit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

AUTH_STATE = Path(__file__).resolve().parent / ".hancom_auth.json"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
OUT_DIR = FIXTURES / "hancom_screenshots"


def do_login() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.webkit.launch(headless=False)
        context = browser.new_context(**pw.devices["iPhone 14 Pro Max"])
        page = context.new_page()
        page.goto("https://www.hancom.com/login")
        print("Log in manually in the browser. Press Enter here when done.")
        input()
        context.storage_state(path=str(AUTH_STATE))
        print(f"Auth saved to {AUTH_STATE}")
        browser.close()


def capture_url(url: str, out_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    if not AUTH_STATE.exists():
        sys.exit("No auth state. Run with --login first.")

    with sync_playwright() as pw:
        browser = pw.webkit.launch(headless=False)
        context = browser.new_context(
            **pw.devices["iPhone 14 Pro Max"],
            storage_state=str(AUTH_STATE),
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle")

        if "login" in page.url.lower():
            browser.close()
            sys.exit("Session expired. Run with --login to re-authenticate.")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out_path), full_page=True)
        print(f"Saved: {out_path}")
        # TODO: page navigation/scroll for multi-page documents
        # TODO: DOM selector calibration for Hancom Docs viewer
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture Hancom Docs screenshots")
    parser.add_argument("--login", action="store_true", help="Open browser for manual login")
    parser.add_argument("--url", type=str, help="Hancom Docs document URL to capture")
    parser.add_argument("--out", type=Path, default=None, help="Output PNG path")
    args = parser.parse_args()

    if args.login:
        do_login()
    elif args.url:
        out = args.out or OUT_DIR / "capture.png"
        capture_url(args.url, out)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
