"""Self-contained layout engine for precise document pagination.

Measures glyphs with freetype-py, computes line breaks and page splits,
and outputs to HTML (absolute positioning), PDF, or image.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LayoutLine:
    """A single line of text after line-breaking."""
    text: str
    width: float
    height: float
    baseline: float
    x_offset: float = 0.0
    inlines: list = field(default_factory=list)


@dataclass
class LayoutBlock:
    """A laid-out block with computed position and dimensions."""
    block_id: str
    block_type: str
    x: float
    y: float
    width: float
    height: float
    lines: list[LayoutLine] = field(default_factory=list)
    children: list[LayoutBlock] = field(default_factory=list)
    page: int = 0


@dataclass
class LayoutPage:
    """A single page of laid-out content."""
    page_index: int
    width: float
    height: float
    margin_top: float
    margin_bottom: float
    margin_left: float
    margin_right: float
    blocks: list[LayoutBlock] = field(default_factory=list)


@dataclass
class LayoutResult:
    """Complete layout result for a document."""
    pages: list[LayoutPage] = field(default_factory=list)
    total_blocks: int = 0
    total_lines: int = 0
