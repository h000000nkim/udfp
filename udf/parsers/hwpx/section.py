"""HWPX section XML parser -- converts section content to document blocks."""

from __future__ import annotations

import re
from typing import Any

from lxml import etree

from udf.core.ids import make_block_id, make_verbatim_id
from udf.schema import (
    Block,
    BlockFormat,
    CellFormat,
    EndnoteBlock,
    EquationInline,
    FooterBlock,
    FootnoteBlock,
    FootnoteRefInline,
    HeaderBlock,
    HeadingBlock,
    ImageInline,
    LinkInline,
    ListBlock,
    ListItem,
    PageBreakBlock,
    ParagraphBlock,
    PositionInfo,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
    TextInline,
)
from udf.schema.types import Ratio, hwpunit_to_pt
from udf.pipeline.verbatim import VerbatimBlock
from udf.parsers.hwp.doc_info import DocInfoResult
from udf.parsers.hwpx.header import NS

_HWPUNIT_PER_PT = 100
_HWPUNIT_PER_MM = 283.46

_PCT_RE = re.compile(r"^(-?\d+(?:\.\d+)?)%?$")
_OUTLINE_RE = re.compile(r"^개요\s*(\d+)$|^Outline\s*(\d+)$", re.IGNORECASE)

_LIST_STYLE_RE = re.compile(
    r"^(?:MsoListParagraph"
    r"|㉿\d+\."
    r"|[가-힣]\."
    r"|[가-힣]\.[가-힣]\.[가-힣]\."
    r"|ListParagraph"
    r"|List\s*(?:Bullet|Number|Continue)"
    r")$",
    re.IGNORECASE,
)

def _parse_pct(s: str) -> float | None:
    """Parse a percentage string to float."""
    m = _PCT_RE.match(s)
    return float(m.group(1)) if m else None


_block_counter: int = 0


def parse_section_xml(
    section_bytes: bytes,
    info: DocInfoResult,
    section_name: str,
) -> tuple[list[Block], dict[str, VerbatimBlock]]:
    """Parse an HWPX section XML file into document blocks.

    Parameters
    ----------
    section_bytes : bytes
        Raw XML content of a ``Contents/sectionN.xml`` file.
    info : DocInfoResult
        Parsed header.xml data (char shapes, para shapes, styles, etc.).
    section_name : str
        Section identifier for block ID generation.

    Returns
    -------
    tuple[list[Block], dict[str, VerbatimBlock]]
        Semantic blocks and their verbatim preservation data.
    """
    global _block_counter
    _block_counter = 0

    root = etree.fromstring(section_bytes)
    blocks: list[Block] = []
    verbatim_map: dict[str, VerbatimBlock] = {}

    list_acc: list[tuple[int, ParagraphBlock]] = []

    for p_el in root.iterfind("hp:p", NS):
        style_id_ref = int(p_el.get("styleIDRef", "0"))

        if _is_list_style(style_id_ref, info):
            result = _parse_paragraph(p_el, info, verbatim_map)
            if result is not None:
                flat = result if isinstance(result, list) else [result]
                for blk in flat:
                    if isinstance(blk, ParagraphBlock):
                        list_acc.append((style_id_ref, blk))
                    else:
                        if list_acc:
                            blocks.append(_flush_list(list_acc, info))
                            list_acc = []
                        blocks.append(blk)
            continue

        if list_acc:
            blocks.append(_flush_list(list_acc, info))
            list_acc = []

        result = _parse_paragraph(p_el, info, verbatim_map)
        if result is not None:
            if isinstance(result, list):
                blocks.extend(result)
            else:
                blocks.append(result)

    if list_acc:
        blocks.append(_flush_list(list_acc, info))

    # secPr에서 header/footer 추출
    hf_blocks = _extract_header_footer(root, info, verbatim_map)
    blocks.extend(hf_blocks)

    return blocks, verbatim_map


def _next_block_id() -> str:
    """Generate the next sequential block ID."""
    global _block_counter
    bid = make_block_id(_block_counter)
    _block_counter += 1
    return bid


def _next_verbatim_id() -> str:
    """Generate a verbatim ID matching the current block."""
    global _block_counter
    return make_verbatim_id(_block_counter - 1)


