"""UdfDocument → HTML 렌더러.

PDF/HWP/DOCX 파서 출력에 모두 적용 가능한 범용 렌더러.
블록을 순서대로 렌더링하며 verbatim bbox 좌표에 의존하지 않음.
"""

from __future__ import annotations

from typing import Any

from udf.core.schema import (
    ChartBlock,
    DrawingBlock,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    ParagraphBlock,
    TableBlock,
    TextArtBlock,
    TextInline,
    UdfDocument,
)

# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def render_html(doc: UdfDocument, *, title: str = "") -> str:
    """Render a UdfDocument to a complete standalone HTML document.

    Parameters
    ----------
    doc : UdfDocument
        The document model to render.
    title : str, optional
        Document title for the HTML header. If empty, uses metadata title.

    Returns
    -------
    str
        Complete HTML document string with embedded CSS styling.
    """
    doc_title = title or (doc.metadata.title if doc.metadata and doc.metadata.title else "Document")

    meta_parts: list[str] = []
    if doc.metadata:
        if doc.metadata.author:
            meta_parts.append(f"Author: {_esc(doc.metadata.author)}")
        if doc.metadata.created_at:
            meta_parts.append(f"Created: {_esc(doc.metadata.created_at)}")
    meta_html = (
        f'<p class="meta">{" &nbsp;|&nbsp; ".join(meta_parts)}</p>'
        if meta_parts else ""
    )

    # 첫 블록이 제목과 같은 헤딩이면 doc-header와 중복되므로 건너뜀
    title_norm = doc_title.strip().lower()
    skip_first_heading = True  # 첫 번째 일치 헤딩 한 번만 스킵

    block_parts: list[str] = []
    list_acc: list[str] = []
    list_ordered: bool = False

    def flush_list() -> None:
        """Flush accumulated list items into a completed HTML list element."""
        if not list_acc:
            return
        tag = "ol" if list_ordered else "ul"
        block_parts.append(f"<{tag}>\n" + "\n".join(list_acc) + f"\n</{tag}>")
        list_acc.clear()

    for block in doc.blocks:
        if isinstance(block, ListBlock):
            if list_acc and block.ordered != list_ordered:
                flush_list()
            list_ordered = block.ordered
            for item in block.items:
                text = _render_inlines(item.inlines)
                sub_html = ""
                if item.children:
                    sub_items = "\n".join(f"<li>{_render_inlines(c.inlines)}</li>" for c in item.children)
                    sub_html = f"\n<ul>\n{sub_items}\n</ul>"
                list_acc.append(f"<li>{text}{sub_html}</li>")
            continue

        flush_list()

        # 제목 블록이 doc-header h1과 동일한 텍스트면 처음 한 번 스킵
        if skip_first_heading and isinstance(block, HeadingBlock):
            block_text_norm = block.text.split("\n")[0].strip().lower()
            if block_text_norm == title_norm:
                skip_first_heading = False
                continue

        html = _render_block(block)
        if html:
            block_parts.append(html)

    flush_list()

    body = "\n".join(block_parts)

    return _TEMPLATE.format(
        title=_esc(doc_title),
        meta=meta_html,
        body=body,
        source_format=(doc.source_format or "").upper(),
        parser_version=(doc.conversion_trace.parser_version if doc.conversion_trace else ""),
        total_blocks=len(doc.blocks),
    )


# ---------------------------------------------------------------------------
# 블록 렌더러
# ---------------------------------------------------------------------------


def _render_block(block: Any) -> str | None:
    """Render a single block to an HTML fragment."""
    if isinstance(block, HeadingBlock):
        lvl = max(1, min(6, block.level))
        text = _esc(block.text)
        return f"<h{lvl}>{text}</h{lvl}>"

    if isinstance(block, ParagraphBlock):
        text = _render_inlines(block.inlines)
        if not text.strip():
            return None
        return f"<p>{text}</p>"

    if isinstance(block, TableBlock):
        return _render_table(block)

    if isinstance(block, ImageBlock):
        if block.src and (block.src.startswith("data:") or block.src.startswith("http")):
            alt = _esc(block.alt or "")
            style_parts = []
            if block.width:
                style_parts.append(f"width:{block.width}")
            if block.height:
                style_parts.append(f"height:{block.height}")
            style_parts.append("max-width:100%")
            style = ";".join(style_parts)
            return f'<figure><img src="{block.src}" alt="{alt}" style="{style}"><figcaption>{alt}</figcaption></figure>'
        return None  # embedded: src (bytes not injected) → skip

    if isinstance(block, DrawingBlock):
        label = block.shape_type or "vector graphic"
        return f'<div class="drawing-placeholder">[ {_esc(label)} ]</div>'

    if isinstance(block, ChartBlock):
        return '<div class="chart-placeholder">[ chart: not implemented ]</div>'

    if isinstance(block, TextArtBlock):
        text = _esc(block.text) if block.text else "text art"
        return f'<div class="textart-placeholder">[ {text} ]</div>'

    return None


