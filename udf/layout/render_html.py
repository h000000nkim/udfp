"""Render layout results to absolute-positioned HTML.

Each line and block is placed at exact coordinates computed by the
layout engine, bypassing browser layout entirely.
"""

from __future__ import annotations

from udf.core.schema import UdfDocument
from udf.layout import LayoutPage, LayoutResult
from udf.layout.page_break import split_into_pages
from udf.layout.style_resolve import extract_page_dims
from udf.renderers.html import render_html as render_html_dom


def layout_to_html(result: LayoutResult, title: str = "Document", lang: str = "ko") -> str:
    parts: list[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; }}
body {{
  margin: 0;
  padding: 32px 16px 64px;
  background: #e0e0e0;
  font-family: 'Noto Sans KR', 'Apple SD Gothic Neo', sans-serif;
  color: #1a1a1a;
}}
.page {{
  background: #fff;
  margin: 0 auto 24px;
  box-shadow: 0 2px 12px rgba(0,0,0,.15);
  position: relative;
  overflow: hidden;
}}
.layout-block {{
  position: absolute;
}}
.layout-line {{
  position: absolute;
  white-space: pre;
}}
</style>
</head>
<body>
""")

    for page in result.pages:
        pw = page.width * 1.333
        ph = page.height * 1.333
        parts.append(
            f'<section class="page" style="width:{pw:.2f}px;height:{ph:.2f}px">'
        )

        for block in page.blocks:
            if block.lines:
                y_offset = 0.0
                for line in block.lines:
                    lx = (block.x + line.x_offset) * 1.333
                    ly = (block.y + y_offset) * 1.333
                    parts.append(
                        f'<div class="layout-line" style="left:{lx:.2f}px;top:{ly:.2f}px">'
                        f'{_esc(line.text)}</div>'
                    )
                    y_offset += line.height
            else:
                bx = block.x * 1.333
                by = block.y * 1.333
                bw = block.width * 1.333
                bh = block.height * 1.333
                parts.append(
                    f'<div class="layout-block" data-type="{block.block_type}" '
                    f'style="left:{bx:.2f}px;top:{by:.2f}px;width:{bw:.2f}px;height:{bh:.2f}px">'
                    f'</div>'
                )

        parts.append("</section>")

    parts.append("</body>\n</html>")
    return "\n".join(parts)


def render_html_precise(doc: UdfDocument, **kwargs) -> str:
    dims = extract_page_dims(doc)
    pages = split_into_pages(
        doc.document.blocks if hasattr(doc, "document") else doc.blocks,
        dims.width, dims.height,
        dims.margin_top, dims.margin_bottom,
        dims.margin_left, dims.margin_right,
    )
    result = LayoutResult(
        pages=pages,
        total_blocks=sum(len(p.blocks) for p in pages),
        total_lines=sum(sum(len(b.lines) for b in p.blocks) for p in pages),
    )
    title = kwargs.get("title", "Document")
    return layout_to_html(result, title=title)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