def _parse_paragraph(
    p_el: etree._Element,
    info: DocInfoResult,
    verbatim_map: dict[str, VerbatimBlock],
) -> Block | list[Block] | None:
    """<hp:p> → ParagraphBlock or HeadingBlock or TableBlock or list[Block].

    Returns a list when footnotes/endnotes produce extra blocks alongside
    the main paragraph block.
    """
    para_pr_id = int(p_el.get("paraPrIDRef", "0"))
    style_id_ref = int(p_el.get("styleIDRef", "0"))

    # 페이지 브레이크 확인
    page_break = p_el.get("pageBreak", "").lower() == "true"

    # 테이블이 이 단락에 있는지 확인
    for run in p_el.iterfind("hp:run", NS):
        tbl = run.find("hp:tbl", NS)
        if tbl is not None:
            result: list[Block] = []
            if page_break:
                pb_id = _next_block_id()
                result.append(PageBreakBlock(type="page_break", id=pb_id))
            result.append(_parse_table(tbl, info, verbatim_map))
            return result if len(result) > 1 else result[0]

    # 텍스트 인라인 수집 (extra_blocks for footnotes/endnotes)
    extra_blocks: list[Block] = []
    inlines = _collect_inlines(p_el, info, extra_blocks=extra_blocks)

    # 포맷 결정
    fmt = _build_para_format(para_pr_id, info)

    # 헤딩 레벨 결정
    heading_level = _determine_heading_level(para_pr_id, style_id_ref, info)

    block_id = _next_block_id()
    vid = _next_verbatim_id()

    verbatim_map[vid] = VerbatimBlock(decoded={"paraPrIDRef": para_pr_id, "styleIDRef": style_id_ref})

    result_blocks: list[Block] = []

    if page_break:
        pb_id = _next_block_id()
        result_blocks.append(PageBreakBlock(type="page_break", id=pb_id))

    if heading_level and heading_level >= 1:
        text = "".join(i.text for i in inlines if isinstance(i, TextInline))
        result_blocks.append(HeadingBlock(
            type="heading",
            id=block_id,
            level=min(heading_level, 6),
            text=text,
            inlines=inlines,
            format=fmt,
            verbatim_ref=vid,
        ))
    else:
        result_blocks.append(ParagraphBlock(
            type="paragraph",
            id=block_id,
            inlines=inlines,
            format=fmt,
            verbatim_ref=vid,
        ))

    result_blocks.extend(extra_blocks)

    if len(result_blocks) == 1:
        return result_blocks[0]
    return result_blocks


def _collect_inlines(
    p_el: etree._Element,
    info: DocInfoResult,
    extra_blocks: list[Block] | None = None,
) -> list[Any]:
    """<hp:p> 내 모든 <hp:run>에서 인라인 요소를 수집한다.

    hp:t (텍스트), hp:pic (이미지), hp:eqEdit (수식), hp:ctrl (하이퍼링크 등),
    hp:footNote, hp:endNote, hp:container (텍스트박스) 를 처리한다.

    extra_blocks가 주어지면, 각주/미주 블록을 해당 리스트에 추가한다.
    """
    inlines: list[Any] = []

    for run in p_el.iterfind("hp:run", NS):
        char_pr_id = int(run.get("charPrIDRef", "0"))
        cs = info.char_shapes[char_pr_id] if char_pr_id < len(info.char_shapes) else {}

        for child in run:
            tag = _local_tag(child)

            if tag == "t":
                _collect_text_inlines(child, cs, info, inlines)
            elif tag == "pic":
                img = _parse_pic(child)
                if img is not None:
                    inlines.append(img)
            elif tag == "eqEdit":
                eq = _parse_equation(child)
                if eq is not None:
                    inlines.append(eq)
            elif tag == "ctrl":
                ctrl_id = child.get("ctrlID", "")
                if ctrl_id == "hlnk":
                    link = _parse_hyperlink_ctrl(child, info)
                    if link is not None:
                        inlines.append(link)
            elif tag == "footNote" or tag == "endNote":
                ref_inline, note_block = _parse_note(child, tag, info)
                if ref_inline is not None:
                    inlines.append(ref_inline)
                if note_block is not None and extra_blocks is not None:
                    extra_blocks.append(note_block)
            elif tag == "container":
                tb = _parse_textbox_from_container(child, info)
                if tb is not None and extra_blocks is not None:
                    extra_blocks.append(tb)

    return inlines


