"""HTML to UdfDocument parser.

Parses HTML produced by ``render_html(embed_ids=True)`` back into a
UdfDocument. Block IDs are recovered from ``data-bid`` attributes when
present; otherwise sequential IDs are assigned.
"""

from __future__ import annotations

import itertools
import re
from html.parser import HTMLParser
from typing import Any

from udf.core.ids import make_block_id
from udf.schema import (
    Block,
    BlockFormat,
    BookmarkBlock,
    CellFormat,
    ChartBlock,
    CodeBlock,
    CodeInline,
    CommentBlock,
    DocumentMetadata,
    DocumentSchema,
    DrawingBlock,
    EndnoteBlock,
    EndnoteRefInline,
    EquationBlock,
    EquationInline,
    FieldBlock,
    FooterBlock,
    FootnoteBlock,
    FootnoteRefInline,
    HeaderBlock,
    HeadingBlock,
    HorizontalRuleBlock,
    ImageBlock,
    ImageInline,
    Inline,
    LinkInline,
    ListBlock,
    ListItem,
    PageBreakBlock,
    ParagraphBlock,
    PositionInfo,
    QuoteBlock,
    Ratio,
    RubyInline,
    TableBlock,
    TableCell,
    TableRow,
    TextArtBlock,
    TextBoxBlock,
    TextInline,
    UnknownBlock,
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
        if tag not in ("br", "img", "hr", "meta", "link", "input"):
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
            cls = child.get("class", "")
            if "field" in cls:
                ft = child.get("data-field-type", "")
                ft_text = _collect_text(child).strip()
                result.append(TextInline(text=ft_text, font_name=font_name,
                                         font_size=_parse_pt(font_size) if font_size else None,
                                         color=color))
                if child.tail:
                    _append_text_parts(result, child.tail, bold, italic, underline, strike,
                                       font_name, font_size, color)
                continue
            text_extras = _extract_text_extras(sty, cls)
            if text_extras:
                child_inlines = _extract_inlines(
                    child, bold=nb, italic=ni, underline=nu, strike=ns,
                    font_name=nfn, font_size=nfs, color=nc,
                )
                result.extend(
                    _apply_text_extras(il, text_extras) if isinstance(il, TextInline) else il
                    for il in child_inlines
                )
                if child.tail:
                    _append_text_parts(result, child.tail, bold, italic, underline, strike,
                                       font_name, font_size, color)
                continue
        elif tag == "code":
            code_text = _collect_text(child)
            result.append(CodeInline(code=code_text))
            if child.tail:
                _append_text_parts(result, child.tail, bold, italic, underline, strike,
                                   font_name, font_size, color)
            continue
        elif tag == "ruby":
            base = ""
            rt_text = ""
            for rc in child.children:
                if rc.tag.lower() == "rt":
                    rt_text = _collect_text(rc)
                elif rc.tag.lower() not in ("rp",):
                    base += _collect_text(rc)
            if not base:
                base = child.text or ""
            result.append(RubyInline(base_text=base, ruby_text=rt_text))
            if child.tail:
                _append_text_parts(result, child.tail, bold, italic, underline, strike,
                                   font_name, font_size, color)
            continue
        elif tag == "sub":
            sub_inlines = _extract_inlines(
                child, bold=nb, italic=ni, underline=nu, strike=ns,
                font_name=nfn, font_size=nfs, color=nc,
            )
            for si in sub_inlines:
                if isinstance(si, TextInline):
                    si = TextInline(
                        text=si.text, bold=si.bold, italic=si.italic,
                        underline=si.underline, strikethrough=si.strikethrough,
                        subscript=True, font_name=si.font_name,
                        font_size=si.font_size, color=si.color,
                    )
                result.append(si)
            if child.tail:
                _append_text_parts(result, child.tail, bold, italic, underline, strike,
                                   font_name, font_size, color)
            continue
        elif tag == "mark":
            mark_inlines = _extract_inlines(
                child, bold=nb, italic=ni, underline=nu, strike=ns,
                font_name=nfn, font_size=nfs, color=nc,
            )
            for mi in mark_inlines:
                if isinstance(mi, TextInline):
                    mi = TextInline(
                        text=mi.text, bold=mi.bold, italic=mi.italic,
                        underline=mi.underline, strikethrough=mi.strikethrough,
                        font_name=mi.font_name, font_size=mi.font_size,
                        color=mi.color, highlight_color="#ffff00",
                    )
                result.append(mi)
            if child.tail:
                _append_text_parts(result, child.tail, bold, italic, underline, strike,
                                   font_name, font_size, color)
            continue
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
            ref_link = _find_ref_link(child)
            if ref_link:
                ref_cls = ref_link.get("class", "")
                href = ref_link.get("href", "")
                link_text = _collect_text(ref_link).strip()
                if "footnote-ref" in ref_cls or href.startswith("#fn-") or href.startswith("#footnote-"):
                    ref_id = href.lstrip("#").replace("fn-", "").replace("footnote-", "")
                    num = _try_int(link_text)
                    result.append(FootnoteRefInline(ref_id=ref_id, number=num))
                    if child.tail:
                        _append_text_parts(result, child.tail, bold, italic, underline, strike,
                                           font_name, font_size, color)
                    continue
                if "endnote-ref" in ref_cls or href.startswith("#en-") or href.startswith("#endnote-"):
                    ref_id = href.lstrip("#").replace("en-", "").replace("endnote-", "")
                    num = _try_int(link_text)
                    result.append(EndnoteRefInline(ref_id=ref_id, number=num))
                    if child.tail:
                        _append_text_parts(result, child.tail, bold, italic, underline, strike,
                                           font_name, font_size, color)
                    continue
            sup_inlines = _extract_inlines(
                child, bold=nb, italic=ni, underline=nu, strike=ns,
                font_name=nfn, font_size=nfs, color=nc,
            )
            for si in sup_inlines:
                if isinstance(si, TextInline):
                    si = TextInline(
                        text=si.text, bold=si.bold, italic=si.italic,
                        underline=si.underline, strikethrough=si.strikethrough,
                        superscript=True, font_name=si.font_name,
                        font_size=si.font_size, color=si.color,
                    )
                result.append(si)
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


def _extract_text_extras(sty: dict[str, str], cls: str) -> dict[str, Any]:
    """Extract additional TextInline properties from CSS that aren't covered by
    the standard bold/italic/font_name/font_size/color parameters."""
    extras: dict[str, Any] = {}
    if "background-color" in sty:
        extras["highlight_color"] = sty["background-color"]
    if "letter-spacing" in sty:
        v = sty["letter-spacing"]
        if v.endswith("em"):
            try:
                extras["letter_spacing"] = float(v[:-2]) * 100
            except ValueError:
                pass
    if "font-variant" in sty and "small-caps" in sty["font-variant"]:
        extras["small_caps"] = True
    if "text-transform" in sty and sty["text-transform"] == "uppercase":
        extras["all_caps"] = True
    if "direction" in sty and sty["direction"] == "rtl":
        extras["rtl"] = True
    if "-webkit-text-stroke" in sty:
        extras["outline"] = True
    if "text-shadow" in sty:
        shadow_val = sty["text-shadow"]
        if "#fff" in shadow_val and "#888" in shadow_val:
            if shadow_val.startswith("1px 1px"):
                extras["emboss"] = True
            else:
                extras["engrave"] = True
        else:
            extras["shadow"] = True
    if "text-emphasis" in sty:
        te = sty["text-emphasis"]
        mark_map = {"dot": "dot", "circle": "circle"}
        extras["emphasis_mark"] = mark_map.get(te, te)
    if "transform" in sty:
        m = re.match(r"scaleX\(([0-9.]+)\)", sty["transform"])
        if m:
            extras["char_scale"] = Ratio(float(m.group(1)) * 100)
    va = sty.get("vertical-align", "")
    if va.endswith("em") and va != "middle":
        try:
            extras["char_offset"] = float(va[:-2]) * 100
        except ValueError:
            pass
    if "text-decoration-style" in sty:
        extras["underline_type"] = sty["text-decoration-style"]
    if "text-decoration-color" in sty:
        extras["underline_color"] = sty["text-decoration-color"]
    if "display" in sty and sty["display"] == "none":
        extras["hidden"] = True
    if "hidden" in cls:
        extras["hidden"] = True
    return extras


def _apply_text_extras(il: TextInline, extras: dict[str, Any]) -> TextInline:
    """Apply extra CSS-derived properties to a TextInline."""
    d = il.model_dump(exclude_none=True)
    d.pop("type", None)
    d.update(extras)
    return TextInline(**d)


def _try_int(s: str) -> int | None:
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _find_ref_link(node: _Node) -> _Node | None:
    """Find a footnote/endnote reference link inside a sup element."""
    for c in node.children:
        if c.tag.lower() == "a":
            return c
        found = _find_ref_link(c)
        if found:
            return found
    return None


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
    if "margin-left" in sty:
        parts["indent_left"] = _parse_pt(sty["margin-left"])
    elif "padding-left" in sty:
        parts["indent_left"] = _parse_pt(sty["padding-left"])
    if "margin-right" in sty:
        parts["indent_right"] = _parse_pt(sty["margin-right"])
    elif "padding-right" in sty:
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

    # --- Figure (image with optional caption) ---
    if tag == "figure":
        return _parse_figure_node(node, bid, counter)

    # --- List ---
    if tag in ("ul", "ol"):
        return _parse_list_node(node, bid, tag == "ol", counter)

    # --- Code block ---
    if tag == "pre":
        return _parse_pre_node(node, bid)

    # --- Quote ---
    if tag == "blockquote":
        inner = _extract_content_blocks(node, counter)
        return QuoteBlock(type="quote", id=bid, content=inner)

    # --- Horizontal rule ---
    if tag == "hr":
        return HorizontalRuleBlock(type="horizontal_rule", id=bid)

    # --- Aside (footnote, endnote, comment, or generic) ---
    if tag == "aside":
        return _parse_aside_node(node, bid, counter)

    # --- Header / Footer (document-level, not site chrome) ---
    if tag == "header":
        role = node.get("role", "")
        if role == "banner" or "doc-header" in node.get("class", ""):
            inner = _extract_content_blocks(node, counter)
            return HeaderBlock(type="header", id=bid, content=inner)
    if tag == "footer":
        role = node.get("role", "")
        if role == "contentinfo" or "doc-footer" in node.get("class", ""):
            inner = _extract_content_blocks(node, counter)
            return FooterBlock(type="footer", id=bid, content=inner)

    # --- Div containers ---
    if tag == "div":
        if _is_skip_div(node):
            return None

        cls = node.get("class", "")

        # UDF renderer patterns (class-based detection)
        if "page-break" in cls:
            return PageBreakBlock(type="page_break", id=bid)
        if "text-art" in cls:
            text = _collect_text(node).strip()
            return TextArtBlock(type="text_art", id=bid, text=text)
        if "equation" in cls:
            text = _collect_text(node).strip()
            if text.startswith("$$") and text.endswith("$$"):
                text = text[2:-2].strip()
            return EquationBlock(type="equation", id=bid, latex=text)
        if "drawing" in cls:
            pos = _parse_position_info(sty)
            inner = _extract_content_blocks(node, counter) if node.children else []
            return DrawingBlock(
                type="drawing", id=bid, position=pos,
                background_color=sty.get("background-color") or sty.get("background"),
                content=inner or None,
            )
        if "unknown" in cls:
            desc = node.get("data-description", "")
            return UnknownBlock(type="unknown", id=bid, description=desc)

        # Footnote
        if "fn" in cls or "footnote" in cls:
            return _parse_footnote_node(node, bid, counter)

        # Check for image wrapper: <div style="text-align:center"><img></div>
        if sty.get("text-align") == "center":
            imgs = [c for c in node.children if c.tag == "img"]
            if imgs:
                return _parse_image_node(imgs[0], bid)

        # TextBoxBlock: padding/border pattern or class-based
        if "text-box" in cls or _is_textbox_div(sty):
            inner = _extract_content_blocks(node, counter)
            pos = _parse_position_info(sty)
            return TextBoxBlock(
                type="text_box", id=bid, content=inner,
                position=pos,
                background_color=sty.get("background-color") or sty.get("background"),
            )

        # DrawingBlock: position:absolute
        if sty.get("position") == "absolute":
            pos = _parse_position_info(sty)
            return DrawingBlock(
                type="drawing", id=bid, position=pos,
                background_color=sty.get("background-color") or sty.get("background"),
            )

        # Generic div: unwrap children
        inner_blocks = _extract_content_blocks(node, counter)
        if inner_blocks:
            if len(inner_blocks) == 1:
                return inner_blocks[0]
        return None

    # --- Anchor (bookmark) ---
    if tag == "a":
        cls = node.get("class", "")
        if "bookmark" in cls:
            name = node.get("id", "").replace("bm-", "")
            return BookmarkBlock(type="bookmark", id=bid, name=name)

    return None


def _parse_table_node(
    node: _Node,
    bid: str,
    counter: itertools.count[int],
) -> TableBlock:
    _parse_style(node.get("style"))
    rows: list[TableRow] = []

    tr_nodes: list[_Node] = []
    for child in node.children:
        if child.tag.lower() in ("thead", "tbody", "tfoot"):
            for sub in child.children:
                if sub.tag.lower() == "tr":
                    tr_nodes.append(sub)
        elif child.tag.lower() == "tr":
            tr_nodes.append(child)

    for tr in tr_nodes:
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
    block_tags = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "table", "div",
                  "ul", "ol", "pre", "blockquote", "hr", "figure", "aside"}
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
        td_sty = _parse_style(td.get("style"))
        td_fmt = _parse_block_format(td_sty)
        inlines = _extract_inlines(td)
        if "font-style" in td_sty and td_sty["font-style"] == "italic":
            inlines = [
                TextInline(text=il.text, italic=True, **{
                    k: v for k, v in il.model_dump(exclude_none=True).items()
                    if k not in ("text", "type", "italic")
                }) if isinstance(il, TextInline) else il
                for il in inlines
            ]
        if inlines or td.text.strip():
            blocks.append(ParagraphBlock(
                type="paragraph",
                id=make_block_id(next(counter)),
                inlines=inlines if inlines else [],
                format=td_fmt,
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

    has_positioning = any(k in sty for k in ("position", "left", "top"))
    if has_positioning:
        pos = _parse_position_info(sty)
        return ImageBlock(type="image", id=bid, src=src, alt=alt, position=pos)

    return ImageBlock(type="image", id=bid, src=src, alt=alt, width=w, height=h)


def _parse_figure_node(
    node: _Node,
    bid: str,
    counter: itertools.count[int],
) -> Block | None:
    """Parse <figure> containing <img> and optional <figcaption>."""
    cls = node.get("class", "")
    if "chart" in cls:
        desc = node.get("aria-label", "chart")
        return ChartBlock(type="chart", id=bid, description=desc)

    img = None
    caption_inlines: list[Inline] | None = None
    for child in node.children:
        tag = child.tag.lower()
        if tag == "img" and img is None:
            img = child
        elif tag == "figcaption":
            caption_inlines = _extract_inlines(child)

    if img:
        blk = _parse_image_node(img, bid)
        if blk and caption_inlines:
            blk = ImageBlock(
                type="image", id=blk.id, src=blk.src, alt=blk.alt,
                width=blk.width, height=blk.height,
                position=blk.position, caption=caption_inlines,
            )
        return blk

    inner = _extract_content_blocks(node, counter)
    if inner:
        return inner[0]
    return None


def _parse_list_node(
    node: _Node,
    bid: str,
    ordered: bool,
    counter: itertools.count[int],
) -> ListBlock:
    """Parse <ul>/<ol> into ListBlock."""
    start = 1
    if ordered and node.get("start"):
        try:
            start = int(node.get("start"))
        except ValueError:
            pass

    items: list[ListItem] = []
    for child in node.children:
        if child.tag.lower() != "li":
            continue
        items.append(_parse_list_item(child, counter))

    return ListBlock(type="list", id=bid, ordered=ordered, start=start, items=items)


def _parse_list_item(node: _Node, counter: itertools.count[int]) -> ListItem:
    """Parse a single <li> into ListItem."""
    checked: bool | None = None

    for child in node.children:
        if child.tag.lower() == "input" and child.get("type") == "checkbox":
            checked = child.get("checked") is not None
            break

    virtual = _Node("li", {})
    virtual.text = node.text
    for child in node.children:
        tag = child.tag.lower()
        if tag in ("ul", "ol") or (tag == "input" and child.get("type") == "checkbox"):
            if child.tail:
                if virtual.children:
                    virtual.children[-1].tail += child.tail
                else:
                    virtual.text = (virtual.text or "") + child.tail
        else:
            virtual.children.append(child)

    inlines: list[Inline] = _extract_inlines(virtual)
    inlines = [il for il in inlines
               if not (isinstance(il, TextInline) and not il.text.strip())]

    children: list[ListItem] = []
    for child in node.children:
        if child.tag.lower() in ("ul", "ol"):
            for li in child.children:
                if li.tag.lower() == "li":
                    children.append(_parse_list_item(li, counter))

    return ListItem(
        id=make_block_id(next(counter)),
        inlines=inlines, children=children, checked=checked,
    )


def _parse_pre_node(node: _Node, bid: str) -> CodeBlock:
    """Parse <pre><code>...</code></pre> into CodeBlock."""
    code_node = None
    for child in node.children:
        if child.tag.lower() == "code":
            code_node = child
            break

    if code_node:
        code = _collect_text(code_node)
        cls = code_node.get("class", "")
        lang = None
        if cls.startswith("language-"):
            lang = cls[len("language-"):]
    else:
        code = _collect_text(node)
        lang = None

    return CodeBlock(type="code", id=bid, code=code, language=lang)


def _parse_aside_node(
    node: _Node,
    bid: str,
    counter: itertools.count[int],
) -> Block | None:
    """Parse <aside> — footnote, endnote, comment, or skip."""
    cls = node.get("class", "")
    role = node.get("role", "")

    if "footnote" in cls or role == "doc-footnote":
        return _parse_footnote_node(node, bid, counter)

    if "endnote" in cls or role == "doc-endnotes":
        node_id = node.get("id", "")
        ref = node_id.replace("en-", "") if node_id.startswith("en-") else node_id
        content: list[Block] = []
        for child in node.children:
            blk = _node_to_block(child, counter)
            if blk:
                content.append(blk)
        return EndnoteBlock(type="endnote", id=bid, ref=ref, content=content)

    if "comment" in cls or role == "note":
        author = node.get("data-author", "")
        content_blocks: list[Block] = []
        for child in node.children:
            blk = _node_to_block(child, counter)
            if blk:
                content_blocks.append(blk)
        return CommentBlock(type="comment", id=bid, author=author or None, content=content_blocks)

    return None


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


_CONTAINER_TAGS = frozenset(("section", "article", "main", "details"))


def _extract_content_blocks(
    parent: _Node,
    counter: itertools.count[int],
) -> list[Block]:
    """페이지/콘텐츠 div에서 블록을 추출. 컨테이너 태그는 투명하게 통과."""
    blocks: list[Block] = []
    for child in parent.children:
        if child.tag.lower() in _CONTAINER_TAGS:
            blocks.extend(_extract_content_blocks(child, counter))
        else:
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
            if c.tag in ("div", "section") and "page" in (c.get("class", ""))
        ]
        if not page_divs:
            articles = [c for c in body.children if c.tag == "article"]
            page_divs = articles if articles else [body]

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