def _render_table(block: TableBlock) -> str:
    """Render a TableBlock to an HTML table element."""
    if not block.rows:
        return ""
    lines = ["<table>"]
    for ri, row in enumerate(block.rows):
        tag = "th" if ri == 0 else "td"
        cells_html = []
        row_text_total = ""
        for cell in row.cells:
            attrs = ""
            if cell.row_span > 1:
                attrs += f' rowspan="{cell.row_span}"'
            if cell.col_span > 1:
                attrs += f' colspan="{cell.col_span}"'
            cell_text = " ".join(
                _render_inlines(b.inlines)
                for b in cell.content
                if isinstance(b, ParagraphBlock)
            )
            row_text_total += cell_text.strip()
            cells_html.append(f"<{tag}{attrs}>{cell_text}</{tag}>")
        if not row_text_total:  # 모든 셀이 비어있는 행 건너뜀
            continue
        lines.append("<tr>")
        lines.extend(cells_html)
        lines.append("</tr>")
    lines.append("</table>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 인라인 렌더러
# ---------------------------------------------------------------------------


def _render_inlines(inlines: list[Any]) -> str:
    """Render a list of inline elements to an HTML string."""
    parts: list[str] = []
    for il in inlines:
        if isinstance(il, TextInline):
            text = _esc(il.text)
            if not text:
                continue
            if il.bold:
                text = f"<strong>{text}</strong>"
            if il.italic:
                text = f"<em>{text}</em>"
            if il.underline:
                text = f"<u>{text}</u>"
            if il.strikethrough:
                text = f"<del>{text}</del>"
            parts.append(text)
        else:
            text = getattr(il, "text", "")
            if text:
                parts.append(_esc(text))
    return "".join(parts)


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# HTML 템플릿
# ---------------------------------------------------------------------------

_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}

  body {{
    margin: 0;
    padding: 32px 16px 64px;
    background: #f0f0f0;
    font-family: 'Malgun Gothic', 'Noto Sans KR', 'Apple SD Gothic Neo',
                 Georgia, serif;
    color: #1a1a1a;
    line-height: 1.7;
  }}

  article {{
    max-width: 820px;
    margin: 0 auto;
    background: #fff;
    padding: 56px 72px;
    box-shadow: 0 4px 24px rgba(0,0,0,.10);
    border-radius: 6px;
  }}

  .doc-header {{
    border-bottom: 3px solid #222;
    margin-bottom: 36px;
    padding-bottom: 16px;
  }}

  .doc-header h1 {{
    margin: 0 0 8px;
    font-size: 2rem;
    letter-spacing: -0.5px;
  }}

  .meta {{
    font-size: 0.82em;
    color: #666;
    margin: 0;
  }}

  .doc-footer {{
    margin-top: 48px;
    padding-top: 12px;
    border-top: 1px solid #ddd;
    font-size: 0.78em;
    color: #999;
  }}

  h1 {{ font-size: 1.9em; margin: 1.6em 0 0.4em; }}
  h2 {{ font-size: 1.5em; margin: 1.4em 0 0.35em; }}
  h3 {{ font-size: 1.25em; margin: 1.2em 0 0.3em; }}
  h4, h5, h6 {{ font-size: 1.08em; margin: 1em 0 0.25em; }}

  p {{ margin: 0.45em 0; }}

  ul, ol {{ padding-left: 1.6em; margin: 0.6em 0; }}
  li {{ margin: 0.25em 0; }}

  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 1.2em 0;
    font-size: 0.92em;
  }}

  th, td {{
    border: 1px solid #bbb;
    padding: 7px 11px;
    text-align: left;
    vertical-align: top;
  }}

  th {{
    background: #f5f5f5;
    font-weight: 600;
  }}

  tr:nth-child(even) td {{
    background: #fafafa;
  }}

  figure {{
    margin: 1.4em 0;
    text-align: center;
  }}

  figure img {{
    max-width: 100%;
    height: auto;
    border-radius: 3px;
    box-shadow: 0 2px 8px rgba(0,0,0,.12);
  }}

  figcaption {{
    margin-top: 6px;
    font-size: 0.82em;
    color: #666;
  }}

  .drawing-placeholder {{
    background: #f8f8f8;
    border: 1px dashed #bbb;
    border-radius: 4px;
    padding: 24px;
    text-align: center;
    color: #888;
    font-size: 0.88em;
    margin: 1em 0;
  }}

  strong {{ font-weight: 700; }}
  em     {{ font-style: italic; }}
</style>
</head>
<body>
<article>
  <div class="doc-header">
    <h1>{title}</h1>
    {meta}
  </div>

  {body}

  <div class="doc-footer">
    Rendered by UDF &nbsp;|&nbsp;
    Source: {source_format} &nbsp;|&nbsp;
    Parser: {parser_version} &nbsp;|&nbsp;
    Blocks: {total_blocks}
  </div>
</article>
</body>
</html>
"""