def _local_tag(el: etree._Element) -> str:
    """요소의 로컬 이름을 반환한다 (네임스페이스 제거)."""
    tag = el.tag
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _collect_text_inlines(
    t_el: etree._Element,
    cs: dict[str, Any],
    info: DocInfoResult,
    inlines: list[Any],
) -> None:
    """<hp:t> 요소에서 텍스트와 하위 요소(tab, lineBreak 등)를 수집한다."""
    font_name = _resolve_font_name(cs, info)

    def _make_text_inline(text: str) -> TextInline:
        ls = cs.get("letter_spacing")
        co = cs.get("char_offset")
        return TextInline(
            text=text,
            bold=cs.get("bold"),
            italic=cs.get("italic"),
            underline=cs.get("underline"),
            strikethrough=cs.get("strikethrough"),
            color=_normalize_color(cs.get("color")),
            background_color=cs.get("shade_color"),
            font_name=font_name,
            font_size=cs["font_size_pt"] if cs.get("font_size_pt") else None,
            char_scale=cs.get("char_scale"),
            letter_spacing=_parse_pct(ls) if isinstance(ls, str) else ls,
            char_offset=_parse_pct(co) if isinstance(co, str) else co,
            outline=cs.get("outline"),
            shadow=cs.get("shadow"),
            emboss=cs.get("emboss"),
            engrave=cs.get("engrave"),
            underline_type=cs.get("underline_type"),
            underline_color=cs.get("underline_color"),
            strikeout_type=cs.get("strikeout_type"),
            strikeout_color=cs.get("strikeout_color"),
        )

    # 직접 텍스트
    text = t_el.text or ""
    if text:
        inlines.append(_make_text_inline(text))

    # 하위 요소 (tab, lineBreak 등)
    for sub in t_el:
        sub_tag = _local_tag(sub)
        if sub_tag == "tab":
            inlines.append(TextInline(text="\t"))
        elif sub_tag == "lineBreak":
            inlines.append(TextInline(text="\n"))
        # tail 텍스트 (하위 요소 뒤의 텍스트)
        if sub.tail:
            inlines.append(_make_text_inline(sub.tail))


def _resolve_font_name(cs: dict[str, Any], info: DocInfoResult) -> str | None:
    """charShape의 hangul_face_id로 FontFallbacks에서 폰트명을 가져온다."""
    face_id = cs.get("hangul_face_id")
    if face_id is None:
        return None
    gr = info.global_resources
    ff = gr.face_names.get(str(face_id))
    if ff is None:
        return None
    return ff.hangul or ff.latin


def _normalize_color(color: str | None) -> str | None:
    """#000000은 기본값이므로 None으로."""
    if not color:
        return None
    if color.lower() in ("#000000", "none"):
        return None
    return color


# ---------------------------------------------------------------------------
# 이미지 / 수식 / 하이퍼링크 / 각주 / 텍스트박스 파서
# ---------------------------------------------------------------------------


def _parse_pic(pic_el: etree._Element) -> ImageInline | None:
    """<hp:pic> → ImageInline.

    이미지 소스는 hp:img 요소의 binaryItemIDRef 속성에서 가져온다.
    """
    sz_el = pic_el.find("hp:sz", NS)
    width: float | None = None
    height: float | None = None
    if sz_el is not None:
        w = int(sz_el.get("width", "0"))
        h = int(sz_el.get("height", "0"))
        if w:
            width = hwpunit_to_pt(w)
        if h:
            height = hwpunit_to_pt(h)

    # hp:img는 여러 경로에 있을 수 있음
    img_el = pic_el.find(".//hp:img", NS)
    if img_el is None:
        return None

    binary_item_id = img_el.get("binaryItemIDRef", "")
    if not binary_item_id:
        return None

    src = f"bindata:{binary_item_id}"
    return ImageInline(src=src, width=width, height=height)


def _parse_equation(eq_el: etree._Element) -> EquationInline | None:
    """<hp:eqEdit> → EquationInline.

    수식 스크립트는 script 속성 또는 텍스트 콘텐츠에서 가져온다.
    """
    script = eq_el.get("script", "")
    if not script:
        script = eq_el.text or ""
    if not script:
        # <hp:eqEdit><hp:script>...</hp:script></hp:eqEdit> 패턴도 확인
        script_el = eq_el.find("hp:script", NS)
        if script_el is not None:
            script = script_el.text or ""
    return EquationInline(hwp_script=script if script else None)


