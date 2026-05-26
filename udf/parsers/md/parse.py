"""GFM Markdown parser.

Convert GitHub-Flavored Markdown text into a UdfDocument. Extracts
optional block IDs from ``<!-- id: blk-xxx -->`` comments (as emitted
by ``render_md(embed_ids=True)``). Plain Markdown without IDs is also
accepted (order-based matching).

Supported syntax:
  <!-- id: blk-xxx -->   block ID comment
  # / ## / ... / ######  headings
  **bold**, *italic*     inline formatting
  ~~strikethrough~~, <u>underline</u>
  $...$                  inline equations
  [^ref]                 footnote references
  <table>...</table>     HTML tables (rowspan/colspan)
  | col | col |          GFM pipe tables (legacy compat)
"""

from __future__ import annotations

import re
from typing import Iterator, cast

from udf.schema import (
    Block,
    DocumentMetadata,
    DocumentSchema,
    EquationInline,
    FootnoteBlock,
    FootnoteRefInline,
    HeadingBlock,
    Inline,
    LinkInline,
    ListBlock,
    ListItem,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextInline,
)
from udf.pipeline import UdfDocument, VerbatimLayer
import itertools

from udf.core.ids import make_block_id

_ID_COMMENT_RE = re.compile(r"<!--\s*id:\s*(\S+)\s*-->")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
_SEP_ROW_RE = re.compile(r"^\|[\s\-:|]+\|$")
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^(\w+)\]:\s*(.*)")
_HTML_TABLE_START_RE = re.compile(r"^\s*<table\b", re.IGNORECASE)
_HTML_TABLE_END_RE = re.compile(r"</table>", re.IGNORECASE)
_HTML_TD_RE = re.compile(
    r'<td(?:\s+([^>]*))?>(.+?)</td>', re.IGNORECASE | re.DOTALL,
)
_HTML_ROWSPAN_RE = re.compile(r'rowspan="(\d+)"', re.IGNORECASE)
_HTML_COLSPAN_RE = re.compile(r'colspan="(\d+)"', re.IGNORECASE)
_HTML_WIDTH_RE = re.compile(r'width="([^"]+)"', re.IGNORECASE)


# ---------------------------------------------------------------------------
# 인라인 파서 (재귀, 중첩 서식 지원)
# ---------------------------------------------------------------------------

# render_md 출력 순서: bold → italic → strikethrough → underline (outermost)
_INLINE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\*\*\*(.+?)\*\*\*", re.DOTALL), "bold_italic"),
    (re.compile(r"\*\*(.+?)\*\*", re.DOTALL), "bold"),
    (re.compile(r"\*(.+?)\*", re.DOTALL), "italic"),
    (re.compile(r"~~(.+?)~~", re.DOTALL), "strike"),
    (re.compile(r"<u>(.+?)</u>", re.DOTALL), "underline"),
]

_MD_UNESCAPE_RE = re.compile(r"\\([\\`*_~|\[\].\-+!#>])")


def _unescape(text: str) -> str:
    """Remove markdown backslash escapes."""
    return _MD_UNESCAPE_RE.sub(r"\1", text)


