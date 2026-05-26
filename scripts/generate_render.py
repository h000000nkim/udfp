#!/usr/bin/env python3
"""
HWP 파일을 UDFP로 파싱 → HTML 렌더링 결과만 모아 render.html을 생성한다.
compare.html과 달리 GT 스크린샷 없이 렌더링 결과만 단독 표시.

사용법:
    python scripts/generate_render.py
    python scripts/generate_render.py --hwp-dir tests/fixtures/hwp
    python scripts/generate_render.py --out tests/fixtures/render.html
"""

from __future__ import annotations

import argparse
import glob
import html
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from udf.parsers.hwp.parse import parse_hwp
from udf.renderers.md.render import render_html


def _natural_sort_key(s: str):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", s)]


def generate(hwp_dir: str, html_out_dir: str, render_out: str) -> None:
    os.makedirs(html_out_dir, exist_ok=True)

    hwp_files = sorted(glob.glob(os.path.join(hwp_dir, "*.hwp")), key=_natural_sort_key)
    if not hwp_files:
        print(f"No HWP files found in {hwp_dir}")
        return

    entries: list[dict] = []

    for hwp_path in hwp_files:
        name = os.path.splitext(os.path.basename(hwp_path))[0]
        html_path = os.path.join(html_out_dir, f"{name}.html")

        print(f"  Rendering: {name}")
        try:
            doc = parse_hwp(hwp_path)
            html_content = render_html(doc, embed_images=True)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            print(f"    FAIL: {e}")
            continue

        entries.append({
            "name": name,
            "html_rel": os.path.relpath(html_path, os.path.dirname(render_out)),
        })

    _write_render_html(entries, render_out)
    print(f"\nDone: {render_out} ({len(entries)} documents)")


def _write_render_html(entries: list[dict], out_path: str) -> None:
    nav_links = []
    sections = []

    for e in entries:
        eid = html.escape(e["name"])
        nav_links.append(f'<a href="#{eid}">{eid}</a>')

        sections.append(f"""\
<div class="doc-section" id="{eid}">
<div class="doc-header">{eid}</div>
<div class="render-body">
<iframe src="{html.escape(e["html_rel"])}"></iframe>
</div>
</div>""")

    page = f"""\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>UDFP HTML Rendering</title>
<style>
body {{ font-family: system-ui; margin: 20px; background: #f5f5f5; }}
h1 {{ text-align: center; }}
.doc-section {{ margin: 30px auto; max-width: 900px; border: 1px solid #ccc; background: white; border-radius: 8px; overflow: hidden; }}
.doc-header {{ background: #333; color: white; padding: 10px 20px; font-size: 18px; font-weight: bold; }}
.render-body {{ padding: 10px; }}
.render-body iframe {{ display: block; border: none; width: 100%; min-height: 800px; }}
nav {{ position: sticky; top: 0; background: white; z-index: 100; padding: 10px; border-bottom: 2px solid #333; display: flex; flex-wrap: wrap; gap: 5px; }}
nav a {{ padding: 4px 8px; background: #eee; border-radius: 4px; text-decoration: none; color: #333; font-size: 12px; }}
nav a:hover {{ background: #ddd; }}
</style></head><body>
<script>
function autoResize() {{
  document.querySelectorAll('.render-body iframe').forEach(iframe => {{
    try {{
      const doc = iframe.contentDocument || iframe.contentWindow.document;
      const pages = doc.querySelectorAll('.page');
      if (pages.length > 0) {{
        let h = 0;
        pages.forEach(p => {{ h += p.offsetHeight + 10; }});
        iframe.style.height = (h + 40) + 'px';
      }} else {{
        iframe.style.height = doc.body.scrollHeight + 'px';
      }}
    }} catch(e) {{}}
  }});
}}
window.addEventListener('load', function() {{
  setTimeout(autoResize, 500);
  setTimeout(autoResize, 2000);
}});
window.addEventListener('resize', autoResize);
</script>
<h1>UDFP HTML Rendering</h1>
<nav>
{chr(10).join(nav_links)}
</nav>
{chr(10).join(sections)}
</body></html>"""

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HWP → UDFP HTML 렌더링 단독 페이지 생성")
    parser.add_argument("--hwp-dir", default="tests/fixtures/hwp", help="HWP 파일 디렉토리")
    parser.add_argument("--html-out-dir", default="tests/fixtures/html_output", help="HTML 출력 디렉토리")
    parser.add_argument("--out", default="tests/fixtures/render.html", help="렌더 HTML 출력 경로")
    args = parser.parse_args()

    generate(args.hwp_dir, args.html_out_dir, args.out)
