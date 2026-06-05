"""Block types — content units that compose a document."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .formats import BlockFormat, CellFormat, PositionInfo, RevisionInfo
from .inlines import Inline


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class UnsupportedFeature(_Base):
    """Metadata for a feature recognized by the parser but not expressible in the Document Model."""
    feature: str
    value: str | None = None
    reason: str | None = None


class BlockBase(_Base, ABC):
    """Abstract base for all block types. Defines the common contract (id, verbatim_ref, text_content)."""
    id: str
    verbatim_ref: str | None = None
    unsupported: UnsupportedFeature | None = None

    @abstractmethod
    def text_content(self) -> str:
        """Return plain-text representation of this block for semantic comparison."""
        ...


# ---------------------------------------------------------------------------
# 구조 블록
# ---------------------------------------------------------------------------

class HeadingBlock(BlockBase):
    """A heading (section title) with a hierarchical level."""

    type: Literal["heading"] = "heading"
    level: int
    text: str
    inlines: list[Inline] = []
    format: BlockFormat | None = None
    revision: RevisionInfo | None = None

    def text_content(self) -> str:
        """Return the heading text."""
        return self.text


class ParagraphBlock(BlockBase):
    """A paragraph — the primary text-bearing block composed of inlines."""

    type: Literal["paragraph"] = "paragraph"
    inlines: list[Inline] = []
    format: BlockFormat | None = None
    revision: RevisionInfo | None = None

    def text_content(self) -> str:
        """Return concatenated inline text."""
        return "".join(
            i.text for i in self.inlines if hasattr(i, "text")
        )


class ListItem(_Base):
    """A single item within a ListBlock, optionally nested."""

    id: str
    inlines: list[Inline] = []
    children: list[ListItem] = []
    checked: bool | None = None
    format: BlockFormat | None = None
    verbatim_ref: str | None = None

    def text_content(self) -> str:
        """Return concatenated inline text of this list item."""
        return "".join(
            i.text for i in self.inlines if hasattr(i, "text")
        )


class ListBlock(BlockBase):
    """An ordered or unordered list containing ListItems."""

    type: Literal["list"] = "list"
    ordered: bool = False
    start: int | None = None
    items: list[ListItem] = []
    format: BlockFormat | None = None
    numbering_id: str | None = None
    bullet_id: str | None = None
    list_style: str | None = None

    def text_content(self) -> str:
        """Return newline-joined text of all list items."""
        return "\n".join(item.text_content() for item in self.items)


# ---------------------------------------------------------------------------
# 표
# ---------------------------------------------------------------------------

class TableColumnDef(_Base):
    """Column width definition for a table."""

    width: float | None = None


class TableCell(_Base):
    """A single cell within a table row, supporting row/col spans."""

    id: str
    row_span: int = 1
    col_span: int = 1
    width: float | None = None
    height: float | None = None
    fixed_width: bool = False
    fixed_height: bool = False
    content: list[Block] = []
    format: CellFormat | None = None
    is_header: bool | None = None
    verbatim_ref: str | None = None
    unsupported: UnsupportedFeature | None = None


class TableRow(_Base):
    """A row of cells within a table."""

    cells: list[TableCell]
    height: float | None = None
    revision: RevisionInfo | None = None


class TableBlock(BlockBase):
    """A table with rows, cells, optional captions, and border definitions."""

    type: Literal["table"] = "table"
    width: float | None = None
    rows: list[TableRow] = []
    format: BlockFormat | None = None
    position: PositionInfo | None = None
    cell_spacing: float | None = None
    default_padding: float | None = None
    repeat_header: bool | None = None
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    border_inside_h: str | None = None
    border_inside_v: str | None = None
    caption: list[Inline] | None = None
    description: str | None = None
    border_fill_id: int | None = None
    col_widths: list[TableColumnDef] = []
    layout_type: Literal["fixed", "auto"] | None = None

    def text_content(self) -> str:
        """Return space-joined text of all cells."""
        parts = []
        for row in self.rows:
            for cell in row.cells:
                for block in cell.content:
                    parts.append(block.text_content())
        return " ".join(parts)

    def freeze_columns(self) -> None:
        """Fix all cell widths to their current values."""
        for row in self.rows:
            for cell in row.cells:
                cell.fixed_width = True

    def freeze_rows(self, row_indices: list[int] | None = None) -> None:
        """Fix row heights. If row_indices is None, freeze all rows."""
        for ri, row in enumerate(self.rows):
            if row_indices is None or ri in row_indices:
                for cell in row.cells:
                    cell.fixed_height = True

    def freeze_cell(self, row: int, col: int) -> None:
        """Fix a specific cell's width and height."""
        cell = self.rows[row].cells[col]
        cell.fixed_width = True
        cell.fixed_height = True

    def freeze_labels(self, label_col: int = 0) -> None:
        """Fix label column width and height (keeps form layout intact)."""
        for row in self.rows:
            if label_col < len(row.cells):
                row.cells[label_col].fixed_width = True
                row.cells[label_col].fixed_height = True


