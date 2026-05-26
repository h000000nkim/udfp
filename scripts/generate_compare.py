#!/usr/bin/env python3
"""
HWP 파일을 UDFP로 파싱 → HTML 렌더링한 뒤,
스크린샷(Ground Truth)과 나란히 비교하는 compare.html을 생성한다.

사용법:
    python scripts/generate_compare.py
    python scripts/generate_compare.py --hwp-dir tests/fixtures/hwp
    python scripts/generate_compare.py --out tests/fixtures/compare.html
"""

from __future__ import annotations

import argparse
import glob
import html
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from udf.parsers.hwp.parse import parse_hwp
from udf.renderers.md.render import render_html


def _natural_sort_key(s: str):
    import re
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", s)]


def generate(
    hwp_dir: str,
    screenshots_dir: str,
    html_out_dir: str,
    compare_out: str,
) -> None:
    os.makedirs(html_out_dir, exist_ok=True)

    hwp_files = sorted(glob.glob(os.path.join(hwp_dir, "*.hwp")), key=_natural_sort_key)
    if not hwp_files:
        print(f"No HWP files found in {hwp_dir}")
        return

    entries: list[dict] = []

    for hwp_path in hwp_files:
        name = os.path.splitext(os.path.basename(hwp_path))[0]
        html_path = os.path.join(html_out_dir, f"{name}.html")
        screenshot_folder = os.path.join(screenshots_dir, name)

        print(f"  Rendering: {name}")
        try:
            doc = parse_hwp(hwp_path)
            html_content = render_html(doc, embed_images=True)
            # Strip body/page chrome so the page fills the iframe edge-to-edge
            override = (
                "<style id='cmp'>"
                "body{margin:0!important;padding:0!important;background:#fff!important}"
                ".page{margin:0 0 4px 0!important;box-shadow:none!important;"
                "transform-origin:top left!important;"
                "border-bottom:2px solid red!important}"
                "</style>"
                "<script>"
                "window.addEventListener('load',function(){"
                "document.querySelectorAll('.page').forEach(function(p){"
                "var s=p.parentElement.clientWidth/p.offsetWidth;"
                "if(s<1){p.style.transform='scale('+s+')';p.style.marginBottom='-'+(p.offsetHeight*(1-s))+'px'}"
                "})});"
                "</script>"
            )
            html_content = html_content.replace("</head>", override + "</head>", 1)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            print(f"    FAIL: {e}")
            continue

        screenshots = []
        if os.path.isdir(screenshot_folder):
            screenshots = sorted(
                glob.glob(os.path.join(screenshot_folder, "*.png")),
                key=_natural_sort_key,
            )

        entries.append({
            "name": name,
            "html_rel": os.path.relpath(html_path, os.path.dirname(compare_out)),
            "screenshots_rel": [
                os.path.relpath(s, os.path.dirname(compare_out)) for s in screenshots
            ],
            "page_count": len(screenshots) if screenshots else "?",
        })

    _write_compare_html(entries, compare_out)
    print(f"\nDone: {compare_out} ({len(entries)} documents)")


def _write_compare_html(entries: list[dict], out_path: str) -> None:
    nav_links = []
    sections = []

    for e in entries:
        eid = html.escape(e["name"])
        nav_links.append(f'<a href="#{eid}">{eid}</a>')

        screenshot_imgs = ""
        if e["screenshots_rel"]:
            imgs = "\n".join(
                f'<img src="{html.escape(s)}">'
                for s in e["screenshots_rel"]
            )
            screenshot_imgs = imgs
        else:
            screenshot_imgs = '<p style="text-align:center;color:#999">No screenshots</p>'

        sections.append(f"""\
<div class="doc-section" id="{eid}">
<div class="doc-header">{eid} ({e["page_count"]} pages)</div>
<div class="compare-row">
<div class="col"><div class="col-header">HWP Viewer (Ground Truth)</div>
{screenshot_imgs}
</div>
<div class="col"><div class="col-header">UDFP render_html()</div>
<div class="iframe-wrap">
<iframe src="{html.escape(e["html_rel"])}" scrolling="no"></iframe>
</div>
</div>
</div></div>""")

    # 595pt = ~793px at 96dpi. iframe is this native width, then scaled down to fit column.
    page = f"""\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>HWP Screenshot vs UDFP HTML Comparison</title>
<style>
body {{ font-family: system-ui; margin: 20px; background: #f5f5f5; }}
h1 {{ text-align: center; }}
.doc-section {{ margin: 30px 0; border: 1px solid #ccc; background: white; border-radius: 8px; overflow: hidden; }}
.doc-header {{ background: #333; color: white; padding: 10px 20px; font-size: 18px; font-weight: bold; }}
.compare-row {{ display: grid; grid-template-columns: 1fr 1fr; padding: 10px; }}
.col-header {{ text-align: center; font-weight: bold; padding: 5px; background: #eee; margin-bottom: 5px; }}
.col img {{ width: 100%; display: block; border: 2px solid #f00; box-sizing: border-box; }}
.iframe-wrap {{ overflow: hidden; border: 2px solid #00f; box-sizing: border-box; }}
.iframe-wrap iframe {{ display: block; border: none; width: 100%; }}
nav {{ position: sticky; top: 0; background: white; z-index: 100; padding: 10px; border-bottom: 2px solid #333; display: flex; flex-wrap: wrap; gap: 5px; }}
nav a {{ padding: 4px 8px; background: #eee; border-radius: 4px; text-decoration: none; color: #333; font-size: 12px; }}
nav a:hover {{ background: #ddd; }}
</style></head><body>
<script>
function fitAll() {{
  document.querySelectorAll('.compare-row').forEach(row => {{
    const cols = row.querySelectorAll('.col');
    if (cols.length < 2) return;
    const iframeWrap = cols[1].querySelector('.iframe-wrap');
    const iframe = iframeWrap && iframeWrap.querySelector('iframe');
    if (!iframe) return;

    // Match height to left column images
    const leftCol = cols[0];
    const imgs = leftCol.querySelectorAll('img');
    let leftH = 0;
    imgs.forEach(img => {{ leftH += img.offsetHeight; }});
    if (leftH === 0) leftH = leftCol.clientWidth * 1.414;

    iframe.style.height = leftH + 'px';
    iframeWrap.style.height = leftH + 'px';
  }});
}}
window.addEventListener('load', fitAll);
window.addEventListener('resize', fitAll);
</script>
<h1>HWP Screenshot vs UDFP HTML Comparison</h1>
<nav>
{chr(10).join(nav_links)}
</nav>
{chr(10).join(sections)}
</body></html>"""

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HWP → UDFP HTML 렌더링 + 비교 페이지 생성")
    parser.add_argument("--hwp-dir", default="tests/fixtures/hwp", help="HWP 파일 디렉토리")
    parser.add_argument("--screenshots-dir", default="tests/fixtures/screenshots", help="스크린샷 디렉토리")
    parser.add_argument("--html-out-dir", default="tests/fixtures/html_output", help="HTML 출력 디렉토리")
    parser.add_argument("--out", default="tests/fixtures/compare.html", help="비교 HTML 출력 경로")
    args = parser.parse_args()

    generate(args.hwp_dir, args.screenshots_dir, args.html_out_dir, args.out)