_EQUATION_INLINE_RE = re.compile(r"\$([^\$]+)\$")
_FOOTNOTE_REF_RE = re.compile(r"\[\^(\w+)\](?!:)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_UL_RE = re.compile(r"^(\s*)[-*+]\s+(.*)")
_OL_RE = re.compile(r"^(\s*)(\d+)\.\s+(.*)")


def _parse_inlines(text: str) -> list[Inline]:
    """재귀 인라인 서식 파서 — 중첩 포맷(~~***text***~~ 등) 지원.

    $...$은 EquationInline, [^id]는 FootnoteRefInline으로 변환.
    """
    result: list[Inline] = []
    _split_special_inlines(text, result)
    return result


def _split_special_inlines(text: str, out: list[Inline]) -> None:
    """$...$, [^ref], [text](url) 등 특수 인라인을 먼저 분리한 뒤, 나머지를 서식 파서로 전달."""
    patterns: list[tuple[re.Pattern[str], str]] = [
        (_EQUATION_INLINE_RE, "equation"),
        (_FOOTNOTE_REF_RE, "fnref"),
        (_LINK_RE, "link"),
    ]
    earliest_start = len(text)
    earliest_m: re.Match[str] | None = None
    earliest_key = ""
    for pat, key in patterns:
        m = pat.search(text)
        if m and m.start() < earliest_start:
            earliest_start = m.start()
            earliest_m = m
            earliest_key = key
    if earliest_m is None:
        styled: list[TextInline] = []
        _parse_seg(text, bold=False, italic=False, strike=False, underline=False, out=styled)
        out.extend(styled)
        return
    if earliest_start > 0:
        styled = []
        _parse_seg(text[:earliest_start], bold=False, italic=False, strike=False, underline=False, out=styled)
        out.extend(styled)
    if earliest_key == "equation":
        out.append(EquationInline(latex=_unescape(earliest_m.group(1))))
    elif earliest_key == "fnref":
        out.append(FootnoteRefInline(ref_id=earliest_m.group(1)))
    elif earliest_key == "link":
        out.append(LinkInline(text=_unescape(earliest_m.group(1)), url=earliest_m.group(2)))
    if earliest_m.end() < len(text):
        _split_special_inlines(text[earliest_m.end():], out)


def _parse_seg(
    text: str,
    *,
    bold: bool,
    italic: bool,
    strike: bool,
    underline: bool,
    out: list[TextInline],
) -> None:
    """Recursively parse inline markdown formatting into TextInline spans."""
    if not text:
        return

    # 가장 앞서 매칭되는 패턴을 찾는다
    earliest_start = len(text)
    earliest_m: re.Match[str] | None = None
    earliest_key = ""

    for pat, key in _INLINE_PATTERNS:
        m = pat.search(text)
        if m and m.start() < earliest_start:
            earliest_start = m.start()
            earliest_m = m
            earliest_key = key

    if earliest_m is None:
        plain = _unescape(text)
        if plain:
            out.append(
                TextInline(
                    text=plain,
                    bold=bold or None,
                    italic=italic or None,
                    strikethrough=strike or None,
                    underline=underline or None,
                )
            )
        return

    # 매칭 이전 평문
    if earliest_start > 0:
        plain = _unescape(text[:earliest_start])
        if plain:
            out.append(
                TextInline(
                    text=plain,
                    bold=bold or None,
                    italic=italic or None,
                    strikethrough=strike or None,
                    underline=underline or None,
                )
            )

    # 매칭 내부를 재귀 처리
    nb = bold or earliest_key in ("bold", "bold_italic")
    ni = italic or earliest_key in ("italic", "bold_italic")
    ns = strike or earliest_key == "strike"
    nu = underline or earliest_key == "underline"
    _parse_seg(
        earliest_m.group(1), bold=nb, italic=ni, strike=ns, underline=nu, out=out
    )

    # 매칭 이후 잔여 텍스트
    _parse_seg(
        text[earliest_m.end() :],
        bold=bold,
        italic=italic,
        strike=strike,
        underline=underline,
        out=out,
    )


# ---------------------------------------------------------------------------
# 블록 파서
# ---------------------------------------------------------------------------


def _extract_cell_text(cell: str) -> str:
    """Strip whitespace from a table cell string."""
    return cell.strip()


def _parse_table_rows(lines: list[str]) -> TableBlock | None:
    """파이프 테이블 행 목록 → TableBlock. 구분행 제외."""
    data_rows = [ln for ln in lines if not _SEP_ROW_RE.match(ln)]
    if not data_rows:
        return None

    block_counter = itertools.count(1)
    rows: list[TableRow] = []
    for ln in data_rows:
        cols = [c.strip() for c in ln.strip("|").split("|")]
        cells = [
            TableCell(
                id=make_block_id(next(block_counter)),
                content=[
                    ParagraphBlock(
                        type="paragraph",
                        id=make_block_id(next(block_counter)),
                        inlines=_parse_inlines(c),
                    )
                ],
            )
            for c in cols
        ]
        rows.append(TableRow(cells=cells))

    return TableBlock(
        type="table",
        id=make_block_id(next(block_counter)),
        rows=rows,
    )


def _unescape_html(text: str) -> str:
    """Unescape basic HTML entities."""
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


_HTML_INLINE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"<strong>(.+?)</strong>", re.DOTALL), "bold"),
    (re.compile(r"<em>(.+?)</em>", re.DOTALL), "italic"),
    (re.compile(r"<del>(.+?)</del>", re.DOTALL), "strike"),
    (re.compile(r"<u>(.+?)</u>", re.DOTALL), "underline"),
]


def _parse_html_inlines(html: str) -> list[Inline]:
    """Parse HTML inline tags into Inline objects."""
    out: list[TextInline] = []
    _parse_html_seg(html, bold=False, italic=False, strike=False, underline=False, out=out)
    return cast(list[Inline], out)


