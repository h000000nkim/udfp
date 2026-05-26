"""Generic XML to document blocks converter (best-effort heuristic)."""

from __future__ import annotations

import itertools

from lxml import etree

from udf.core.ids import make_block_id
from udf.schema import (
    Block,
    CodeBlock,
    HeadingBlock,
    ImageBlock,
    Inline,
    LinkInline,
    ListBlock,
    ListItem,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextInline,
    UnknownBlock,
)


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


_PARA_TAGS = {"p", "para", "paragraph", "simpara", "text", "body"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "title", "heading"}
_CODE_TAGS = {"code", "pre", "listing", "programlisting", "screen"}
_QUOTE_TAGS = {"blockquote", "quote"}
_LIST_TAGS = {"ul", "ol", "list", "itemizedlist", "orderedlist"}
_TABLE_TAGS = {"table", "informaltable"}
_IMAGE_TAGS = {"img", "image"}
_ITEM_TAGS = {"li", "item", "listitem"}
_ROW_TAGS = {"tr", "row"}
_CELL_TAGS = {"td", "th", "entry", "cell"}
_LINK_TAGS = {"a", "link", "ulink"}

_HEADING_LEVEL: dict[str, int] = {
    "h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6,
}


def parse_generic(
    root: etree._Element,
    counter: itertools.count[int],
) -> list[Block]:
    """Parse arbitrary XML into document blocks using tag-name heuristics.

    Recognizes common element names (p, h1-h6, table, ul/ol, img, code,
    etc.) and maps them to the appropriate block types.

    Parameters
    ----------
    root : etree._Element
        Root element of the parsed XML tree.
    counter : itertools.count[int]
        Shared counter for generating unique block IDs.

    Returns
    -------
    list[Block]
        Extracted document blocks.
    """
    return _parse_children(root, counter)


def _parse_children(
    parent: etree._Element,
    counter: itertools.count[int],
) -> list[Block]:
    blocks: list[Block] = []
    for child in parent:
        if isinstance(child, etree._Comment) or not isinstance(child.tag, str):
            continue
        block = _element_to_block(child, counter)
        if block is not None:
            if isinstance(block, list):
                blocks.extend(block)
            else:
                blocks.append(block)
    return blocks


def _element_to_block(
    el: etree._Element,
    counter: itertools.count[int],
) -> Block | list[Block] | None:
    local = _local(el.tag)

    if local in _HEADING_TAGS:
        return _parse_heading(el, counter, local)

    if local in _PARA_TAGS:
        return _parse_para(el, counter)

    if local in _CODE_TAGS:
        return _parse_code(el, counter)

    if local in _LIST_TAGS:
        return _parse_list(el, counter, local)

    if local in _TABLE_TAGS:
        return _parse_table(el, counter)

    if local in _IMAGE_TAGS:
        return _parse_image(el, counter)

    if _has_block_children(el):
        return _parse_children(el, counter)

    text = _text_content(el).strip()
    if text:
        bid = make_block_id(next(counter))
        return ParagraphBlock(
            type="paragraph", id=bid, inlines=[TextInline(text=text)],
        )

    bid = make_block_id(next(counter))
    raw = etree.tostring(el, encoding="unicode")
    return UnknownBlock(type="unknown", id=bid, raw_bytes=raw)


def _has_block_children(el: etree._Element) -> bool:
    known = _PARA_TAGS | _HEADING_TAGS | _CODE_TAGS | _LIST_TAGS | _TABLE_TAGS
    for child in el:
        if isinstance(child, etree._Comment) or not isinstance(child.tag, str):
            continue
        if _local(child.tag) in known:
            return True
    return False


def _parse_heading(
    el: etree._Element,
    counter: itertools.count[int],
    local: str,
) -> HeadingBlock:
    bid = make_block_id(next(counter))
    level = _HEADING_LEVEL.get(local, 1)
    inlines = _extract_inlines(el)
    text = _text_content(el).strip()
    return HeadingBlock(
        type="heading", id=bid, level=level, text=text, inlines=inlines,
    )


