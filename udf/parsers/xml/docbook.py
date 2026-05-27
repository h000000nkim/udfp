"""DocBook 5.x XML to document blocks converter."""

from __future__ import annotations

import itertools

from lxml import etree

from udf.core.ids import make_block_id
from udf.schema import (
    Block,
    BlockFormat,
    CodeBlock,
    EquationBlock,
    FootnoteBlock,
    HeadingBlock,
    ImageBlock,
    Inline,
    LinkInline,
    ListBlock,
    ListItem,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextInline,
    UnknownBlock,
)

_NS = "http://docbook.org/ns/docbook"
_XLINK = "http://www.w3.org/1999/xlink"


def _tag(local: str) -> str:
    return f"{{{_NS}}}{local}"


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_docbook(
    root: etree._Element,
    counter: itertools.count[int],
) -> list[Block]:
    """Parse a DocBook 5.x XML tree into document blocks.

    Handles standard DocBook elements: sections, paragraphs, tables,
    lists, figures, code listings, footnotes, equations, etc.

    Parameters
    ----------
    root : etree._Element
        Root element of the DocBook XML (e.g. ``<book>`` or ``<article>``).
    counter : itertools.count[int]
        Shared counter for generating unique block IDs.

    Returns
    -------
    list[Block]
        Extracted document blocks.
    """
    return _parse_children(root, counter, depth=0)


def _parse_children(
    parent: etree._Element,
    counter: itertools.count[int],
    depth: int,
) -> list[Block]:
    blocks: list[Block] = []
    for child in parent:
        if isinstance(child, etree._Comment) or not isinstance(child.tag, str):
            continue
        block = _element_to_block(child, counter, depth)
        if block is not None:
            if isinstance(block, list):
                blocks.extend(block)
            else:
                blocks.append(block)
    return blocks


def _element_to_block(
    el: etree._Element,
    counter: itertools.count[int],
    depth: int,
) -> Block | list[Block] | None:
    local = _local(el.tag)

    if local == "info":
        return None

    if local == "section":
        return _parse_section(el, counter, depth + 1)

    if local == "title":
        return _parse_title(el, counter, depth)

    if local == "para" or local == "simpara":
        return _parse_para(el, counter)

    if local in ("programlisting", "screen", "literallayout"):
        return _parse_code(el, counter, local)

    if local == "blockquote":
        return _parse_blockquote(el, counter, depth)

    if local in ("itemizedlist", "orderedlist", "variablelist"):
        return _parse_list(el, counter, local)

    if local in ("table", "informaltable"):
        return _parse_table(el, counter)

    if local in ("figure", "informalfigure"):
        return _parse_figure(el, counter)

    if local == "mediaobject":
        return _parse_mediaobject(el, counter)

    if local in ("equation", "informalequation"):
        return _parse_equation(el, counter)

    if local == "footnote":
        return _parse_footnote(el, counter, depth)

    if local in ("chapter", "part", "preface", "appendix", "article", "book"):
        return _parse_children(el, counter, depth)

    if _has_block_children(el):
        return _parse_children(el, counter, depth)

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
    block_tags = {
        "para", "simpara", "section", "table", "informaltable",
        "programlisting", "screen", "itemizedlist", "orderedlist",
        "blockquote", "figure", "mediaobject", "equation",
    }
    for child in el:
        if isinstance(child, etree._Comment) or not isinstance(child.tag, str):
            continue
        if _local(child.tag) in block_tags:
            return True
    return False


# --- Section / Title ---

def _parse_section(
    el: etree._Element,
    counter: itertools.count[int],
    depth: int,
) -> list[Block]:
    return _parse_children(el, counter, depth)


def _parse_title(
    el: etree._Element,
    counter: itertools.count[int],
    depth: int,
) -> HeadingBlock:
    bid = make_block_id(next(counter))
    level = min(max(depth, 1), 6)
    inlines = _extract_inlines(el)
    text = _text_content(el).strip()
    return HeadingBlock(
        type="heading", id=bid, level=level, text=text, inlines=inlines,
    )


# --- Paragraph ---

def _parse_para(
    el: etree._Element,
    counter: itertools.count[int],
) -> ParagraphBlock:
    bid = make_block_id(next(counter))
    inlines = _extract_inlines(el)
    return ParagraphBlock(type="paragraph", id=bid, inlines=inlines)


# --- Code ---

def _parse_code(
    el: etree._Element,
    counter: itertools.count[int],
    local: str,
) -> CodeBlock:
    bid = make_block_id(next(counter))
    lang = el.get("language")
    code = _text_content(el)
    return CodeBlock(type="code", id=bid, language=lang, code=code)


# --- Blockquote ---

def _parse_blockquote(
    el: etree._Element,
    counter: itertools.count[int],
    depth: int,
) -> QuoteBlock:
    bid = make_block_id(next(counter))
    content = _parse_children(el, counter, depth)
    return QuoteBlock(type="quote", id=bid, content=content)


# --- List ---

def _parse_list(
    el: etree._Element,
    counter: itertools.count[int],
    local: str,
) -> ListBlock:
    bid = make_block_id(next(counter))
    ordered = local == "orderedlist"
    items: list[ListItem] = []
    item_tag = "listitem" if local != "variablelist" else "varlistentry"
    for child in el:
        if _local(child.tag) == item_tag:
            inlines = _extract_inlines_from_children(child)
            items.append(ListItem(id=make_block_id(next(counter)), inlines=inlines))
        elif _local(child.tag) == "listitem":
            inlines = _extract_inlines_from_children(child)
            items.append(ListItem(id=make_block_id(next(counter)), inlines=inlines))
    return ListBlock(type="list", id=bid, ordered=ordered, items=items)


