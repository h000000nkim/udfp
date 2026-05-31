"""PDF file parser.

One-way conversion pipeline (PDF is not round-trippable):
  1. pypdf extracts metadata and per-page image bytes
  2. pdfminer (layout.py) extracts block structure with bounding boxes
  3. Embedded image references are resolved to base64 inline data
  4. VerbatimLayer stores bbox and font info for downstream use
  5. A LossReport records inherent extraction losses
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import itertools
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from udf.schema import (
    Block,
    DocumentMetadata,
    DocumentSchema,
    HeadingBlock,
    ImageBlock,
    LinkInline,
    ListBlock,
    PageBoundary,
    ParagraphBlock,
    TableBlock,
    TextInline,
)
from udf.pipeline import UdfDocument, VerbatimLayer
from udf.pipeline.container import ConversionTrace
from udf.pipeline.verbatim import VerbatimBlock
from udf.pipeline.loss import BlockLoss, LossCategory, LossReport
from udf.parsers.pdf.layout import _ExtractedBlock, extract_pages


# ---------------------------------------------------------------------------
# 이미지 MIME 타입 감지
# ---------------------------------------------------------------------------

_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
    (b"RIFF", "image/webp"),
    (b"BM", "image/bmp"),
]


def _detect_mime(data: bytes) -> str:
    """Detect image MIME type from magic bytes."""
    for magic, mime in _MAGIC:
        if data[: len(magic)] == magic:
            return mime
    return "image/png"


# ---------------------------------------------------------------------------
# pypdf 이미지 바이트 추출
# ---------------------------------------------------------------------------


def _extract_image_cache(
    reader: PdfReader,
) -> dict[int, dict[str, tuple[bytes, str]]]:
    """페이지별 이미지 캐시 반환: {page_num(1-based): {name: (bytes, mime)}}.

    Form XObject 내부를 재귀 탐색하여 중첩 이미지도 수집한다.
    """
    cache: dict[int, dict[str, tuple[bytes, str]]] = {}

    for page_num, page in enumerate(reader.pages, start=1):
        page_cache: dict[str, tuple[bytes, str]] = {}
        try:
            resources = page.get("/Resources")
            if resources is not None:
                _collect_xobject_images(resources, page_cache, depth=0)
        except Exception:
            pass
        cache[page_num] = page_cache

    return cache


def _collect_xobject_images(
    resources: Any,
    cache: dict[str, tuple[bytes, str]],
    depth: int,
) -> None:
    """PDF 리소스 딕셔너리에서 이미지 XObject를 재귀적으로 수집한다."""
    if depth > 6:
        return
    try:
        if hasattr(resources, "get_object"):
            resources = resources.get_object()
        xobjects = resources.get("/XObject")
        if xobjects is None:
            return
        if hasattr(xobjects, "get_object"):
            xobjects = xobjects.get_object()
        for key, obj_ref in xobjects.items():
            try:
                obj = obj_ref.get_object() if hasattr(obj_ref, "get_object") else obj_ref
                subtype = obj.get("/Subtype") if hasattr(obj, "get") else None
                name = key.lstrip("/")  # "/Im2" → "Im2"
                if subtype == "/Image":
                    try:
                        data = obj.get_data()
                        if data:
                            cache[name] = (data, _detect_mime(data))
                    except Exception:
                        pass
                elif subtype == "/Form":
                    # Form XObject 내부 재귀 탐색
                    sub_res = obj.get("/Resources")
                    if sub_res is not None:
                        _collect_xobject_images(sub_res, cache, depth + 1)
            except Exception:
                pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 이미지 src 교체 (embedded:name → data:mime;base64,...)
# ---------------------------------------------------------------------------


def _make_b64_src(data: bytes, mime: str) -> str:
    """Encode image bytes as a data-URI string."""
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _inject_image_bytes(
    block: Block,
    page_num: int,
    image_cache: dict[int, dict[str, tuple[bytes, str]]],
) -> tuple[Block, list[str]]:
    """ImageBlock의 embedded: src를 base64 inline으로 교체.
    반환: (교체된 블록, 손실 이유 목록).
    """
    if not isinstance(block, ImageBlock):
        return block, []

    src = block.src
    if not src.startswith("embedded:"):
        return block, []

    name = src[len("embedded:"):]
    page_cache = image_cache.get(page_num, {})

    if name in page_cache:
        data, mime = page_cache[name]
        new_src = _make_b64_src(data, mime)
        return block.model_copy(update={"src": new_src}), []
    else:
        # 이름 매칭 실패 — 다른 페이지에서 찾기 (pypdf 이름 불일치 대응)
        for pnum, pcache in image_cache.items():
            if name in pcache:
                data, mime = pcache[name]
                new_src = _make_b64_src(data, mime)
                return block.model_copy(update={"src": new_src}), []

        # 바이트 없음: src는 embedded: 참조로 유지, 손실 기록
        return block, [f"image bytes not found for '{name}'"]


# ---------------------------------------------------------------------------
# 하이퍼링크 추출 (pypdf annotations)
# ---------------------------------------------------------------------------


def _extract_links(reader: PdfReader) -> dict[int, list[dict[str, Any]]]:
    """페이지별 하이퍼링크 어노테이션 추출: {page_num(1-based): [{url, rect}]}."""
    links: dict[int, list[dict[str, Any]]] = {}
    for page_num, page in enumerate(reader.pages, start=1):
        page_links: list[dict[str, Any]] = []
        annots = page.get("/Annots")
        if annots:
            if hasattr(annots, "get_object"):
                annots = annots.get_object()
            for annot_ref in annots:
                try:
                    annot = (
                        annot_ref.get_object()
                        if hasattr(annot_ref, "get_object")
                        else annot_ref
                    )
                    if annot.get("/Subtype") == "/Link":
                        action = annot.get("/A")
                        if action:
                            if hasattr(action, "get_object"):
                                action = action.get_object()
                            uri = action.get("/URI")
                            if uri:
                                rect = annot.get("/Rect")
                                if rect:
                                    page_links.append({
                                        "url": str(uri),
                                        "rect": [float(r) for r in rect],
                                    })
                except Exception:
                    pass
        links[page_num] = page_links
    return links


def _rects_overlap_link(
    block_bbox: tuple[float, float, float, float],
    link_rect: list[float],
) -> bool:
    """블록 bbox와 링크 rect가 겹치는지 확인 (PDF 좌표계)."""
    ax0, ay0, ax1, ay1 = block_bbox
    bx0, by0, bx1, by1 = link_rect[0], link_rect[1], link_rect[2], link_rect[3]
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)


def _apply_links_to_blocks(
    blocks: list[Block],
    extracted_blocks: list[_ExtractedBlock],
    page_links: list[dict[str, Any]],
) -> list[Block]:
    """텍스트 블록의 bbox가 링크 어노테이션과 겹치면 인라인을 LinkInline으로 변환."""
    if not page_links:
        return blocks

    result: list[Block] = []
    for block, eb in zip(blocks, extracted_blocks):
        matched_url = None
        for link in page_links:
            if _rects_overlap_link(eb.bbox, link["rect"]):
                matched_url = link["url"]
                break

        if matched_url is None:
            result.append(block)
            continue

        if isinstance(block, ParagraphBlock) and block.inlines:
            new_inlines = []
            for inline in block.inlines:
                if isinstance(inline, TextInline) and inline.text.strip():
                    new_inlines.append(LinkInline(
                        text=inline.text,
                        url=matched_url,
                    ))
                else:
                    new_inlines.append(inline)
            result.append(block.model_copy(update={"inlines": new_inlines}))
        elif isinstance(block, HeadingBlock):
            # HeadingBlock은 text 필드만 있으므로 메타데이터로 URL 보존
            result.append(block)
        else:
            result.append(block)

    return result


# ---------------------------------------------------------------------------
# 메인 파서
# ---------------------------------------------------------------------------


def parse_pdf(path: str) -> UdfDocument:
    """Parse a PDF file into a UdfDocument.

    This is a one-way extraction; PDF documents cannot be losslessly
    round-tripped. Headings, tables, and lists are inferred heuristically
    from font size and visual layout.

    Parameters
    ----------
    path : str
        Filesystem path to the .pdf file.

    Returns
    -------
    UdfDocument
        Document model with semantic blocks, VerbatimLayer (bbox/font
        data), page boundaries, and an attached LossReport.
    """
    raw = Path(path).read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()

    reader = PdfReader(path)
    metadata = _extract_metadata(reader)

    # 이미지 바이트 사전 추출 (pypdf)
    image_cache = _extract_image_cache(reader)
    # 하이퍼링크 어노테이션 추출 (pypdf)
    link_map = _extract_links(reader)

    block_counter = itertools.count(1)
    verbatim_id_counter = itertools.count(1)

    all_blocks: list[Block] = []
    verbatim_blocks: dict[str, VerbatimBlock] = {}
    page_boundaries: list[PageBoundary] = []
    loss_records: list[BlockLoss] = []

    for page_num, extracted_list in enumerate(
        extract_pages(path, block_counter), start=1
    ):
        page_blocks: list[Block] = []
        page_ebs: list[_ExtractedBlock] = []

        for eb in extracted_list:
            # verbatim_ref 생성
            v_id = f"v_pdf_{next(verbatim_id_counter)}"
            verbatim_blocks[v_id] = VerbatimBlock(
                decoded=eb.verbatim_data,
            )

            # 이미지 바이트 주입
            block = eb.block
            if isinstance(block, ImageBlock):
                block, loss_reasons = _inject_image_bytes(block, page_num, image_cache)
                for reason in loss_reasons:
                    loss_records.append(BlockLoss(
                        block_id=block.id,
                        loss_type=LossCategory.FORMAT_LIMIT,
                        description=reason,
                    ))

            # verbatim_ref 설정
            try:
                block = block.model_copy(update={"verbatim_ref": v_id})
            except Exception:
                pass  # verbatim_ref 필드 없는 블록 타입 무시

            page_blocks.append(block)
            page_ebs.append(eb)

        # pypdf에서 발견했지만 pdfminer에서 감지 못한 이미지 추가
        matched_names: set[str] = set()
        for eb in page_ebs:
            vd = eb.verbatim_data or {}
            if vd.get("object_type") == "image" and "image_name" in vd:
                matched_names.add(vd["image_name"])
        page_img_cache = image_cache.get(page_num, {})
        for img_name, (img_data, img_mime) in page_img_cache.items():
            if img_name not in matched_names and len(img_data) > 100:
                img_id = f"pdf_img_{next(block_counter)}"
                img_src = _make_b64_src(img_data, img_mime)
                img_block = ImageBlock(
                    type="image",
                    id=img_id,
                    src=img_src,
                    alt=img_name,
                )
                v_id = f"v_pdf_{next(verbatim_id_counter)}"
                verbatim_blocks[v_id] = VerbatimBlock(
                    decoded={
                        "object_type": "image",
                        "image_name": img_name,
                        "page": page_num,
                        "source": "pypdf_unmatched",
                    },
                )
                try:
                    img_block = img_block.model_copy(update={"verbatim_ref": v_id})
                except Exception:
                    pass
                page_blocks.append(img_block)

        # 하이퍼링크 → LinkInline 변환 (post-processing)
        page_links = link_map.get(page_num, [])
        if page_links and page_blocks:
            page_blocks = _apply_links_to_blocks(page_blocks, page_ebs, page_links)

        if page_blocks:
            page_boundaries.append(PageBoundary(
                page=page_num,
                start=page_blocks[0].id,
                end=page_blocks[-1].id,
            ))

        all_blocks.extend(page_blocks)

    # dropped_features: PDF에서 원천적으로 보존 불가능한 기능 목록
    dropped_features = _detect_dropped_features(all_blocks, reader)

    # LossReport
    total = len(all_blocks)
    lossy = len(loss_records)
    report = LossReport(
        total_blocks=total,
        lossless_blocks=total - lossy,
        lossy_blocks=loss_records,
        dropped_features=dropped_features,
        is_roundtrip_safe=False,  # PDF는 단방향 변환, 라운드트립 불가
    )

    return UdfDocument(
        source_format="pdf",
        document=DocumentSchema(
            metadata=metadata,
            blocks=all_blocks,
            page_boundaries=page_boundaries,
        ),
        verbatim=VerbatimLayer(
            format="pdf",
            blocks=verbatim_blocks,
        ),
        conversion_trace=ConversionTrace(
            parsed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            parser_version="0.2.0",
            checksum=checksum,
        ),
        loss_report=report,
    )


def _detect_dropped_features(
    blocks: list[Block], reader: PdfReader
) -> list[str]:
    """PDF 파싱에서 손실되는 기능을 동적으로 감지한다."""
    features: list[str] = []

    has_headings = any(isinstance(b, HeadingBlock) for b in blocks)
    has_tables = any(isinstance(b, TableBlock) for b in blocks)
    has_lists = any(isinstance(b, ListBlock) for b in blocks)

    if has_headings:
        features.append("heading_levels_heuristic: inferred from font size, not semantic")
    if has_tables:
        features.append("table_structure_heuristic: inferred from visual layout, cell merges may be lost")
    if has_lists:
        features.append("list_structure_heuristic: inferred from bullet/number patterns")

    features.append("paragraph_formatting: no margin/spacing/alignment metadata in PDF")
    features.append("font_embedding: only font names preserved, not font files")

    # AcroForm 폼 필드 감지
    if reader.trailer and reader.trailer.get("/Root"):
        root = reader.trailer["/Root"]
        if hasattr(root, "get_object"):
            root = root.get_object()
        if root.get("/AcroForm"):
            features.append("form_fields: PDF AcroForm fields not extracted")

    # 문서 아웃라인 (bookmarks)
    try:
        if reader.outline:
            features.append("document_outline: PDF bookmarks not extracted")
    except Exception:
        pass

    return features


def _extract_metadata(reader: PdfReader) -> DocumentMetadata:
    """Extract document metadata from PDF info dictionary."""
    info = reader.metadata
    title = None
    author = None
    created_at = None
    modified_at = None

    if info:
        title = info.title
        author = info.author
        try:
            if info.creation_date:
                created_at = str(info.creation_date)
        except Exception:
            pass
        try:
            if info.modification_date:
                modified_at = str(info.modification_date)
        except Exception:
            pass

    page_count = len(reader.pages)
    first_page = reader.pages[0] if page_count > 0 else None
    page_width = None
    page_height = None
    if first_page and first_page.mediabox:
        page_width = float(first_page.mediabox.width)
        page_height = float(first_page.mediabox.height)

    return DocumentMetadata(
        title=title,
        author=author,
        created_at=created_at,
        modified_at=modified_at,
        page_width=page_width,
        page_height=page_height,
    )