def _parse_hyperlink_ctrl(
    ctrl_el: etree._Element, info: DocInfoResult
) -> LinkInline | None:
    """<hp:ctrl ctrlID="hlnk"> → LinkInline.

    href는 hp:url 속성 또는 하위 hp:url 요소에서 가져온다.
    텍스트는 내부 hp:t에서 수집한다.
    """
    url = ctrl_el.get("href", "")
    if not url:
        url_el = ctrl_el.find(".//hp:url", NS)
        if url_el is not None:
            url = url_el.text or url_el.get("href", "")
    if not url:
        # ha:url 네임스페이스 시도
        url = ctrl_el.get("url", "")

    # 텍스트 수집
    texts: list[str] = []
    for t_el in ctrl_el.iter():
        if _local_tag(t_el) == "t" and t_el.text:
            texts.append(t_el.text)
    text = "".join(texts) if texts else url

    if not url and not text:
        return None

    return LinkInline(text=text, url=url)


def _parse_note(
    note_el: etree._Element,
    note_type: str,
    info: DocInfoResult,
) -> tuple[FootnoteRefInline | None, Block | None]:
    """<hp:footNote> 또는 <hp:endNote> → (FootnoteRefInline, FootnoteBlock/EndnoteBlock).

    subList 안의 단락들을 파싱하여 각주/미주 블록의 content로 사용한다.
    """
    ref_id = _next_block_id()

    # 각주/미주 번호
    number_str = note_el.get("number", "")
    number = int(number_str) if number_str.isdigit() else None

    ref_inline = FootnoteRefInline(ref_id=ref_id, number=number)

    # subList에서 content 파싱
    sub_list = note_el.find("hp:subList", NS)
    content: list[Block] = []
    if sub_list is not None:
        # subList 내 paragraph를 간단히 파싱 (verbatim_map 없이)
        dummy_verbatim: dict[str, VerbatimBlock] = {}
        for sub_p in sub_list.iterfind("hp:p", NS):
            block = _parse_paragraph(sub_p, info, dummy_verbatim)
            if block is not None:
                if isinstance(block, list):
                    content.extend(block)
                else:
                    content.append(block)

    note_id = _next_block_id()
    if note_type == "footNote":
        note_block: Block = FootnoteBlock(
            type="footnote", id=note_id, ref=ref_id, content=content
        )
    else:
        note_block = EndnoteBlock(
            type="endnote", id=note_id, ref=ref_id, content=content
        )

    return ref_inline, note_block


def _parse_textbox_from_container(
    container_el: etree._Element, info: DocInfoResult
) -> TextBoxBlock | None:
    """<hp:container> → TextBoxBlock.

    drawText > subList 안의 단락들을 파싱한다.
    """
    # hp:drawText 또는 직접 hp:subList 찾기
    sub_list = container_el.find(".//hp:subList", NS)
    if sub_list is None:
        return None

    content: list[Block] = []
    dummy_verbatim: dict[str, VerbatimBlock] = {}
    for sub_p in sub_list.iterfind("hp:p", NS):
        block = _parse_paragraph(sub_p, info, dummy_verbatim)
        if block is not None:
            if isinstance(block, list):
                content.extend(block)
            else:
                content.append(block)

    if not content:
        return None

    tb_id = _next_block_id()
    return TextBoxBlock(type="text_box", id=tb_id, content=content)


