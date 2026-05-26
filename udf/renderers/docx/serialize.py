"""Document Model → OOXML 직렬화: UdfDocument 블록을 DOCX XML로 변환."""

from __future__ import annotations

import math

from lxml import etree

from udf.core.schema import (
    Block,
    CodeBlock,
    ColumnDef,
    DrawingBlock,
    EndnoteBlock,
    EquationBlock,
    EquationInline,
    FieldBlock,
    FooterBlock,
    FootnoteBlock,
    FootnoteRefInline,
    HeaderBlock,
    HeadingBlock,
    ImageBlock,
    LinkInline,
    ListBlock,
    ListItem,
    PageBreakBlock,
    ParagraphBlock,
    QuoteBlock,
    SectionDef,
    TableBlock,
    TextBoxBlock,
    TextInline,
    UdfDocument,
)

# ---------------------------------------------------------------------------
# OOXML namespaces
# ---------------------------------------------------------------------------

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"

_NSMAP_DOC = {"w": _W, "r": _R}

_REL_TYPE_STYLES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
)
_REL_TYPE_NUMBERING = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
)
_REL_TYPE_IMAGE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)
_REL_TYPE_DOCUMENT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)

_REL_TYPE_HYPERLINK = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
)

_ALIGNMENT_MAP = {
    "left": "left",
    "center": "center",
    "right": "right",
    "justify": "both",
}

_hyperlink_rels: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def blocks_to_document_xml(
    blocks: list[Block],
    doc: UdfDocument | None = None,
    *,
    header_rids: list[str] | None = None,
    footer_rids: list[str] | None = None,
) -> tuple[bytes, dict[str, str]]:
    """Serialize Document Model blocks to word/document.xml bytes.

    Parameters
    ----------
    blocks : list[Block]
        Document blocks to serialize.
    doc : UdfDocument or None
        Full document (for metadata/section definitions).
    header_rids : list[str] or None
        Relationship IDs for header references in sectPr.
    footer_rids : list[str] or None
        Relationship IDs for footer references in sectPr.

    Returns
    -------
    tuple[bytes, dict[str, str]]
        XML bytes and a mapping of relationship IDs to hyperlink URLs.
    """
    _hyperlink_rels.clear()
    root = etree.Element(f"{{{_W}}}document", nsmap=_NSMAP_DOC)
    body = etree.SubElement(root, f"{{{_W}}}body")

    for block in blocks:
        elements = _serialize_block(block)
        for el in elements:
            body.append(el)

    need_sect_pr = (
        (doc and doc.metadata and doc.metadata.sections)
        or header_rids
        or footer_rids
    )
    if need_sect_pr:
        if doc and doc.metadata and doc.metadata.sections:
            sect_pr = _serialize_section_def(doc.metadata.sections[-1])
        else:
            sect_pr = etree.Element(f"{{{_W}}}sectPr")
        _HDR_TYPE_MAP = {0: "default", 1: "even", 2: "first"}
        for i, rid in enumerate(header_rids or []):
            href = etree.SubElement(sect_pr, f"{{{_W}}}headerReference")
            href.set(f"{{{_W}}}type", _HDR_TYPE_MAP.get(i, "default"))
            href.set(f"{{{_R}}}id", rid)
        _FTR_TYPE_MAP = {0: "default", 1: "even", 2: "first"}
        for i, rid in enumerate(footer_rids or []):
            fref = etree.SubElement(sect_pr, f"{{{_W}}}footerReference")
            fref.set(f"{{{_W}}}type", _FTR_TYPE_MAP.get(i, "default"))
            fref.set(f"{{{_R}}}id", rid)
        body.append(sect_pr)

    rels = dict(_hyperlink_rels)
    _hyperlink_rels.clear()
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8"), rels


