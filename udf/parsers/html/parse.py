"""HTML to UdfDocument parser.

Parses HTML produced by ``render_html(embed_ids=True)`` back into a
UdfDocument. Block IDs are recovered from ``data-bid`` attributes when
present; otherwise sequential IDs are assigned.
"""

from __future__ import annotations

import itertools
import re
from html.parser import HTMLParser
from typing import Any, cast

from udf.core.ids import make_block_id
from udf.schema import (
    Block,
    BlockFormat,
    CellFormat,
    DocumentMetadata,
    DocumentSchema,
    DrawingBlock,
    EquationBlock,
    EquationInline,
    FootnoteBlock,
    HeadingBlock,
    ImageBlock,
    ImageInline,
    Inline,
    LinkInline,
    ParagraphBlock,
    PositionInfo,
    Ratio,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
    TextInline,
)
from udf.pipeline import UdfDocument, VerbatimLayer


# ---------------------------------------------------------------------------
# 경량 DOM 트리 (lxml-style text/tail 모델)
# ---------------------------------------------------------------------------


class _Node:
    """Lightweight DOM node with lxml-style text/tail model."""

    __slots__ = ("tag", "attrs", "children", "text", "tail", "parent")

    def __init__(self, tag: str, attrs: dict[str, str | None]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[_Node] = []
        self.text: str = ""
        self.tail: str = ""
        self.parent: _Node | None = None

    def get(self, key: str, default: str = "") -> str:
        """Get an attribute value by key, with a default fallback."""
        return self.attrs.get(key) or default

    def find_all(self, tag: str) -> list[_Node]:
        """Recursively find all descendant nodes with the given tag."""
        result: list[_Node] = []
        for c in self.children:
            if c.tag == tag:
                result.append(c)
            result.extend(c.find_all(tag))
        return result

    def find(self, tag: str, **attrs: str) -> _Node | None:
        """Find the first descendant node matching tag and attributes."""
        for c in self.children:
            if c.tag == tag:
                if all(c.attrs.get(k) == v for k, v in attrs.items()):
                    return c
            found = c.find(tag, **attrs)
            if found:
                return found
        return None


class _TreeBuilder(HTMLParser):
    """HTML parser that builds a _Node tree with text/tail semantics."""

    def __init__(self) -> None:
        super().__init__()
        self.root = _Node("root", {})
        self._stack: list[_Node] = [self.root]
        self._last_closed: _Node | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Handle an opening HTML tag by pushing a new node onto the stack."""
        node = _Node(tag, dict(attrs))
        node.parent = self._stack[-1]
        self._stack[-1].children.append(node)
        self._last_closed = None
        if tag not in ("br", "img", "hr", "meta", "link"):
            self._stack.append(node)
        else:
            self._last_closed = node

    def handle_endtag(self, tag: str) -> None:
        """Handle a closing HTML tag by popping the stack."""
        if len(self._stack) > 1 and self._stack[-1].tag == tag:
            self._last_closed = self._stack.pop()

    def _append_text(self, data: str) -> None:
        if self._last_closed is not None:
            self._last_closed.tail += data
        elif self._stack:
            self._stack[-1].text += data

    def handle_data(self, data: str) -> None:
        """Handle raw text data."""
        self._append_text(data)

    def handle_entityref(self, name: str) -> None:
        """Handle a named HTML entity reference."""
        ch = {"amp": "&", "lt": "<", "gt": ">", "nbsp": " ", "quot": '"'}.get(
            name, f"&{name};"
        )
        self._append_text(ch)

    def handle_charref(self, name: str) -> None:
        """Handle a numeric character reference."""
        try:
            ch = chr(int(name, 16) if name.startswith("x") else int(name))
        except ValueError:
            ch = f"&#{name};"
        self._append_text(ch)


def _build_dom(html: str) -> _Node:
    """Parse HTML string into a _Node tree."""
    builder = _TreeBuilder()
    builder.feed(html)
    return builder.root


# ---------------------------------------------------------------------------
# CSS style 파서
# ---------------------------------------------------------------------------

_STYLE_RE = re.compile(r"([a-zA-Z\-]+)\s*:\s*([^;]+)")


def _parse_style(style: str | None) -> dict[str, str]:
    if not style:
        return {}
    return {m.group(1).strip(): m.group(2).strip() for m in _STYLE_RE.finditer(style)}


def _parse_pt(val: str | None) -> float:
    if not val:
        return 0.0
    v = val.strip().rstrip("pt").rstrip("px").strip()
    try:
        return float(v)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# 인라인 파서 (text/tail 모델 대응)
# ---------------------------------------------------------------------------


def _extract_inlines(node: _Node, *, bold: bool = False, italic: bool = False,
                     underline: bool = False, strike: bool = False,
                     font_name: str | None = None, font_size: str | None = None,
                     color: str | None = None) -> list[Inline]:
    """DOM 노드에서 인라인 요소를 재귀 추출 (text/tail 순서 보존)."""
    result: list[Inline] = []

    # 1. node.text (첫 자식 앞 텍스트)
    if node.text:
        _append_text_parts(result, node.text, bold, italic, underline, strike,
                           font_name, font_size, color)

    # 2. 자식 순회: 각 자식 처리 후 자식의 tail 처리
    for child in node.children:
        tag = child.tag.lower()
        nb, ni, nu, ns = bold, italic, underline, strike
        nfn, nfs, nc = font_name, font_size, color

        if tag in ("strong", "b"):
            nb = True
        elif tag in ("em", "i"):
            ni = True
        elif tag == "u":
            nu = True
        elif tag in ("del", "s"):
            ns = True
        elif tag == "span":
            sty = _parse_style(child.get("style"))
            if "font-size" in sty:
                nfs = sty["font-size"]
            if "font-family" in sty:
                raw_ff = sty["font-family"]
                nfn = raw_ff.split(",")[0].strip().strip("'\"")
            if "color" in sty:
                nc = sty["color"]
        elif tag == "a":
            href = child.get("href")
            link_text = _collect_text(child)
            result.append(LinkInline(text=link_text, url=href))
            if child.tail:
                _append_text_parts(result, child.tail, bold, italic, underline, strike,
                                   font_name, font_size, color)
            continue
        elif tag == "img":
            sty = _parse_style(child.get("style"))
            if "max-height" in sty and "1.2em" in sty.get("max-height", ""):
                result.append(ImageInline(
                    src=child.get("src"),
                    alt=child.get("alt"),
                ))
            if child.tail:
                _append_text_parts(result, child.tail, bold, italic, underline, strike,
                                   font_name, font_size, color)
            continue
        elif tag == "sup":
            result.extend(_extract_inlines(
                child, bold=nb, italic=ni, underline=nu, strike=ns,
                font_name=nfn, font_size=nfs, color=nc,
            ))
            if child.tail:
                _append_text_parts(result, child.tail, bold, italic, underline, strike,
                                   font_name, font_size, color)
            continue
        elif tag == "br":
            result.append(TextInline(text="\n"))
            if child.tail:
                _append_text_parts(result, child.tail, bold, italic, underline, strike,
                                   font_name, font_size, color)
            continue

        result.extend(_extract_inlines(
            child, bold=nb, italic=ni, underline=nu, strike=ns,
            font_name=nfn, font_size=nfs, color=nc,
        ))
        # 자식의 tail 텍스트 (부모의 서식 컨텍스트 사용)
        if child.tail:
            _append_text_parts(result, child.tail, bold, italic, underline, strike,
                               font_name, font_size, color)

    return result


def _append_text_parts(
    result: list[Inline], text: str,
    bold: bool, italic: bool, underline: bool, strike: bool,
    font_name: str | None, font_size: str | None, color: str | None,
) -> None:
    """텍스트에서 MathJax 인라인 수식 분리 후 TextInline 추가."""
    parts = re.split(r"(\\\(.*?\\\))", text)
    fs_val = _parse_pt(font_size) if font_size else None
    if fs_val == 0.0:
        fs_val = None
    for part in parts:
        if part.startswith("\\(") and part.endswith("\\)"):
            latex = part[2:-2]
            result.append(EquationInline(latex=latex))
        elif part:
            result.append(TextInline(
                text=part,
                bold=bold or None,
                italic=italic or None,
                underline=underline or None,
                strikethrough=strike or None,
                font_name=font_name,
                font_size=fs_val,
                color=color,
            ))


def _collect_text(node: _Node) -> str:
    """노드 전체 텍스트 수집 (text + children text/tail 재귀)."""
    parts = [node.text]
    for c in node.children:
        parts.append(_collect_text(c))
        parts.append(c.tail)
    return "".join(parts)


# ---------------------------------------------------------------------------
# 블록 파서
# ---------------------------------------------------------------------------

_AUTONUMBER_RE = re.compile(
    r"^(?:\d+\.)+\s*"          # "1." "1.2." etc.
    r"|^[가-하]\.\s*"           # Korean syllable "가." "나."
    r"|^\([0-9]+\)\s*"         # "(1)" "(2)"
    r"|^[ㄱ-ㅎ]\.\s*"          # Korean jamo "ㄱ." "ㄴ."
)


def _strip_autonumber_inlines(inlines: list[Inline]) -> list[Inline]:
    """render_html _NumberingState가 삽입한 번호 prefix를 인라인 목록에서 제거.

    패턴: <strong>번호.</strong> 텍스트... → 첫 bold TextInline이 번호 패턴이면 제거.
    """
    if not inlines:
        return inlines
    first = inlines[0]
    if isinstance(first, TextInline) and first.bold:
        if _AUTONUMBER_RE.match(first.text.strip()):
            rest = inlines[1:]
            if rest and isinstance(rest[0], TextInline) and rest[0].text.startswith(" "):
                rest = [TextInline(text=rest[0].text.lstrip(" "), **{
                    k: v for k, v in rest[0].model_dump(exclude_none=True).items()
                    if k not in ("text", "type")
                })] + list(rest[1:])
            return rest
    return inlines


def _is_skip_div(node: _Node) -> bool:
    """렌더링 아티팩트 div 감지 (clear:both, 페이지 번호 등)."""
    sty = _parse_style(node.get("style"))
    if sty.get("clear") == "both":
        return True
    if (sty.get("text-align") == "center"
            and sty.get("font-size", "").startswith("9pt")):
        text = _collect_text(node).strip()
        if re.match(r"^-\s*\d+\s*-$", text):
            return True
    return False


def _is_equation_block(node: _Node) -> bool:
    """<p>$$...$$</p> 패턴 감지."""
    text = _collect_text(node).strip()
    return text.startswith("$$") and text.endswith("$$") and len(text) > 4


def _parse_block_format(sty: dict[str, str]) -> BlockFormat | None:
    parts: dict[str, Any] = {}
    if "text-align" in sty:
        a = sty["text-align"]
        if a in ("left", "center", "right", "justify"):
            parts["alignment"] = a
    if "line-height" in sty:
        try:
            val = float(sty["line-height"])
            parts["line_spacing"] = Ratio(val * 100)
        except ValueError:
            pass
    if "margin-top" in sty:
        parts["space_before"] = _parse_pt(sty["margin-top"])
    if "margin-bottom" in sty:
        parts["space_after"] = _parse_pt(sty["margin-bottom"])
    if "padding-left" in sty:
        parts["indent_left"] = _parse_pt(sty["padding-left"])
    if "padding-right" in sty:
        parts["indent_right"] = _parse_pt(sty["padding-right"])
    if "text-indent" in sty:
        parts["indent_first"] = _parse_pt(sty["text-indent"])
    return BlockFormat(**parts) if parts else None


def _is_textbox_div(sty: dict[str, str]) -> bool:
    """TextBox 패턴 감지: padding + border 조합 or overflow:hidden."""
    has_padding = any(k.startswith("padding") for k in sty)
    has_border = any(k.startswith("border") for k in sty)
    has_overflow = sty.get("overflow") == "hidden"
    return (has_padding and has_border) or (has_padding and has_overflow)


def _parse_position_info(sty: dict[str, str]) -> PositionInfo | None:
    parts: dict[str, Any] = {}
    if "left" in sty:
        parts["x"] = _parse_pt(sty["left"])
    if "top" in sty:
        parts["y"] = _parse_pt(sty["top"])
    if "width" in sty:
        parts["width"] = _parse_pt(sty["width"])
    if "height" in sty:
        parts["height"] = _parse_pt(sty["height"])
    return PositionInfo(**parts) if parts else None


def _parse_cell_format(sty: dict[str, str]) -> CellFormat | None:
    parts: dict[str, Any] = {}
    for side in ("top", "bottom", "left", "right"):
        key = f"border-{side}"
        if key in sty:
            parts[key.replace("-", "_")] = sty[key]
    if "background" in sty and sty["background"] != "#ffffff":
        parts["background_color"] = sty["background"]
    if "vertical-align" in sty:
        va = sty["vertical-align"]
        if va in ("top", "middle", "bottom"):
            parts["vertical_align"] = va
    if "padding" in sty:
        pad_parts = sty["padding"].split()
        sides = ["top", "right", "bottom", "left"]
        for i, s in enumerate(sides):
            if i < len(pad_parts):
                parts[f"padding_{s}"] = _parse_pt(pad_parts[i])
    return CellFormat(**parts) if parts else None


def _node_to_block(
    node: _Node,
    counter: itertools.count[int],
) -> Block | None:
    tag = node.tag.lower()
    bid = node.get("data-bid") or make_block_id(next(counter))
    sty = _parse_style(node.get("style"))

    # --- Paragraph ---
    if tag == "p":
        if _is_equation_block(node):
            text = _collect_text(node).strip()
            latex = text[2:-2].strip()
            return EquationBlock(type="equation", id=bid, latex=latex)

        text = _collect_text(node)
        if text.strip() in ("", "\xa0"):
            fmt = _parse_block_format(sty)
            return ParagraphBlock(type="paragraph", id=bid, inlines=[], format=fmt)

        inlines = _extract_inlines(node)
        fmt = _parse_block_format(sty)
        return ParagraphBlock(type="paragraph", id=bid, inlines=inlines, format=fmt)

    # --- Heading ---
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag[1])
        inlines = _extract_inlines(node)
        has_bid = bool(node.get("data-bid"))
        if has_bid:
            inlines = _strip_autonumber_inlines(inlines)
        text = "".join(
            il.text for il in inlines if isinstance(il, TextInline)
        ).strip()
        fmt = _parse_block_format(sty)
        return HeadingBlock(
            type="heading", id=bid, level=level, text=text,
            inlines=inlines, format=fmt,
        )

    # --- Table ---
    if tag == "table":
        return _parse_table_node(node, bid, counter)

    # --- Image (block-level, wrapped in div or standalone) ---
    if tag == "img":
        return _parse_image_node(node, bid)

    # --- Div containers ---
    if tag == "div":
        if _is_skip_div(node):
            return None

        cls = node.get("class", "")
        # Footnote
        if "fn" in cls:
            return _parse_footnote_node(node, bid, counter)

        # Check for image wrapper: <div style="text-align:center"><img></div>
        if sty.get("text-align") == "center":
            imgs = [c for c in node.children if c.tag == "img"]
            if imgs:
                return _parse_image_node(imgs[0], bid)

        # TextBoxBlock: padding/border pattern with inner content
        if _is_textbox_div(sty):
            inner = _extract_content_blocks(node, counter)
            pos = _parse_position_info(sty)
            return TextBoxBlock(
                type="text_box", id=bid, content=inner,
                position=pos,
                background_color=sty.get("background"),
            )

        # DrawingBlock: position:absolute
        if sty.get("position") == "absolute":
            pos = _parse_position_info(sty)
            return DrawingBlock(
                type="drawing", id=bid, position=pos,
                background_color=sty.get("background"),
            )

        inner_blocks = _extract_content_blocks(node, counter)
        if inner_blocks:
            if len(inner_blocks) == 1:
                return inner_blocks[0]
        return None

    return None


def _parse_table_node(
    node: _Node,
    bid: str,
    counter: itertools.count[int],
) -> TableBlock:
    sty = _parse_style(node.get("style"))
    rows: list[TableRow] = []

    for tr in node.children:
        if tr.tag.lower() != "tr":
            continue
        cells: list[TableCell] = []
        for td in tr.children:
            if td.tag.lower() not in ("td", "th"):
                continue
            td_sty = _parse_style(td.get("style"))

            row_span = 1
            col_span = 1
            if td.get("rowspan"):
                try:
                    row_span = int(td.get("rowspan"))
                except ValueError:
                    pass
            if td.get("colspan"):
                try:
                    col_span = int(td.get("colspan"))
                except ValueError:
                    pass

            # Cell width
            width = 0.0
            if "width" in td_sty:
                width = _parse_pt(td_sty["width"])

            # Cell height
            height = 0.0
            if "height" in td_sty:
                height = _parse_pt(td_sty["height"])

            cell_fmt = _parse_cell_format(td_sty)

            # Cell content: paragraphs, images, equations
            content = _extract_cell_content(td, counter)

            cells.append(TableCell(
                id=make_block_id(next(counter)),
                content=content,
                row_span=row_span,
                col_span=col_span,
                width=width or None,
                height=height or None,
                format=cell_fmt,
            ))
        if cells:
            rows.append(TableRow(cells=cells))

    return TableBlock(type="table", id=bid, rows=rows)


def _extract_cell_content(
    td: _Node,
    counter: itertools.count[int],
) -> list[Block]:
    """테이블 셀 내부 콘텐츠를 블록으로 추출.

    셀 내부에는 래핑 태그 없이 인라인 콘텐츠가 직접 올 수 있으므로,
    자식 노드가 없거나 텍스트만 있으면 단일 ParagraphBlock으로 처리.
    """
    blocks: list[Block] = []

    # 자식이 블록 레벨 요소인지 확인
    block_tags = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "table", "div"}
    has_block_children = any(c.tag.lower() in block_tags for c in td.children)

    if has_block_children:
        for child in td.children:
            if child.tag.lower() in block_tags:
                blk = _node_to_block(child, counter)
                if blk:
                    blocks.append(blk)
            elif child.tag.lower() == "img":
                blk = _parse_image_node(child, make_block_id(next(counter)))
                if blk:
                    blocks.append(blk)
    else:
        inlines = _extract_inlines(td)
        if inlines or td.text.strip():
            blocks.append(ParagraphBlock(
                type="paragraph",
                id=make_block_id(next(counter)),
                inlines=inlines if inlines else [],
            ))

    if not blocks:
        blocks.append(ParagraphBlock(
            type="paragraph",
            id=make_block_id(next(counter)),
            inlines=[],
        ))

    return blocks


def _parse_image_node(node: _Node, bid: str) -> ImageBlock | None:
    src = node.get("src")
    if not src:
        return None
    alt = node.get("alt")
    sty = _parse_style(node.get("style"))

    w = _parse_pt(sty.get("width")) if "width" in sty else None
    h = _parse_pt(sty.get("height")) if "height" in sty else None

    pos = PositionInfo(width=w, height=h) if w or h else None

    return ImageBlock(type="image", id=bid, src=src, alt=alt, position=pos)


def _parse_footnote_node(
    node: _Node,
    bid: str,
    counter: itertools.count[int],
) -> FootnoteBlock:
    fn_id = node.get("id", "")
    ref = fn_id.replace("fn-", "") if fn_id.startswith("fn-") else fn_id

    content: list[Block] = []
    for child in node.children:
        if child.tag.lower() == "sup":
            continue
        blk = _node_to_block(child, counter)
        if blk:
            content.append(blk)

    if not content:
        text = _collect_text(node).strip()
        if ref and text.startswith(ref):
            text = text[len(ref):].strip()
        if text:
            content.append(ParagraphBlock(
                type="paragraph",
                id=make_block_id(next(counter)),
                inlines=[TextInline(text=text)],
            ))

    return FootnoteBlock(type="footnote", id=bid, ref=ref, content=content)


def _extract_content_blocks(
    parent: _Node,
    counter: itertools.count[int],
) -> list[Block]:
    """페이지/콘텐츠 div에서 블록을 추출."""
    blocks: list[Block] = []
    for child in parent.children:
        blk = _node_to_block(child, counter)
        if blk:
            blocks.append(blk)
    return blocks


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def parse_html(html: str) -> UdfDocument:
    """Parse an HTML string into a UdfDocument.

    Designed to round-trip HTML produced by the UDF HTML renderer.
    The verbatim layer is empty since no original binary data exists.

    Parameters
    ----------
    html : str
        HTML string (typically output of ``render_html()``).

    Returns
    -------
    UdfDocument
        Parsed document with blocks extracted from the HTML DOM.
    """
    dom = _build_dom(html)
    counter: itertools.count[int] = itertools.count(1)
    blocks: list[Block] = []

    # body > div.page > div.content 구조에서 콘텐츠 추출
    body_nodes = dom.find_all("body")
    if not body_nodes:
        body_nodes = [dom]

    for body in body_nodes:
        page_divs = [
            c for c in body.children
            if c.tag == "div" and "page" in (c.get("class", ""))
        ]
        if not page_divs:
            page_divs = [body]

        for page in page_divs:
            content_divs = [
                c for c in page.children
                if c.tag == "div" and "content" in (c.get("class", ""))
            ]
            if not content_divs:
                content_divs = [page]

            for content in content_divs:
                blocks.extend(_extract_content_blocks(content, counter))

    return UdfDocument(
        source_format="html",
        document=DocumentSchema(
            metadata=DocumentMetadata(),
            blocks=blocks,
        ),
        verbatim=VerbatimLayer(format="html"),
    )