def _extract_header_footer(
    root: etree._Element,
    info: DocInfoResult,
    verbatim_map: dict[str, VerbatimBlock],
) -> list[Block]:
    """section XML의 secPr에서 headerFooter 요소를 찾아 HeaderBlock/FooterBlock을 생성한다."""
    blocks: list[Block] = []

    # secPr은 hp:p > hp:run > hp:secPr 경로에 있음
    for p_el in root.iterfind("hp:p", NS):
        for run in p_el.iterfind("hp:run", NS):
            sec_pr = run.find("hp:secPr", NS)
            if sec_pr is None:
                continue

            for hf_el in sec_pr:
                hf_tag = _local_tag(hf_el)
                if hf_tag != "headerFooter":
                    continue

                hf_type = hf_el.get("type", "BOTH")  # BOTH, EVEN, ODD, FIRST
                header_or_footer = hf_el.get("headerFooter", "HEADER")

                apply_to_map = {
                    "BOTH": "all",
                    "EVEN": "even",
                    "ODD": "odd",
                    "FIRST": "first",
                }
                apply_to = apply_to_map.get(hf_type, "all")

                # subList 안의 단락 파싱
                sub_list = hf_el.find("hp:subList", NS)
                content: list[Block] = []
                if sub_list is not None:
                    for sub_p in sub_list.iterfind("hp:p", NS):
                        block = _parse_paragraph(sub_p, info, verbatim_map)
                        if block is not None:
                            if isinstance(block, list):
                                content.extend(block)
                            else:
                                content.append(block)

                hf_id = _next_block_id()
                if header_or_footer == "HEADER":
                    blocks.append(HeaderBlock(
                        type="header", id=hf_id, apply_to=apply_to, content=content
                    ))
                else:
                    blocks.append(FooterBlock(
                        type="footer", id=hf_id, apply_to=apply_to, content=content
                    ))

    return blocks


def _build_para_format(para_pr_id: int, info: DocInfoResult) -> BlockFormat | None:
    """para_shapes[N] → BlockFormat."""
    if para_pr_id >= len(info.para_shapes):
        return None

    ps = info.para_shapes[para_pr_id]
    _VALID_ALIGNS = ("left", "center", "right", "justify")
    _VALID_LS_TYPES = ("follow_char", "fixed", "leading_only", "minimum", "ratio")

    align = ps.get("alignment")
    ls_type = ps.get("line_spacing_type")
    ls_val = ps.get("line_spacing_hwp", 0)

    def _to_pt(v: int) -> float | None:
        if not v or v >= 0xFFFFFFF0:
            return None
        return hwpunit_to_pt(v)

    line_spacing: float | Ratio | None = None
    if ls_val and ls_val < 0xFFFFFFF0:
        if ls_type in (None, "ratio"):
            line_spacing = Ratio(ls_val)
        else:
            line_spacing = hwpunit_to_pt(ls_val)

    keep_with_next = True if ps.get("with_next_paragraph") else None
    page_break_before = True if ps.get("start_new_page") else None
    widow_orphan = True if ps.get("protect") else None

    fmt = BlockFormat(
        alignment=align if align in _VALID_ALIGNS else None,
        indent_left=_to_pt(ps.get("indent_left_hwp", 0)),
        indent_right=_to_pt(ps.get("indent_right_hwp", 0)),
        space_before=_to_pt(ps.get("space_before_hwp", 0)),
        space_after=_to_pt(ps.get("space_after_hwp", 0)),
        line_spacing=line_spacing,
        line_spacing_type=ls_type if ls_type in _VALID_LS_TYPES else None,
        keep_with_next=keep_with_next,
        page_break_before=page_break_before,
        widow_orphan=widow_orphan,
    )
    return fmt


def _determine_heading_level(
    para_pr_id: int, style_id_ref: int, info: DocInfoResult
) -> int | None:
    """스타일 이름 또는 paraPr의 heading level로 헤딩 판별."""
    # 스타일 이름으로 판별
    if style_id_ref < len(info.style_names):
        style_name = info.style_names[style_id_ref]
        m = _OUTLINE_RE.match(style_name.strip())
        if m:
            level = int(m.group(1) or m.group(2))
            return min(max(level, 1), 6)

    # paraPr의 level로 판별
    if para_pr_id < len(info.para_shapes):
        ps = info.para_shapes[para_pr_id]
        level = ps.get("level")
        if level and level > 0:
            return min(level, 6)

    return None


def _is_list_style(style_id_ref: int, info: DocInfoResult) -> bool:
    """style_id_ref가 리스트 스타일인지 판별."""
    if style_id_ref >= len(info.style_names):
        return False
    name = info.style_names[style_id_ref].strip()
    return _LIST_STYLE_RE.match(name) is not None