def _parse_html_seg(
    text: str,
    *,
    bold: bool,
    italic: bool,
    strike: bool,
    underline: bool,
    out: list[TextInline],
) -> None:
    """Recursively parse HTML inline formatting into TextInline spans."""
    if not text:
        return
    earliest_start = len(text)
    earliest_m: re.Match[str] | None = None
    earliest_key = ""
    for pat, key in _HTML_INLINE_PATTERNS:
        m = pat.search(text)
        if m and m.start() < earliest_start:
            earliest_start = m.start()
            earliest_m = m
            earliest_key = key
    if earliest_m is None:
        plain = _unescape_html(text)
        if plain:
            out.append(TextInline(
                text=plain,
                bold=bold or None, italic=italic or None,
                strikethrough=strike or None, underline=underline or None,
            ))
        return
    if earliest_start > 0:
        plain = _unescape_html(text[:earliest_start])
        if plain:
            out.append(TextInline(
                text=plain,
                bold=bold or None, italic=italic or None,
                strikethrough=strike or None, underline=underline or None,
            ))
    nb = bold or earliest_key == "bold"
    ni = italic or earliest_key == "italic"
    ns = strike or earliest_key == "strike"
    nu = underline or earliest_key == "underline"
    _parse_html_seg(earliest_m.group(1), bold=nb, italic=ni, strike=ns, underline=nu, out=out)
    _parse_html_seg(text[earliest_m.end():], bold=bold, italic=italic, strike=strike, underline=underline, out=out)


