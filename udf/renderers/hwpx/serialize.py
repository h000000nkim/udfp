"""Document Model → HWPX section XML 직렬화.

UdfDocument 블록 트리를 OWPML section*.xml 형식으로 변환한다.
"""

from __future__ import annotations

from typing import Any

from lxml import etree

from udf.core.schema import (
    Block,
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
    ImageInline,
    LinkInline,
    ListBlock,
    ListItem,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
    TextInline,
    UdfDocument,
)

# ---------------------------------------------------------------------------
# OWPML 네임스페이스
# ---------------------------------------------------------------------------

_NSMAP = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
}

_HP = f"{{{_NSMAP['hp']}}}"
_HS = f"{{{_NSMAP['hs']}}}"
_HC = f"{{{_NSMAP['hc']}}}"
_HH = f"{{{_NSMAP['hh']}}}"

_HWPUNIT_PER_PT = 100


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def blocks_to_section_xml(blocks: list[Block], doc: UdfDocument) -> bytes:
    """Convert a block list into HWPX section XML bytes.

    Parameters
    ----------
    blocks : list[Block]
        Blocks to serialize.
    doc : UdfDocument
        Full document (for metadata and global_resources references).

    Returns
    -------
    bytes
        UTF-8 encoded section XML with XML declaration.
    """
    sec = etree.Element(f"{_HS}sec", nsmap=_NSMAP)

    # 첫 번째 단락에 secPr 삽입 (From Scratch에서 최소한의 페이지 설정)
    secpr_para = _build_secpr_paragraph(doc)
    sec.append(secpr_para)

    for block in blocks:
        elements = _block_to_elements(block, doc)
        for el in elements:
            sec.append(el)

    return etree.tostring(
        sec,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def build_minimal_header_xml(doc: UdfDocument) -> bytes:
    """Generate a minimal header.xml for From Scratch mode.

    Includes one default fontface, charPr, paraPr, and style entry.

    Parameters
    ----------
    doc : UdfDocument
        Document model (used for potential metadata references).

    Returns
    -------
    bytes
        UTF-8 encoded header XML.
    """
    root = etree.Element(f"{_HH}head", nsmap=_NSMAP)

    # beginNum
    begin_num = etree.SubElement(root, f"{_HH}beginNum")
    begin_num.set("page", "1")
    begin_num.set("footnote", "1")
    begin_num.set("endnote", "1")
    begin_num.set("pic", "1")
    begin_num.set("tbl", "1")
    begin_num.set("equation", "1")

    # refList
    ref_list = etree.SubElement(root, f"{_HH}refList")

    # fontfaces — 한글 + Latin 기본
    fontfaces = etree.SubElement(ref_list, f"{_HH}fontfaces")
    for lang in ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER"):
        ff = etree.SubElement(fontfaces, f"{_HH}fontface")
        ff.set("lang", lang)
        font = etree.SubElement(ff, f"{_HH}font")
        font.set("face", "함초롬돋움")

    # borderFills — 최소 1개 (빈 보더/채우기)
    border_fills = etree.SubElement(ref_list, f"{_HH}borderFills")
    bf = etree.SubElement(border_fills, f"{_HH}borderFill")
    bf.set("id", "1")
    for side in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
        b = etree.SubElement(bf, f"{_HH}{side}")
        b.set("type", "NONE")
        b.set("width", "0.1 mm")
        b.set("color", "#000000")

    # charProperties — 기본 charPr 1개
    char_props = etree.SubElement(ref_list, f"{_HH}charProperties")
    cp = etree.SubElement(char_props, f"{_HH}charPr")
    cp.set("id", "0")
    cp.set("height", "1000")
    cp.set("textColor", "#000000")
    cp.set("shadeColor", "none")
    font_ref = etree.SubElement(cp, f"{_HH}fontRef")
    for lang in ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER"):
        font_ref.set(lang, "0")

    # paraProperties — 기본 paraPr 1개
    para_props = etree.SubElement(ref_list, f"{_HH}paraProperties")
    pp = etree.SubElement(para_props, f"{_HH}paraPr")
    pp.set("id", "0")
    align = etree.SubElement(pp, f"{_HH}align")
    align.set("horizontal", "JUSTIFY")
    ls = etree.SubElement(pp, f"{_HH}lineSpacing")
    ls.set("type", "PERCENT")
    ls.set("value", "160")

    # styles — 기본 바탕글 스타일 1개
    styles = etree.SubElement(ref_list, f"{_HH}styles")
    st = etree.SubElement(styles, f"{_HH}style")
    st.set("id", "0")
    st.set("type", "PARA")
    st.set("name", "바탕글")
    st.set("engName", "Normal")
    st.set("paraPrIDRef", "0")
    st.set("charPrIDRef", "0")

    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def build_content_hpf(section_count: int = 1) -> bytes:
    """Generate a content.hpf (OPF package file) for From Scratch mode.

    Parameters
    ----------
    section_count : int, default 1
        Number of section XML files to reference.

    Returns
    -------
    bytes
        UTF-8 encoded OPF package XML.
    """
    nsmap = {
        "opf": "http://www.idpf.org/2007/opf/",
    }
    package = etree.Element("{http://www.idpf.org/2007/opf/}package", nsmap=nsmap)
    package.set("version", "")
    package.set("unique-identifier", "")

    metadata = etree.SubElement(package, "{http://www.idpf.org/2007/opf/}metadata")
    title = etree.SubElement(metadata, "{http://www.idpf.org/2007/opf/}title")
    title.text = ""
    lang = etree.SubElement(metadata, "{http://www.idpf.org/2007/opf/}language")
    lang.text = "ko"

    manifest = etree.SubElement(package, "{http://www.idpf.org/2007/opf/}manifest")

    # header
    item = etree.SubElement(manifest, "{http://www.idpf.org/2007/opf/}item")
    item.set("id", "header")
    item.set("href", "Contents/header.xml")
    item.set("media-type", "application/xml")

    # sections
    for i in range(section_count):
        item = etree.SubElement(manifest, "{http://www.idpf.org/2007/opf/}item")
        item.set("id", f"section{i}")
        item.set("href", f"Contents/section{i}.xml")
        item.set("media-type", "application/xml")

    spine = etree.SubElement(package, "{http://www.idpf.org/2007/opf/}spine")
    ref = etree.SubElement(spine, "{http://www.idpf.org/2007/opf/}itemref")
    ref.set("idref", "header")
    ref.set("linear", "yes")
    for i in range(section_count):
        ref = etree.SubElement(spine, "{http://www.idpf.org/2007/opf/}itemref")
        ref.set("idref", f"section{i}")
        ref.set("linear", "yes")

    return etree.tostring(
        package,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def build_container_xml() -> bytes:
    """Generate META-INF/container.xml for From Scratch mode.

    Returns
    -------
    bytes
        UTF-8 encoded container XML pointing to Contents/content.hpf.
    """
    nsmap = {
        "ocf": "urn:oasis:names:tc:opendocument:xmlns:container",
    }
    container = etree.Element(
        "{urn:oasis:names:tc:opendocument:xmlns:container}container", nsmap=nsmap
    )
    rootfiles = etree.SubElement(
        container, "{urn:oasis:names:tc:opendocument:xmlns:container}rootfiles"
    )
    rf = etree.SubElement(
        rootfiles, "{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
    )
    rf.set("full-path", "Contents/content.hpf")
    rf.set("media-type", "application/hwpml-package+xml")

    return etree.tostring(
        container,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def build_version_xml() -> bytes:
    """Generate version.xml for From Scratch mode.

    Returns
    -------
    bytes
        UTF-8 encoded version XML with HWPML version metadata.
    """
    nsmap = {"hv": "http://www.hancom.co.kr/hwpml/2011/version"}
    root = etree.Element(
        "{http://www.hancom.co.kr/hwpml/2011/version}HCFVersion", nsmap=nsmap
    )
    root.set("tagetApplication", "WORDPROCESSOR")
    root.set("major", "5")
    root.set("minor", "1")
    root.set("micro", "1")
    root.set("buildNumber", "0")
    root.set("xmlVersion", "1.5")
    root.set("application", "UDF")
    root.set("appVersion", "0.1.0")

    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


# ---------------------------------------------------------------------------
# 블록 → XML 요소 변환 (내부 함수)
# ---------------------------------------------------------------------------


def _block_to_elements(block: Block, doc: UdfDocument) -> list[etree._Element]:
    """단일 블록을 XML 요소 리스트로 변환한다.

    대부분은 1개 요소를 반환하지만, FootnoteBlock 등은 0개(참조 인라인에 포함)
    를 반환할 수 있다.
    """
    if isinstance(block, ParagraphBlock):
        return [_paragraph_to_xml(block, doc)]
    elif isinstance(block, HeadingBlock):
        return [_heading_to_xml(block, doc)]
    elif isinstance(block, TableBlock):
        return [_table_to_xml(block, doc)]
    elif isinstance(block, ImageBlock):
        return [_image_block_to_xml(block, doc)]
    elif isinstance(block, ListBlock):
        return _list_to_paragraphs(block, doc)
    elif isinstance(block, EquationBlock):
        return [_equation_block_to_xml(block, doc)]
    elif isinstance(block, (FootnoteBlock, EndnoteBlock)):
        return []
    elif isinstance(block, TextBoxBlock):
        elements: list[etree._Element] = []
        for child in block.content:
            elements.extend(_block_to_elements(child, doc))
        return elements if elements else [_empty_paragraph()]
    elif isinstance(block, (HeaderBlock, FooterBlock)):
        return []
    elif isinstance(block, DrawingBlock):
        return []
    elif isinstance(block, FieldBlock):
        if block.inlines:
            p = _paragraph_to_xml(
                ParagraphBlock(type="paragraph", id=block.id, inlines=block.inlines),
                doc,
            )
            return [p]
        return [_empty_paragraph()]
    else:
        return [_empty_paragraph()]


def _build_secpr_paragraph(doc: UdfDocument) -> etree._Element:
    """secPr을 포함하는 첫 번째 단락을 생성한다."""
    p = etree.Element(f"{_HP}p")
    p.set("paraPrIDRef", "0")
    p.set("styleIDRef", "0")
    p.set("pageBreak", "0")
    p.set("columnBreak", "0")
    p.set("merged", "0")

    run = etree.SubElement(p, f"{_HP}run")
    run.set("charPrIDRef", "0")

    sec_pr = etree.SubElement(run, f"{_HP}secPr")
    sec_pr.set("textDirection", "HORIZONTAL")
    sec_pr.set("spaceColumns", "1134")
    sec_pr.set("tabStop", "8000")

    # pagePr — A4 기본값 (단위: HWPUNIT, 1pt = 100 HWPUNIT)
    width = 59528
    height = 84186
    margin_top = 5668
    margin_bottom = 4252
    margin_left = 8504
    margin_right = 8504
    margin_header = 4252
    margin_footer = 4252

    # 메타데이터에서 실제 값이 있으면 사용
    if doc.metadata and doc.metadata.sections:
        sec = doc.metadata.sections[0]
        if sec.page_width:
            width = _pt_to_hwpunit(sec.page_width)
        if sec.page_height:
            height = _pt_to_hwpunit(sec.page_height)
        if sec.margins:
            margin_top = _pt_to_hwpunit(sec.margins.top)
            margin_bottom = _pt_to_hwpunit(sec.margins.bottom)
            margin_left = _pt_to_hwpunit(sec.margins.left)
            margin_right = _pt_to_hwpunit(sec.margins.right)
        if sec.header_margin:
            margin_header = _pt_to_hwpunit(sec.header_margin)
        if sec.footer_margin:
            margin_footer = _pt_to_hwpunit(sec.footer_margin)

    landscape = False
    if doc.metadata and doc.metadata.sections:
        sec = doc.metadata.sections[0]
        if sec.orientation == "landscape":
            landscape = True

    page_pr = etree.SubElement(sec_pr, f"{_HP}pagePr")
    page_pr.set("landscape", "true" if landscape else "WIDELY")
    page_pr.set("width", str(width))
    page_pr.set("height", str(height))
    page_pr.set("gutterType", "LEFT_ONLY")

    gutter_val = "0"
    if doc.metadata and doc.metadata.sections:
        sec = doc.metadata.sections[0]
        if sec.gutter:
            gutter_val = str(_pt_to_hwpunit(sec.gutter))

    margin = etree.SubElement(page_pr, f"{_HP}margin")
    margin.set("header", str(margin_header))
    margin.set("footer", str(margin_footer))
    margin.set("gutter", gutter_val)
    margin.set("left", str(margin_left))
    margin.set("right", str(margin_right))
    margin.set("top", str(margin_top))
    margin.set("bottom", str(margin_bottom))

    if doc.metadata and doc.metadata.sections:
        sec = doc.metadata.sections[0]
        if sec.columns and sec.columns.count > 1:
            col_el = etree.SubElement(page_pr, f"{_HP}multiColumn")
            col_el.set("count", str(sec.columns.count))
            if sec.columns.gap:
                col_el.set("gap", str(_pt_to_hwpunit(sec.columns.gap)))
            col_el.set("sameWidth", "1" if sec.columns.same_width else "0")

    return p


def _paragraph_to_xml(
    block: ParagraphBlock, doc: UdfDocument
) -> etree._Element:
    """Convert a ParagraphBlock to an <hp:p> element."""
    p = etree.Element(f"{_HP}p")

    para_pr_id = "0"
    style_id = "0"
    if block.verbatim_ref and doc.verbatim and block.verbatim_ref in doc.verbatim.blocks:
        vb = doc.verbatim.blocks[block.verbatim_ref]
        if vb.decoded:
            para_pr_id = str(vb.decoded.get("paraPrIDRef", 0))
            style_id = str(vb.decoded.get("styleIDRef", 0))

    p.set("paraPrIDRef", para_pr_id)
    p.set("styleIDRef", style_id)
    p.set("pageBreak", "0")
    p.set("columnBreak", "0")
    p.set("merged", "0")

    _append_inlines_as_runs(p, block.inlines, doc)
    return p


def _heading_to_xml(
    block: HeadingBlock, doc: UdfDocument
) -> etree._Element:
    """Convert a HeadingBlock to an <hp:p> with outline style reference."""
    p = etree.Element(f"{_HP}p")

    para_pr_id = "0"
    style_id = "0"
    if block.verbatim_ref and doc.verbatim and block.verbatim_ref in doc.verbatim.blocks:
        vb = doc.verbatim.blocks[block.verbatim_ref]
        if vb.decoded:
            para_pr_id = str(vb.decoded.get("paraPrIDRef", 0))
            style_id = str(vb.decoded.get("styleIDRef", 0))

    p.set("paraPrIDRef", para_pr_id)
    p.set("styleIDRef", style_id)
    p.set("pageBreak", "0")
    p.set("columnBreak", "0")
    p.set("merged", "0")

    # 헤딩은 inlines가 있으면 인라인 사용, 없으면 text 사용
    inlines = block.inlines
    if not inlines and block.text:
        inlines = [TextInline(text=block.text)]

    _append_inlines_as_runs(p, inlines, doc)
    return p


def _table_to_xml(block: TableBlock, doc: UdfDocument) -> etree._Element:
    """Convert a TableBlock to an <hp:p> containing <hp:tbl>."""
    # 테이블은 hp:p > hp:run > hp:tbl 구조
    p = etree.Element(f"{_HP}p")
    p.set("paraPrIDRef", "0")
    p.set("styleIDRef", "0")
    p.set("pageBreak", "0")
    p.set("columnBreak", "0")
    p.set("merged", "0")

    run = etree.SubElement(p, f"{_HP}run")
    run.set("charPrIDRef", "0")

    row_cnt = len(block.rows)
    col_cnt = max((len(r.cells) for r in block.rows), default=0)

    tbl = etree.SubElement(run, f"{_HP}tbl")
    tbl.set("rowCnt", str(row_cnt))
    tbl.set("colCnt", str(col_cnt))
    tbl.set("cellSpacing", "0")
    if block.border_fill_id is not None:
        tbl.set("borderFillIDRef", str(block.border_fill_id))
    tbl.set("repeatHeader", "1" if block.repeat_header else "0")

    # sz
    sz = etree.SubElement(tbl, f"{_HP}sz")
    width_hu = 51008  # 기본 테이블 폭
    height_hu = 0
    if block.position and block.position.width:
        width_hu = int(block.position.width * _HWPUNIT_PER_PT)
    if block.position and block.position.height:
        height_hu = int(block.position.height * _HWPUNIT_PER_PT)
    sz.set("width", str(width_hu))
    sz.set("widthRelTo", "ABSOLUTE")
    sz.set("height", str(height_hu))
    sz.set("heightRelTo", "ABSOLUTE")
    sz.set("protect", "0")

    # pos
    pos = etree.SubElement(tbl, f"{_HP}pos")
    like_char = "1"
    if block.position and block.position.like_char is not None:
        like_char = "1" if block.position.like_char else "0"
    pos.set("treatAsChar", like_char)
    pos.set("affectLSpacing", "0")
    pos.set("flowWithText", "1")
    pos.set("allowOverlap", "0")

    for row in block.rows:
        tr = _table_row_to_xml(row, doc)
        tbl.append(tr)

    return p


def _table_row_to_xml(row: TableRow, doc: UdfDocument) -> etree._Element:
    """Convert a TableRow to an <hp:tr> element."""
    tr = etree.Element(f"{_HP}tr")
    for cell in row.cells:
        tc = _table_cell_to_xml(cell, doc)
        tr.append(tc)
    return tr


def _table_cell_to_xml(cell: TableCell, doc: UdfDocument) -> etree._Element:
    """Convert a TableCell to an <hp:tc> element."""
    tc = etree.Element(f"{_HP}tc")

    if cell.col_span > 1 or cell.row_span > 1:
        span = etree.SubElement(tc, f"{_HP}cellSpan")
        span.set("colSpan", str(cell.col_span))
        span.set("rowSpan", str(cell.row_span))

    if cell.width or cell.height:
        sz = etree.SubElement(tc, f"{_HP}cellSz")
        sz.set("width", str(int(cell.width * _HWPUNIT_PER_PT)) if cell.width else "0")
        sz.set("height", str(int(cell.height * _HWPUNIT_PER_PT)) if cell.height else "0")

    if cell.format:
        _fmt = cell.format
        if _fmt.padding_left or _fmt.padding_right or _fmt.padding_top or _fmt.padding_bottom:
            cm = etree.SubElement(tc, f"{_HP}cellMargin")
            cm.set("left", str(_pt_str_to_hwpunit(_fmt.padding_left)))
            cm.set("right", str(_pt_str_to_hwpunit(_fmt.padding_right)))
            cm.set("top", str(_pt_str_to_hwpunit(_fmt.padding_top)))
            cm.set("bottom", str(_pt_str_to_hwpunit(_fmt.padding_bottom)))

    # subList with cell content
    sub_list = etree.SubElement(tc, f"{_HP}subList")
    if cell.format and cell.format.vertical_align:
        va_map = {"top": "TOP", "middle": "CENTER", "bottom": "BOTTOM"}
        sub_list.set("vertAlign", va_map.get(cell.format.vertical_align, "TOP"))

    for content_block in cell.content:
        elements = _block_to_elements(content_block, doc)
        for el in elements:
            sub_list.append(el)

    # subList가 비어있으면 빈 단락 추가
    if len(sub_list) == 0:
        sub_list.append(_empty_paragraph())

    return tc


def _image_block_to_xml(block: ImageBlock, doc: UdfDocument) -> etree._Element:
    """Convert an ImageBlock to an <hp:p> containing <hp:pic>."""
    p = etree.Element(f"{_HP}p")
    p.set("paraPrIDRef", "0")
    p.set("styleIDRef", "0")
    p.set("pageBreak", "0")

    run = etree.SubElement(p, f"{_HP}run")
    run.set("charPrIDRef", "0")

    pic = etree.SubElement(run, f"{_HP}pic")

    # sz
    sz = etree.SubElement(pic, f"{_HP}sz")
    w_hu = _pt_str_to_hwpunit(block.width) if block.width else 0
    h_hu = _pt_str_to_hwpunit(block.height) if block.height else 0
    sz.set("width", str(w_hu))
    sz.set("height", str(h_hu))

    # img
    img = etree.SubElement(pic, f"{_HP}img")
    # src는 "bindata:NAME" 형식 → binaryItemIDRef로 변환
    src = block.src
    if src.startswith("bindata:"):
        src = src[len("bindata:"):]
    img.set("binaryItemIDRef", src)

    return p


def _equation_block_to_xml(
    block: EquationBlock, doc: UdfDocument
) -> etree._Element:
    """Convert an EquationBlock to an <hp:p> containing <hp:eqEdit>."""
    p = etree.Element(f"{_HP}p")
    p.set("paraPrIDRef", "0")
    p.set("styleIDRef", "0")
    p.set("pageBreak", "0")

    run = etree.SubElement(p, f"{_HP}run")
    run.set("charPrIDRef", "0")

    eq = etree.SubElement(run, f"{_HP}eqEdit")
    script = block.hwp_script or block.latex or ""
    eq.set("script", script)

    return p


def _list_to_paragraphs(
    block: ListBlock, doc: UdfDocument
) -> list[etree._Element]:
    """ListBlock → 단락 리스트 (HWPX에는 별도 리스트 요소 없음, 단락으로 직렬화)."""
    result: list[etree._Element] = []
    for item in block.items:
        result.extend(_list_item_to_paragraphs(item, doc))
    return result


def _list_item_to_paragraphs(
    item: ListItem, doc: UdfDocument
) -> list[etree._Element]:
    """ListItem → 단락(들)."""
    p = etree.Element(f"{_HP}p")
    p.set("paraPrIDRef", "0")
    p.set("styleIDRef", "0")
    p.set("pageBreak", "0")

    _append_inlines_as_runs(p, item.inlines, doc)
    result = [p]

    for child in item.children:
        result.extend(_list_item_to_paragraphs(child, doc))

    return result


def _append_inlines_as_runs(
    p: etree._Element,
    inlines: list[Any],
    doc: UdfDocument,
) -> None:
    """인라인 리스트를 <hp:run>/<hp:t> 등으로 변환하여 단락에 추가한다.

    동일 charPrIDRef를 가진 연속 TextInline은 하나의 run으로 병합한다.
    """
    if not inlines:
        # 빈 단락도 run + t 구조는 필요
        run = etree.SubElement(p, f"{_HP}run")
        run.set("charPrIDRef", "0")
        etree.SubElement(run, f"{_HP}t")
        return

    for inline in inlines:
        if isinstance(inline, TextInline):
            run = etree.SubElement(p, f"{_HP}run")
            run.set("charPrIDRef", "0")
            t = etree.SubElement(run, f"{_HP}t")

            # 탭/줄바꿈 처리
            text = inline.text
            if text == "\t":
                etree.SubElement(t, f"{_HP}tab")
            elif text == "\n":
                etree.SubElement(t, f"{_HP}lineBreak")
            else:
                t.text = text

        elif isinstance(inline, LinkInline):
            run = etree.SubElement(p, f"{_HP}run")
            run.set("charPrIDRef", "0")
            ctrl = etree.SubElement(run, f"{_HP}ctrl")
            ctrl.set("ctrlID", "hlnk")
            ctrl.set("href", inline.url or "")
            t = etree.SubElement(ctrl, f"{_HP}t")
            t.text = inline.text

        elif isinstance(inline, ImageInline):
            run = etree.SubElement(p, f"{_HP}run")
            run.set("charPrIDRef", "0")
            pic = etree.SubElement(run, f"{_HP}pic")
            sz = etree.SubElement(pic, f"{_HP}sz")
            sz.set("width", str(_pt_str_to_hwpunit(inline.width)))
            sz.set("height", str(_pt_str_to_hwpunit(inline.height)))
            img = etree.SubElement(pic, f"{_HP}img")
            src = inline.src
            if src.startswith("bindata:"):
                src = src[len("bindata:"):]
            img.set("binaryItemIDRef", src)

        elif isinstance(inline, EquationInline):
            run = etree.SubElement(p, f"{_HP}run")
            run.set("charPrIDRef", "0")
            eq = etree.SubElement(run, f"{_HP}eqEdit")
            script = inline.hwp_script or inline.latex or ""
            eq.set("script", script)

        elif isinstance(inline, FootnoteRefInline):
            run = etree.SubElement(p, f"{_HP}run")
            run.set("charPrIDRef", "0")
            fn = etree.SubElement(run, f"{_HP}footNote")
            if inline.number is not None:
                fn.set("number", str(inline.number))
            # 각주 본문은 FootnoteBlock에서 별도 처리
            sub_list = etree.SubElement(fn, f"{_HP}subList")
            sub_list.append(_empty_paragraph())


def _empty_paragraph() -> etree._Element:
    """빈 <hp:p> 요소를 생성한다."""
    p = etree.Element(f"{_HP}p")
    p.set("paraPrIDRef", "0")
    p.set("styleIDRef", "0")
    p.set("pageBreak", "0")
    p.set("columnBreak", "0")
    p.set("merged", "0")
    run = etree.SubElement(p, f"{_HP}run")
    run.set("charPrIDRef", "0")
    etree.SubElement(run, f"{_HP}t")
    return p


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def _pt_to_hwpunit(val: Any) -> int:
    """pt 값을 HWPUNIT로 변환한다.

    문자열('595.28pt', '210.0mm') 및 숫자(float/int, pt 단위)
    모두 지원한다. Ratio 객체가 오면 percent 값을 그대로 반환한다.
    """
    if val is None:
        return 0
    # float/int — pt 단위로 간주
    if isinstance(val, (int, float)):
        return int(val * _HWPUNIT_PER_PT)
    # Ratio 객체 (line_spacing 등)
    if hasattr(val, "percent"):
        return int(val.percent)
    # 문자열
    if isinstance(val, str):
        if not val:
            return 0
        v = val.strip()
        if v.endswith("pt"):
            try:
                return int(float(v[:-2]) * _HWPUNIT_PER_PT)
            except ValueError:
                return 0
        if v.endswith("mm"):
            try:
                return int(float(v[:-2]) * 283.46)
            except ValueError:
                return 0
        try:
            return int(float(v))
        except ValueError:
            return 0
    return 0


def _pt_str_to_hwpunit(val: Any) -> int:
    """pt 값을 HWPUNIT로 변환한다. None → 0.

    문자열('12.0pt') 및 숫자(float) 모두 지원.
    """
    if val is None:
        return 0
    return _pt_to_hwpunit(val)