def _flush_list(
    acc: list[tuple[int, ParagraphBlock]],
    info: DocInfoResult,
) -> ListBlock:
    """누적된 리스트 단락들을 ListBlock으로 변환."""
    bid = _next_block_id()

    first_style_id = acc[0][0]
    style_name = ""
    if first_style_id < len(info.style_names):
        style_name = info.style_names[first_style_id].strip()

    ordered = style_name not in ("MsoListParagraph", "ListParagraph")

    items: list[ListItem] = []
    for _style_id, pb in acc:
        text = "".join(i.text for i in pb.inlines if isinstance(i, TextInline)).strip()
        if not text:
            continue
        items.append(ListItem(
            id=pb.id,
            inlines=pb.inlines,
            format=pb.format,
            verbatim_ref=pb.verbatim_ref,
        ))

    return ListBlock(
        type="list",
        id=bid,
        ordered=ordered,
        items=items,
        list_style=style_name or None,
    )


def _parse_table(
    tbl_el: etree._Element,
    info: DocInfoResult,
    verbatim_map: dict[str, VerbatimBlock],
) -> TableBlock:
    """<hp:tbl> → TableBlock."""
    block_id = _next_block_id()
    vid = _next_verbatim_id()

    row_cnt = int(tbl_el.get("rowCnt", "0"))
    col_cnt = int(tbl_el.get("colCnt", "0"))
    cell_spacing = int(tbl_el.get("cellSpacing", "0"))
    border_fill_id_ref = tbl_el.get("borderFillIDRef")

    # 위치 정보
    pos_el = tbl_el.find("hp:pos", NS)
    position: PositionInfo | None = None
    if pos_el is not None:
        like_char = pos_el.get("treatAsChar") == "1"
        position = PositionInfo(like_char=like_char)

    # 크기 정보
    sz_el = tbl_el.find("hp:sz", NS)
    if sz_el is not None and position:
        w = int(sz_el.get("width", "0"))
        h = int(sz_el.get("height", "0"))
        if w:
            position.width = w / _HWPUNIT_PER_PT
        if h:
            position.height = h / _HWPUNIT_PER_PT

    rows: list[TableRow] = []
    for tr_el in tbl_el.iterfind("hp:tr", NS):
        row = _parse_table_row(tr_el, info, verbatim_map)
        rows.append(row)

    verbatim_map[vid] = VerbatimBlock(decoded={"rowCnt": row_cnt, "colCnt": col_cnt})

    return TableBlock(
        type="table",
        id=block_id,
        rows=rows,
        position=position,
        cell_spacing=hwpunit_to_pt(cell_spacing) if cell_spacing else None,
        border_fill_id=int(border_fill_id_ref) if border_fill_id_ref else None,
        verbatim_ref=vid,
    )


def _parse_table_row(
    tr_el: etree._Element,
    info: DocInfoResult,
    verbatim_map: dict[str, VerbatimBlock],
) -> TableRow:
    """<hp:tr> → TableRow."""
    cells: list[TableCell] = []
    for tc_el in tr_el.iterfind("hp:tc", NS):
        cell = _parse_table_cell(tc_el, info, verbatim_map)
        cells.append(cell)
    return TableRow(cells=cells)


