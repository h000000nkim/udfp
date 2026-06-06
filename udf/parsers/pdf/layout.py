"""PDF layout analysis using pdfminer.six -- extracts document blocks.

Pipeline:
  1. Build pdfminer LTPage layout tree
  2. Detect table regions from vector lines/rects
  3. Detect chart regions from dense LTCurve clusters
  4. Collect image positions from LTFigure/LTImage
  5. Classify headings/body by font-size heuristic
  6. Record bbox in verbatim_data for all blocks
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import (
    LAParams,
    LTAnno,
    LTChar,
    LTContainer,
    LTCurve,
    LTFigure,
    LTImage,
    LTLine,
    LTPage,
    LTRect,
    LTTextBox,
    LTTextLine,
)
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage

from udf.schema import (
    Block,
    DrawingBlock,
    FooterBlock,
    FootnoteBlock,
    HeaderBlock,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextInline,
    UnsupportedFeature,
)


try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False

# ---------------------------------------------------------------------------
# 추출 결과 컨테이너
# ---------------------------------------------------------------------------


@dataclass
class _ExtractedBlock:
    """블록 + bbox + verbatim 데이터 컨테이너."""

    block: Block
    # PDF pt 좌표 (x0, y0, x1, y1), 원점=페이지 왼쪽 하단
    bbox: tuple[float, float, float, float]
    verbatim_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class _ImageRef:
    """페이지 내 이미지 위치 정보 (바이트는 parse.py가 pypdf로 주입)."""

    name: str
    bbox: tuple[float, float, float, float]


# ---------------------------------------------------------------------------
# pdfminer 레이아웃 트리 추출
# ---------------------------------------------------------------------------


def _get_pages(path: str) -> Iterator[LTPage]:
    rsrcmgr = PDFResourceManager()
    laparams = LAParams(
        char_margin=2.0,
        line_margin=0.5,
        word_margin=0.1,
        boxes_flow=0.5,
    )
    device = PDFPageAggregator(rsrcmgr, laparams=laparams)
    interpreter = PDFPageInterpreter(rsrcmgr, device)

    with open(path, "rb") as f:
        for page in PDFPage.get_pages(f):
            interpreter.process_page(page)
            layout: LTPage = device.get_result()
            yield layout


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------


def _iter_all(container: LTContainer) -> Iterator[object]:
    for obj in container:
        yield obj
        if isinstance(obj, LTContainer):
            yield from _iter_all(obj)


def _rects_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)


# ---------------------------------------------------------------------------
# 벡터 라인 → 테이블 영역 감지
# ---------------------------------------------------------------------------

_SNAP = 3.0


@dataclass
class _GridRegion:
    x0: float
    y0: float
    x1: float
    y1: float
    col_xs: list[float] = field(default_factory=list)
    row_ys: list[float] = field(default_factory=list)


def _snap(val: float, tol: float = _SNAP) -> float:
    return round(val / tol) * tol


def _cluster_h_ys(h_ys: list[float]) -> list[list[float]]:
    """h_ys를 수직 간격이 큰 곳에서 분리해 테이블별 클러스터를 반환한다."""
    if len(h_ys) < 2:
        return [h_ys] if h_ys else []
    sorted_ys = sorted(h_ys)
    gaps = [sorted_ys[i + 1] - sorted_ys[i] for i in range(len(sorted_ys) - 1)]
    median_gap = sorted(gaps)[len(gaps) // 2]
    split_threshold = max(median_gap * 4, 40.0)

    clusters: list[list[float]] = []
    current: list[float] = [sorted_ys[0]]
    for i, gap in enumerate(gaps):
        if gap > split_threshold:
            clusters.append(current)
            current = [sorted_ys[i + 1]]
        else:
            current.append(sorted_ys[i + 1])
    clusters.append(current)
    return clusters


def _detect_table_regions(page: LTPage) -> list[_GridRegion]:
    """벡터 라인/사각형에서 격자 테이블 영역을 감지한다.

    페이지에 여러 테이블이 있는 경우 각각을 별도 _GridRegion으로 반환한다.
    """
    h_lines: list[tuple[float, float, float]] = []
    v_lines: list[tuple[float, float, float]] = []

    for obj in _iter_all(page):
        if isinstance(obj, LTLine):
            x0s, y0s = _snap(obj.x0), _snap(obj.y0)
            x1s, y1s = _snap(obj.x1), _snap(obj.y1)
            if abs(y0s - y1s) < _SNAP:
                h_lines.append((_snap((y0s + y1s) / 2), min(x0s, x1s), max(x0s, x1s)))
            elif abs(x0s - x1s) < _SNAP:
                v_lines.append((_snap((x0s + x1s) / 2), min(y0s, y1s), max(y0s, y1s)))
        elif isinstance(obj, LTRect):
            x0s, y0s = _snap(obj.x0), _snap(obj.y0)
            x1s, y1s = _snap(obj.x1), _snap(obj.y1)
            h_lines.append((y0s, x0s, x1s))
            h_lines.append((y1s, x0s, x1s))
            v_lines.append((x0s, y0s, y1s))
            v_lines.append((x1s, y0s, y1s))

    if len(h_lines) < 2 or len(v_lines) < 2:
        return []

    h_ys_all = sorted({y for y, _, _ in h_lines})
    if len(h_ys_all) < 2:
        return []

    clusters = _cluster_h_ys(h_ys_all)
    regions: list[_GridRegion] = []

    for cluster in clusters:
        if len(cluster) < 2:
            continue
        y_min, y_max = cluster[0], cluster[-1]
        # 이 클러스터 y-범위에 걸치는 v_lines만 사용
        cluster_v_xs = sorted({
            x for x, vy0, vy1 in v_lines
            if vy1 >= y_min - _SNAP and vy0 <= y_max + _SNAP
        })
        if len(cluster_v_xs) < 2:
            continue
        region = _GridRegion(
            x0=cluster_v_xs[0], y0=cluster[0],
            x1=cluster_v_xs[-1], y1=cluster[-1],
            col_xs=cluster_v_xs, row_ys=cluster,
        )
        page_w = page.x1 - page.x0
        page_h = page.y1 - page.y0
        region_w = region.x1 - region.x0
        region_h = region.y1 - region.y0
        covers_page = (region_w > page_w * 0.9 and region_h > page_h * 0.9)
        too_few_lines = len(cluster) < 4 and len(cluster_v_xs) < 4
        if covers_page and too_few_lines:
            continue
        regions.append(region)

    return regions


def _detect_tables_pdfplumber(
    path: str, page_num_0: int, page_height: float,
    block_counter: itertools.count[int],
) -> list[tuple[float, _ExtractedBlock]]:
    """pdfplumber를 사용한 테이블 감지 (기존 벡터 감지의 보충)."""
    if not _HAS_PDFPLUMBER:
        return []
    results: list[tuple[float, _ExtractedBlock]] = []
    try:
        pdf = pdfplumber.open(path)
        if page_num_0 >= len(pdf.pages):
            pdf.close()
            return []
        plumber_page = pdf.pages[page_num_0]
        tables = plumber_page.extract_tables()
        table_objs = plumber_page.find_tables()
        for tbl_idx, tbl_data in enumerate(tables):
            if not tbl_data or len(tbl_data) < 2:
                continue
            rows: list[TableRow] = []
            for row_data in tbl_data:
                if not row_data:
                    continue
                cells: list[TableCell] = []
                for cell_val in row_data:
                    cell_id = f"pdf_cell_{next(block_counter)}"
                    content = []
                    if cell_val:
                        content.append(ParagraphBlock(
                            type="paragraph",
                            id=f"pdf_p_{next(block_counter)}",
                            inlines=[TextInline(text=str(cell_val))],
                        ))
                    cells.append(TableCell(id=cell_id, content=content))
                if cells:
                    rows.append(TableRow(cells=cells))
            if rows:
                tbl_block = TableBlock(
                    type="table",
                    id=f"pdf_tbl_{next(block_counter)}",
                    rows=rows,
                )
                bbox = (0.0, 0.0, 0.0, 0.0)
                if tbl_idx < len(table_objs):
                    tb = table_objs[tbl_idx].bbox
                    bbox = (tb[0], page_height - tb[3], tb[2], page_height - tb[1])
                y_top = bbox[3] if bbox[3] else page_height / 2
                eb = _ExtractedBlock(
                    block=tbl_block,
                    bbox=bbox,
                    verbatim_data={
                        "bbox": list(bbox),
                        "object_type": "table",
                        "page": page_num_0 + 1,
                        "source": "pdfplumber",
                    },
                )
                results.append((y_top, eb))
        pdf.close()
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# LTCurve 밀집 영역 → 차트 감지
# ---------------------------------------------------------------------------

_MIN_CURVES_FOR_CHART = 8
_MIN_CHART_AREA_PT2 = 2500  # 약 50×50pt


def _detect_chart_regions(
    page: LTPage,
    table_regions: list[_GridRegion],
) -> list[tuple[float, float, float, float]]:
    """LTCurve 밀집 영역(차트 후보) bbox 목록 반환. 테이블 영역과 겹치면 제외."""
    curves = [
        obj for obj in _iter_all(page)
        if isinstance(obj, LTCurve) and not isinstance(obj, (LTLine, LTRect))
    ]
    if len(curves) < _MIN_CURVES_FOR_CHART:
        return []

    x0 = min(c.x0 for c in curves)
    y0 = min(c.y0 for c in curves)
    x1 = max(c.x1 for c in curves)
    y1 = max(c.y1 for c in curves)

    if (x1 - x0) * (y1 - y0) < _MIN_CHART_AREA_PT2:
        return []

    chart_bbox = (x0, y0, x1, y1)
    for tr in table_regions:
        if _rects_overlap(chart_bbox, (tr.x0, tr.y0, tr.x1, tr.y1)):
            return []

    return [chart_bbox]


# ---------------------------------------------------------------------------
# 이미지 위치 수집 (바이트는 parse.py에서 pypdf로 주입)
# ---------------------------------------------------------------------------


_MIN_IMAGE_DIM_PT = 5.0  # 5pt 이하 폭/높이는 유령 이미지(선/장식)로 간주


def _collect_page_images(page: LTPage, page_num: int) -> list[_ImageRef]:
    """페이지에서 이미지 위치 정보를 수집한다.

    LTFigure를 재귀 탐색하여 중첩 이미지도 수집한다.
    0pt/미세 차원 이미지(장식선 등)는 제외한다.
    """
    refs: list[_ImageRef] = []
    seen_names: set[str] = set()

    def _add(name: str, bbox: tuple[float, float, float, float]) -> None:
        x0, y0, x1, y1 = bbox
        w, h = x1 - x0, y1 - y0
        if w < _MIN_IMAGE_DIM_PT or h < _MIN_IMAGE_DIM_PT:
            return
        if name not in seen_names:
            refs.append(_ImageRef(name=name, bbox=bbox))
            seen_names.add(name)

    def _scan(container: Any, fallback_bbox: tuple[float, float, float, float] | None = None) -> None:
        for obj in container:
            if isinstance(obj, LTImage):
                name = obj.name or f"img_p{page_num}_{id(obj)}"
                _add(name, (obj.x0, obj.y0, obj.x1, obj.y1))
            elif isinstance(obj, LTFigure):
                fig_bbox = (obj.x0, obj.y0, obj.x1, obj.y1)
                _scan(obj, fig_bbox)

    _scan(page)
    return refs


# ---------------------------------------------------------------------------
# 텍스트 상자 폰트 분석
# ---------------------------------------------------------------------------

# ISO 32000-1 FontDescriptor Flags
_PDF_FLAG_ITALIC = 1 << 6        # bit 7
_PDF_FLAG_FORCE_BOLD = 1 << 18   # bit 19

_BOLD_NAME_TOKENS = frozenset([
    "bold", "heavy", "black", "extrabold", "ultrabold",
    "demibold", "semibold", "boldmt", "bolditalic", "boldoblique",
    "-bd", "_bd",
])
_ITALIC_NAME_TOKENS = frozenset([
    "italic", "oblique", "-it", "_it", "italicmt",
    "bolditalic", "boldoblique",
])


def _font_style_from_char(char: LTChar) -> tuple[bool, bool]:
    """PDFFont flags → (bold, italic). 이름 패턴은 fallback."""
    bold = False
    italic = False

    # Priority 1: FontDescriptor flags via graphicstate.font (PDFFont object)
    font = getattr(getattr(char, "graphicstate", None), "font", None)
    if font is not None:
        flags = getattr(font, "flags", None)
        if flags is not None:
            bold = bool(flags & _PDF_FLAG_FORCE_BOLD)
            italic = bool(flags & _PDF_FLAG_ITALIC)
            if bold or italic:
                return bold, italic

        # Priority 2: ItalicAngle
        angle = getattr(font, "italic_angle", None)
        if angle is not None and abs(angle) > 0.5:
            italic = True

    # Priority 3: font name pattern matching (fallback)
    fname_lower = (char.fontname or "").lower()
    if any(tok in fname_lower for tok in _BOLD_NAME_TOKENS):
        bold = True
    if any(tok in fname_lower for tok in _ITALIC_NAME_TOKENS):
        italic = True

    return bold, italic


@dataclass
class _RichSpan:
    text: str
    font_name: str = ""
    font_size: float = 0.0
    bold: bool = False
    italic: bool = False


def _extract_spans_from_line(line: LTTextLine) -> list[_RichSpan]:
    spans: list[_RichSpan] = []
    current_chars: list[str] = []
    current_font = ""
    current_size = 0.0
    current_char_obj: LTChar | None = None

    for char in line:
        if isinstance(char, LTChar):
            fname = char.fontname or ""
            fsize = round(char.size, 1)
            if fname != current_font or fsize != current_size:
                if current_chars:
                    spans.append(_make_span("".join(current_chars), current_font, current_size, current_char_obj))
                current_chars = [char.get_text()]
                current_font = fname
                current_size = fsize
                current_char_obj = char
            else:
                current_chars.append(char.get_text())
        elif isinstance(char, LTAnno):
            current_chars.append(char.get_text())

    if current_chars:
        spans.append(_make_span("".join(current_chars), current_font, current_size, current_char_obj))
    return spans


def _make_span(text: str, font_name: str, font_size: float, char: LTChar | None = None) -> _RichSpan:
    if char is not None:
        bold, italic = _font_style_from_char(char)
    else:
        fname_lower = font_name.lower()
        bold = any(tok in fname_lower for tok in _BOLD_NAME_TOKENS)
        italic = any(tok in fname_lower for tok in _ITALIC_NAME_TOKENS)
    return _RichSpan(text=text, font_name=font_name, font_size=font_size, bold=bold, italic=italic)


def _extract_spans_from_box(box: LTTextBox) -> list[_RichSpan]:
    spans: list[_RichSpan] = []
    for line in box:
        if isinstance(line, LTTextLine):
            spans.extend(_extract_spans_from_line(line))
    return spans


def _dominant_font_size(spans: Sequence[_RichSpan]) -> float:
    if not spans:
        return 0.0
    size_chars: dict[float, int] = {}
    for s in spans:
        n = len(s.text.strip())
        if n > 0:
            size_chars[s.font_size] = size_chars.get(s.font_size, 0) + n
    if not size_chars:
        return spans[0].font_size
    return max(size_chars, key=lambda k: size_chars[k])


# ---------------------------------------------------------------------------
# 리스트 / 헤딩 감지
# ---------------------------------------------------------------------------

_BULLET_RE = re.compile(r"^[\s]*([•‣◦⁃∙▪●○■□–—•·‣⁃–—\-\*])\s+")
_ORDERED_RE = re.compile(r"^[\s]*(\d+|[a-zA-Z]|[ivxlcdmIVXLCDM]+)[.)]\s+")
_MIN_HEADING_RATIO = 1.15


def _is_list_item(text: str) -> tuple[bool, bool, str]:
    m = _BULLET_RE.match(text)
    if m:
        return True, False, text[m.end():]
    m = _ORDERED_RE.match(text)
    if m:
        return True, True, text[m.end():]
    return False, False, text


def _heading_level(font_size: float, body_size: float) -> int | None:
    if body_size <= 0 or font_size <= body_size * _MIN_HEADING_RATIO:
        return None
    ratio = font_size / body_size
    if ratio >= 2.0:
        return 1
    if ratio >= 1.6:
        return 2
    if ratio >= 1.3:
        return 3
    return 4


def _heading_level_by_style(spans: list[_RichSpan], body_size: float) -> int | None:
    """폰트 크기가 본문과 같아도 전체 텍스트가 bold면 H4로 처리한다."""
    if not spans:
        return None
    text_chars = sum(len(s.text.strip()) for s in spans)
    if text_chars == 0:
        return None
    bold_chars = sum(len(s.text.strip()) for s in spans if s.bold)
    if bold_chars / text_chars >= 0.8:  # 80% 이상 bold
        return 4
    return None


# ---------------------------------------------------------------------------
# 테이블 영역에 텍스트 매핑
# ---------------------------------------------------------------------------


def _text_in_rect(
    boxes: list[LTTextBox],
    x0: float, y0: float, x1: float, y1: float,
) -> str:
    tol = _SNAP
    parts: list[str] = []
    for box in boxes:
        cx = (box.x0 + box.x1) / 2
        cy = (box.y0 + box.y1) / 2
        if x0 - tol <= cx <= x1 + tol and y0 - tol <= cy <= y1 + tol:
            parts.append(box.get_text().strip())
            continue
        # Overlap fallback: if box bbox intersects cell rect, assign to this cell
        if box.x0 < x1 + tol and box.x1 > x0 - tol and box.y0 < y1 + tol and box.y1 > y0 - tol:
            # Compute overlap fraction relative to the text box
            ow = min(box.x1, x1) - max(box.x0, x0)
            oh = min(box.y1, y1) - max(box.y0, y0)
            bw = box.x1 - box.x0
            bh = box.y1 - box.y0
            if bw > 0 and bh > 0 and ow > 0 and oh > 0:
                overlap_ratio = (ow * oh) / (bw * bh)
                if overlap_ratio >= 0.3:
                    parts.append(box.get_text().strip())
    return " ".join(parts)


def _build_table_block(
    region: _GridRegion,
    boxes: list[LTTextBox],
    block_counter: itertools.count[int],
) -> TableBlock:
    row_ys = sorted(region.row_ys, reverse=True)
    col_xs = sorted(region.col_xs)

    rows: list[TableRow] = []
    for ri in range(len(row_ys) - 1):
        cells: list[TableCell] = []
        for ci in range(len(col_xs) - 1):
            cell_text = _text_in_rect(
                boxes,
                col_xs[ci], row_ys[ri + 1], col_xs[ci + 1], row_ys[ri],
            )
            cell_id = f"pdf_cell_{next(block_counter)}"
            content = []
            if cell_text:
                content.append(ParagraphBlock(
                    type="paragraph",
                    id=f"pdf_p_{next(block_counter)}",
                    inlines=[TextInline(text=cell_text)],
                ))
            cells.append(TableCell(id=cell_id, content=content))
        if cells:
            rows.append(TableRow(cells=cells))

    return TableBlock(
        type="table",
        id=f"pdf_tbl_{next(block_counter)}",
        rows=rows,
    )


def _box_in_region(box: LTTextBox, region: _GridRegion) -> bool:
    cx = (box.x0 + box.x1) / 2
    cy = (box.y0 + box.y1) / 2
    return (
        region.x0 - _SNAP <= cx <= region.x1 + _SNAP
        and region.y0 - _SNAP <= cy <= region.y1 + _SNAP
    )


def _box_in_bbox(box: LTTextBox, bbox: tuple[float, float, float, float]) -> bool:
    cx = (box.x0 + box.x1) / 2
    cy = (box.y0 + box.y1) / 2
    x0, y0, x1, y1 = bbox
    return x0 - _SNAP <= cx <= x1 + _SNAP and y0 - _SNAP <= cy <= y1 + _SNAP


# ---------------------------------------------------------------------------
# 인라인 변환
# ---------------------------------------------------------------------------


def _spans_to_inlines(spans: list[_RichSpan]) -> list[TextInline]:
    inlines: list[TextInline] = []
    for s in spans:
        if not s.text:
            continue
        inlines.append(TextInline(
            text=s.text,
            bold=s.bold or None,
            italic=s.italic or None,
            font_name=s.font_name or None,
            font_size=s.font_size or None,
        ))
    return inlines


# ---------------------------------------------------------------------------
# 머리글/바닥글 감지 (반복 텍스트)
# ---------------------------------------------------------------------------

_HEADER_FOOTER_MARGIN_RATIO = 0.08  # 페이지 높이의 8% 이내


@dataclass
class _RepeatingText:
    """여러 페이지에서 반복되는 텍스트 정보."""

    text: str
    y_position: float  # 스냅된 y 좌표
    is_header: bool  # True=header, False=footer


def _detect_repeating_content(
    page_data: list[tuple[LTPage, list[LTTextBox], int]],
) -> set[tuple[str, float]]:
    """페이지 상단/하단에서 반복되는 텍스트를 찾아 (text_hash, snapped_y) 집합 반환.

    50% 이상의 페이지에서 동일 텍스트가 동일 y 좌표에 나타나면 머리글/바닥글로 판정.
    """
    if len(page_data) < 2:
        return set()

    # 페이지별로 상단/하단 텍스트 수집: {(text_stripped, snapped_y): set of page_nums}
    occurrence: dict[tuple[str, float], set[int]] = {}

    for page, text_boxes, page_num in page_data:
        page_height = page.y1 - page.y0
        margin = page_height * _HEADER_FOOTER_MARGIN_RATIO

        for box in text_boxes:
            box_center_y = (box.y0 + box.y1) / 2
            # 상단 영역 (PDF 좌표: y가 클수록 위)
            is_top = box_center_y > (page.y1 - margin)
            # 하단 영역
            is_bottom = box_center_y < (page.y0 + margin)

            if not (is_top or is_bottom):
                continue

            text = box.get_text().strip()
            if not text:
                continue

            # 페이지 번호 같은 숫자만 있는 경우도 반복 텍스트 후보
            snapped_y = _snap(box_center_y, tol=5.0)
            key = (text, snapped_y)
            if key not in occurrence:
                occurrence[key] = set()
            occurrence[key].add(page_num)

    total_pages = len(page_data)
    threshold = total_pages * 0.5

    repeating: set[tuple[str, float]] = set()
    for key, pages in occurrence.items():
        if len(pages) >= threshold:
            repeating.add(key)

    return repeating


def _is_repeating_box(
    box: LTTextBox,
    repeating: set[tuple[str, float]],
) -> bool:
    """텍스트 박스가 반복 머리글/바닥글인지 확인."""
    if not repeating:
        return False
    text = box.get_text().strip()
    if not text:
        return False
    snapped_y = _snap((box.y0 + box.y1) / 2, tol=5.0)
    return (text, snapped_y) in repeating


# ---------------------------------------------------------------------------
# 각주 감지
# ---------------------------------------------------------------------------

_FOOTNOTE_RE = re.compile(r"^\s*(\d+)\s*[.)\s]")
_FOOTNOTE_BOTTOM_RATIO = 0.15  # 페이지 하단 15%


def _detect_footnotes(
    text_boxes: list[LTTextBox],
    page: LTPage,
    block_counter: itertools.count[int],
) -> tuple[list[_ExtractedBlock], set[int]]:
    """페이지 하단의 각주 후보를 감지하여 FootnoteBlock 목록과 제외할 box 인덱스를 반환.

    조건: 페이지 하단 15% 영역에 위치하고, 숫자로 시작하며,
    그 위에 수평선(LTLine/LTRect)이 있는 경우.
    """
    page_height = page.y1 - page.y0
    footnote_threshold_y = page.y0 + page_height * _FOOTNOTE_BOTTOM_RATIO

    # 수평선 감지: 각주 구분선 존재 여부
    has_separator = False
    for obj in _iter_all(page):
        if isinstance(obj, (LTLine, LTRect)):
            # 수평선: y 범위가 좁고 x 범위가 넓음 (페이지 폭의 20% 이상)
            page_width = page.x1 - page.x0
            obj_width = abs(obj.x1 - obj.x0)
            obj_height = abs(obj.y1 - obj.y0)
            if (
                obj_height < 3.0
                and obj_width > page_width * 0.2
                and obj.y0 < footnote_threshold_y + page_height * 0.05
                and obj.y0 > page.y0
            ):
                has_separator = True
                break

    if not has_separator:
        return [], set()

    footnote_blocks: list[_ExtractedBlock] = []
    excluded_indices: set[int] = set()

    for i, box in enumerate(text_boxes):
        box_center_y = (box.y0 + box.y1) / 2
        if box_center_y > footnote_threshold_y:
            continue

        text = box.get_text().strip()
        m = _FOOTNOTE_RE.match(text)
        if not m:
            continue

        ref_num = m.group(1)
        footnote_text = text[m.end():].strip()

        fn_id = f"pdf_fn_{next(block_counter)}"
        content = []
        if footnote_text:
            content.append(ParagraphBlock(
                type="paragraph",
                id=f"pdf_p_{next(block_counter)}",
                inlines=[TextInline(text=footnote_text)],
            ))

        block = FootnoteBlock(
            type="footnote",
            id=fn_id,
            ref=ref_num,
            content=content,
        )
        bbox = (box.x0, box.y0, box.x1, box.y1)
        eb = _ExtractedBlock(
            block=block,
            bbox=bbox,
            verbatim_data={
                "bbox": list(bbox),
                "object_type": "footnote",
                "ref_number": ref_num,
            },
        )
        footnote_blocks.append(eb)
        excluded_indices.add(i)

    return footnote_blocks, excluded_indices


# ---------------------------------------------------------------------------
# 다단 감지 (컬럼 레이아웃)
# ---------------------------------------------------------------------------

_MIN_COLUMN_GAP_PT = 20.0  # 컬럼 간 최소 간격 (pt)
_MIN_BOXES_PER_COLUMN = 2  # 컬럼으로 인정하는 최소 텍스트 박스 수


@dataclass
class _Column:
    x_min: float
    x_max: float
    boxes: list[tuple[int, LTTextBox]]  # (원래 인덱스, box) 쌍


def _detect_columns(
    text_boxes: list[LTTextBox],
    excluded_indices: set[int],
    page: LTPage,
) -> list[_Column] | None:
    """텍스트 박스의 x 좌표 분포를 분석하여 컬럼을 감지.

    단일 컬럼이면 None 반환, 2+ 컬럼이면 정렬된 Column 목록 반환.
    """
    active_boxes = [
        (i, box) for i, box in enumerate(text_boxes) if i not in excluded_indices
    ]
    if len(active_boxes) < 4:
        return None

    page_width = page.x1 - page.x0
    if page_width < 100:
        return None

    # 각 박스의 x 중심점 수집
    x_centers = [(i, (box.x0 + box.x1) / 2, box) for i, box in active_boxes]
    x_centers.sort(key=lambda t: t[1])

    # 간격 기반 클러스터링: x 중심점 간 큰 간격에서 분할
    if len(x_centers) < 2:
        return None

    # x_min, x_max로 박스들을 좌/우 영역으로 나누기
    x_vals = [xc for _, xc, _ in x_centers]
    gaps: list[tuple[float, int]] = []
    for j in range(len(x_vals) - 1):
        gap = x_vals[j + 1] - x_vals[j]
        if gap >= _MIN_COLUMN_GAP_PT:
            gaps.append((gap, j))

    if not gaps:
        return None

    # 가장 큰 간격으로 분할 (2-column이 가장 흔함)
    gaps.sort(key=lambda g: -g[0])
    split_idx = gaps[0][1]

    left_items = x_centers[: split_idx + 1]
    right_items = x_centers[split_idx + 1:]

    if (
        len(left_items) < _MIN_BOXES_PER_COLUMN
        or len(right_items) < _MIN_BOXES_PER_COLUMN
    ):
        return None

    # x 범위가 실제로 겹치지 않는지 확인
    left_max_x = max(box.x1 for _, _, box in left_items)
    right_min_x = min(box.x0 for _, _, box in right_items)
    if left_max_x > right_min_x - _MIN_COLUMN_GAP_PT * 0.5:
        return None

    left_col = _Column(
        x_min=min(box.x0 for _, _, box in left_items),
        x_max=left_max_x,
        boxes=[(i, box) for i, _, box in left_items],
    )
    right_col = _Column(
        x_min=right_min_x,
        x_max=max(box.x1 for _, _, box in right_items),
        boxes=[(i, box) for i, _, box in right_items],
    )

    return [left_col, right_col]


# ---------------------------------------------------------------------------
# 메인: 페이지별 블록 추출
# ---------------------------------------------------------------------------


def _process_text_boxes(
    sorted_boxes: list[tuple[int, LTTextBox]],
    body_size: float,
    block_counter: itertools.count[int],
    page_num: int,
    positioned: list[tuple[float, _ExtractedBlock]],
) -> None:
    """텍스트 박스 목록을 순서대로 처리하여 positioned에 블록 추가."""
    pending_list_items: list[ListItem] = []
    pending_ordered: bool = False
    pending_y: float = 0.0
    pending_bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    def _flush_list() -> None:
        nonlocal pending_list_items, pending_ordered
        if pending_list_items:
            list_id = f"pdf_list_{next(block_counter)}"
            block = ListBlock(
                type="list",
                id=list_id,
                ordered=pending_ordered,
                items=list(pending_list_items),
            )
            eb = _ExtractedBlock(
                block=block,
                bbox=pending_bbox,
                verbatim_data={
                    "bbox": list(pending_bbox),
                    "object_type": "list",
                    "page": page_num,
                },
            )
            positioned.append((pending_y, eb))
            pending_list_items.clear()

    for _, box in sorted_boxes:
        spans = _extract_spans_from_box(box)
        if not spans:
            continue

        text = box.get_text().strip()
        if not text:
            continue

        box_bbox = (box.x0, box.y0, box.x1, box.y1)

        is_list, is_ordered, cleaned = _is_list_item(text)
        if is_list:
            if pending_list_items and is_ordered != pending_ordered:
                _flush_list()
            if not pending_list_items:
                pending_y = box.y1
                pending_bbox = box_bbox
            pending_ordered = is_ordered
            item_id = f"pdf_li_{next(block_counter)}"
            pending_list_items.append(ListItem(
                id=item_id,
                inlines=[TextInline(text=cleaned)],
            ))
            continue

        _flush_list()

        dom_size = _dominant_font_size(spans)
        max_size = max((s.font_size for s in spans if s.text.strip()), default=dom_size)
        level = _heading_level(max_size, body_size)
        if level is None:
            level = _heading_level_by_style(spans, body_size)
        dominant_font = spans[0].font_name if spans else ""

        if level is not None:
            block: Block = HeadingBlock(
                type="heading",
                id=f"pdf_h_{next(block_counter)}",
                level=level,
                text=text,
            )
            verbatim_data = {
                "bbox": list(box_bbox),
                "object_type": "heading",
                "font_name": dominant_font,
                "font_size": dom_size,
                "page": page_num,
            }
        else:
            inlines = _spans_to_inlines(spans)
            block = ParagraphBlock(
                type="paragraph",
                id=f"pdf_p_{next(block_counter)}",
                inlines=inlines,
            )
            verbatim_data = {
                "bbox": list(box_bbox),
                "object_type": "paragraph",
                "font_name": dominant_font,
                "font_size": dom_size,
                "page": page_num,
            }

        positioned.append((box.y1, _ExtractedBlock(
            block=block,
            bbox=box_bbox,
            verbatim_data=verbatim_data,
        )))

    _flush_list()


def extract_pages(
    path: str,
    block_counter: itertools.count[int],
) -> Iterator[list[_ExtractedBlock]]:
    """Extract document blocks from each page of a PDF file.

    Yields one list of ``_ExtractedBlock`` per page, each annotated with
    bounding-box and verbatim data. Image bytes are not included here --
    they are injected later by ``parse.py`` using pypdf.

    Parameters
    ----------
    path : str
        Filesystem path to the PDF file.
    block_counter : itertools.count[int]
        Shared counter for generating unique block IDs.

    Yields
    ------
    list[_ExtractedBlock]
        Blocks extracted from a single page.
    """
    all_spans: list[_RichSpan] = []
    page_data: list[tuple[LTPage, list[LTTextBox], int]] = []

    def _collect_text_boxes(container: LTContainer, out: list[LTTextBox]) -> None:
        for obj in container:
            if isinstance(obj, LTTextBox):
                out.append(obj)
            elif isinstance(obj, LTFigure):
                _collect_text_boxes(obj, out)

    for page_num_0, page in enumerate(_get_pages(path)):
        text_boxes: list[LTTextBox] = []
        for obj in page:
            if isinstance(obj, LTTextBox):
                text_boxes.append(obj)
            elif isinstance(obj, LTFigure):
                _collect_text_boxes(obj, text_boxes)
        page_data.append((page, text_boxes, page_num_0 + 1))

        for box in text_boxes:
            all_spans.extend(_extract_spans_from_box(box))

    body_size = _dominant_font_size(all_spans)

    # 머리글/바닥글 감지 (전체 페이지 대상)
    repeating_content = _detect_repeating_content(page_data)

    for page, text_boxes, page_num in page_data:
        table_regions = _detect_table_regions(page)
        chart_bboxes = _detect_chart_regions(page, table_regions)
        image_refs = _collect_page_images(page, page_num)

        # 테이블/차트 영역에 속하는 텍스트 상자 제외
        table_box_indices: set[int] = set()
        for region in table_regions:
            for i, box in enumerate(text_boxes):
                if _box_in_region(box, region):
                    table_box_indices.add(i)

        chart_box_indices: set[int] = set()
        for cbbox in chart_bboxes:
            for i, box in enumerate(text_boxes):
                if _box_in_bbox(box, cbbox):
                    chart_box_indices.add(i)

        # 머리글/바닥글로 감지된 텍스트 상자 제외
        header_footer_indices: set[int] = set()
        for i, box in enumerate(text_boxes):
            if _is_repeating_box(box, repeating_content):
                header_footer_indices.add(i)

        # 각주 감지
        base_excluded = table_box_indices | chart_box_indices | header_footer_indices
        footnote_blocks, footnote_indices = _detect_footnotes(
            text_boxes, page, block_counter,
        )

        # (y_top, _ExtractedBlock) 쌍으로 모아 최종 정렬
        positioned: list[tuple[float, _ExtractedBlock]] = []

        # 머리글/바닥글 블록 (페이지 첫 번째에 머리글, 마지막에 바닥글)
        page_height = page.y1 - page.y0
        page_mid_y = page.y0 + page_height / 2
        for i in header_footer_indices:
            box = text_boxes[i]
            text = box.get_text().strip()
            if not text:
                continue
            box_center_y = (box.y0 + box.y1) / 2
            box_bbox = (box.x0, box.y0, box.x1, box.y1)
            if box_center_y > page_mid_y:
                # 상단 → HeaderBlock
                hdr_id = f"pdf_hdr_{next(block_counter)}"
                hdr_block = HeaderBlock(
                    type="header",
                    id=hdr_id,
                    apply_to="all",
                    content=[ParagraphBlock(
                        type="paragraph",
                        id=f"pdf_p_{next(block_counter)}",
                        inlines=[TextInline(text=text)],
                    )],
                )
                positioned.append((box.y1 + 1000, _ExtractedBlock(
                    block=hdr_block,
                    bbox=box_bbox,
                    verbatim_data={
                        "bbox": list(box_bbox),
                        "object_type": "header",
                        "page": page_num,
                    },
                )))
            else:
                # 하단 → FooterBlock
                ftr_id = f"pdf_ftr_{next(block_counter)}"
                ftr_block = FooterBlock(
                    type="footer",
                    id=ftr_id,
                    apply_to="all",
                    content=[ParagraphBlock(
                        type="paragraph",
                        id=f"pdf_p_{next(block_counter)}",
                        inlines=[TextInline(text=text)],
                    )],
                )
                positioned.append((-1000.0, _ExtractedBlock(
                    block=ftr_block,
                    bbox=box_bbox,
                    verbatim_data={
                        "bbox": list(box_bbox),
                        "object_type": "footer",
                        "page": page_num,
                    },
                )))

        # 테이블 (pdfplumber 우선, 없으면 벡터 감지 보충)
        plumber_tables = _detect_tables_pdfplumber(
            path, page_num - 1, page_height, block_counter,
        )
        if plumber_tables:
            for y_top, eb in plumber_tables:
                positioned.append((y_top, eb))
                for i, box in enumerate(text_boxes):
                    if _box_in_bbox(box, eb.bbox):
                        table_box_indices.add(i)
        elif table_regions:
            for region in table_regions:
                tbl = _build_table_block(region, text_boxes, block_counter)
                if tbl.rows:
                    bbox = (region.x0, region.y0, region.x1, region.y1)
                    eb = _ExtractedBlock(
                        block=tbl,
                        bbox=bbox,
                        verbatim_data={
                            "bbox": list(bbox),
                            "object_type": "table",
                            "page": page_num,
                        },
                    )
                    positioned.append((region.y1, eb))
        # (pdfplumber fallback removed — now called first above)

        # 차트 (벡터 그래픽 밀집 영역)
        for cbbox in chart_bboxes:
            x0, y0, x1, y1 = cbbox
            draw_id = f"pdf_chart_{next(block_counter)}"
            block = DrawingBlock(
                type="drawing",
                id=draw_id,
                shape_type="vector_chart",
                unsupported=UnsupportedFeature(
                    feature="pdf.vector_chart",
                    reason="vector_graphics_not_representable",
                ),
            )
            eb = _ExtractedBlock(
                block=block,
                bbox=cbbox,
                verbatim_data={
                    "bbox": list(cbbox),
                    "object_type": "vector_chart",
                    "page": page_num,
                },
            )
            positioned.append((y1, eb))

        # 이미지 (바이트는 parse.py에서 주입, 여기선 embedded: 참조만)
        for iref in image_refs:
            img_id = f"pdf_img_{next(block_counter)}"
            x0, y0, x1, y1 = iref.bbox
            w = x1 - x0
            h = y1 - y0
            block = ImageBlock(
                type="image",
                id=img_id,
                src=f"embedded:{iref.name}",
                alt=iref.name,
                width=w if w > 0 else None,
                height=h if h > 0 else None,
            )
            eb = _ExtractedBlock(
                block=block,
                bbox=iref.bbox,
                verbatim_data={
                    "bbox": list(iref.bbox),
                    "object_type": "image",
                    "image_name": iref.name,
                    "page": page_num,
                },
            )
            positioned.append((y1, eb))

        # 각주 블록 추가 (페이지 하단에 위치)
        for fn_eb in footnote_blocks:
            positioned.append((fn_eb.bbox[1], fn_eb))  # y0 사용 (하단)

        # 텍스트 (리스트/헤딩/단락) — 제외 인덱스 통합
        excluded_indices = base_excluded | footnote_indices

        # 다단 감지
        columns = _detect_columns(text_boxes, excluded_indices, page)

        if columns is not None:
            # 다단: 왼쪽 컬럼 → 오른쪽 컬럼 순서로 처리
            for col in columns:
                col_sorted = sorted(
                    ((i, box) for i, box in col.boxes if i not in excluded_indices),
                    key=lambda ib: (-ib[1].y0, ib[1].x0),
                )
                _process_text_boxes(
                    col_sorted, body_size, block_counter, page_num, positioned,
                )
        else:
            # 단일 컬럼: 기존 로직
            sorted_boxes = sorted(
                (
                    (i, box)
                    for i, box in enumerate(text_boxes)
                    if i not in excluded_indices
                ),
                key=lambda ib: (-ib[1].y0, ib[1].x0),
            )
            _process_text_boxes(
                sorted_boxes, body_size, block_counter, page_num, positioned,
            )

        positioned.sort(key=lambda pair: -pair[0])
        yield [eb for _, eb in positioned]