def _parse_para(
    el: etree._Element,
    counter: itertools.count[int],
) -> ParagraphBlock:
    bid = make_block_id(next(counter))
    inlines = _extract_inlines(el)
    return ParagraphBlock(type="paragraph", id=bid, inlines=inlines)


def _parse_code(
    el: etree._Element,
    counter: itertools.count[int],
) -> CodeBlock:
    bid = make_block_id(next(counter))
    lang = el.get("language") or el.get("class")
    code = _text_content(el)
    return CodeBlock(type="code", id=bid, language=lang, code=code)


def _parse_list(
    el: etree._Element,
    counter: itertools.count[int],
    local: str,
) -> ListBlock:
    bid = make_block_id(next(counter))
    ordered = local in ("ol", "orderedlist")
    items: list[ListItem] = []
    for child in el:
        if _local(child.tag) in _ITEM_TAGS:
            inlines = _extract_inlines(child)
            if not inlines:
                text = _text_content(child).strip()
                if text:
                    inlines = [TextInline(text=text)]
            items.append(ListItem(id=make_block_id(next(counter)), inlines=inlines))
    return ListBlock(type="list", id=bid, ordered=ordered, items=items)


def _parse_table(
    el: etree._Element,
    counter: itertools.count[int],
) -> TableBlock:
    bid = make_block_id(next(counter))
    rows: list[TableRow] = []
    for desc in el.iter():
        if _local(desc.tag) in _ROW_TAGS:
            cells: list[TableCell] = []
            for cell_el in desc:
                if _local(cell_el.tag) in _CELL_TAGS:
                    cid = make_block_id(next(counter))
                    text = _text_content(cell_el).strip()
                    content: list[Block] = []
                    if text:
                        pid = make_block_id(next(counter))
                        content.append(ParagraphBlock(
                            type="paragraph", id=pid,
                            inlines=[TextInline(text=text)],
                        ))
                    cells.append(TableCell(id=cid, content=content))
            if cells:
                rows.append(TableRow(cells=cells))
    return TableBlock(type="table", id=bid, rows=rows)


def _parse_dim(val: str | None) -> float | None:
    if not val:
        return None
    v = val.strip().rstrip("px").rstrip("pt").rstrip("em").strip()
    try:
        return float(v)
    except ValueError:
        return None


def _parse_image(
    el: etree._Element,
    counter: itertools.count[int],
) -> ImageBlock:
    bid = make_block_id(next(counter))
    src = el.get("src") or el.get("href") or el.get("fileref") or ""
    w = _parse_dim(el.get("width"))
    h = _parse_dim(el.get("height"))
    return ImageBlock(type="image", id=bid, src=src, width=w, height=h)


def _extract_inlines(el: etree._Element) -> list[Inline]:
    parts: list[Inline] = []
    if el.text:
        parts.append(TextInline(text=el.text))
    for child in el:
        if isinstance(child, etree._Comment) or not isinstance(child.tag, str):
            if child.tail:
                parts.append(TextInline(text=child.tail))
            continue
        local = _local(child.tag)
        if local in _LINK_TAGS:
            url = child.get("href") or child.get("url") or ""
            text = _text_content(child)
            if text:
                parts.append(LinkInline(text=text, url=url))
        elif local in ("strong", "b"):
            text = _text_content(child)
            if text:
                parts.append(TextInline(text=text, bold=True))
        elif local in ("em", "i", "emphasis"):
            text = _text_content(child)
            if text:
                parts.append(TextInline(text=text, italic=True))
        elif local in ("code", "tt", "literal"):
            text = _text_content(child)
            if text:
                parts.append(TextInline(text=text, font_name="monospace"))
        else:
            text = _text_content(child)
            if text:
                parts.append(TextInline(text=text))
        if child.tail:
            parts.append(TextInline(text=child.tail))
    return parts


def _text_content(el: etree._Element) -> str:
    return "".join(el.itertext())