def _parse_table_cell(
    tc_el: etree._Element,
    info: DocInfoResult,
    verbatim_map: dict[str, VerbatimBlock],
) -> TableCell:
    """<hp:tc> → TableCell."""
    cell_id = _next_block_id()

    # span
    span_el = tc_el.find("hp:cellSpan", NS)
    col_span = 1
    row_span = 1
    if span_el is not None:
        col_span = int(span_el.get("colSpan", "1"))
        row_span = int(span_el.get("rowSpan", "1"))

    # size
    sz_el = tc_el.find("hp:cellSz", NS)
    width: float | None = None
    height: float | None = None
    if sz_el is not None:
        w = int(sz_el.get("width", "0"))
        h = int(sz_el.get("height", "0"))
        if w:
            width = w / _HWPUNIT_PER_PT
        if h:
            height = h / _HWPUNIT_PER_PT

    # format
    border_fill_id_ref = tc_el.get("borderFillIDRef")
    cell_margin_el = tc_el.find("hp:cellMargin", NS)
    sub_list_el = tc_el.find("hp:subList", NS)

    vert_align: str | None = None
    if sub_list_el is not None:
        va = sub_list_el.get("vertAlign", "").upper()
        if va == "CENTER":
            vert_align = "middle"
        elif va == "BOTTOM":
            vert_align = "bottom"
        elif va == "TOP":
            vert_align = "top"

    padding_left: float | None = None
    padding_right: float | None = None
    padding_top: float | None = None
    padding_bottom: float | None = None
    if cell_margin_el is not None:
        pl = int(cell_margin_el.get("left", "0"))
        pr = int(cell_margin_el.get("right", "0"))
        pt_val = int(cell_margin_el.get("top", "0"))
        pb = int(cell_margin_el.get("bottom", "0"))
        if pl:
            padding_left = hwpunit_to_pt(pl)
        if pr:
            padding_right = hwpunit_to_pt(pr)
        if pt_val:
            padding_top = hwpunit_to_pt(pt_val)
        if pb:
            padding_bottom = hwpunit_to_pt(pb)

    cell_format = CellFormat(
        vertical_align=vert_align,
        padding_left=padding_left,
        padding_right=padding_right,
        padding_top=padding_top,
        padding_bottom=padding_bottom,
    )

    # 셀 내용 (subList 안의 단락들)
    content: list[Block] = []
    if sub_list_el is not None:
        for sub_p in sub_list_el.iterfind("hp:p", NS):
            block = _parse_paragraph(sub_p, info, verbatim_map)
            if block is not None:
                if isinstance(block, list):
                    content.extend(block)
                else:
                    content.append(block)

    return TableCell(
        id=cell_id,
        row_span=row_span,
        col_span=col_span,
        width=width,
        height=height,
        content=content,
        format=cell_format,
    )


def extract_page_def(section_bytes: bytes) -> dict[str, Any] | None:
    """Extract page dimensions and margins from an HWPX section XML.

    Parameters
    ----------
    section_bytes : bytes
        Raw XML content of a section file.

    Returns
    -------
    dict[str, Any] | None
        Page dimensions in points, or ``None`` if no page definition is found.
    """
    root = etree.fromstring(section_bytes)

    for p_el in root.iterfind("hp:p", NS):
        for run in p_el.iterfind("hp:run", NS):
            sec_pr = run.find("hp:secPr", NS)
            if sec_pr is not None:
                page_pr = sec_pr.find("hp:pagePr", NS)
                if page_pr is not None:
                    return _extract_from_page_pr(page_pr)
    return None


def _extract_from_page_pr(page_pr: etree._Element) -> dict[str, Any]:
    """Convert a pagePr element to a page dimensions dict in points."""
    width = int(page_pr.get("width", "0"))
    height = int(page_pr.get("height", "0"))

    margin_el = page_pr.find("hp:margin", NS)
    left = top = right = bottom = header = footer = 0
    if margin_el is not None:
        left = int(margin_el.get("left", "0"))
        right = int(margin_el.get("right", "0"))
        top = int(margin_el.get("top", "0"))
        bottom = int(margin_el.get("bottom", "0"))
        header = int(margin_el.get("header", "0"))
        footer = int(margin_el.get("footer", "0"))

    result: dict[str, Any] = {
        "page_width": hwpunit_to_pt(width),
        "page_height": hwpunit_to_pt(height),
        "margin_left": hwpunit_to_pt(left),
        "margin_right": hwpunit_to_pt(right),
        "margin_top": hwpunit_to_pt(top),
        "margin_bottom": hwpunit_to_pt(bottom),
        "header_offset": hwpunit_to_pt(header),
        "footer_offset": hwpunit_to_pt(footer),
    }

    landscape = page_pr.get("landscape", "")
    if landscape in ("true", "1"):
        result["orientation"] = "landscape"

    gutter_el = page_pr.find("hp:gutter", NS)
    if gutter_el is not None:
        gutter_val = int(gutter_el.get("value", "0"))
        if gutter_val:
            result["gutter"] = hwpunit_to_pt(gutter_val)

    col_el = page_pr.find("hp:multiColumn", NS)
    if col_el is None:
        col_el = page_pr.find("hp:columnDef", NS)
    if col_el is not None:
        col_count = int(col_el.get("count", "1"))
        if col_count > 1:
            col_gap = int(col_el.get("gap", "0"))
            same_width = col_el.get("sameWidth", "1") == "1"
            result["column_count"] = col_count
            if col_gap:
                result["column_gap"] = hwpunit_to_pt(col_gap)
            result["column_same_width"] = same_width

    return result
