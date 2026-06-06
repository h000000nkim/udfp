"""Shared test utilities."""

from __future__ import annotations

from udf.schema.blocks import HeadingBlock, ParagraphBlock
from udf.schema.inlines import TextInline


def all_texts(doc, *, include_headings: bool = True) -> list[str]:
    """Extract non-empty text strings from ParagraphBlock (and optionally HeadingBlock)."""
    texts: list[str] = []
    for block in doc.blocks:
        if isinstance(block, ParagraphBlock):
            t = "".join(i.text for i in block.inlines if isinstance(i, TextInline))
            if t.strip():
                texts.append(t)
        elif include_headings and isinstance(block, HeadingBlock):
            if block.text.strip():
                texts.append(block.text)
    return texts
