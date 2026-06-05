"""Render layout results to PDF using ReportLab."""

from __future__ import annotations

from pathlib import Path
from typing import IO

from udf.core.schema import UdfDocument
from udf.layout import LayoutResult
from udf.layout.page_break import split_into_pages
from udf.layout.style_resolve import extract_page_dims
from udf.layout.font_metrics import find_font_path


def _register_korean_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    registered = set()
    fonts_to_try = [
        ("NotoSansKR", "Noto Sans KR"),
        ("NotoSerifKR", "Noto Serif KR"),
        ("AppleSDGothicNeo", "Apple SD Gothic Neo"),
        ("MalgunGothic", "맑은 고딕"),
        ("NanumGothic", "나눔고딕"),
    ]
    for reg_name, display_name in fonts_to_try:
        path = find_font_path(display_name)
        if path and path not in registered:
            try:
                pdfmetrics.registerFont(TTFont(reg_name, path))
                registered.add(path)
            except Exception:
                pass
    return bool(registered)


def layout_to_pdf(result: LayoutResult, output: str | Path | IO) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as rl_canvas

    if isinstance(output, (str, Path)):
        c = rl_canvas.Canvas(str(output))
    else:
        c = rl_canvas.Canvas(output)

    _register_korean_fonts()

    for page in result.pages:
        pw = page.width
        ph = page.height
        c.setPageSize((pw, ph))

        for block in page.blocks:
            if block.lines:
                y_offset = 0.0
                for line in block.lines:
                    x = block.x + line.x_offset
                    y = ph - (block.y + y_offset + line.baseline)

                    font_name = "Helvetica"
                    font_size = line.baseline if line.baseline > 0 else 10.0
                    try:
                        c.setFont("NotoSansKR", font_size)
                        font_name = "NotoSansKR"
                    except Exception:
                        try:
                            c.setFont("AppleSDGothicNeo", font_size)
                            font_name = "AppleSDGothicNeo"
                        except Exception:
                            c.setFont("Helvetica", font_size)

                    c.drawString(x, y, line.text)
                    y_offset += line.height

        c.showPage()

    c.save()


def render_pdf(doc: UdfDocument, output: str | Path, **kwargs) -> None:
    dims = extract_page_dims(doc)
    blocks = doc.document.blocks if hasattr(doc, "document") else doc.blocks
    pages = split_into_pages(
        blocks, dims.width, dims.height,
        dims.margin_top, dims.margin_bottom,
        dims.margin_left, dims.margin_right,
    )
    result = LayoutResult(
        pages=pages,
        total_blocks=sum(len(p.blocks) for p in pages),
        total_lines=sum(sum(len(b.lines) for b in p.blocks) for p in pages),
    )
    layout_to_pdf(result, output)