def _extract_inlines_from_children(el: etree._Element) -> list[Inline]:
    parts: list[Inline] = []
    for child in el:
        if _local(child.tag) in ("para", "simpara"):
            parts.extend(_extract_inlines(child))
        elif _local(child.tag) == "term":
            text = _text_content(child).strip()
            if text:
                parts.append(TextInline(text=text, bold=True))
                parts.append(TextInline(text=": "))
    if not parts:
        text = _text_content(el).strip()
        if text:
            parts.append(TextInline(text=text))
    return parts


# --- Table (CALS model) ---

def _parse_table(
    el: etree._Element,
    counter: itertools.count[int],
) -> TableBlock:
    bid = make_block_id(next(counter))
    rows: list[TableRow] = []

    for tgroup in el.iter():
        if _local(tgroup.tag) == "tgroup":
            for body_el in tgroup:
                local = _local(body_el.tag)
                if local in ("thead", "tbody", "tfoot"):
                    for row_el in body_el:
                        if _local(row_el.tag) == "row":
                            rows.append(_parse_row(row_el, counter))
            break
    else:
        for row_el in el.iter():
            if _local(row_el.tag) in ("tr", "row"):
                rows.append(_parse_row(row_el, counter))

    return TableBlock(type="table", id=bid, rows=rows)


def _parse_row(
    row_el: etree._Element,
    counter: itertools.count[int],
) -> TableRow:
    cells: list[TableCell] = []
    for cell_el in row_el:
        local = _local(cell_el.tag)
        if local in ("entry", "td", "th"):
            cid = make_block_id(next(counter))
            content: list[Block] = []
            for child in cell_el:
                if isinstance(child, etree._Comment):
                    continue
                b = _element_to_block(child, counter, depth=1)
                if b is not None:
                    if isinstance(b, list):
                        content.extend(b)
                    else:
                        content.append(b)
            if not content:
                text = _text_content(cell_el).strip()
                if text:
                    pid = make_block_id(next(counter))
                    content.append(ParagraphBlock(
                        type="paragraph", id=pid,
                        inlines=[TextInline(text=text)],
                    ))

            namest = cell_el.get("namest")
            nameend = cell_el.get("nameend")
            colspan = 1
            if namest and nameend:
                try:
                    s = int(namest.replace("col", ""))
                    e = int(nameend.replace("col", ""))
                    colspan = max(1, e - s + 1)
                except ValueError:
                    pass
            morerows = cell_el.get("morerows")
            rowspan = 1 + int(morerows) if morerows and morerows.isdigit() else 1

            cells.append(TableCell(
                id=cid, content=content,
                col_span=colspan, row_span=rowspan,
            ))
    return TableRow(cells=cells)


# --- Image / Figure ---

def _parse_figure(
    el: etree._Element,
    counter: itertools.count[int],
) -> ImageBlock | None:
    for mo in el.iter():
        if _local(mo.tag) == "mediaobject":
            img = _parse_mediaobject(mo, counter)
            if img:
                title_el = el.find(_tag("title"))
                if title_el is not None:
                    img.caption = [TextInline(text=_text_content(title_el).strip())]
                return img
    return None


def _parse_dim(val: str | None) -> float | None:
    if not val:
        return None
    v = val.strip().rstrip("px").rstrip("pt").rstrip("em").strip()
    try:
        return float(v)
    except ValueError:
        return None


def _parse_mediaobject(
    el: etree._Element,
    counter: itertools.count[int],
) -> ImageBlock | None:
    for io in el.iter():
        if _local(io.tag) == "imageobject":
            for id_el in io:
                if _local(id_el.tag) == "imagedata":
                    bid = make_block_id(next(counter))
                    src = id_el.get("fileref") or ""
                    w = _parse_dim(id_el.get("contentwidth") or id_el.get("width"))
                    h = _parse_dim(id_el.get("contentdepth") or id_el.get("depth"))
                    return ImageBlock(
                        type="image", id=bid, src=src,
                        width=w, height=h,
                    )
    return None


# --- Equation ---

def _parse_equation(
    el: etree._Element,
    counter: itertools.count[int],
) -> EquationBlock:
    bid = make_block_id(next(counter))
    text = _text_content(el).strip()
    return EquationBlock(type="equation", id=bid, latex=text or None)


# --- Footnote ---

def _parse_footnote(
    el: etree._Element,
    counter: itertools.count[int],
    depth: int,
) -> FootnoteBlock:
    bid = make_block_id(next(counter))
    content = _parse_children(el, counter, depth)
    return FootnoteBlock(type="footnote", id=bid, content=content)


# --- Inline extraction ---

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
        if local == "emphasis":
            role = child.get("role", "")
            text = _text_content(child)
            if text:
                parts.append(TextInline(
                    text=text,
                    bold=role == "bold" or role == "strong",
                    italic=role != "bold" and role != "strong",
                ))
        elif local in ("link", "ulink"):
            url = child.get(f"{{{_XLINK}}}href") or child.get("url") or ""
            text = _text_content(child)
            if text:
                parts.append(LinkInline(text=text, url=url))
        elif local == "literal" or local == "code":
            text = _text_content(child)
            if text:
                parts.append(TextInline(text=text, font_name="monospace"))
        elif local == "superscript":
            text = _text_content(child)
            if text:
                parts.append(TextInline(text=text, superscript=True))
        elif local == "subscript":
            text = _text_content(child)
            if text:
                parts.append(TextInline(text=text, subscript=True))
        elif local == "footnote":
            pass
        else:
            text = _text_content(child)
            if text:
                parts.append(TextInline(text=text))
        if child.tail:
            parts.append(TextInline(text=child.tail))
    return parts


def _text_content(el: etree._Element) -> str:
    return "".join(el.itertext())
