"""Document Model → OOXML 직렬화: UdfDocument 블록을 DOCX XML로 변환."""

from __future__ import annotations

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
    HorizontalRuleBlock,
    ImageBlock,
    ImageInline,
    LinkInline,
    ListBlock,
    ListItem,
    PageBreakBlock,
    ParagraphBlock,
    QuoteBlock,
    SectionDef,
    TableBlock,
    TableCell,
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

_NSMAP_DOC = {
    "w": _W,
    "r": _R,
    "wp": _WP,
    "a": _A,
    "pic": _PIC,
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "o": "urn:schemas-microsoft-com:office:office",
    "v": "urn:schemas-microsoft-com:vml",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "wp14": "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
}

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

_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"

_ALIGNMENT_MAP = {
    "left": "left",
    "center": "center",
    "right": "right",
    "justify": "both",
    "distribute": "distribute",
}

_hyperlink_rels: dict[str, str] = {}
_image_rels: dict[str, str] = {}
_page_content_width_twips: int = 9360
_bindata_keys: set[str] = set()

_FONT_MAP: dict[str, str] = {
    "함초롬바탕": "바탕",
    "함초롬돋움": "돋움",
    "한컴바탕": "바탕",
    "한컴돋움": "돋움",
    "한컴산뜻돋움": "맑은 고딕",
    "한컴산뜻바탕": "바탕",
    "한컴소망M": "맑은 고딕",
    "한양신명조": "바탕",
    "한양중고딕": "맑은 고딕",
    "HY헤드라인M": "맑은 고딕",
    "HY신명조": "바탕",
    "HY중고딕": "맑은 고딕",
    "HY울릉도B": "맑은 고딕",
    "휴먼명조": "바탕",
    "휴먼고딕": "돋움",
    "휴먼둥근헤드라인": "맑은 고딕",
    "필기": "궁서",
    "돋움체": "돋움",
    "바탕체": "바탕",
    "굴림체": "굴림",
    "궁서체": "궁서",
}


def _map_font(name: str) -> str:
    return _FONT_MAP.get(name, name)