def build_styles_xml() -> bytes:
    """Generate a minimal styles.xml with Normal and Heading1-6 styles.

    Returns
    -------
    bytes
        UTF-8 encoded XML bytes for word/styles.xml.
    """
    root = etree.Element(f"{{{_W}}}styles", nsmap={"w": _W})

    # Normal style
    normal = etree.SubElement(root, f"{{{_W}}}style")
    normal.set(f"{{{_W}}}type", "paragraph")
    normal.set(f"{{{_W}}}styleId", "Normal")
    normal.set(f"{{{_W}}}default", "1")
    name_el = etree.SubElement(normal, f"{{{_W}}}name")
    name_el.set(f"{{{_W}}}val", "Normal")

    _HEADING_SIZES = {1: 32, 2: 26, 3: 24, 4: 22, 5: 20, 6: 20}

    for lvl in range(1, 7):
        style = etree.SubElement(root, f"{{{_W}}}style")
        style.set(f"{{{_W}}}type", "paragraph")
        style.set(f"{{{_W}}}styleId", f"Heading{lvl}")
        n = etree.SubElement(style, f"{{{_W}}}name")
        n.set(f"{{{_W}}}val", f"heading {lvl}")
        based = etree.SubElement(style, f"{{{_W}}}basedOn")
        based.set(f"{{{_W}}}val", "Normal")
        ppr = etree.SubElement(style, f"{{{_W}}}pPr")
        outline = etree.SubElement(ppr, f"{{{_W}}}outlineLvl")
        outline.set(f"{{{_W}}}val", str(lvl - 1))
        etree.SubElement(ppr, f"{{{_W}}}keepNext")
        spacing = etree.SubElement(ppr, f"{{{_W}}}spacing")
        spacing.set(f"{{{_W}}}before", "240")
        spacing.set(f"{{{_W}}}after", "120")
        rpr = etree.SubElement(style, f"{{{_W}}}rPr")
        sz = etree.SubElement(rpr, f"{{{_W}}}sz")
        sz.set(f"{{{_W}}}val", str(_HEADING_SIZES[lvl] * 2))
        sz_cs = etree.SubElement(rpr, f"{{{_W}}}szCs")
        sz_cs.set(f"{{{_W}}}val", str(_HEADING_SIZES[lvl] * 2))
        etree.SubElement(rpr, f"{{{_W}}}b")
        etree.SubElement(rpr, f"{{{_W}}}bCs")

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_content_types_xml(
    has_footnotes: bool = False,
    has_numbering: bool = False,
    header_count: int = 0,
    footer_count: int = 0,
) -> bytes:
    """Generate [Content_Types].xml for the DOCX package.

    Parameters
    ----------
    has_footnotes : bool, default False
        Include footnotes.xml content type override.
    has_numbering : bool, default False
        Include numbering.xml content type override.
    header_count : int, default 0
        Number of header parts to register.
    footer_count : int, default 0
        Number of footer parts to register.

    Returns
    -------
    bytes
        UTF-8 encoded XML bytes.
    """
    root = etree.Element(f"{{{_CT}}}Types")

    _add_default(root, "rels", "application/vnd.openxmlformats-package.relationships+xml")
    _add_default(root, "xml", "application/xml")
    _add_default(root, "png", "image/png")
    _add_default(root, "jpeg", "image/jpeg")

    _add_override(
        root,
        "/word/document.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    )
    _add_override(
        root,
        "/word/styles.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
    )
    if has_numbering:
        _add_override(
            root,
            "/word/numbering.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml",
        )
    if has_footnotes:
        _add_override(
            root,
            "/word/footnotes.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
        )
    _add_override(
        root,
        "/word/settings.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml",
    )
    _add_override(
        root,
        "/docProps/core.xml",
        "application/vnd.openxmlformats-package.core-properties+xml",
    )
    for i in range(1, header_count + 1):
        _add_override(
            root,
            f"/word/header{i}.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
        )
    for i in range(1, footer_count + 1):
        _add_override(
            root,
            f"/word/footer{i}.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
        )

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_rels_xml() -> bytes:
    """Generate _rels/.rels (top-level package relationships).

    Returns
    -------
    bytes
        UTF-8 encoded XML bytes.
    """
    root = etree.Element(f"{{{_RELS}}}Relationships")
    rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
    rel.set("Id", "rId1")
    rel.set("Type", _REL_TYPE_DOCUMENT)
    rel.set("Target", "word/document.xml")
    rel2 = etree.SubElement(root, f"{{{_RELS}}}Relationship")
    rel2.set("Id", "rId2")
    rel2.set("Type", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties")
    rel2.set("Target", "docProps/core.xml")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_document_rels_xml(
    has_styles: bool = True,
    has_numbering: bool = False,
    image_rels: dict[str, str] | None = None,
    hyperlink_rels: dict[str, str] | None = None,
    header_footer_rels: dict[str, tuple[str, str]] | None = None,
) -> bytes:
    """Generate word/_rels/document.xml.rels.

    Parameters
    ----------
    has_styles : bool, default True
        Include a relationship to styles.xml.
    has_numbering : bool, default False
        Include a relationship to numbering.xml.
    image_rels : dict[str, str] or None
        Mapping of rId to image target path.
    hyperlink_rels : dict[str, str] or None
        Mapping of rId to external hyperlink URL.
    header_footer_rels : dict[str, tuple[str, str]] or None
        Mapping of rId to (relationship type, target) for headers/footers.

    Returns
    -------
    bytes
        UTF-8 encoded XML bytes.
    """
    root = etree.Element(f"{{{_RELS}}}Relationships")
    rid_counter = 1

    if has_styles:
        rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
        rel.set("Id", f"rId{rid_counter}")
        rel.set("Type", _REL_TYPE_STYLES)
        rel.set("Target", "styles.xml")
        rid_counter += 1

    if has_numbering:
        rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
        rel.set("Id", f"rId{rid_counter}")
        rel.set("Type", _REL_TYPE_NUMBERING)
        rel.set("Target", "numbering.xml")
        rid_counter += 1

    rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
    rel.set("Id", f"rId{rid_counter}")
    rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings")
    rel.set("Target", "settings.xml")
    rid_counter += 1

    for rid, target in (image_rels or {}).items():
        rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
        rel.set("Id", rid)
        rel.set("Type", _REL_TYPE_IMAGE)
        rel.set("Target", target)

    for rid, url in (hyperlink_rels or {}).items():
        rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
        rel.set("Id", rid)
        rel.set("Type", _REL_TYPE_HYPERLINK)
        rel.set("Target", url)
        rel.set("TargetMode", "External")

    for rid, (rel_type, target) in (header_footer_rels or {}).items():
        rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
        rel.set("Id", rid)
        rel.set("Type", rel_type)
        rel.set("Target", target)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_numbering_xml(blocks: list[Block]) -> bytes | None:
    """Generate numbering.xml if the document contains list blocks.

    Parameters
    ----------
    blocks : list[Block]
        Document blocks to scan for ListBlock instances.

    Returns
    -------
    bytes or None
        UTF-8 encoded XML bytes, or None if no lists are present.
    """
    has_list = any(isinstance(b, ListBlock) for b in blocks)
    if not has_list:
        return None

    root = etree.Element(f"{{{_W}}}numbering", nsmap={"w": _W})

    # abstractNum for ordered and unordered
    for abs_id, num_fmt, char in [("0", "decimal", "%1."), ("1", "bullet", "•")]:
        abstract = etree.SubElement(root, f"{{{_W}}}abstractNum")
        abstract.set(f"{{{_W}}}abstractNumId", abs_id)
        for ilvl in range(9):
            lvl = etree.SubElement(abstract, f"{{{_W}}}lvl")
            lvl.set(f"{{{_W}}}ilvl", str(ilvl))
            fmt = etree.SubElement(lvl, f"{{{_W}}}numFmt")
            fmt.set(f"{{{_W}}}val", num_fmt)
            txt = etree.SubElement(lvl, f"{{{_W}}}lvlText")
            txt.set(f"{{{_W}}}val", char if num_fmt == "bullet" else f"%{ilvl + 1}.")
            left_twips = 720 * (ilvl + 1)
            ppr = etree.SubElement(lvl, f"{{{_W}}}pPr")
            ind = etree.SubElement(ppr, f"{{{_W}}}ind")
            ind.set(f"{{{_W}}}left", str(left_twips))
            ind.set(f"{{{_W}}}hanging", "360")

    # num elements — assign numId 1=ordered, 2=unordered
    for num_id, abs_id in [("1", "0"), ("2", "1")]:
        num = etree.SubElement(root, f"{{{_W}}}num")
        num.set(f"{{{_W}}}numId", num_id)
        ref = etree.SubElement(num, f"{{{_W}}}abstractNumId")
        ref.set(f"{{{_W}}}val", abs_id)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_header_xml(header_block: HeaderBlock) -> bytes:
    """Serialize a HeaderBlock to word/headerN.xml bytes.

    Parameters
    ----------
    header_block : HeaderBlock
        Header block containing content paragraphs.

    Returns
    -------
    bytes
        UTF-8 encoded XML bytes.
    """
    root = etree.Element(f"{{{_W}}}hdr", nsmap=_NSMAP_DOC)
    for child in header_block.content:
        for el in _serialize_block(child):
            root.append(el)
    if len(root) == 0:
        root.append(_make_empty_paragraph())
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_footer_xml(footer_block: FooterBlock) -> bytes:
    """Serialize a FooterBlock to word/footerN.xml bytes.

    Parameters
    ----------
    footer_block : FooterBlock
        Footer block containing content paragraphs.

    Returns
    -------
    bytes
        UTF-8 encoded XML bytes.
    """
    root = etree.Element(f"{{{_W}}}ftr", nsmap=_NSMAP_DOC)
    for child in footer_block.content:
        for el in _serialize_block(child):
            root.append(el)
    if len(root) == 0:
        root.append(_make_empty_paragraph())
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_footnotes_xml(notes: list[FootnoteBlock]) -> bytes:
    """Serialize a list of FootnoteBlocks to word/footnotes.xml bytes.

    Parameters
    ----------
    notes : list[FootnoteBlock]
        Footnote blocks to serialize.

    Returns
    -------
    bytes
        UTF-8 encoded XML bytes.
    """
    root = etree.Element(f"{{{_W}}}footnotes", nsmap=_NSMAP_DOC)
    for i, note in enumerate(notes, start=1):
        fn = etree.SubElement(root, f"{{{_W}}}footnote")
        fn.set(f"{{{_W}}}id", str(i))
        for child in note.content:
            for el in _serialize_block(child):
                fn.append(el)
        if len(fn) == 0:
            fn.append(_make_empty_paragraph())
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


# ---------------------------------------------------------------------------
# Block serialization
# ---------------------------------------------------------------------------


def _serialize_block(block: Block) -> list[etree._Element]:
    """Convert a single Document Model block to a list of OOXML elements."""
    if isinstance(block, HeadingBlock):
        return [_serialize_heading(block)]
    elif isinstance(block, ParagraphBlock):
        return [_serialize_paragraph(block)]
    elif isinstance(block, TableBlock):
        return [_serialize_table(block)]
    elif isinstance(block, ListBlock):
        return _serialize_list(block)
    elif isinstance(block, PageBreakBlock):
        return [_serialize_page_break()]
    elif isinstance(block, ImageBlock):
        return [_serialize_image_block(block)]
    elif isinstance(block, CodeBlock):
        return [_serialize_code_block(block)]
    elif isinstance(block, QuoteBlock):
        return _serialize_quote_block(block)
    elif isinstance(block, EquationBlock):
        return [_serialize_equation_block(block)]
    elif isinstance(block, (FootnoteBlock, EndnoteBlock)):
        return _serialize_note_block(block)
    elif isinstance(block, TextBoxBlock):
        return _serialize_textbox_block(block)
    elif isinstance(block, (HeaderBlock, FooterBlock)):
        return []
    elif isinstance(block, DrawingBlock):
        return []
    elif isinstance(block, FieldBlock):
        return [_serialize_field_block(block)]
    else:
        return [_make_empty_paragraph()]


def _serialize_heading(block: HeadingBlock) -> etree._Element:
    """Serialize a HeadingBlock to a w:p element with heading style."""
    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    ppr = etree.SubElement(p, f"{{{_W}}}pPr")
    pstyle = etree.SubElement(ppr, f"{{{_W}}}pStyle")
    pstyle.set(f"{{{_W}}}val", f"Heading{block.level}")

    if block.format:
        _apply_ppr_format(ppr, block.format)

    if block.inlines:
        for inline in block.inlines:
            _append_inline(p, inline)
    else:
        # Fallback: use block.text
        r = etree.SubElement(p, f"{{{_W}}}r")
        t = etree.SubElement(r, f"{{{_W}}}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = block.text

    return p


def _serialize_paragraph(block: ParagraphBlock) -> etree._Element:
    """Serialize a ParagraphBlock to a w:p element."""
    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)

    if block.format:
        ppr = etree.SubElement(p, f"{{{_W}}}pPr")
        _apply_ppr_format(ppr, block.format)

    for inline in block.inlines:
        _append_inline(p, inline)

    return p


_DOCX_TOTAL_WIDTH_TWIPS = 9360   # Letter width ≈ 6.5" content area
_MIN_COL_WIDTH_TWIPS = 720       # ≈ 0.5 inch minimum


def _visual_text_len(text: str) -> float:
    """Approximate visual width — CJK chars count 1.8, ASCII 1.0."""
    w = 0.0
    for ch in text:
        cp = ord(ch)
        if 0xAC00 <= cp <= 0xD7A3 or 0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F:
            w += 1.8
        else:
            w += 1.0
    return w


def _auto_col_widths_twips(block: TableBlock, n_cols: int) -> list[int]:
    """Content-proportional column widths in twips with sqrt dampening."""
    if n_cols <= 1:
        return [_DOCX_TOTAL_WIDTH_TWIPS]

    max_w = [0.0] * n_cols
    for row in block.rows:
        for ci, cell in enumerate(row.cells):
            if ci < n_cols:
                text = cell.text_content() if hasattr(cell, "text_content") else ""
                if not text:
                    text = "".join(
                        getattr(i, "text", "") for b in cell.content
                        for i in getattr(b, "inlines", [])
                    )
                max_w[ci] = max(max_w[ci], _visual_text_len(text))

    dampened = [math.sqrt(max(w, 1.0)) for w in max_w]
    total_d = sum(dampened) or 1.0
    widths = [int(d / total_d * _DOCX_TOTAL_WIDTH_TWIPS) for d in dampened]

    for i in range(n_cols):
        if widths[i] < _MIN_COL_WIDTH_TWIPS:
            deficit = _MIN_COL_WIDTH_TWIPS - widths[i]
            widths[i] = _MIN_COL_WIDTH_TWIPS
            above = [(j, widths[j]) for j in range(n_cols)
                     if j != i and widths[j] > _MIN_COL_WIDTH_TWIPS]
            above_total = sum(w for _, w in above) or 1
            for j, w in above:
                widths[j] -= int(deficit * w / above_total)

    diff = _DOCX_TOTAL_WIDTH_TWIPS - sum(widths)
    if diff != 0:
        widths[-1] += diff

    return widths


def _serialize_table(block: TableBlock) -> etree._Element:
    """Serialize a TableBlock to a w:tbl element with rows and cells."""
    tbl = etree.Element(f"{{{_W}}}tbl", nsmap=_NSMAP_DOC)

    tbl_pr = etree.SubElement(tbl, f"{{{_W}}}tblPr")
    has_cell_borders = any(
        cell.format and any(
            getattr(cell.format, f"border_{s}", None)
            for s in ("top", "bottom", "left", "right")
        )
        for row in block.rows for cell in row.cells
    )
    if not has_cell_borders:
        tbl_borders = etree.SubElement(tbl_pr, f"{{{_W}}}tblBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            border = etree.SubElement(tbl_borders, f"{{{_W}}}{side}")
            border.set(f"{{{_W}}}val", "single")
            border.set(f"{{{_W}}}sz", "4")
            border.set(f"{{{_W}}}space", "0")
            border.set(f"{{{_W}}}color", "000000")

    col_count = max((len(row.cells) for row in block.rows), default=1)
    first_row = block.rows[0] if block.rows else None
    has_model_widths = first_row and any(c.width for c in first_row.cells)

    tbl_grid = etree.SubElement(tbl, f"{{{_W}}}tblGrid")
    if has_model_widths and first_row:
        col_widths_twips = [int((c.width or 0) * 20) for c in first_row.cells]
        if all(w == 0 for w in col_widths_twips):
            col_widths_twips = [9360 // col_count] * col_count
        for w in col_widths_twips:
            gc = etree.SubElement(tbl_grid, f"{{{_W}}}gridCol")
            gc.set(f"{{{_W}}}w", str(w))
    else:
        col_widths_twips = _auto_col_widths_twips(block, col_count)
        for w in col_widths_twips:
            gc = etree.SubElement(tbl_grid, f"{{{_W}}}gridCol")
            gc.set(f"{{{_W}}}w", str(w))

    for row in block.rows:
        tr = etree.SubElement(tbl, f"{{{_W}}}tr")
        if row.height:
            trpr = etree.SubElement(tr, f"{{{_W}}}trPr")
            trh = etree.SubElement(trpr, f"{{{_W}}}trHeight")
            trh.set(f"{{{_W}}}val", str(int(row.height * 20)))
            trh.set(f"{{{_W}}}hRule", "atLeast")
        for ci, cell in enumerate(row.cells):
            tc = etree.SubElement(tr, f"{{{_W}}}tc")

            tcpr = etree.SubElement(tc, f"{{{_W}}}tcPr")
            if cell.width:
                cell_w = int(cell.width * 20)
            elif ci < len(col_widths_twips):
                cell_w = col_widths_twips[ci] * cell.col_span
            else:
                cell_w = col_widths_twips[0] * cell.col_span if col_widths_twips else 9360 // col_count
            tcw = etree.SubElement(tcpr, f"{{{_W}}}tcW")
            tcw.set(f"{{{_W}}}w", str(cell_w))
            tcw.set(f"{{{_W}}}type", "dxa")
            if cell.col_span > 1:
                gs = etree.SubElement(tcpr, f"{{{_W}}}gridSpan")
                gs.set(f"{{{_W}}}val", str(cell.col_span))
            if cell.row_span > 1:
                vm = etree.SubElement(tcpr, f"{{{_W}}}vMerge")
                vm.set(f"{{{_W}}}val", "restart")
            if cell.format:
                _apply_cell_format(tcpr, cell.format)

            # Cell content (must have at least one w:p)
            if cell.content:
                for child_block in cell.content:
                    for el in _serialize_block(child_block):
                        tc.append(el)
            else:
                tc.append(_make_empty_paragraph())

    return tbl


def _serialize_list(block: ListBlock) -> list[etree._Element]:
    """Serialize a ListBlock to multiple w:p elements with numbering properties."""
    num_id = "1" if block.ordered else "2"
    elements: list[etree._Element] = []
    for item in block.items:
        elements.append(_serialize_list_item(item, num_id, 0))
        for child in item.children:
            elements.append(_serialize_list_item(child, num_id, 1))
    return elements


def _serialize_list_item(
    item: ListItem, num_id: str, ilvl: int,
) -> etree._Element:
    """Serialize a single list item to a w:p element with numPr."""
    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    ppr = etree.SubElement(p, f"{{{_W}}}pPr")
    num_pr = etree.SubElement(ppr, f"{{{_W}}}numPr")
    ilvl_el = etree.SubElement(num_pr, f"{{{_W}}}ilvl")
    ilvl_el.set(f"{{{_W}}}val", str(ilvl))
    num_id_el = etree.SubElement(num_pr, f"{{{_W}}}numId")
    num_id_el.set(f"{{{_W}}}val", num_id)

    for inline in item.inlines:
        _append_inline(p, inline)

    return p


def _serialize_page_break() -> etree._Element:
    """Serialize a page break as a w:p containing w:br type='page'."""
    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    r = etree.SubElement(p, f"{{{_W}}}r")
    br = etree.SubElement(r, f"{{{_W}}}br")
    br.set(f"{{{_W}}}type", "page")
    return p


def _serialize_image_block(block: ImageBlock) -> etree._Element:
    """Serialize an ImageBlock to a w:p containing w:drawing with wp:inline."""
    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    r = etree.SubElement(p, f"{{{_W}}}r")
    drawing = etree.SubElement(r, f"{{{_W}}}drawing")

    nsmap_wp = {"wp": _WP, "a": _A, "pic": _PIC, "r": _R}
    inline = etree.SubElement(drawing, f"{{{_WP}}}inline", nsmap=nsmap_wp)

    # extent
    cx = "914400"  # 1 inch default
    cy = "914400"
    if block.width:
        cx = str(_pt_to_emu(block.width))
    if block.height:
        cy = str(_pt_to_emu(block.height))
    extent = etree.SubElement(inline, f"{{{_WP}}}extent")
    extent.set("cx", cx)
    extent.set("cy", cy)

    # graphic > graphicData > pic:pic > pic:blipFill > a:blip
    graphic = etree.SubElement(inline, f"{{{_A}}}graphic")
    gd = etree.SubElement(graphic, f"{{{_A}}}graphicData")
    gd.set("uri", _PIC)
    pic = etree.SubElement(gd, f"{{{_PIC}}}pic")
    bf = etree.SubElement(pic, f"{{{_PIC}}}blipFill")
    blip = etree.SubElement(bf, f"{{{_A}}}blip")

    # Extract rId from src if it follows bindata: pattern
    src = block.src or ""
    if src.startswith("bindata:"):
        media_name = src[len("bindata:"):]
        blip.set(f"{{{_R}}}embed", f"rImg_{media_name}")
    else:
        blip.set(f"{{{_R}}}embed", "rId_unknown")

    return p


def _serialize_code_block(block: CodeBlock) -> etree._Element:
    """Serialize a CodeBlock to a w:p with Courier New monospace font."""
    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    r = etree.SubElement(p, f"{{{_W}}}r")
    rpr = etree.SubElement(r, f"{{{_W}}}rPr")
    fonts = etree.SubElement(rpr, f"{{{_W}}}rFonts")
    fonts.set(f"{{{_W}}}ascii", "Courier New")
    fonts.set(f"{{{_W}}}hAnsi", "Courier New")
    t = etree.SubElement(r, f"{{{_W}}}t")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = block.code
    return p


def _serialize_quote_block(block: QuoteBlock) -> list[etree._Element]:
    """Serialize a QuoteBlock by serializing its child blocks directly."""
    elements: list[etree._Element] = []
    for child in block.content:
        elements.extend(_serialize_block(child))
    return elements


def _serialize_equation_block(block: EquationBlock) -> etree._Element:
    """Serialize an EquationBlock to a w:p with equation text as placeholder."""
    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    text = block.latex or block.hwp_script or ""
    if text:
        r = etree.SubElement(p, f"{{{_W}}}r")
        t = etree.SubElement(r, f"{{{_W}}}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = text
    return p


def _serialize_note_block(block: FootnoteBlock | EndnoteBlock) -> list[etree._Element]:
    """Serialize a footnote or endnote block as inline body paragraphs."""
    elements: list[etree._Element] = []
    for child in block.content:
        elements.extend(_serialize_block(child))
    return elements if elements else [_make_empty_paragraph()]


def _serialize_textbox_block(block: TextBoxBlock) -> list[etree._Element]:
    """Serialize a TextBoxBlock by serializing its child blocks inline."""
    elements: list[etree._Element] = []
    for child in block.content:
        elements.extend(_serialize_block(child))
    return elements if elements else [_make_empty_paragraph()]


def _serialize_field_block(block: FieldBlock) -> etree._Element:
    """Serialize a FieldBlock to a w:p with field value or inlines."""
    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    if block.inlines:
        for inline in block.inlines:
            _append_inline(p, inline)
    elif block.value:
        r = etree.SubElement(p, f"{{{_W}}}r")
        t = etree.SubElement(r, f"{{{_W}}}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = block.value
    return p


# ---------------------------------------------------------------------------
# Inline serialization
# ---------------------------------------------------------------------------


def _append_inline(p: etree._Element, inline: object) -> None:
    """Append an inline element (text, link, equation, etc.) to a w:p."""
    if isinstance(inline, TextInline):
        r = etree.SubElement(p, f"{{{_W}}}r")
        rpr = _build_rpr(inline)
        if rpr is not None:
            r.insert(0, rpr)
        t = etree.SubElement(r, f"{{{_W}}}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = inline.text
    elif isinstance(inline, EquationInline):
        r = etree.SubElement(p, f"{{{_W}}}r")
        t = etree.SubElement(r, f"{{{_W}}}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = inline.latex or inline.hwp_script or ""
    elif isinstance(inline, FootnoteRefInline):
        r = etree.SubElement(p, f"{{{_W}}}r")
        rpr = etree.SubElement(r, f"{{{_W}}}rPr")
        etree.SubElement(rpr, f"{{{_W}}}vertAlign").set(f"{{{_W}}}val", "superscript")
        t = etree.SubElement(r, f"{{{_W}}}t")
        t.text = str(inline.number or inline.ref_id)
    elif isinstance(inline, LinkInline):
        url = inline.url or ""
        if url:
            rid = f"rHyp{len(_hyperlink_rels) + 1}"
            _hyperlink_rels[rid] = url
            hl = etree.SubElement(p, f"{{{_W}}}hyperlink", nsmap=_NSMAP_DOC)
            hl.set(f"{{{_R}}}id", rid)
            r = etree.SubElement(hl, f"{{{_W}}}r")
            rpr = etree.SubElement(r, f"{{{_W}}}rPr")
            rs = etree.SubElement(rpr, f"{{{_W}}}rStyle")
            rs.set(f"{{{_W}}}val", "Hyperlink")
            color = etree.SubElement(rpr, f"{{{_W}}}color")
            color.set(f"{{{_W}}}val", "0563C1")
            u = etree.SubElement(rpr, f"{{{_W}}}u")
            u.set(f"{{{_W}}}val", "single")
        else:
            r = etree.SubElement(p, f"{{{_W}}}r")
        t = etree.SubElement(r, f"{{{_W}}}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = inline.text


def _build_rpr(inline: TextInline) -> etree._Element | None:
    """Build a w:rPr element from TextInline formatting. Returns None if no formatting."""
    parts: list[etree._Element] = []

    if inline.bold:
        parts.append(etree.Element(f"{{{_W}}}b"))
    if inline.italic:
        parts.append(etree.Element(f"{{{_W}}}i"))
    if inline.underline:
        u = etree.Element(f"{{{_W}}}u")
        utype = getattr(inline, "underline_type", None) or "single"
        u.set(f"{{{_W}}}val", utype)
        ucolor = getattr(inline, "underline_color", None)
        if ucolor:
            u.set(f"{{{_W}}}color", _strip_hash(ucolor))
        parts.append(u)
    if inline.strikethrough:
        parts.append(etree.Element(f"{{{_W}}}strike"))

    if inline.font_name:
        fonts = etree.Element(f"{{{_W}}}rFonts")
        fonts.set(f"{{{_W}}}ascii", inline.font_name)
        fonts.set(f"{{{_W}}}hAnsi", inline.font_name)
        parts.append(fonts)

    if inline.font_size:
        sz = etree.Element(f"{{{_W}}}sz")
        pt_val = _parse_pt(inline.font_size)
        if pt_val is not None:
            # OOXML font size = half-points
            sz.set(f"{{{_W}}}val", str(int(pt_val * 2)))
            parts.append(sz)

    if inline.color:
        color = etree.Element(f"{{{_W}}}color")
        color.set(f"{{{_W}}}val", _strip_hash(inline.color))
        parts.append(color)

    if inline.background_color:
        shd = etree.Element(f"{{{_W}}}shd")
        shd.set(f"{{{_W}}}val", "clear")
        shd.set(f"{{{_W}}}fill", _strip_hash(inline.background_color))
        parts.append(shd)

    if inline.superscript:
        vert = etree.Element(f"{{{_W}}}vertAlign")
        vert.set(f"{{{_W}}}val", "superscript")
        parts.append(vert)
    elif inline.subscript:
        vert = etree.Element(f"{{{_W}}}vertAlign")
        vert.set(f"{{{_W}}}val", "subscript")
        parts.append(vert)

    if inline.small_caps:
        parts.append(etree.Element(f"{{{_W}}}smallCaps"))

    if inline.hidden:
        parts.append(etree.Element(f"{{{_W}}}vanish"))

    if inline.letter_spacing:
        sp = etree.Element(f"{{{_W}}}spacing")
        pt_val = _parse_pt(inline.letter_spacing)
        if pt_val is not None:
            # OOXML spacing = twips (1pt = 20 twips)
            sp.set(f"{{{_W}}}val", str(int(pt_val * 20)))
            parts.append(sp)

    if not parts:
        return None

    rpr = etree.Element(f"{{{_W}}}rPr")
    for el in parts:
        rpr.append(el)
    return rpr


# ---------------------------------------------------------------------------
# Paragraph format helpers
# ---------------------------------------------------------------------------


def _apply_ppr_format(ppr: etree._Element, fmt: object) -> None:
    """Apply BlockFormat properties as w:pPr child elements."""
    from udf.core.schema import BlockFormat

    if not isinstance(fmt, BlockFormat):
        return

    if fmt.alignment and fmt.alignment in _ALIGNMENT_MAP:
        jc = etree.SubElement(ppr, f"{{{_W}}}jc")
        jc.set(f"{{{_W}}}val", _ALIGNMENT_MAP[fmt.alignment])

    has_spacing = fmt.line_spacing or fmt.space_before or fmt.space_after
    if has_spacing:
        spacing = etree.SubElement(ppr, f"{{{_W}}}spacing")
        if fmt.space_before:
            pt = _parse_pt(fmt.space_before)
            if pt is not None:
                spacing.set(f"{{{_W}}}before", str(int(pt * 20)))
        if fmt.space_after:
            pt = _parse_pt(fmt.space_after)
            if pt is not None:
                spacing.set(f"{{{_W}}}after", str(int(pt * 20)))
        if fmt.line_spacing:
            ls = fmt.line_spacing
            if hasattr(ls, "value"):
                # Ratio object: percentage (e.g. Ratio(160) = 160%)
                spacing.set(f"{{{_W}}}line", str(int(ls.value / 100 * 240)))
            elif isinstance(ls, (int, float)):
                # numeric float: fixed pt
                spacing.set(f"{{{_W}}}line", str(int(ls * 20)))
                spacing.set(f"{{{_W}}}lineRule", "exact")
            elif isinstance(ls, str) and ls.endswith("%"):
                try:
                    ratio = float(ls[:-1])
                    spacing.set(f"{{{_W}}}line", str(int(ratio / 100 * 240)))
                except ValueError:
                    pass
            else:
                pt = _parse_pt(ls)
                if pt is not None:
                    spacing.set(f"{{{_W}}}line", str(int(pt * 20)))
                    spacing.set(f"{{{_W}}}lineRule", "exact")

    has_indent = fmt.indent_left or fmt.indent_right or fmt.indent_first
    if has_indent:
        ind = etree.SubElement(ppr, f"{{{_W}}}ind")
        if fmt.indent_left:
            pt = _parse_pt(fmt.indent_left)
            if pt is not None:
                ind.set(f"{{{_W}}}left", str(int(pt * 20)))
        if fmt.indent_right:
            pt = _parse_pt(fmt.indent_right)
            if pt is not None:
                ind.set(f"{{{_W}}}right", str(int(pt * 20)))
        if fmt.indent_first:
            pt = _parse_pt(fmt.indent_first)
            if pt is not None:
                if pt >= 0:
                    ind.set(f"{{{_W}}}firstLine", str(int(pt * 20)))
                else:
                    ind.set(f"{{{_W}}}hanging", str(int(abs(pt) * 20)))

    if fmt.keep_with_next:
        etree.SubElement(ppr, f"{{{_W}}}keepNext")
    if fmt.widow_orphan:
        etree.SubElement(ppr, f"{{{_W}}}widowControl")
    if fmt.page_break_before:
        etree.SubElement(ppr, f"{{{_W}}}pageBreakBefore")

    if fmt.background_color:
        shd = etree.SubElement(ppr, f"{{{_W}}}shd")
        shd.set(f"{{{_W}}}val", "clear")
        shd.set(f"{{{_W}}}fill", _strip_hash(fmt.background_color))

    p_borders_present = any(
        getattr(fmt, f"border_{s}", None) for s in ("top", "bottom", "left", "right")
    )
    if p_borders_present:
        p_bdr = etree.SubElement(ppr, f"{{{_W}}}pBdr")
        for side in ("top", "bottom", "left", "right"):
            val = getattr(fmt, f"border_{side}", None)
            if val:
                _apply_border_side(p_bdr, side, val)

    if hasattr(fmt, "outline_level") and fmt.outline_level is not None:
        ol = etree.SubElement(ppr, f"{{{_W}}}outlineLvl")
        ol.set(f"{{{_W}}}val", str(fmt.outline_level))


def _apply_cell_format(tcpr: etree._Element, fmt: object) -> None:
    """Apply CellFormat properties as w:tcPr child elements."""
    from udf.core.schema import CellFormat

    if not isinstance(fmt, CellFormat):
        return

    borders_present = any(
        getattr(fmt, f"border_{s}", None) for s in ("top", "bottom", "left", "right")
    )
    if borders_present:
        tc_borders = etree.SubElement(tcpr, f"{{{_W}}}tcBorders")
        for side in ("top", "bottom", "left", "right"):
            val = getattr(fmt, f"border_{side}", None)
            if val:
                _apply_border_side(tc_borders, side, val)

    if fmt.background_color:
        shd = etree.SubElement(tcpr, f"{{{_W}}}shd")
        shd.set(f"{{{_W}}}val", "clear")
        shd.set(f"{{{_W}}}fill", _strip_hash(fmt.background_color))

    padding_sides = {
        "top": getattr(fmt, "padding_top", None),
        "bottom": getattr(fmt, "padding_bottom", None),
        "start": getattr(fmt, "padding_left", None),
        "end": getattr(fmt, "padding_right", None),
    }
    if any(v for v in padding_sides.values()):
        tc_mar = etree.SubElement(tcpr, f"{{{_W}}}tcMar")
        for side_name, pv in padding_sides.items():
            if pv:
                pt_val = _to_pt_value(pv)
                if pt_val is not None:
                    m = etree.SubElement(tc_mar, f"{{{_W}}}{side_name}")
                    m.set(f"{{{_W}}}w", str(int(pt_val * 20)))
                    m.set(f"{{{_W}}}type", "dxa")

    if fmt.vertical_align:
        va = etree.SubElement(tcpr, f"{{{_W}}}vAlign")
        val = "center" if fmt.vertical_align == "middle" else fmt.vertical_align
        va.set(f"{{{_W}}}val", val)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _make_empty_paragraph() -> etree._Element:
    """Create an empty w:p element."""
    return etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)


def _parse_pt(value) -> float | None:
    """'12.5pt' → 12.5, or float/int → float, or Ratio → Ratio.value. invalid → None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if hasattr(value, "value"):  # Ratio or similar
        return float(value.value)
    # String parsing (v1 compatibility)
    if isinstance(value, str):
        if value.endswith("pt"):
            try:
                return float(value[:-2])
            except ValueError:
                return None
        if value.endswith("mm"):
            try:
                return float(value[:-2]) * 2.835  # 1mm ≈ 2.835pt
            except ValueError:
                return None
        # Try bare number
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _to_pt_value(val: object) -> float | None:
    """padding 등의 다양한 형식을 pt 숫자로 변환."""
    if isinstance(val, (int, float)):
        return float(val)
    if hasattr(val, "value"):
        return float(val.value)
    if isinstance(val, str):
        s = val.strip()
        if s.endswith("pt"):
            try:
                return float(s[:-2])
            except ValueError:
                return None
        if s.endswith("mm"):
            try:
                return float(s[:-2]) * 2.835
            except ValueError:
                return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


_BORDER_SPEC_RE = __import__("re").compile(
    r"([\d.]+)pt\s+(solid|dashed|dotted|double|none)\s+(#?[0-9a-fA-F]{3,6})"
)


def _apply_border_side(parent: etree._Element, side: str, spec: str) -> None:
    """'0.3pt solid #000000' → <w:{side} val="single" sz="..." color="..."/>"""
    m = _BORDER_SPEC_RE.match(str(spec).strip())
    if not m:
        return
    width_pt = float(m.group(1))
    style = m.group(2)
    color = m.group(3).lstrip("#").upper()
    val_map = {"solid": "single", "dashed": "dashed", "dotted": "dotted", "double": "double", "none": "none"}
    el = etree.SubElement(parent, f"{{{_W}}}{side}")
    el.set(f"{{{_W}}}val", val_map.get(style, "single"))
    el.set(f"{{{_W}}}sz", str(max(1, int(width_pt * 8))))
    el.set(f"{{{_W}}}space", "0")
    el.set(f"{{{_W}}}color", color)


def _strip_hash(color) -> str:
    """Strip leading '#' from a color string or Color object."""
    if color is None:
        return ""
    if hasattr(color, "to_hex"):
        s = color.to_hex()
    else:
        s = str(color)
    return s.lstrip("#").upper()


def _pt_to_emu(pt_val) -> int:
    """Convert a pt value (string or number) to EMU (1pt = 12700 EMU)."""
    pt = _parse_pt(pt_val)
    if pt is None:
        return 914400  # 1 inch fallback
    return int(pt * 12700)


def _add_default(root: etree._Element, ext: str, content_type: str) -> None:
    """Add a Default content type element by file extension."""
    d = etree.SubElement(root, f"{{{_CT}}}Default")
    d.set("Extension", ext)
    d.set("ContentType", content_type)


def _add_override(root: etree._Element, part: str, content_type: str) -> None:
    """Add an Override content type element by part name."""
    o = etree.SubElement(root, f"{{{_CT}}}Override")
    o.set("PartName", part)
    o.set("ContentType", content_type)


# ---------------------------------------------------------------------------
# Section properties serialization
# ---------------------------------------------------------------------------

_BREAK_TYPE_MAP = {
    "next_page": "nextPage",
    "continuous": "continuous",
    "even_page": "evenPage",
    "odd_page": "oddPage",
    "new_column": "nextColumn",
}


def _serialize_section_def(sect: SectionDef) -> etree._Element:
    """Serialize a SectionDef to a w:sectPr element with page size and margins."""
    sect_pr = etree.Element(f"{{{_W}}}sectPr")

    if sect.page_width or sect.page_height or sect.orientation:
        pg_sz = etree.SubElement(sect_pr, f"{{{_W}}}pgSz")
        if sect.page_width:
            pt = _parse_pt(sect.page_width)
            if pt is not None:
                pg_sz.set(f"{{{_W}}}w", str(int(pt * 20)))
        if sect.page_height:
            pt = _parse_pt(sect.page_height)
            if pt is not None:
                pg_sz.set(f"{{{_W}}}h", str(int(pt * 20)))
        if sect.orientation == "landscape":
            pg_sz.set(f"{{{_W}}}orient", "landscape")

    if sect.margins:
        pg_mar = etree.SubElement(sect_pr, f"{{{_W}}}pgMar")
        for attr in ("top", "bottom", "left", "right"):
            val = getattr(sect.margins, attr, None)
            if val:
                pt = _parse_pt(val)
                if pt is not None:
                    pg_mar.set(f"{{{_W}}}{attr}", str(int(pt * 20)))
        if sect.header_margin:
            pt = _parse_pt(sect.header_margin)
            if pt is not None:
                pg_mar.set(f"{{{_W}}}header", str(int(pt * 20)))
        if sect.footer_margin:
            pt = _parse_pt(sect.footer_margin)
            if pt is not None:
                pg_mar.set(f"{{{_W}}}footer", str(int(pt * 20)))
        if sect.gutter:
            pt = _parse_pt(sect.gutter)
            if pt is not None:
                pg_mar.set(f"{{{_W}}}gutter", str(int(pt * 20)))

    if sect.break_type and sect.break_type in _BREAK_TYPE_MAP:
        type_el = etree.SubElement(sect_pr, f"{{{_W}}}type")
        type_el.set(f"{{{_W}}}val", _BREAK_TYPE_MAP[sect.break_type])

    if sect.columns:
        _serialize_column_def(sect_pr, sect.columns)

    return sect_pr


def _serialize_column_def(parent: etree._Element, col: ColumnDef) -> None:
    """Serialize a ColumnDef as a w:cols child element of the parent."""
    cols = etree.SubElement(parent, f"{{{_W}}}cols")
    if col.count > 1:
        cols.set(f"{{{_W}}}num", str(col.count))
    if col.gap:
        pt = _parse_pt(col.gap)
        if pt is not None:
            cols.set(f"{{{_W}}}space", str(int(pt * 20)))
    if col.separator:
        cols.set(f"{{{_W}}}sep", "true")
    if not col.same_width:
        cols.set(f"{{{_W}}}equalWidth", "false")
        for w in col.widths:
            c = etree.SubElement(cols, f"{{{_W}}}col")
            pt = _parse_pt(w)
            if pt is not None:
                c.set(f"{{{_W}}}w", str(int(pt * 20)))


# ---------------------------------------------------------------------------
# Auxiliary XML builders
# ---------------------------------------------------------------------------

_DC = "http://purl.org/dc/elements/1.1/"
_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DCTERMS = "http://purl.org/dc/terms/"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def build_settings_xml() -> bytes:
    """Generate a minimal word/settings.xml with compatibility mode 15.

    Returns
    -------
    bytes
        UTF-8 encoded XML bytes.
    """
    root = etree.Element(f"{{{_W}}}settings", nsmap={"w": _W})
    compat = etree.SubElement(root, f"{{{_W}}}compat")
    cs = etree.SubElement(compat, f"{{{_W}}}compatSetting")
    cs.set(f"{{{_W}}}name", "compatibilityMode")
    cs.set(f"{{{_W}}}uri", "http://schemas.microsoft.com/office/word")
    cs.set(f"{{{_W}}}val", "15")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_core_props_xml(
    title: str = "",
    creator: str = "",
) -> bytes:
    """Generate docProps/core.xml with Dublin Core metadata.

    Parameters
    ----------
    title : str, optional
        Document title.
    creator : str, optional
        Document author/creator.

    Returns
    -------
    bytes
        UTF-8 encoded XML bytes.
    """
    nsmap = {"cp": _CP, "dc": _DC, "dcterms": _DCTERMS, "xsi": _XSI}
    root = etree.Element(f"{{{_CP}}}coreProperties", nsmap=nsmap)
    if title:
        el = etree.SubElement(root, f"{{{_DC}}}title")
        el.text = title
    if creator:
        el = etree.SubElement(root, f"{{{_DC}}}creator")
        el.text = creator
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")
