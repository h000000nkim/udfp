"""Render layout results to PNG image using Pillow."""

from __future__ import annotations

from pathlib import Path

from udf.core.schema import UdfDocument
from udf.layout import LayoutResult
from udf.layout.page_break import split_into_pages
from udf.layout.style_resolve import extract_page_dims
from udf.layout.font_metrics import find_font_path


def layout_to_image(result: LayoutResult, output_dir: str | Path, dpi: int = 144) -> list[str]:
    from PIL import Image, ImageDraw, ImageFont

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    font_path = find_font_path("맑은 고딕") or find_font_path("나눔고딕")
    paths: list[str] = []

    for page in result.pages:
        scale = dpi / 72.0
        pw = int(page.width * scale)
        ph = int(page.height * scale)
        img = Image.new("RGB", (pw, ph), "white")
        draw = ImageDraw.Draw(img)

        for block in page.blocks:
            if block.lines:
                y_offset = 0.0
                for line in block.lines:
                    x = (block.x + line.x_offset) * scale
                    y = (block.y + y_offset) * scale
                    fs = max(int(line.baseline * scale), 8)

                    try:
                        if font_path:
                            font = ImageFont.truetype(font_path, fs)
                        else:
                            font = ImageFont.load_default()
                    except Exception:
                        font = ImageFont.load_default()

                    draw.text((x, y), line.text, fill="black", font=font)
                    y_offset += line.height

        out_path = output_dir / f"page_{page.page_index + 1:03d}.png"
        img.save(str(out_path))
        paths.append(str(out_path))

    return paths


def render_image(doc: UdfDocument, output_dir: str | Path, dpi: int = 144, **kwargs) -> list[str]:
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
    return layout_to_image(result, output_dir, dpi)