def _resolve_media_name(name: str) -> str:
    """Resolve bindata name, adding extension from bindata_keys if missing."""
    if name in _bindata_keys:
        return name
    for key in _bindata_keys:
        if key.rsplit(".", 1)[0] == name:
            return key
    return name


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
    tuple[bytes, dict[str, str], dict[str, str]]
        XML bytes, hyperlink relationship IDs, and image relationship IDs.
    """
    global _image_id_counter, _page_content_width_twips
    _hyperlink_rels.clear()
    _image_rels.clear()
    _bindata_keys.clear()
    if doc and doc.verbatim and doc.verbatim.bindata_streams:
        _bindata_keys.update(doc.verbatim.bindata_streams.keys())
    _image_id_counter = 0

    _page_content_width_twips = 9360
    if doc and doc.metadata and doc.metadata.sections:
        sect = doc.metadata.sections[-1]
        pw = sect.page_width or 595.28
        ml = sect.margins.left if sect.margins and sect.margins.left else 56.69
        mr = sect.margins.right if sect.margins and sect.margins.right else 56.69
        _page_content_width_twips = int((pw - ml - mr) * 20)

    root = etree.Element(f"{{{_W}}}document", nsmap=_NSMAP_DOC)
    root.set(f"{{{_MC}}}Ignorable", "w14 wp14 wps")
    body = etree.SubElement(root, f"{{{_W}}}body")

    for block in blocks:
        if isinstance(block, FieldBlock) and block.field_type in ("page_number", "num_pages"):
            continue
        elements = _serialize_block(block)
        for el in elements:
            body.append(el)

    _trim_trailing_empty_paragraphs(body)

    if doc and doc.metadata and doc.metadata.sections:
        sect_pr = _serialize_section_def(doc.metadata.sections[-1])
    else:
        sect_pr = etree.Element(f"{{{_W}}}sectPr")
        pg_sz = etree.SubElement(sect_pr, f"{{{_W}}}pgSz")
        pg_sz.set(f"{{{_W}}}w", "11906")
        pg_sz.set(f"{{{_W}}}h", "16838")
        pg_mar = etree.SubElement(sect_pr, f"{{{_W}}}pgMar")
        pg_mar.set(f"{{{_W}}}top", "1134")
        pg_mar.set(f"{{{_W}}}bottom", "1134")
        pg_mar.set(f"{{{_W}}}left", "1134")
        pg_mar.set(f"{{{_W}}}right", "1134")
        pg_mar.set(f"{{{_W}}}header", "851")
        pg_mar.set(f"{{{_W}}}footer", "851")
        pg_mar.set(f"{{{_W}}}gutter", "0")
        cols = etree.SubElement(sect_pr, f"{{{_W}}}cols")
        cols.set(f"{{{_W}}}space", "425")
        doc_grid = etree.SubElement(sect_pr, f"{{{_W}}}docGrid")
        doc_grid.set(f"{{{_W}}}linePitch", "360")

    if True:
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
    img_rels = dict(_image_rels)
    _image_rels.clear()
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8"), rels, img_rels


def build_styles_xml() -> bytes:
    """Generate styles.xml with docDefaults, Normal, and Heading1-6 styles."""
    _W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
    root = etree.Element(f"{{{_W}}}styles", nsmap={"w": _W, "w14": _W14})

    doc_defaults = etree.SubElement(root, f"{{{_W}}}docDefaults")
    rpr_default = etree.SubElement(doc_defaults, f"{{{_W}}}rPrDefault")
    rpr_def = etree.SubElement(rpr_default, f"{{{_W}}}rPr")
    def_fonts = etree.SubElement(rpr_def, f"{{{_W}}}rFonts")
    def_fonts.set(f"{{{_W}}}ascii", "맑은 고딕")
    def_fonts.set(f"{{{_W}}}eastAsia", "맑은 고딕")
    def_fonts.set(f"{{{_W}}}hAnsi", "맑은 고딕")
    def_fonts.set(f"{{{_W}}}cs", "맑은 고딕")
    kern = etree.SubElement(rpr_def, f"{{{_W}}}kern")
    kern.set(f"{{{_W}}}val", "2")
    def_sz = etree.SubElement(rpr_def, f"{{{_W}}}sz")
    def_sz.set(f"{{{_W}}}val", "22")
    def_szcs = etree.SubElement(rpr_def, f"{{{_W}}}szCs")
    def_szcs.set(f"{{{_W}}}val", "22")
    lang = etree.SubElement(rpr_def, f"{{{_W}}}lang")
    lang.set(f"{{{_W}}}val", "en-US")
    lang.set(f"{{{_W}}}eastAsia", "ko-KR")
    lang.set(f"{{{_W}}}bidi", "ar-SA")

    ppr_default = etree.SubElement(doc_defaults, f"{{{_W}}}pPrDefault")
    ppr_def = etree.SubElement(ppr_default, f"{{{_W}}}pPr")
    def_spacing = etree.SubElement(ppr_def, f"{{{_W}}}spacing")
    def_spacing.set(f"{{{_W}}}after", "160")
    def_spacing.set(f"{{{_W}}}line", "259")
    def_spacing.set(f"{{{_W}}}lineRule", "auto")

    normal = etree.SubElement(root, f"{{{_W}}}style")
    normal.set(f"{{{_W}}}type", "paragraph")
    normal.set(f"{{{_W}}}styleId", "Normal")
    normal.set(f"{{{_W}}}default", "1")
    name_el = etree.SubElement(normal, f"{{{_W}}}name")
    name_el.set(f"{{{_W}}}val", "Normal")
    etree.SubElement(normal, f"{{{_W}}}qFormat")
    normal_ppr = etree.SubElement(normal, f"{{{_W}}}pPr")
    etree.SubElement(normal_ppr, f"{{{_W}}}widowControl")
    normal_rpr = etree.SubElement(normal, f"{{{_W}}}rPr")
    normal_fonts = etree.SubElement(normal_rpr, f"{{{_W}}}rFonts")
    normal_fonts.set(f"{{{_W}}}ascii", "맑은 고딕")
    normal_fonts.set(f"{{{_W}}}hAnsi", "맑은 고딕")
    normal_fonts.set(f"{{{_W}}}eastAsia", "맑은 고딕")

    _HEADING_SIZES = {1: 24, 2: 18, 3: 14, 4: 12, 5: 11, 6: 11}

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
    has_endnotes: bool = False,
    has_font_table: bool = False,
    has_theme: bool = False,
    has_web_settings: bool = False,
    has_app_props: bool = False,
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
    root = etree.Element(f"{{{_CT}}}Types", nsmap={None: _CT})

    _add_default(root, "rels", "application/vnd.openxmlformats-package.relationships+xml")
    _add_default(root, "xml", "application/xml")
    _add_default(root, "png", "image/png")
    _add_default(root, "jpeg", "image/jpeg")
    _add_default(root, "jpg", "image/jpeg")
    _add_default(root, "bmp", "image/bmp")
    _add_default(root, "gif", "image/gif")
    _add_default(root, "tiff", "image/tiff")
    _add_default(root, "emf", "image/x-emf")
    _add_default(root, "wmf", "image/x-wmf")

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
    if has_endnotes:
        _add_override(
            root,
            "/word/endnotes.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml",
        )
    _add_override(
        root,
        "/word/settings.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml",
    )
    if has_font_table:
        _add_override(
            root,
            "/word/fontTable.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml",
        )
    if has_theme:
        _add_override(
            root,
            "/word/theme/theme1.xml",
            "application/vnd.openxmlformats-officedocument.theme+xml",
        )
    if has_web_settings:
        _add_override(
            root,
            "/word/webSettings.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.webSettings+xml",
        )
    _add_override(
        root,
        "/docProps/core.xml",
        "application/vnd.openxmlformats-package.core-properties+xml",
    )
    if has_app_props:
        _add_override(
            root,
            "/docProps/app.xml",
            "application/vnd.openxmlformats-officedocument.extended-properties+xml",
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


def build_rels_xml(has_app_props: bool = False) -> bytes:
    """Generate _rels/.rels (top-level package relationships).

    Returns
    -------
    bytes
        UTF-8 encoded XML bytes.
    """
    root = etree.Element(f"{{{_RELS}}}Relationships", nsmap={None: _RELS})
    rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
    rel.set("Id", "rId1")
    rel.set("Type", _REL_TYPE_DOCUMENT)
    rel.set("Target", "word/document.xml")
    rel2 = etree.SubElement(root, f"{{{_RELS}}}Relationship")
    rel2.set("Id", "rId2")
    rel2.set("Type", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties")
    rel2.set("Target", "docProps/core.xml")
    if has_app_props:
        rel3 = etree.SubElement(root, f"{{{_RELS}}}Relationship")
        rel3.set("Id", "rId3")
        rel3.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties")
        rel3.set("Target", "docProps/app.xml")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_document_rels_xml(
    has_styles: bool = True,
    has_numbering: bool = False,
    has_footnotes: bool = False,
    has_endnotes: bool = False,
    has_font_table: bool = False,
    has_theme: bool = False,
    has_web_settings: bool = False,
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
    root = etree.Element(f"{{{_RELS}}}Relationships", nsmap={None: _RELS})
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

    if has_footnotes:
        rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
        rel.set("Id", f"rId{rid_counter}")
        rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes")
        rel.set("Target", "footnotes.xml")
        rid_counter += 1

    if has_endnotes:
        rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
        rel.set("Id", f"rId{rid_counter}")
        rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes")
        rel.set("Target", "endnotes.xml")
        rid_counter += 1

    if has_font_table:
        rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
        rel.set("Id", f"rId{rid_counter}")
        rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable")
        rel.set("Target", "fontTable.xml")
        rid_counter += 1

    if has_theme:
        rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
        rel.set("Id", f"rId{rid_counter}")
        rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme")
        rel.set("Target", "theme/theme1.xml")
        rid_counter += 1

    if has_web_settings:
        rel = etree.SubElement(root, f"{{{_RELS}}}Relationship")
        rel.set("Id", f"rId{rid_counter}")
        rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/webSettings")
        rel.set("Target", "webSettings.xml")
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
        return _serialize_code_block(block)
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
        return _serialize_drawing_block(block)
    elif isinstance(block, FieldBlock):
        return [_serialize_field_block(block)]
    elif isinstance(block, HorizontalRuleBlock):
        return [_serialize_horizontal_rule()]
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
        _apply_ppr_format(ppr, block.format, suppress_keep_next=True)

    for inline in block.inlines:
        _append_inline(p, inline)

    return p




def _even_col_widths(n_cols: int) -> list[int]:
    """Evenly distribute page content width across *n_cols* columns (twips)."""
    if n_cols <= 0:
        return []
    base = _page_content_width_twips // n_cols
    widths = [base] * n_cols
    # Distribute rounding remainder to the last column
    widths[-1] += _page_content_width_twips - base * n_cols
    return widths


def _serialize_table(block: TableBlock) -> etree._Element:
    """Serialize a TableBlock to a w:tbl element with rows and cells."""
    tbl = etree.Element(f"{{{_W}}}tbl", nsmap=_NSMAP_DOC)

    tbl_pr = etree.SubElement(tbl, f"{{{_W}}}tblPr")
    tbl_w = etree.SubElement(tbl_pr, f"{{{_W}}}tblW")
    tbl_w.set(f"{{{_W}}}w", str(_page_content_width_twips))
    tbl_w.set(f"{{{_W}}}type", "dxa")
    tbl_borders = etree.SubElement(tbl_pr, f"{{{_W}}}tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = etree.SubElement(tbl_borders, f"{{{_W}}}{side}")
        border.set(f"{{{_W}}}val", "single")
        border.set(f"{{{_W}}}sz", "4")
        border.set(f"{{{_W}}}space", "0")
        border.set(f"{{{_W}}}color", "000000")

    # tblLayout placeholder — set after we know whether model widths exist
    _needs_fixed_layout = False

    # --- grid layout: assign each cell a logical column position ----
    n_rows = len(block.rows)
    # merge_cont[(model_row, grid_col)] = col_span of the continuation
    merge_cont: dict[tuple[int, int], int] = {}
    # cell_col[ri] = list of (grid_col, cell) in column order
    cell_col: list[list[tuple[int, "TableCell"]]] = []

    grid_col_count = 0
    for ri, row in enumerate(block.rows):
        cursor = 0
        positions: list[tuple[int, "TableCell"]] = []
        for cell in row.cells:
            while (ri, cursor) in merge_cont:
                cursor += merge_cont[(ri, cursor)]
            positions.append((cursor, cell))
            if cell.row_span > 1:
                for dr in range(1, cell.row_span):
                    tr_idx = ri + dr
                    if tr_idx < n_rows:
                        merge_cont[(tr_idx, cursor)] = cell.col_span
            cursor += cell.col_span
        cell_col.append(positions)
        if cursor > grid_col_count:
            grid_col_count = cursor

    col_count = max(grid_col_count, 1)
    first_row = block.rows[0] if block.rows else None
    has_model_widths = first_row and any(c.width for c in first_row.cells)

    tbl_grid = etree.SubElement(tbl, f"{{{_W}}}tblGrid")
    if has_model_widths and first_row:
        col_widths_twips = [0] * col_count
        for gc_idx, cell in cell_col[0]:
            w_twips = int((cell.width or 0) * 20)
            span = cell.col_span
            per_col = w_twips // span if span else w_twips
            for c in range(span):
                if gc_idx + c < col_count:
                    col_widths_twips[gc_idx + c] = per_col
            remainder = w_twips - per_col * span
            if remainder and gc_idx + span - 1 < col_count:
                col_widths_twips[gc_idx + span - 1] += remainder
        # Fill missing (zero-width) columns proportionally from remaining space
        nonzero = [(i, w) for i, w in enumerate(col_widths_twips) if w > 0]
        zero_idxs = [i for i, w in enumerate(col_widths_twips) if w == 0]
        if zero_idxs:
            used = sum(w for _, w in nonzero)
            remaining = max(_page_content_width_twips - used, 0)
            per_missing = remaining // len(zero_idxs) if zero_idxs else 0
            for i in zero_idxs:
                col_widths_twips[i] = per_missing
            # Distribute rounding remainder to last missing column
            diff = remaining - per_missing * len(zero_idxs)
            if diff and zero_idxs:
                col_widths_twips[zero_idxs[-1]] += diff
        if all(w == 0 for w in col_widths_twips):
            col_widths_twips = _even_col_widths(col_count)
        for w in col_widths_twips:
            gc = etree.SubElement(tbl_grid, f"{{{_W}}}gridCol")
            gc.set(f"{{{_W}}}w", str(w))
    else:
        # No width info (e.g. MD source) — even distribution + fixed layout
        _needs_fixed_layout = True
        col_widths_twips = _even_col_widths(col_count)
        for w in col_widths_twips:
            gc = etree.SubElement(tbl_grid, f"{{{_W}}}gridCol")
            gc.set(f"{{{_W}}}w", str(w))

    # Add fixed table layout when no model widths exist — produces
    # predictable column widths that don't shift based on content.
    if _needs_fixed_layout:
        tbl_layout = etree.SubElement(tbl_pr, f"{{{_W}}}tblLayout")
        tbl_layout.set(f"{{{_W}}}type", "fixed")

    # --- serialize rows, inserting vMerge continuation cells ---------
    for ri, row in enumerate(block.rows):
        tr = etree.SubElement(tbl, f"{{{_W}}}tr")
        if row.height:
            trpr = etree.SubElement(tr, f"{{{_W}}}trPr")
            trh = etree.SubElement(trpr, f"{{{_W}}}trHeight")
            trh.set(f"{{{_W}}}val", str(int(row.height * 20)))
            trh.set(f"{{{_W}}}hRule", "atLeast")

        real_cells = {gc: c for gc, c in cell_col[ri]}
        cursor = 0
        while cursor < col_count:
            if cursor in real_cells:
                cell = real_cells[cursor]
                tc = etree.SubElement(tr, f"{{{_W}}}tc")
                tcpr = etree.SubElement(tc, f"{{{_W}}}tcPr")
                cell_w = sum(col_widths_twips[cursor:cursor + cell.col_span])
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
                if cell.content:
                    for child_block in cell.content:
                        for el in _serialize_block(child_block):
                            tc.append(el)
                else:
                    tc.append(_make_empty_paragraph())
                cursor += cell.col_span
            elif (ri, cursor) in merge_cont:
                cont_span = merge_cont[(ri, cursor)]
                tc = etree.SubElement(tr, f"{{{_W}}}tc")
                tcpr = etree.SubElement(tc, f"{{{_W}}}tcPr")
                cell_w = sum(col_widths_twips[cursor:cursor + cont_span])
                tcw = etree.SubElement(tcpr, f"{{{_W}}}tcW")
                tcw.set(f"{{{_W}}}w", str(cell_w))
                tcw.set(f"{{{_W}}}type", "dxa")
                if cont_span > 1:
                    gs = etree.SubElement(tcpr, f"{{{_W}}}gridSpan")
                    gs.set(f"{{{_W}}}val", str(cont_span))
                vm = etree.SubElement(tcpr, f"{{{_W}}}vMerge")
                tc.append(_make_empty_paragraph())
                cursor += cont_span
            else:
                cursor += 1

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


def _serialize_horizontal_rule() -> etree._Element:
    """Serialize a horizontal rule as a paragraph with a bottom border."""
    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    ppr = etree.SubElement(p, f"{{{_W}}}pPr")
    pbdr = etree.SubElement(ppr, f"{{{_W}}}pBdr")
    bottom = etree.SubElement(pbdr, f"{{{_W}}}bottom")
    bottom.set(f"{{{_W}}}val", "single")
    bottom.set(f"{{{_W}}}sz", "6")
    bottom.set(f"{{{_W}}}space", "1")
    bottom.set(f"{{{_W}}}color", "auto")
    return p


def _serialize_page_break() -> etree._Element:
    """Serialize a page break as a w:p containing w:br type='page'."""
    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    r = etree.SubElement(p, f"{{{_W}}}r")
    br = etree.SubElement(r, f"{{{_W}}}br")
    br.set(f"{{{_W}}}type", "page")
    return p


_image_id_counter = 0


def _serialize_image_block(block: ImageBlock) -> etree._Element:
    """Serialize an ImageBlock to a w:p containing w:drawing."""
    global _image_id_counter
    _image_id_counter += 1
    img_id = _image_id_counter

    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    r = etree.SubElement(p, f"{{{_W}}}r")
    drawing = etree.SubElement(r, f"{{{_W}}}drawing")

    pt_to_emu = 12700
    cx = "914400"
    cy = "914400"
    if block.width:
        cx = str(_pt_to_emu(block.width))
    if block.height:
        cy = str(_pt_to_emu(block.height))

    pos = block.position
    use_anchor = pos is not None and pos.x is not None and pos.y is not None

    if use_anchor:
        wrap_el = etree.SubElement(drawing, f"{{{_WP}}}anchor")
        wrap_el.set("distT", "0")
        wrap_el.set("distB", "0")
        wrap_el.set("distL", "0")
        wrap_el.set("distR", "0")
        wrap_el.set("simplePos", "0")
        wrap_el.set("relativeHeight", "251658240" if pos.flow != "back" else "0")
        wrap_el.set("behindDoc", "1" if pos.flow == "back" else "0")
        wrap_el.set("locked", "0")
        wrap_el.set("layoutInCell", "1")
        wrap_el.set("allowOverlap", "1")

        simple_pos = etree.SubElement(wrap_el, f"{{{_WP}}}simplePos")
        simple_pos.set("x", "0")
        simple_pos.set("y", "0")

        _RELTO_H = {"paper": "page", "page": "page", "column": "column", "paragraph": "column"}
        posH = etree.SubElement(wrap_el, f"{{{_WP}}}positionH")
        posH.set("relativeFrom", _RELTO_H.get(pos.hrelto or "page", "page"))
        posH_off = etree.SubElement(posH, f"{{{_WP}}}posOffset")
        posH_off.text = str(int(_clip_x(pos.x, getattr(block, 'width', None) or 0) * pt_to_emu))

        _RELTO_V = {"paper": "page", "page": "page", "paragraph": "paragraph"}
        posV = etree.SubElement(wrap_el, f"{{{_WP}}}positionV")
        posV.set("relativeFrom", _RELTO_V.get(pos.vrelto or "page", "page"))
        posV_off = etree.SubElement(posV, f"{{{_WP}}}posOffset")
        posV_off.text = str(int(pos.y * pt_to_emu))
    else:
        wrap_el = etree.SubElement(drawing, f"{{{_WP}}}inline")
        wrap_el.set("distT", "0")
        wrap_el.set("distB", "0")
        wrap_el.set("distL", "0")
        wrap_el.set("distR", "0")

    extent = etree.SubElement(wrap_el, f"{{{_WP}}}extent")
    extent.set("cx", cx)
    extent.set("cy", cy)

    eff_ext = etree.SubElement(wrap_el, f"{{{_WP}}}effectExtent")
    eff_ext.set("l", "0")
    eff_ext.set("t", "0")
    eff_ext.set("r", "0")
    eff_ext.set("b", "0")

    if use_anchor:
        etree.SubElement(wrap_el, f"{{{_WP}}}wrapNone")

    doc_pr = etree.SubElement(wrap_el, f"{{{_WP}}}docPr")
    doc_pr.set("id", str(img_id))
    doc_pr.set("name", f"Picture {img_id}")

    # graphic > graphicData > pic:pic
    graphic = etree.SubElement(wrap_el, f"{{{_A}}}graphic")
    gd = etree.SubElement(graphic, f"{{{_A}}}graphicData")
    gd.set("uri", _PIC)
    pic = etree.SubElement(gd, f"{{{_PIC}}}pic")

    # pic:nvPicPr (required)
    nv = etree.SubElement(pic, f"{{{_PIC}}}nvPicPr")
    cnv_pr = etree.SubElement(nv, f"{{{_PIC}}}cNvPr")
    cnv_pr.set("id", str(img_id))
    cnv_pr.set("name", f"Picture {img_id}")
    etree.SubElement(nv, f"{{{_PIC}}}cNvPicPr")

    # pic:blipFill > a:blip + a:stretch
    bf = etree.SubElement(pic, f"{{{_PIC}}}blipFill")
    blip = etree.SubElement(bf, f"{{{_A}}}blip")
    stretch = etree.SubElement(bf, f"{{{_A}}}stretch")
    etree.SubElement(stretch, f"{{{_A}}}fillRect")

    # pic:spPr (required)
    sp_pr = etree.SubElement(pic, f"{{{_PIC}}}spPr")
    xfrm = etree.SubElement(sp_pr, f"{{{_A}}}xfrm")
    off = etree.SubElement(xfrm, f"{{{_A}}}off")
    off.set("x", "0")
    off.set("y", "0")
    ext = etree.SubElement(xfrm, f"{{{_A}}}ext")
    ext.set("cx", cx)
    ext.set("cy", cy)
    prstGeom = etree.SubElement(sp_pr, f"{{{_A}}}prstGeom")
    prstGeom.set("prst", "rect")
    etree.SubElement(prstGeom, f"{{{_A}}}avLst")

    src = block.src or ""
    if src.startswith("bindata:"):
        media_name = _resolve_media_name(src[len("bindata:"):])
        rid = f"rImg_{media_name}"
        blip.set(f"{{{_R}}}embed", rid)
        _image_rels[rid] = f"media/{media_name}"
    else:
        blip.set(f"{{{_R}}}embed", "rId_unknown")

    return p


def _serialize_code_block(block: CodeBlock) -> list[etree._Element]:
    """Serialize a CodeBlock as one w:p per line with Courier New and gray background."""
    code = block.code or ""
    lines = code.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if not lines:
        lines = [""]

    elements: list[etree._Element] = []
    for line in lines:
        p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
        ppr = etree.SubElement(p, f"{{{_W}}}pPr")
        spacing = etree.SubElement(ppr, f"{{{_W}}}spacing")
        spacing.set(f"{{{_W}}}after", "0")
        spacing.set(f"{{{_W}}}line", "240")
        spacing.set(f"{{{_W}}}lineRule", "auto")
        shd = etree.SubElement(ppr, f"{{{_W}}}shd")
        shd.set(f"{{{_W}}}val", "clear")
        shd.set(f"{{{_W}}}fill", "F2F2F2")
        pbdr = etree.SubElement(ppr, f"{{{_W}}}pBdr")
        left_bdr = etree.SubElement(pbdr, f"{{{_W}}}left")
        left_bdr.set(f"{{{_W}}}val", "single")
        left_bdr.set(f"{{{_W}}}sz", "12")
        left_bdr.set(f"{{{_W}}}space", "4")
        left_bdr.set(f"{{{_W}}}color", "CCCCCC")
        ind = etree.SubElement(ppr, f"{{{_W}}}ind")
        ind.set(f"{{{_W}}}left", "360")
        r = etree.SubElement(p, f"{{{_W}}}r")
        rpr = etree.SubElement(r, f"{{{_W}}}rPr")
        fonts = etree.SubElement(rpr, f"{{{_W}}}rFonts")
        fonts.set(f"{{{_W}}}ascii", "Courier New")
        fonts.set(f"{{{_W}}}hAnsi", "Courier New")
        fonts.set(f"{{{_W}}}eastAsia", "Courier New")
        sz = etree.SubElement(rpr, f"{{{_W}}}sz")
        sz.set(f"{{{_W}}}val", "20")
        sz_cs = etree.SubElement(rpr, f"{{{_W}}}szCs")
        sz_cs.set(f"{{{_W}}}val", "20")
        t = etree.SubElement(r, f"{{{_W}}}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = line
        elements.append(p)
    return elements


def _serialize_quote_block(block: QuoteBlock) -> list[etree._Element]:
    """Serialize a QuoteBlock by serializing its child blocks directly."""
    elements: list[etree._Element] = []
    for child in block.content:
        elements.extend(_serialize_block(child))
    return elements


def _serialize_equation_block(block: EquationBlock) -> etree._Element:
    """Serialize an EquationBlock to a w:p containing OMML math."""
    from udf.renderers.docx.latex_to_omml import latex_to_omml_para

    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    latex = block.latex or ""
    if not latex and block.hwp_script:
        try:
            from udf.parsers.hwp.equation import hwp_script_to_latex
            latex = hwp_script_to_latex(block.hwp_script)
        except Exception:
            latex = ""
    if latex:
        try:
            omml_para = latex_to_omml_para(latex)
            p.append(omml_para)
        except Exception:
            r = etree.SubElement(p, f"{{{_W}}}r")
            t = etree.SubElement(r, f"{{{_W}}}t")
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            t.text = latex
    return p


def _serialize_note_block(block: FootnoteBlock | EndnoteBlock) -> list[etree._Element]:
    """Serialize a footnote or endnote block as inline body paragraphs."""
    elements: list[etree._Element] = []
    for child in block.content:
        elements.extend(_serialize_block(child))
    return elements if elements else [_make_empty_paragraph()]


def _serialize_drawing_block_flat(block: DrawingBlock) -> list[etree._Element]:
    """Serialize DrawingBlock content as flat paragraphs (no wrapping shape)."""
    elements: list[etree._Element] = []
    for child in block.content:
        if isinstance(child, DrawingBlock):
            elements.extend(_serialize_drawing_block_flat(child))
        elif isinstance(child, TextBoxBlock):
            for inner in child.content:
                elements.extend(_serialize_block(inner))
        else:
            elements.extend(_serialize_block(child))
    for child_draw in block.children:
        elements.extend(_serialize_drawing_block_flat(child_draw))
    return elements


def _has_drawing_child(el: etree._Element) -> bool:
    """Check if element contains w:drawing (incompatible with txbxContent)."""
    if el.tag == f"{{{_W}}}drawing":
        return True
    return el.find(f".//{{{_W}}}drawing") is not None


def _serialize_drawing_block(block: DrawingBlock) -> list[etree._Element]:
    """Serialize DrawingBlock — as textbox shape if it has visual properties, else inline."""
    child_elements: list[etree._Element] = []
    for child in block.content:
        if isinstance(child, (DrawingBlock, TextBoxBlock)):
            if isinstance(child, DrawingBlock):
                child_elements.extend(_serialize_drawing_block_flat(child))
            else:
                for inner in child.content:
                    child_elements.extend(_serialize_block(inner))
        else:
            child_elements.extend(_serialize_block(child))
    for child_draw in block.children:
        child_elements.extend(_serialize_drawing_block_flat(child_draw))

    if not block.background_color and not block.line_color:
        return child_elements

    txbx_safe: list[etree._Element] = []
    extracted: list[etree._Element] = []
    for el in child_elements:
        if _has_drawing_child(el):
            extracted.append(el)
        else:
            txbx_safe.append(el)

    child_elements = txbx_safe
    if not child_elements:
        child_elements = [_make_empty_paragraph()]

    global _image_id_counter
    _image_id_counter += 1
    tb_id = _image_id_counter
    pt_to_emu = 12700

    pos = block.position
    w_emu = int((pos.width * pt_to_emu)) if pos and pos.width else int(200 * pt_to_emu)
    h_emu = int((pos.height * pt_to_emu)) if pos and pos.height else int(100 * pt_to_emu)

    use_anchor = pos is not None and pos.x is not None and pos.y is not None and not pos.like_char

    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    r = etree.SubElement(p, f"{{{_W}}}r")

    nsmap_mc = {"mc": _MC, "wp": _WP, "a": _A, "wps": _WPS, "w": _W}
    alt = etree.SubElement(r, f"{{{_MC}}}AlternateContent", nsmap=nsmap_mc)
    choice = etree.SubElement(alt, f"{{{_MC}}}Choice")
    choice.set("Requires", "wps")

    drawing = etree.SubElement(choice, f"{{{_W}}}drawing")

    if use_anchor:
        wrap_el = etree.SubElement(drawing, f"{{{_WP}}}anchor")
        wrap_el.set("distT", "0")
        wrap_el.set("distB", "0")
        wrap_el.set("distL", "114300")
        wrap_el.set("distR", "114300")
        wrap_el.set("simplePos", "0")
        wrap_el.set("relativeHeight", str((pos.z_order or 0) + 251658240))
        wrap_el.set("behindDoc", "1" if pos.flow == "back" else "0")
        wrap_el.set("locked", "0")
        wrap_el.set("layoutInCell", "1")
        wrap_el.set("allowOverlap", "1" if pos.overlap_others else "0")

        simple_pos = etree.SubElement(wrap_el, f"{{{_WP}}}simplePos")
        simple_pos.set("x", "0")
        simple_pos.set("y", "0")

        _RELTO_H_MAP = {"paper": "page", "page": "page", "column": "column", "paragraph": "column"}
        posH = etree.SubElement(wrap_el, f"{{{_WP}}}positionH")
        posH.set("relativeFrom", _RELTO_H_MAP.get(pos.hrelto or "page", "page"))
        posH_off = etree.SubElement(posH, f"{{{_WP}}}posOffset")
        posH_off.text = str(int(_clip_x(pos.x, getattr(block, 'width', None) or 0) * pt_to_emu))

        posV = etree.SubElement(wrap_el, f"{{{_WP}}}positionV")
        _RELTO_V_MAP = {"paper": "page", "page": "page", "column": "page", "paragraph": "paragraph"}
        posV.set("relativeFrom", _RELTO_V_MAP.get(pos.vrelto or "page", "page"))
        posV_off = etree.SubElement(posV, f"{{{_WP}}}posOffset")
        posV_off.text = str(int(pos.y * pt_to_emu))
    else:
        wrap_el = etree.SubElement(drawing, f"{{{_WP}}}inline")
        wrap_el.set("distT", "0")
        wrap_el.set("distB", "0")
        wrap_el.set("distL", "0")
        wrap_el.set("distR", "0")

    extent = etree.SubElement(wrap_el, f"{{{_WP}}}extent")
    extent.set("cx", str(w_emu))
    extent.set("cy", str(h_emu))

    eff_ext = etree.SubElement(wrap_el, f"{{{_WP}}}effectExtent")
    eff_ext.set("l", "0")
    eff_ext.set("t", "0")
    eff_ext.set("r", "0")
    eff_ext.set("b", "0")

    if use_anchor:
        etree.SubElement(wrap_el, f"{{{_WP}}}wrapNone")

    doc_pr = etree.SubElement(wrap_el, f"{{{_WP}}}docPr")
    doc_pr.set("id", str(tb_id))
    doc_pr.set("name", f"Shape {tb_id}")

    graphic = etree.SubElement(wrap_el, f"{{{_A}}}graphic")
    gd = etree.SubElement(graphic, f"{{{_A}}}graphicData")
    gd.set("uri", "http://schemas.microsoft.com/office/word/2010/wordprocessingShape")

    wsp = etree.SubElement(gd, f"{{{_WPS}}}wsp")
    cnv = etree.SubElement(wsp, f"{{{_WPS}}}cNvSpPr")
    cnv.set("txBox", "1")

    sp_pr = etree.SubElement(wsp, f"{{{_WPS}}}spPr")
    xfrm = etree.SubElement(sp_pr, f"{{{_A}}}xfrm")
    off = etree.SubElement(xfrm, f"{{{_A}}}off")
    off.set("x", "0")
    off.set("y", "0")
    ext = etree.SubElement(xfrm, f"{{{_A}}}ext")
    ext.set("cx", str(w_emu))
    ext.set("cy", str(h_emu))
    prstGeom = etree.SubElement(sp_pr, f"{{{_A}}}prstGeom")
    prstGeom.set("prst", "rect")
    etree.SubElement(prstGeom, f"{{{_A}}}avLst")

    if block.background_color:
        solid = etree.SubElement(sp_pr, f"{{{_A}}}solidFill")
        sc = etree.SubElement(solid, f"{{{_A}}}srgbClr")
        sc.set("val", _strip_hash(block.background_color))
    else:
        etree.SubElement(sp_pr, f"{{{_A}}}noFill")

    ln = etree.SubElement(sp_pr, f"{{{_A}}}ln")
    if block.line_color:
        solid = etree.SubElement(ln, f"{{{_A}}}solidFill")
        sc = etree.SubElement(solid, f"{{{_A}}}srgbClr")
        sc.set("val", _strip_hash(block.line_color))
        if block.line_width:
            ln.set("w", str(int(block.line_width * pt_to_emu)))
    else:
        etree.SubElement(ln, f"{{{_A}}}noFill")

    txbx = etree.SubElement(wsp, f"{{{_WPS}}}txbx")
    txbx_content = etree.SubElement(txbx, f"{{{_W}}}txbxContent")
    for el in child_elements:
        txbx_content.append(el)

    body_pr = etree.SubElement(wsp, f"{{{_WPS}}}bodyPr")
    body_pr.set("rot", "0")
    body_pr.set("vert", "horz")
    body_pr.set("wrap", "square")
    body_pr.set("lIns", str(int(4.52 * pt_to_emu)))
    body_pr.set("tIns", str(int(4.52 * pt_to_emu)))
    body_pr.set("rIns", str(int(4.52 * pt_to_emu)))
    body_pr.set("bIns", str(int(4.52 * pt_to_emu)))
    body_pr.set("anchor", "t")

    etree.SubElement(alt, f"{{{_MC}}}Fallback")

    result = [p]
    result.extend(extracted)
    return result


def _serialize_textbox_block(block: TextBoxBlock) -> list[etree._Element]:
    """Serialize a TextBoxBlock as an OOXML Drawing text box."""
    has_visual = block.background_color or block.line_color
    pos = block.position
    has_position = pos is not None and pos.x is not None and pos.y is not None

    if not has_visual and not has_position:
        elements: list[etree._Element] = []
        for child in block.content:
            elements.extend(_serialize_block(child))
        return elements if elements else [_make_empty_paragraph()]

    global _image_id_counter
    _image_id_counter += 1
    tb_id = _image_id_counter

    all_children: list[etree._Element] = []
    for child in block.content:
        if isinstance(child, TextBoxBlock):
            inner_els = []
            for inner in child.content:
                inner_els.extend(_serialize_block(inner))
            if child.line_color and inner_els:
                wrapper = _wrap_in_bordered_table(inner_els, child.line_color)
                all_children.append(wrapper)
            else:
                all_children.extend(inner_els)
        else:
            all_children.extend(_serialize_block(child))

    child_elements: list[etree._Element] = []
    extracted: list[etree._Element] = []
    for el in all_children:
        if _has_drawing_child(el):
            extracted.append(el)
        else:
            child_elements.append(el)
    if not child_elements:
        child_elements = [_make_empty_paragraph()]

    pt_to_emu = 12700
    fallback_w = _page_content_width_twips / 20
    w_emu = int((block.width or fallback_w) * pt_to_emu)
    auto_height = block.height is None
    h_emu = int((block.height or 100) * pt_to_emu)

    use_anchor = has_position and not pos.like_char

    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)
    r = etree.SubElement(p, f"{{{_W}}}r")

    nsmap_mc = {"mc": _MC, "wp": _WP, "a": _A, "wps": _WPS, "w": _W}
    alt = etree.SubElement(r, f"{{{_MC}}}AlternateContent", nsmap=nsmap_mc)
    choice = etree.SubElement(alt, f"{{{_MC}}}Choice")
    choice.set("Requires", "wps")

    drawing = etree.SubElement(choice, f"{{{_W}}}drawing")

    if use_anchor:
        wrap_el = etree.SubElement(drawing, f"{{{_WP}}}anchor")
        wrap_el.set("distT", "0")
        wrap_el.set("distB", "0")
        wrap_el.set("distL", "114300")
        wrap_el.set("distR", "114300")
        wrap_el.set("simplePos", "0")
        wrap_el.set("relativeHeight", str((pos.z_order or 0) + 251658240))
        wrap_el.set("behindDoc", "1" if pos.flow == "back" else "0")
        wrap_el.set("locked", "0")
        wrap_el.set("layoutInCell", "1")
        wrap_el.set("allowOverlap", "1" if pos.overlap_others else "0")

        simple_pos = etree.SubElement(wrap_el, f"{{{_WP}}}simplePos")
        simple_pos.set("x", "0")
        simple_pos.set("y", "0")

        _RELTO_H_MAP = {"paper": "page", "page": "page", "column": "column", "paragraph": "column"}
        posH = etree.SubElement(wrap_el, f"{{{_WP}}}positionH")
        posH.set("relativeFrom", _RELTO_H_MAP.get(pos.hrelto or "page", "page"))
        posH_off = etree.SubElement(posH, f"{{{_WP}}}posOffset")
        posH_off.text = str(int(_clip_x(pos.x, getattr(block, 'width', None) or 0) * pt_to_emu))

        posV = etree.SubElement(wrap_el, f"{{{_WP}}}positionV")
        _RELTO_V_MAP = {"paper": "page", "page": "page", "column": "page", "paragraph": "paragraph"}
        posV.set("relativeFrom", _RELTO_V_MAP.get(pos.vrelto or "page", "page"))
        posV_off = etree.SubElement(posV, f"{{{_WP}}}posOffset")
        posV_off.text = str(int(pos.y * pt_to_emu))
    else:
        wrap_el = etree.SubElement(drawing, f"{{{_WP}}}inline")
        wrap_el.set("distT", "0")
        wrap_el.set("distB", "0")
        wrap_el.set("distL", "0")
        wrap_el.set("distR", "0")

    extent = etree.SubElement(wrap_el, f"{{{_WP}}}extent")
    extent.set("cx", str(w_emu))
    extent.set("cy", str(h_emu))

    eff_ext = etree.SubElement(wrap_el, f"{{{_WP}}}effectExtent")
    eff_ext.set("l", "0")
    eff_ext.set("t", "0")
    eff_ext.set("r", "0")
    eff_ext.set("b", "0")

    if use_anchor:
        etree.SubElement(wrap_el, f"{{{_WP}}}wrapNone")

    doc_pr = etree.SubElement(wrap_el, f"{{{_WP}}}docPr")
    doc_pr.set("id", str(tb_id))
    doc_pr.set("name", f"TextBox {tb_id}")

    graphic = etree.SubElement(wrap_el, f"{{{_A}}}graphic")
    gd = etree.SubElement(graphic, f"{{{_A}}}graphicData")
    gd.set("uri", "http://schemas.microsoft.com/office/word/2010/wordprocessingShape")

    wsp = etree.SubElement(gd, f"{{{_WPS}}}wsp")

    cnv = etree.SubElement(wsp, f"{{{_WPS}}}cNvSpPr")
    cnv.set("txBox", "1")

    sp_pr = etree.SubElement(wsp, f"{{{_WPS}}}spPr")
    xfrm = etree.SubElement(sp_pr, f"{{{_A}}}xfrm")
    off = etree.SubElement(xfrm, f"{{{_A}}}off")
    off.set("x", "0")
    off.set("y", "0")
    ext = etree.SubElement(xfrm, f"{{{_A}}}ext")
    ext.set("cx", str(w_emu))
    ext.set("cy", str(h_emu))
    prstGeom = etree.SubElement(sp_pr, f"{{{_A}}}prstGeom")
    prstGeom.set("prst", "rect")
    etree.SubElement(prstGeom, f"{{{_A}}}avLst")

    if block.background_color:
        solid = etree.SubElement(sp_pr, f"{{{_A}}}solidFill")
        sc = etree.SubElement(solid, f"{{{_A}}}srgbClr")
        sc.set("val", _strip_hash(block.background_color))
    else:
        etree.SubElement(sp_pr, f"{{{_A}}}noFill")

    ln = etree.SubElement(sp_pr, f"{{{_A}}}ln")
    if block.line_color:
        solid = etree.SubElement(ln, f"{{{_A}}}solidFill")
        sc = etree.SubElement(solid, f"{{{_A}}}srgbClr")
        sc.set("val", _strip_hash(block.line_color))
        if block.line_width:
            ln.set("w", str(int(block.line_width * pt_to_emu)))
    else:
        etree.SubElement(ln, f"{{{_A}}}noFill")

    txbx = etree.SubElement(wsp, f"{{{_WPS}}}txbx")
    txbx_content = etree.SubElement(txbx, f"{{{_W}}}txbxContent")
    for el in child_elements:
        txbx_content.append(el)

    body_pr = etree.SubElement(wsp, f"{{{_WPS}}}bodyPr")
    body_pr.set("rot", "0")
    body_pr.set("vert", "horz")
    body_pr.set("wrap", "square")
    pad_emu = int((block.padding_left or 4.52) * pt_to_emu)
    body_pr.set("lIns", str(pad_emu))
    pad_emu = int((block.padding_top or 4.52) * pt_to_emu)
    body_pr.set("tIns", str(pad_emu))
    pad_emu = int((block.padding_right or 4.52) * pt_to_emu)
    body_pr.set("rIns", str(pad_emu))
    pad_emu = int((block.padding_bottom or 4.52) * pt_to_emu)
    body_pr.set("bIns", str(pad_emu))

    va_map = {"top": "t", "middle": "ctr", "bottom": "b"}
    body_pr.set("anchor", va_map.get(block.vertical_align or "top", "t"))
    if auto_height:
        etree.SubElement(body_pr, f"{{{_A}}}spAutoFit")

    etree.SubElement(alt, f"{{{_MC}}}Fallback")

    result = [p]
    result.extend(extracted)
    return result


_FIELD_TYPE_TO_INSTR = {
    "page_number": "PAGE",
    "auto_number": "AUTONUM",
    "hyperlink": "HYPERLINK",
    "date": "DATE",
    "time": "TIME",
    "num_pages": "NUMPAGES",
    "toc": "TOC",
}


def _serialize_field_block(block: FieldBlock) -> etree._Element:
    """Serialize a FieldBlock to a w:p with OOXML field codes."""
    p = etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)

    instr = _FIELD_TYPE_TO_INSTR.get(block.field_type)

    if instr:
        if block.field_type == "hyperlink" and block.value:
            instr = f'HYPERLINK "{block.value}"'

        fld = etree.SubElement(p, f"{{{_W}}}fldSimple", nsmap=_NSMAP_DOC)
        fld.set(f"{{{_W}}}instr", instr)
        r = etree.SubElement(fld, f"{{{_W}}}r")
        t = etree.SubElement(r, f"{{{_W}}}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        display = block.value or ""
        if block.inlines:
            display = "".join(
                getattr(il, "text", "") for il in block.inlines
            ) or display
        t.text = display
    elif block.inlines:
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
        from udf.renderers.docx.latex_to_omml import latex_to_omml
        latex = inline.latex or ""
        if not latex and inline.hwp_script:
            try:
                from udf.parsers.hwp.equation import hwp_script_to_latex
                latex = hwp_script_to_latex(inline.hwp_script)
            except Exception:
                latex = ""
        if latex:
            try:
                p.append(latex_to_omml(latex))
            except Exception:
                r = etree.SubElement(p, f"{{{_W}}}r")
                t = etree.SubElement(r, f"{{{_W}}}t")
                t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                t.text = latex
        else:
            r = etree.SubElement(p, f"{{{_W}}}r")
            t = etree.SubElement(r, f"{{{_W}}}t")
            t.text = inline.hwp_script or ""
    elif isinstance(inline, FootnoteRefInline):
        r = etree.SubElement(p, f"{{{_W}}}r")
        rpr = etree.SubElement(r, f"{{{_W}}}rPr")
        etree.SubElement(rpr, f"{{{_W}}}vertAlign").set(f"{{{_W}}}val", "superscript")
        t = etree.SubElement(r, f"{{{_W}}}t")
        t.text = str(inline.number or inline.ref_id)
    elif isinstance(inline, ImageInline):
        global _image_id_counter
        _image_id_counter += 1
        img_id = _image_id_counter
        r = etree.SubElement(p, f"{{{_W}}}r")
        drawing = etree.SubElement(r, f"{{{_W}}}drawing")
        nsmap_wp = {"wp": _WP, "a": _A, "pic": _PIC, "r": _R}
        inl = etree.SubElement(drawing, f"{{{_WP}}}inline", nsmap=nsmap_wp)
        inl.set("distT", "0")
        inl.set("distB", "0")
        inl.set("distL", "0")
        inl.set("distR", "0")
        cx = str(_pt_to_emu(inline.width)) if inline.width else "914400"
        cy = str(_pt_to_emu(inline.height)) if inline.height else "914400"
        extent = etree.SubElement(inl, f"{{{_WP}}}extent")
        extent.set("cx", cx)
        extent.set("cy", cy)
        eff_ext = etree.SubElement(inl, f"{{{_WP}}}effectExtent")
        eff_ext.set("l", "0")
        eff_ext.set("t", "0")
        eff_ext.set("r", "0")
        eff_ext.set("b", "0")
        doc_pr = etree.SubElement(inl, f"{{{_WP}}}docPr")
        doc_pr.set("id", str(img_id))
        doc_pr.set("name", f"Picture {img_id}")
        graphic = etree.SubElement(inl, f"{{{_A}}}graphic")
        gd = etree.SubElement(graphic, f"{{{_A}}}graphicData")
        gd.set("uri", _PIC)
        pic = etree.SubElement(gd, f"{{{_PIC}}}pic")
        nv = etree.SubElement(pic, f"{{{_PIC}}}nvPicPr")
        cnv_pr = etree.SubElement(nv, f"{{{_PIC}}}cNvPr")
        cnv_pr.set("id", str(img_id))
        cnv_pr.set("name", f"Picture {img_id}")
        etree.SubElement(nv, f"{{{_PIC}}}cNvPicPr")
        bf = etree.SubElement(pic, f"{{{_PIC}}}blipFill")
        blip = etree.SubElement(bf, f"{{{_A}}}blip")
        src = inline.src or ""
        if src.startswith("bindata:"):
            media_name = _resolve_media_name(src[len("bindata:"):])
            rid = f"rImg_{media_name}"
            blip.set(f"{{{_R}}}embed", rid)
            _image_rels[rid] = f"media/{media_name}"
        i_stretch = etree.SubElement(bf, f"{{{_A}}}stretch")
        etree.SubElement(i_stretch, f"{{{_A}}}fillRect")
        sp_pr = etree.SubElement(pic, f"{{{_PIC}}}spPr")
        xfrm = etree.SubElement(sp_pr, f"{{{_A}}}xfrm")
        off = etree.SubElement(xfrm, f"{{{_A}}}off")
        off.set("x", "0")
        off.set("y", "0")
        ext = etree.SubElement(xfrm, f"{{{_A}}}ext")
        ext.set("cx", cx)
        ext.set("cy", cy)
        i_geom = etree.SubElement(sp_pr, f"{{{_A}}}prstGeom")
        i_geom.set("prst", "rect")
        etree.SubElement(i_geom, f"{{{_A}}}avLst")
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
        mapped = _map_font(inline.font_name)
        fonts = etree.Element(f"{{{_W}}}rFonts")
        fonts.set(f"{{{_W}}}ascii", mapped)
        fonts.set(f"{{{_W}}}hAnsi", mapped)
        fonts.set(f"{{{_W}}}eastAsia", mapped)
        parts.append(fonts)

    if inline.font_size:
        pt_val = _parse_pt(inline.font_size)
        if pt_val is not None:
            half_pt = str(int(pt_val * 2))
            sz = etree.Element(f"{{{_W}}}sz")
            sz.set(f"{{{_W}}}val", half_pt)
            parts.append(sz)
            szCs = etree.Element(f"{{{_W}}}szCs")
            szCs.set(f"{{{_W}}}val", half_pt)
            parts.append(szCs)

    if inline.color:
        color = etree.Element(f"{{{_W}}}color")
        color.set(f"{{{_W}}}val", _strip_hash(inline.color))
        parts.append(color)

    if inline.background_color:
        shd = etree.Element(f"{{{_W}}}shd")
        shd.set(f"{{{_W}}}val", "clear")
        shd.set(f"{{{_W}}}fill", _strip_hash(inline.background_color))
        parts.append(shd)

    if inline.highlight_color:
        hl = etree.Element(f"{{{_W}}}highlight")
        hl_name = _color_to_highlight_name(str(inline.highlight_color))
        if hl_name:
            hl.set(f"{{{_W}}}val", hl_name)
            parts.append(hl)

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

    if inline.letter_spacing and inline.letter_spacing > 0:
        sp = etree.Element(f"{{{_W}}}spacing")
        font_pt = inline.font_size or 10.0
        pt_val = inline.letter_spacing * font_pt / 100.0
        sp.set(f"{{{_W}}}val", str(int(pt_val * 20)))
        parts.append(sp)

    if inline.outline:
        parts.append(etree.Element(f"{{{_W}}}outline"))
    if inline.shadow:
        parts.append(etree.Element(f"{{{_W}}}shadow"))
    if inline.emboss:
        parts.append(etree.Element(f"{{{_W}}}emboss"))
    if inline.engrave:
        parts.append(etree.Element(f"{{{_W}}}imprint"))
    if inline.all_caps:
        parts.append(etree.Element(f"{{{_W}}}caps"))
    if inline.emphasis_mark and inline.emphasis_mark != "none":
        em = etree.Element(f"{{{_W}}}em")
        em.set(f"{{{_W}}}val", inline.emphasis_mark)
        parts.append(em)
    if inline.char_scale is not None:
        w_el = etree.Element(f"{{{_W}}}w")
        pct = inline.char_scale
        w_el.set(f"{{{_W}}}val", str(int(pct.percent if hasattr(pct, "percent") else pct)))
        parts.append(w_el)
    if inline.char_offset is not None:
        pt_val = _parse_pt(inline.char_offset)
        if pt_val is not None:
            pos = etree.Element(f"{{{_W}}}position")
            pos.set(f"{{{_W}}}val", str(int(pt_val * 2)))
            parts.append(pos)
    if inline.rtl:
        parts.append(etree.Element(f"{{{_W}}}rtl"))

    if not parts:
        return None

    rpr = etree.Element(f"{{{_W}}}rPr")
    for el in parts:
        rpr.append(el)
    return rpr


# ---------------------------------------------------------------------------
# Paragraph format helpers
# ---------------------------------------------------------------------------


def _apply_ppr_format(
    ppr: etree._Element, fmt: object, *, suppress_keep_next: bool = False
) -> None:
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
            if hasattr(ls, "percent"):
                # Ratio object: percentage (e.g. Ratio(160) = 160%)
                spacing.set(f"{{{_W}}}line", str(int(ls.percent / 100 * 240)))
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

    if fmt.keep_with_next and not suppress_keep_next:
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

    if fmt.tab_stops:
        tabs = etree.SubElement(ppr, f"{{{_W}}}tabs")
        for ts in fmt.tab_stops:
            tab = etree.SubElement(tabs, f"{{{_W}}}tab")
            tab.set(f"{{{_W}}}val", ts.align or "left")
            tab.set(f"{{{_W}}}pos", str(int(ts.position * 20)))
            if ts.leader and ts.leader != "none":
                tab.set(f"{{{_W}}}leader", ts.leader)

    if fmt.bidi:
        etree.SubElement(ppr, f"{{{_W}}}bidi")


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


def _wrap_in_bordered_table(elements: list[etree._Element], color: str) -> etree._Element:
    """Wrap elements in a single-cell table with a colored border."""
    color_val = _strip_hash(color)
    tbl = etree.Element(f"{{{_W}}}tbl", nsmap=_NSMAP_DOC)
    tpr = etree.SubElement(tbl, f"{{{_W}}}tblPr")
    tbl_borders = etree.SubElement(tpr, f"{{{_W}}}tblBorders")
    for side in ("top", "left", "bottom", "right"):
        bdr = etree.SubElement(tbl_borders, f"{{{_W}}}{side}")
        bdr.set(f"{{{_W}}}val", "single")
        bdr.set(f"{{{_W}}}sz", "4")
        bdr.set(f"{{{_W}}}space", "0")
        bdr.set(f"{{{_W}}}color", color_val)
    insideH = etree.SubElement(tbl_borders, f"{{{_W}}}insideH")
    insideH.set(f"{{{_W}}}val", "none")
    insideH.set(f"{{{_W}}}sz", "0")
    insideH.set(f"{{{_W}}}space", "0")
    insideH.set(f"{{{_W}}}color", "auto")
    insideV = etree.SubElement(tbl_borders, f"{{{_W}}}insideV")
    insideV.set(f"{{{_W}}}val", "none")
    insideV.set(f"{{{_W}}}sz", "0")
    insideV.set(f"{{{_W}}}space", "0")
    insideV.set(f"{{{_W}}}color", "auto")
    tbl_w = etree.SubElement(tpr, f"{{{_W}}}tblW")
    tbl_w.set(f"{{{_W}}}w", "5000")
    tbl_w.set(f"{{{_W}}}type", "pct")
    tr = etree.SubElement(tbl, f"{{{_W}}}tr")
    tc = etree.SubElement(tr, f"{{{_W}}}tc")
    tcpr = etree.SubElement(tc, f"{{{_W}}}tcPr")
    shd = etree.SubElement(tcpr, f"{{{_W}}}shd")
    shd.set(f"{{{_W}}}val", "clear")
    shd.set(f"{{{_W}}}color", "auto")
    shd.set(f"{{{_W}}}fill", "FFFFFF")
    for el in elements:
        tc.append(el)
    if not elements:
        tc.append(_make_empty_paragraph())
    return tbl


def _fix_white_text_in_transparent_box(txbx_content: etree._Element) -> None:
    """Change white text to black inside a textbox with no background fill."""
    for color_el in txbx_content.findall(f".//{{{_W}}}color"):
        val = (color_el.get(f"{{{_W}}}val") or "").upper()
        if val in ("FFFFFF", "FFF"):
            color_el.set(f"{{{_W}}}val", "000000")


def _clip_x(x: float, w: float) -> float:
    """Clip x so that x+w doesn't exceed page width."""
    page_w = _page_content_width_twips / 20 + 170
    if w > 0 and x + w > page_w:
        x = max(0, page_w - w)
    return x


