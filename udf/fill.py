"""Template filling — parse an HWP/HWPX template and inject MD draft content by section matching.

This module provides ``fill_template()``, a high-level convenience that:

1. Parses the template document (HWP/HWPX).
2. Parses the Markdown draft.
3. Matches template sections to draft sections by header similarity.
4. Replaces template content paragraphs with draft text.
5. Renders the filled document via Seed Patch.

Usage::

    import udf
    from udf.fill import fill_template

    output = fill_template("template.hwp", "draft.md", "filled.hwp")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from udf.schema.blocks import (
    Block,
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    TableBlock,
    TextBoxBlock,
)
from udf.schema.inlines import TextInline


# ---------------------------------------------------------------------------
# Section extraction — Template
# ---------------------------------------------------------------------------

def _textbox_header_text(block: TextBoxBlock) -> str:
    parts: list[str] = []

    def _collect(children: list[Block]) -> None:
        for c in children:
            if isinstance(c, TextBoxBlock):
                _collect(c.content)
            elif isinstance(c, ParagraphBlock):
                t = "".join(i.text for i in c.inlines if isinstance(i, TextInline))
                if t.strip():
                    parts.append(t.strip())

    _collect(block.content)
    return " / ".join(parts)


def _table_paragraphs(table: TableBlock) -> list[ParagraphBlock]:
    paras: list[ParagraphBlock] = []
    for row in table.rows:
        for cell in row.cells:
            for c in cell.content:
                if isinstance(c, ParagraphBlock):
                    paras.append(c)
    return paras


def _is_data_table(table: TableBlock) -> bool:
    if not table.rows:
        return False
    max_cells = max(len(r.cells) for r in table.rows)
    return len(table.rows) >= 5 and max_cells >= 3


def _para_text(p: ParagraphBlock) -> str:
    return "".join(i.text for i in p.inlines if isinstance(i, TextInline))


class _TemplateSection:
    __slots__ = ("header_raw", "header_norm", "paras")

    def __init__(self, header_raw: str, header_norm: str, paras: list[ParagraphBlock]):
        self.header_raw = header_raw
        self.header_norm = header_norm
        self.paras = paras


def _extract_template_sections(blocks: list[Block]) -> list[_TemplateSection]:
    sections: list[_TemplateSection] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if isinstance(b, TextBoxBlock):
            header = _textbox_header_text(b)
            tables: list[TableBlock] = []
            j = i + 1
            while j < len(blocks) and j < i + 20:
                nxt = blocks[j]
                if isinstance(nxt, TextBoxBlock):
                    break
                if isinstance(nxt, TableBlock):
                    tables.append(nxt)
                j += 1

            if tables:
                paras: list[ParagraphBlock] = []
                for t in tables:
                    if not _is_data_table(t):
                        paras.extend(_table_paragraphs(t))
                sections.append(_TemplateSection(
                    header_raw=header,
                    header_norm=_normalize(header),
                    paras=paras,
                ))
        i += 1
    return sections


# ---------------------------------------------------------------------------
# Section extraction — Markdown
# ---------------------------------------------------------------------------

class _MdSection:
    __slots__ = ("heading", "heading_norm", "level", "paragraphs", "paragraphs_deep")

    def __init__(self, heading: str, heading_norm: str, level: int, paragraphs: list[str]):
        self.heading = heading
        self.heading_norm = heading_norm
        self.level = level
        self.paragraphs = paragraphs
        self.paragraphs_deep: list[str] = []


def _extract_md_sections(doc: Any) -> list[_MdSection]:
    sections: list[_MdSection] = []
    current: _MdSection | None = None

    for block in doc.blocks:
        if isinstance(block, HeadingBlock):
            if current is not None:
                sections.append(current)
            current = _MdSection(
                heading=block.text,
                heading_norm=_normalize(block.text),
                level=block.level,
                paragraphs=[],
            )
        elif isinstance(block, ParagraphBlock):
            text = "".join(i.text for i in block.inlines if isinstance(i, TextInline))
            if text.strip():
                if current is None:
                    current = _MdSection("(preamble)", "", 0, [])
                current.paragraphs.append(text)
        elif isinstance(block, ListBlock):
            if current is not None:
                for item in block.items:
                    t = "".join(i.text for i in item.inlines if isinstance(i, TextInline))
                    if t.strip():
                        current.paragraphs.append(t)
        elif isinstance(block, TableBlock):
            text = _md_table_to_text(block)
            if text and current is not None:
                current.paragraphs.append(text)

    if current is not None:
        sections.append(current)

    for i, sec in enumerate(sections):
        deep = list(sec.paragraphs)
        for j in range(i + 1, len(sections)):
            child = sections[j]
            if child.level <= sec.level and child.level > 0:
                break
            deep.extend(child.paragraphs)
        sec.paragraphs_deep = deep

    return sections


def _md_table_to_text(table: TableBlock) -> str:
    rows: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            parts: list[str] = []
            for c in cell.content:
                if isinstance(c, ParagraphBlock):
                    t = "".join(i.text for i in c.inlines if isinstance(i, TextInline))
                    parts.append(t)
            cells.append(" ".join(parts))
        rows.append(" | ".join(cells))
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Header normalization & matching
# ---------------------------------------------------------------------------

_ROMAN_RE = re.compile(
    r"^(Ⅰ|Ⅱ|Ⅲ|Ⅳ|Ⅴ|Ⅵ|Ⅶ|Ⅷ|Ⅸ|Ⅹ|I{1,3}|IV|VI{0,3}|IX|X)\b\.?\s*",
    re.IGNORECASE,
)
_NUM_PREFIX_RE = re.compile(r"^\d+\.?\s*")
_DECORATIVE = {"AFE", "The Best Educational Camp"}

_SYNONYMS: dict[str, list[str]] = {
    "실험 시 고려 사항": ["변인 통제 및 실험 환경 설정", "변인 통제", "실험 환경"],
    "실험 준비물": ["실험 재료", "실험 설계"],
}


def _normalize(raw: str) -> str:
    parts = raw.split(" / ")
    cleaned: list[str] = []
    for p in parts:
        p = p.strip()
        if p in _DECORATIVE or p.isdigit():
            continue
        p = _ROMAN_RE.sub("", p)
        p = _NUM_PREFIX_RE.sub("", p)
        p = p.strip()
        if p:
            cleaned.append(p)
    return " ".join(cleaned).lower()


def _word_set(s: str) -> set[str]:
    return set(s.split())


def _match_sections(
    tmpl: list[_TemplateSection],
    md: list[_MdSection],
) -> list[tuple[_TemplateSection, _MdSection | None]]:
    used: set[int] = set()
    result: list[tuple[_TemplateSection, _MdSection | None]] = []

    for ts in tmpl:
        t_norm = ts.header_norm
        if not t_norm:
            result.append((ts, None))
            continue

        best_idx = -1
        best_score = 0.0

        for mi, ms in enumerate(md):
            if mi in used:
                continue
            m_norm = ms.heading_norm
            if not m_norm:
                continue

            synonyms = _SYNONYMS.get(t_norm, [])
            if any(syn in m_norm or m_norm in syn for syn in synonyms):
                score = 0.95
            elif t_norm in m_norm or m_norm in t_norm:
                score = 1.0
            else:
                tw = _word_set(t_norm)
                mw = _word_set(m_norm)
                inter = tw & mw
                union = tw | mw
                score = len(inter) / len(union) if union else 0.0

            if score > best_score:
                best_score = score
                best_idx = mi

        if best_score >= 0.3 and best_idx >= 0:
            used.add(best_idx)
            result.append((ts, md[best_idx]))
        else:
            result.append((ts, None))

    return result


# ---------------------------------------------------------------------------
# Content injection
# ---------------------------------------------------------------------------

def _set_text(para: ParagraphBlock, text: str) -> None:
    if para.inlines:
        para.inlines[0] = TextInline(text=text)
        para.inlines = [para.inlines[0]]
    else:
        para.inlines = [TextInline(text=text)]


def _inject(tmpl_paras: list[ParagraphBlock], md_texts: list[str]) -> int:
    if not md_texts:
        return 0

    writable = [p for p in tmpl_paras if _para_text(p).strip()]
    if not writable:
        writable = list(tmpl_paras)
    if not writable:
        return 0

    n = min(len(writable), len(md_texts))
    for i in range(n):
        _set_text(writable[i], md_texts[i])

    if len(md_texts) > len(writable):
        extra = "\n\n".join(md_texts[len(writable):])
        existing = _para_text(writable[-1])
        _set_text(writable[-1], existing + "\n\n" + extra)

    for i in range(n, len(writable)):
        _set_text(writable[i], "")

    return len(md_texts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class FillResult:
    """Result of a fill_template operation."""

    __slots__ = (
        "output_path", "matched", "unmatched", "total_injected",
        "matches_detail",
    )

    def __init__(self) -> None:
        self.output_path: str = ""
        self.matched: int = 0
        self.unmatched: int = 0
        self.total_injected: int = 0
        self.matches_detail: list[dict[str, str]] = []


def fill_template(
    template_path: str,
    draft_md: str,
    output_path: str | None = None,
) -> FillResult:
    """Fill an HWP/HWPX template with Markdown draft content.

    Matches template sections (identified by TextBox headers) to draft
    sections (identified by Markdown headings) and replaces template
    content with draft text.  Renders via Seed Patch when possible.

    Parameters
    ----------
    template_path : str
        Path to the HWP or HWPX template file.
    draft_md : str
        Either a file path to a .md file, or raw Markdown text.
    output_path : str, optional
        Where to write the filled document.  Defaults to
        ``{template_stem}_filled.{ext}`` next to the template.

    Returns
    -------
    FillResult
        Summary with output_path, match counts, and per-section detail.
    """
    import udf

    # Parse template
    tmpl_doc = udf.parse(template_path)
    tmpl_fmt = Path(template_path).suffix.lstrip(".").lower()
    if tmpl_fmt not in ("hwp", "hwpx"):
        raise ValueError(f"Template must be HWP or HWPX, got: {tmpl_fmt}")

    # Parse draft
    draft_path = Path(draft_md)
    if draft_path.exists() and draft_path.suffix.lower() == ".md":
        md_doc = udf.parse(str(draft_path))
    else:
        from udf.parsers.md import parse_md
        md_doc = parse_md(draft_md)

    # Extract sections
    tmpl_sections = _extract_template_sections(tmpl_doc.blocks)
    md_sections = _extract_md_sections(md_doc)

    # Match & inject
    matches = _match_sections(tmpl_sections, md_sections)
    result = FillResult()

    for ts, ms in matches:
        detail: dict[str, str] = {"template": ts.header_norm}
        if ms:
            result.matched += 1
            texts = ms.paragraphs if ms.paragraphs else ms.paragraphs_deep
            injected = _inject(ts.paras, texts)
            result.total_injected += injected
            detail["draft"] = ms.heading_norm
            detail["injected"] = str(injected)
        else:
            result.unmatched += 1
            detail["draft"] = ""
            detail["injected"] = "0"
        result.matches_detail.append(detail)

    # Output path
    if output_path is None:
        stem = Path(template_path).stem
        ext = Path(template_path).suffix
        output_path = str(Path(template_path).parent / f"{stem}_filled{ext}")

    udf.render(tmpl_doc, tmpl_fmt, output_path=output_path)
    result.output_path = output_path
    return result