# ---------------------------------------------------------------------------
# 미디어
# ---------------------------------------------------------------------------

class ImageBlock(BlockBase):
    """A block-level image with optional caption and positioning."""

    type: Literal["image"] = "image"
    src: str
    alt: str | None = None
    width: float | None = None
    height: float | None = None
    caption: list[Inline] | None = None
    position: PositionInfo | None = None
    crop_left: int | None = None
    crop_top: int | None = None
    crop_right: int | None = None
    crop_bottom: int | None = None
    brightness: int | None = None
    contrast: int | None = None
    original_width: float | None = None
    original_height: float | None = None

    def text_content(self) -> str:
        """Return the alt text, or empty string."""
        return self.alt or ""


class EquationBlock(BlockBase):
    """A display-mode equation (LaTeX, HWP script, or MathML)."""

    type: Literal["equation"] = "equation"
    latex: str | None = None
    hwp_script: str | None = None
    display: bool = True
    mathml: str | None = None
    width: float | None = None
    height: float | None = None

    def text_content(self) -> str:
        """Return the LaTeX source, or empty string."""
        return self.latex or ""


class CodeBlock(BlockBase):
    """A fenced code block with optional language annotation."""

    type: Literal["code"] = "code"
    language: str | None = None
    code: str

    def text_content(self) -> str:
        """Return the code string."""
        return self.code


# ---------------------------------------------------------------------------
# 컨테이너
# ---------------------------------------------------------------------------

class QuoteBlock(BlockBase):
    """A block quotation containing nested blocks."""

    type: Literal["quote"] = "quote"
    content: list[Block] = []

    def text_content(self) -> str:
        """Return newline-joined text of nested blocks."""
        return "\n".join(b.text_content() for b in self.content)


class TextBoxBlock(BlockBase):
    """A positioned text container (floating or anchored)."""

    type: Literal["text_box"] = "text_box"
    content: list[Block] = []
    width: float | None = None
    height: float | None = None
    position: PositionInfo | None = None
    padding_top: float | None = None
    padding_bottom: float | None = None
    padding_left: float | None = None
    padding_right: float | None = None
    vertical_align: Literal["top", "middle", "bottom"] | None = None
    background_color: str | None = None
    background_image: str | None = None
    line_color: str | None = None
    line_width: float | None = None
    border_radius: float | None = None

    def text_content(self) -> str:
        """Return newline-joined text of nested blocks."""
        return "\n".join(b.text_content() for b in self.content)


class DrawingBlock(BlockBase):
    """A vector drawing or shape object, possibly containing nested content."""

    type: Literal["drawing"] = "drawing"
    shape_type: str | None = None
    position: PositionInfo | None = None
    background_color: str | None = None
    line_color: str | None = None
    line_width: float | None = None
    line_style: str | None = None
    vertices: list[list[float]] | None = None
    content: list[Block] = []
    children: list[DrawingBlock] = []

    def text_content(self) -> str:
        """Return empty string (drawings have no semantic text)."""
        return ""


# ---------------------------------------------------------------------------
# 각주/미주/머리글/바닥글
# ---------------------------------------------------------------------------

class FootnoteBlock(BlockBase):
    """A footnote definition referenced by FootnoteRefInline."""

    type: Literal["footnote"] = "footnote"
    ref: str
    content: list[Block] = []

    def text_content(self) -> str:
        """Return newline-joined text of footnote content."""
        return "\n".join(b.text_content() for b in self.content)


class EndnoteBlock(BlockBase):
    """An endnote definition referenced by EndnoteRefInline."""

    type: Literal["endnote"] = "endnote"
    ref: str
    content: list[Block] = []

    def text_content(self) -> str:
        """Return newline-joined text of endnote content."""
        return "\n".join(b.text_content() for b in self.content)


class HeaderBlock(BlockBase):
    """Page header content, scoped to all/odd/even/first pages."""

    type: Literal["header"] = "header"
    apply_to: Literal["all", "odd", "even", "first"] | None = None
    content: list[Block] = []

    def text_content(self) -> str:
        """Return newline-joined text of header content."""
        return "\n".join(b.text_content() for b in self.content)