def _trim_trailing_empty_paragraphs(body: etree._Element) -> None:
    """Remove trailing empty paragraphs from body, keeping at least one."""
    children = list(body)
    remove_from = len(children)
    for i in range(len(children) - 1, -1, -1):
        child = children[i]
        if child.tag != f"{{{_W}}}p":
            break
        has_text = child.find(f".//{{{_W}}}t") is not None
        has_drawing = child.find(f".//{{{_W}}}drawing") is not None
        if has_text or has_drawing:
            break
        remove_from = i
    keep_one = remove_from
    for i in range(len(children) - 1, keep_one, -1):
        body.remove(children[i])


def _make_empty_paragraph() -> etree._Element:
    """Create an empty w:p element."""
    return etree.Element(f"{{{_W}}}p", nsmap=_NSMAP_DOC)


def _parse_pt(value) -> float | None:
    """'12.5pt' → 12.5, or float/int → float, or Ratio → Ratio.percent. invalid → None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if hasattr(value, "percent"):  # Ratio or similar
        return float(value.percent)
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
    if hasattr(val, "percent"):
        return float(val.percent)
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


_HIGHLIGHT_NAME_MAP = {
    "#ffff00": "yellow", "#00ff00": "green", "#00ffff": "cyan",
    "#ff00ff": "magenta", "#0000ff": "blue", "#ff0000": "red",
    "#000080": "darkBlue", "#008080": "darkCyan", "#008000": "darkGreen",
    "#800080": "darkMagenta", "#800000": "darkRed", "#808000": "darkYellow",
    "#808080": "darkGray", "#c0c0c0": "lightGray", "#000000": "black",
}


def _color_to_highlight_name(color_hex: str) -> str | None:
    """Map a hex color to OOXML highlight name. Returns None if no match."""
    c = color_hex.lower().lstrip("#")
    if len(c) == 6:
        c = f"#{c}"
    return _HIGHLIGHT_NAME_MAP.get(c)


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
    else:
        cols = etree.SubElement(sect_pr, f"{{{_W}}}cols")
        cols.set(f"{{{_W}}}space", "425")

    doc_grid = etree.SubElement(sect_pr, f"{{{_W}}}docGrid")
    doc_grid.set(f"{{{_W}}}linePitch", "360")

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
    """Generate word/settings.xml with Korean compat and compatibility mode 15."""
    root = etree.Element(f"{{{_W}}}settings", nsmap={"w": _W})
    ps = etree.SubElement(root, f"{{{_W}}}proofState")
    ps.set(f"{{{_W}}}spelling", "clean")
    ps.set(f"{{{_W}}}grammar", "clean")
    etree.SubElement(root, f"{{{_W}}}doNotHyphenateCaps")
    etree.SubElement(root, f"{{{_W}}}bordersDoNotSurroundHeader")
    etree.SubElement(root, f"{{{_W}}}bordersDoNotSurroundFooter")
    tab_stop = etree.SubElement(root, f"{{{_W}}}defaultTabStop")
    tab_stop.set(f"{{{_W}}}val", "800")
    csc = etree.SubElement(root, f"{{{_W}}}characterSpacingControl")
    csc.set(f"{{{_W}}}val", "doNotCompress")
    compat = etree.SubElement(root, f"{{{_W}}}compat")
    etree.SubElement(compat, f"{{{_W}}}spaceForUL")
    etree.SubElement(compat, f"{{{_W}}}balanceSingleByteDoubleByteWidth")
    etree.SubElement(compat, f"{{{_W}}}doNotLeaveBackslashAlone")
    etree.SubElement(compat, f"{{{_W}}}ulTrailSpace")
    etree.SubElement(compat, f"{{{_W}}}doNotExpandShiftReturn")
    etree.SubElement(compat, f"{{{_W}}}adjustLineHeightInTable")
    etree.SubElement(compat, f"{{{_W}}}useFELayout")
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
