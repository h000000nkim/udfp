"""PDF OCR support using PaddleOCR PPStructureV3 + pypdfium2.

Optional dependency — gracefully degrades when not installed.
Install: pip install udfp[ocr]

Pipeline for scan PDF pages (no text layer):
  1. Render PDF page to image via pypdfium2
  2. Run PPStructureV3 (layout + OCR + table recognition)
  3. Convert parsing_res_list into ordered UDF blocks
"""

from __future__ import annotations

import gc
import itertools
from typing import Any

from udf.schema import (
    Block,
    FooterBlock,
    HeaderBlock,
    HeadingBlock,
    ParagraphBlock,
    TableBlock,
    TextInline,
)

try:
    import pypdfium2 as pdfium
    _HAS_PDFIUM = True
except ImportError:
    _HAS_PDFIUM = False

try:
    from paddleocr import PPStructureV3
    _HAS_PADDLE = True
except ImportError:
    _HAS_PADDLE = False

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


def ocr_available() -> bool:
    """Check if OCR dependencies are installed."""
    return _HAS_PDFIUM and _HAS_PADDLE and _HAS_NUMPY


_pp_instance: PPStructureV3 | None = None


def _get_pp() -> PPStructureV3:
    """Lazy-initialize PPStructureV3 singleton with minimal models."""
    global _pp_instance
    if _pp_instance is None:
        _pp_instance = PPStructureV3(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            use_seal_recognition=False,
            use_formula_recognition=False,
            use_chart_recognition=False,
            use_region_detection=False,
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
        )
    return _pp_instance


def render_page_to_image(
    path: str, page_num_0: int, dpi: int = 150,
) -> Any:
    """Render a single PDF page to a numpy array via pypdfium2."""
    if not _HAS_PDFIUM or not _HAS_NUMPY:
        return None
    try:
        pdf = pdfium.PdfDocument(path)
        page = pdf[page_num_0]
        bitmap = page.render(scale=dpi / 72)
        img = bitmap.to_numpy()
        pdf.close()
        if img.ndim == 3:
            if img.shape[2] == 4:
                img = img[:, :, :3]
            if img.shape[2] == 3:
                img = img[:, :, ::-1].copy()
        return img
    except Exception:
        return None


def _html_table_to_block(
    html: str, block_counter: itertools.count[int],
) -> TableBlock | None:
    """Convert PPStructureV3 pred_html to a UDF TableBlock via HTML parser."""
    from udf.parsers.html.parse import parse_html
    try:
        doc = parse_html(html)
        for b in doc.blocks:
            if isinstance(b, TableBlock):
                return b.model_copy(update={"id": f"pdf_ocr_tbl_{next(block_counter)}"})
    except Exception:
        pass
    return None


def _pixel_bbox_to_pdf(
    bbox: list[int | float], scale: float, page_height: float,
) -> tuple[float, float, float, float]:
    """Convert pixel bbox [x0,y0,x1,y1] to PDF coordinate (origin=bottom-left)."""
    x0 = float(bbox[0]) / scale
    y0 = page_height - float(bbox[3]) / scale
    x1 = float(bbox[2]) / scale
    y1 = page_height - float(bbox[1]) / scale
    return (x0, y0, x1, y1)


def ocr_page(
    path: str,
    page_num_0: int,
    block_counter: itertools.count[int],
    page_height: float,
    dpi: int = 150,
) -> list[dict[str, Any]]:
    """Run OCR on a PDF page and return ordered UDF blocks.

    Uses parsing_res_list for document-order layout blocks:
      - header → HeaderBlock
      - paragraph_title / figure_title → HeadingBlock
      - text → ParagraphBlock
      - table → TableBlock (via pred_html → parse_html)
      - footer → FooterBlock
    """
    if not ocr_available():
        return []

    img = render_page_to_image(path, page_num_0, dpi=dpi)
    if img is None:
        return []

    pp = _get_pp()
    try:
        results = list(pp.predict(img))
    except Exception:
        return []
    finally:
        del img
        gc.collect()
        try:
            import paddle.framework.core as core
            core.clear_executor_cache()
        except Exception:
            pass

    if not results:
        return []

    r = results[0]
    scale = dpi / 72
    out: list[dict[str, Any]] = []
    table_idx = 0
    table_res_list = r.get("table_res_list", [])

    for layout_block in r.get("parsing_res_list", []):
        label = getattr(layout_block, "label", "")
        content = getattr(layout_block, "content", "") or ""
        bbox_raw = getattr(layout_block, "bbox", [0, 0, 0, 0])
        bbox = _pixel_bbox_to_pdf(bbox_raw, scale, page_height)

        if label == "table":
            html = content if content.startswith("<html") else ""
            if not html and table_idx < len(table_res_list):
                html = table_res_list[table_idx].get("pred_html", "")
            table_idx += 1
            if not html:
                continue
            block = _html_table_to_block(html, block_counter)
            if block is None:
                continue
            out.append({
                "block": block,
                "bbox": bbox,
                "confidence": 0.95,
                "block_type": "table",
            })

        elif label == "header":
            text = _strip_html(content)
            if not text:
                continue
            bid = f"pdf_ocr_hdr_{next(block_counter)}"
            block = HeaderBlock(
                type="header", id=bid, apply_to="all",
                content=[ParagraphBlock(
                    type="paragraph",
                    id=f"pdf_ocr_{next(block_counter)}",
                    inlines=[TextInline(text=text)],
                )],
            )
            out.append({
                "block": block, "bbox": bbox,
                "confidence": 0.9, "block_type": "header",
            })

        elif label == "footer":
            text = _strip_html(content)
            if not text:
                continue
            bid = f"pdf_ocr_ftr_{next(block_counter)}"
            block = FooterBlock(
                type="footer", id=bid, apply_to="all",
                content=[ParagraphBlock(
                    type="paragraph",
                    id=f"pdf_ocr_{next(block_counter)}",
                    inlines=[TextInline(text=text)],
                )],
            )
            out.append({
                "block": block, "bbox": bbox,
                "confidence": 0.9, "block_type": "footer",
            })

        elif label in ("paragraph_title", "figure_title"):
            text = _strip_html(content)
            if not text:
                continue
            bid = f"pdf_ocr_h_{next(block_counter)}"
            level = 2 if label == "paragraph_title" else 3
            block = HeadingBlock(
                type="heading", id=bid, level=level, text=text,
            )
            out.append({
                "block": block, "bbox": bbox,
                "confidence": 0.9, "block_type": "heading",
            })

        elif label in ("text", "paragraph", "reference", "abstract"):
            text = _strip_html(content)
            if not text:
                continue
            bid = f"pdf_ocr_{next(block_counter)}"
            block = ParagraphBlock(
                type="paragraph", id=bid,
                inlines=[TextInline(text=text)],
            )
            out.append({
                "block": block, "bbox": bbox,
                "confidence": 0.9, "block_type": "paragraph",
            })

        else:
            text = _strip_html(content)
            if not text:
                continue
            bid = f"pdf_ocr_{next(block_counter)}"
            block = ParagraphBlock(
                type="paragraph", id=bid,
                inlines=[TextInline(text=text)],
            )
            out.append({
                "block": block, "bbox": bbox,
                "confidence": 0.8, "block_type": "paragraph",
            })

    return out


def _strip_html(text: str) -> str:
    """Strip HTML tags if present, return plain text."""
    if not text:
        return ""
    if "<html" in text or "<table" in text:
        return ""
    t = text.strip()
    if t.startswith("<") and ">" in t:
        import re
        t = re.sub(r"<[^>]+>", "", t).strip()
    return t
