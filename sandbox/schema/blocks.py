"""블록 타입 — 문서의 내용물 종류."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .formats import BlockFormat, CellFormat, PositionInfo
from .inlines import Inline


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class UnsupportedFeature(_Base):
    """파서가 인식했지만 IR로 표현할 수 없는 기능 메타데이터."""
    feature: str
    value: str | None = None
    reason: str | None = None


class BlockBase(_Base, ABC):
    """모든 블록의 공통 계약."""
    id: str
    verbatim_ref: str | None = None
    unsupported: UnsupportedFeature | None = None

    @abstractmethod
    def text_content(self) -> str:
        """이 블록의 평문 텍스트 표현. 시맨틱 비교용."""
        ...


# ---------------------------------------------------------------------------
# 구조 블록
# ---------------------------------------------------------------------------

class HeadingBlock(BlockBase):
    type: Literal["heading"] = "heading"
    level: int
    text: str
    inlines: list[Inline] = []
    format: BlockFormat | None = None

    def text_content(self) -> str:
        return self.text


class ParagraphBlock(BlockBase):
    type: Literal["paragraph"] = "paragraph"
    inlines: list[Inline] = []
    format: BlockFormat | None = None

    def text_content(self) -> str:
        return "".join(
            i.text for i in self.inlines if hasattr(i, "text")
        )


class ListItem(_Base):
    id: str
    inlines: list[Inline] = []
    children: list[ListItem] = []
    verbatim_ref: str | None = None

    def text_content(self) -> str:
        return "".join(
            i.text for i in self.inlines if hasattr(i, "text")
        )


class ListBlock(BlockBase):
    type: Literal["list"] = "list"
    ordered: bool = False
    items: list[ListItem] = []
    format: BlockFormat | None = None

    def text_content(self) -> str:
        return "\n".join(item.text_content() for item in self.items)


# ---------------------------------------------------------------------------
# 표
# ---------------------------------------------------------------------------

class TableCell(_Base):
    id: str
    row_span: int = 1
    col_span: int = 1
    width: float | None = None
    height: float | None = None
    content: list[Block] = []
    format: CellFormat | None = None
    verbatim_ref: str | None = None
    unsupported: UnsupportedFeature | None = None


class TableRow(_Base):
    cells: list[TableCell]


class TableBlock(BlockBase):
    type: Literal["table"] = "table"
    rows: list[TableRow] = []
    format: BlockFormat | None = None
    position: PositionInfo | None = None
    cell_spacing: float | None = None
    default_padding: float | None = None
    repeat_header: bool | None = None

    def text_content(self) -> str:
        parts = []
        for row in self.rows:
            for cell in row.cells:
                for block in cell.content:
                    parts.append(block.text_content())
        return " ".join(parts)


# ---------------------------------------------------------------------------
# 미디어
# ---------------------------------------------------------------------------

class ImageBlock(BlockBase):
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

    def text_content(self) -> str:
        return self.alt or ""


class EquationBlock(BlockBase):
    type: Literal["equation"] = "equation"
    latex: str | None = None
    display: bool = True

    def text_content(self) -> str:
        return self.latex or ""


class CodeBlock(BlockBase):
    type: Literal["code"] = "code"
    language: str | None = None
    code: str

    def text_content(self) -> str:
        return self.code


# ---------------------------------------------------------------------------
# 컨테이너
# ---------------------------------------------------------------------------

class QuoteBlock(BlockBase):
    type: Literal["quote"] = "quote"
    content: list[Block] = []

    def text_content(self) -> str:
        return "\n".join(b.text_content() for b in self.content)


class TextBoxBlock(BlockBase):
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
        return "\n".join(b.text_content() for b in self.content)


class DrawingBlock(BlockBase):
    type: Literal["drawing"] = "drawing"
    shape_type: str | None = None
    position: PositionInfo | None = None
    background_color: str | None = None
    line_color: str | None = None
    line_width: float | None = None
    children: list[DrawingBlock] = []

    def text_content(self) -> str:
        return ""


# ---------------------------------------------------------------------------
# 각주/미주/머리글/바닥글
# ---------------------------------------------------------------------------

class FootnoteBlock(BlockBase):
    type: Literal["footnote"] = "footnote"
    ref: str
    content: list[Block] = []

    def text_content(self) -> str:
        return "\n".join(b.text_content() for b in self.content)


class EndnoteBlock(BlockBase):
    type: Literal["endnote"] = "endnote"
    ref: str
    content: list[Block] = []

    def text_content(self) -> str:
        return "\n".join(b.text_content() for b in self.content)


class HeaderBlock(BlockBase):
    type: Literal["header"] = "header"
    apply_to: Literal["all", "odd", "even", "first"] | None = None
    content: list[Block] = []

    def text_content(self) -> str:
        return "\n".join(b.text_content() for b in self.content)


class FooterBlock(BlockBase):
    type: Literal["footer"] = "footer"
    apply_to: Literal["all", "odd", "even", "first"] | None = None
    content: list[Block] = []

    def text_content(self) -> str:
        return "\n".join(b.text_content() for b in self.content)


# ---------------------------------------------------------------------------
# 특수
# ---------------------------------------------------------------------------

class FieldBlock(BlockBase):
    type: Literal["field"] = "field"
    field_type: str
    value: str | None = None
    inlines: list[Inline] = []

    def text_content(self) -> str:
        return self.value or ""


class PageBreakBlock(BlockBase):
    type: Literal["page_break"] = "page_break"

    def text_content(self) -> str:
        return ""


class UnknownBlock(BlockBase):
    type: Literal["unknown"] = "unknown"
    raw_bytes: str
    description: str | None = None

    def text_content(self) -> str:
        return ""


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
        PageBreakBlock,
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
ListItem.model_rebuild()