def _parse_html_table(
    html_lines: list[str],
    block_counter: "itertools.count[int]",
) -> TableBlock | None:
    """<table>...</table> HTML → TableBlock."""
    html = "\n".join(html_lines)
    rows: list[TableRow] = []
    for tr_m in re.finditer(r"<tr>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE):
        tr_content = tr_m.group(1)
        cells: list[TableCell] = []
        for td_m in _HTML_TD_RE.finditer(tr_content):
            attrs_str = td_m.group(1) or ""
            cell_html = td_m.group(2).strip()

            row_span = 1
            col_span = 1
            rs_m = _HTML_ROWSPAN_RE.search(attrs_str)
            if rs_m:
                row_span = int(rs_m.group(1))
            cs_m = _HTML_COLSPAN_RE.search(attrs_str)
            if cs_m:
                col_span = int(cs_m.group(1))

            parts = re.split(r"<br\s*/?>", cell_html, flags=re.IGNORECASE)
            content: list[Block] = []
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                inlines = _parse_html_inlines(part)
                if inlines:
                    content.append(ParagraphBlock(
                        type="paragraph",
                        id=make_block_id(next(block_counter)),
                        inlines=inlines,
                    ))
            cells.append(TableCell(
                id=make_block_id(next(block_counter)),
                content=content,
                row_span=row_span,
                col_span=col_span,
            ))
        if cells:
            rows.append(TableRow(cells=cells))
    if not rows:
        return None
    return TableBlock(
        type="table",
        id=make_block_id(next(block_counter)),
        rows=rows,
    )


def _iter_blocks(
    lines: list[str],
    block_counter: "itertools.count[int]",
    verb_counter: "itertools.count[int]",  # noqa: ARG001
) -> "Iterator[Block]":
    """줄 목록을 블록 단위로 순회하며 yield."""
    i = 0
    pending_id: str | None = None

    while i < len(lines):
        line = lines[i]

        # ID 주석
        m = _ID_COMMENT_RE.match(line.strip())
        if m:
            pending_id = m.group(1)
            i += 1
            continue

        # 빈 줄
        if not line.strip():
            i += 1
            continue

        # 각주 정의: [^N]: content
        fnm = _FOOTNOTE_DEF_RE.match(line)
        if fnm:
            ref = fnm.group(1)
            content_text = _unescape(fnm.group(2).strip())
            blk_id = pending_id or make_block_id(next(block_counter))
            pending_id = None
            content_blocks: list[Block] = []
            if content_text:
                content_blocks.append(
                    ParagraphBlock(
                        type="paragraph",
                        id=make_block_id(next(block_counter)),
                        inlines=_parse_inlines(content_text),
                    )
                )
            yield FootnoteBlock(
                type="footnote", id=blk_id, ref=ref, content=content_blocks,
            )
            i += 1
            continue

        # 헤딩
        hm = _HEADING_RE.match(line)
        if hm:
            level = len(hm.group(1))
            text = _unescape(hm.group(2).strip())
            blk_id = pending_id or make_block_id(next(block_counter))
            pending_id = None
            yield HeadingBlock(type="heading", id=blk_id, level=level, text=text)
            i += 1
            continue

        # HTML 테이블: <table> ~ </table> 수집
        if _HTML_TABLE_START_RE.match(line):
            html_lines: list[str] = [line]
            i += 1
            while i < len(lines) and not _HTML_TABLE_END_RE.search(lines[i]):
                html_lines.append(lines[i])
                i += 1
            if i < len(lines):
                html_lines.append(lines[i])
                i += 1
            tbl = _parse_html_table(html_lines, block_counter)
            if tbl is not None:
                blk_id = pending_id or make_block_id(next(block_counter))
                pending_id = None
                tbl = tbl.model_copy(update={"id": blk_id})
                yield tbl
            continue

        # 파이프 테이블: 연속된 파이프 행 수집
        if _TABLE_ROW_RE.match(line):
            tbl_lines: list[str] = []
            while i < len(lines) and _TABLE_ROW_RE.match(lines[i]):
                tbl_lines.append(lines[i])
                i += 1
            tbl = _parse_table_rows(tbl_lines)
            if tbl is not None:
                blk_id = pending_id or make_block_id(next(block_counter))
                pending_id = None
                tbl = tbl.model_copy(update={"id": blk_id})
                yield tbl
            continue

        # 리스트: - / * / + 또는 1. 2. 등
        ul_m = _UL_RE.match(line)
        ol_m = _OL_RE.match(line)
        if ul_m or ol_m:
            ordered = ol_m is not None
            start_num = int(ol_m.group(2)) if ol_m else None
            items: list[ListItem] = []
            while i < len(lines):
                um = _UL_RE.match(lines[i])
                om = _OL_RE.match(lines[i])
                if um and not ordered:
                    item_text = um.group(2)
                    items.append(ListItem(
                        id=make_block_id(next(block_counter)),
                        inlines=_parse_inlines(item_text),
                    ))
                    i += 1
                elif om and ordered:
                    item_text = om.group(3)
                    items.append(ListItem(
                        id=make_block_id(next(block_counter)),
                        inlines=_parse_inlines(item_text),
                    ))
                    i += 1
                else:
                    break
            if items:
                blk_id = pending_id or make_block_id(next(block_counter))
                pending_id = None
                yield ListBlock(
                    type="list", id=blk_id, ordered=ordered,
                    start=start_num, items=items,
                )
            continue

        # 단락: 빈 줄이나 헤딩·테이블 전까지 연속 행 수집
        para_lines: list[str] = []
        while i < len(lines) and lines[i].strip():
            if _HEADING_RE.match(lines[i]) or _TABLE_ROW_RE.match(lines[i]):
                break
            if _HTML_TABLE_START_RE.match(lines[i]):
                break
            if _ID_COMMENT_RE.match(lines[i].strip()):
                break
            if _UL_RE.match(lines[i]) or _OL_RE.match(lines[i]):
                break
            para_lines.append(lines[i])
            i += 1
        if para_lines:
            text = " ".join(para_lines).strip()
            inlines = _parse_inlines(text)
            if inlines:
                blk_id = pending_id or make_block_id(next(block_counter))
                pending_id = None
                yield ParagraphBlock(type="paragraph", id=blk_id, inlines=inlines)
        continue

    # 남은 pending_id는 버림 (빈 블록)


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def parse_md(text: str) -> UdfDocument:
    """Parse a GFM Markdown string into a UdfDocument.

    Parameters
    ----------
    text : str
        GFM Markdown content. Both ``embed_ids=True`` (with block ID
        comments) and plain Markdown are accepted.

    Returns
    -------
    UdfDocument
        Document model with semantic blocks. The VerbatimLayer is empty
        since Markdown has no binary verbatim data.
    """
    block_counter: itertools.count[int] = itertools.count(1)
    verb_counter: itertools.count[int] = itertools.count(1)
    lines = text.splitlines()
    blocks = list(_iter_blocks(lines, block_counter, verb_counter))
    return UdfDocument(
        source_format="md",
        document=DocumentSchema(
            metadata=DocumentMetadata(),
            blocks=blocks,
        ),
        verbatim=VerbatimLayer(format="md"),
    )