class FooterBlock(BlockBase):
    """Page footer content, scoped to all/odd/even/first pages."""

    type: Literal["footer"] = "footer"
    apply_to: Literal["all", "odd", "even", "first"] | None = None
    content: list[Block] = []

    def text_content(self) -> str:
        """Return newline-joined text of footer content."""
        return "\n".join(b.text_content() for b in self.content)


# ---------------------------------------------------------------------------
# 특수
# ---------------------------------------------------------------------------

class FieldBlock(BlockBase):
    """A form field or dynamic field (text input, dropdown, checkbox, etc.)."""

    type: Literal["field"] = "field"
    field_type: str
    value: str | None = None
    inlines: list[Inline] = []
    options: list[str] | None = None
    default_value: str | None = None
    required: bool | None = None
    max_length: int | None = None

    def text_content(self) -> str:
        """Return the field value, or empty string."""
        return self.value or ""


class PageBreakBlock(BlockBase):
    """An explicit page break."""

    type: Literal["page_break"] = "page_break"

    def text_content(self) -> str:
        """Return empty string."""
        return ""


class HorizontalRuleBlock(BlockBase):
    """A horizontal rule (thematic break)."""

    type: Literal["horizontal_rule"] = "horizontal_rule"

    def text_content(self) -> str:
        """Return empty string."""
        return ""


class BookmarkBlock(BlockBase):
    """A named bookmark for internal cross-references."""

    type: Literal["bookmark"] = "bookmark"
    name: str
    start_block_id: str | None = None
    end_block_id: str | None = None

    def text_content(self) -> str:
        """Return empty string."""
        return ""


class CommentBlock(BlockBase):
    """A review comment (annotation) anchored to a range of content."""

    type: Literal["comment"] = "comment"
    author: str | None = None
    date: str | None = None
    content: list[Block] = []
    anchor_start_id: str | None = None
    anchor_end_id: str | None = None
    resolved: bool | None = None
    color: str | None = None
    opacity: float | None = None
    parent_comment_id: str | None = None

    def text_content(self) -> str:
        """Return newline-joined text of comment content."""
        return "\n".join(b.text_content() for b in self.content)


class ChartBlock(BlockBase):
    """A chart object (HWP VtChart). Not parsed internally — preserved via verbatim."""
    type: Literal["chart"] = "chart"
    position: PositionInfo | None = None
    description: str | None = None

    def text_content(self) -> str:
        """Return the chart description, or empty string."""
        return self.description or ""


class TextArtBlock(BlockBase):
    """WordArt / decorative text (HWP tag=94). Not parsed internally — preserved via verbatim."""
    type: Literal["text_art"] = "text_art"
    position: PositionInfo | None = None
    text: str | None = None

    def text_content(self) -> str:
        """Return the text art string, or empty string."""
        return self.text or ""


class UnknownBlock(BlockBase):
    """A block the parser could not classify. Raw bytes are preserved for lossless roundtrip."""

    type: Literal["unknown"] = "unknown"
    raw_bytes: str
    description: str | None = None

    def text_content(self) -> str:
        """Return empty string (raw bytes are not semantic text)."""
        return ""


class OutlineItem(_Base):
    """A node in the document outline (table of contents tree)."""

    title: str
    target_block_id: str | None = None
    children: list[OutlineItem] = []


# ---------------------------------------------------------------------------
# Union + 재귀 해결
# ---------------------------------------------------------------------------

Block = Annotated[
    Union[
        HeadingBlock,
        ParagraphBlock,
        TableBlock,
        ListBlock,
        ImageBlock,
        CodeBlock,
        QuoteBlock,
        EquationBlock,
        FootnoteBlock,
        EndnoteBlock,
        HeaderBlock,
        FooterBlock,
        FieldBlock,
        TextBoxBlock,
        DrawingBlock,
        ChartBlock,
        TextArtBlock,
        HorizontalRuleBlock,
        PageBreakBlock,
        BookmarkBlock,
        CommentBlock,
        UnknownBlock,
    ],
    Field(discriminator="type"),
]

TableCell.model_rebuild()
QuoteBlock.model_rebuild()
FootnoteBlock.model_rebuild()
EndnoteBlock.model_rebuild()
HeaderBlock.model_rebuild()
FooterBlock.model_rebuild()
TextBoxBlock.model_rebuild()
DrawingBlock.model_rebuild()
CommentBlock.model_rebuild()
ListItem.model_rebuild()
OutlineItem.model_rebuild()
