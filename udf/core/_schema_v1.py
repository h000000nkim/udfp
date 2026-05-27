"""UDF JSON Document AST (v1 legacy) — Pydantic v2 스키마."""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# ---------------------------------------------------------------------------
# 인라인 콘텐츠 (S1 + S6)
# ---------------------------------------------------------------------------


class TextInline(_Base):
    type: Literal["text"] = "text"
    text: str
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    strikethrough: bool | None = None
    color: str | None = None
    background_color: str | None = None
    font_name: str | None = None
    font_size: str | None = None
    superscript: bool | None = None
    subscript: bool | None = None
    small_caps: bool | None = None
    hidden: bool | None = None
    all_caps: bool | None = None
    letter_spacing: str | None = None  # CSS letter-spacing 값 (예: "-5%")
    char_scale: int | None = None  # 장평 50~200 (%)
    char_offset: str | None = None  # 상하 오프셋 (예: "10%")
    outline: bool | None = None
    shadow: bool | None = None
    emboss: bool | None = None  # HWP 고유 → unsupported 처리 권장
    engrave: bool | None = None  # HWP 고유 → unsupported 처리 권장
    underline_type: str | None = None  # "solid" | "dot" | "dash" | "wave" | "double" 등
    underline_color: str | None = None
    strikeout_type: str | None = None  # "solid" | "dot" | "dash" 등
    strikeout_color: str | None = None
    highlight_color: str | None = None
    emphasis_mark: Literal["dot", "circle", "comma", "under_dot", "none"] | None = None
    rtl: bool | None = None
    revision: RevisionInfo | None = None


class LinkInline(_Base):
    type: Literal["link"] = "link"
    text: str
    url: str
    title: str | None = None


class ImageInline(_Base):
    type: Literal["image_inline"] = "image_inline"
    src: str
    alt: str | None = None
    width: str | None = None
    height: str | None = None
    original_width: str | None = None
    original_height: str | None = None


class FootnoteRefInline(_Base):
    type: Literal["footnote_ref"] = "footnote_ref"
    ref_id: str
    number: int | None = None


class EndnoteRefInline(_Base):
    type: Literal["endnote_ref"] = "endnote_ref"
    ref_id: str
    number: int | None = None


class EquationInline(_Base):
    type: Literal["equation_inline"] = "equation_inline"
    latex: str | None = None
    hwp_script: str | None = None
    mathml: str | None = None


class RubyInline(_Base):
    type: Literal["ruby"] = "ruby"
    base_text: str
    ruby_text: str
    position: Literal["above", "below"] | None = None


class CodeInline(_Base):
    type: Literal["code_inline"] = "code_inline"
    code: str
    language: str | None = None


Inline = Annotated[
    Union[
        TextInline, LinkInline, ImageInline,
        FootnoteRefInline, EndnoteRefInline, EquationInline,
        RubyInline, CodeInline,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# 포맷 (S2)
# ---------------------------------------------------------------------------


class TabStop(_Base):
    position: str
    align: Literal["left", "center", "right", "decimal"] | None = None
    leader: Literal["none", "dot", "hyphen", "underscore", "heavy", "middle_dot"] | None = None


class BlockFormat(_Base):
    font_name: str | None = None
    font_size: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    alignment: Literal["left", "center", "right", "justify"] | None = None
    line_spacing: str | None = None
    space_before: str | None = None
    space_after: str | None = None
    indent_left: str | None = None
    indent_right: str | None = None
    indent_first: str | None = None
    text_direction: Literal["horizontal", "vertical"] | None = None
    keep_with_next: bool | None = None
    widow_orphan: bool | None = None
    page_break_before: bool | None = None
    outline_level: int | None = Field(None, ge=0, le=7)  # 0=본문, 1~7=개요
    line_spacing_type: (
        Literal["follow_char", "fixed", "leading_only", "minimum", "ratio"] | None
    ) = None
    drop_cap_lines: int | None = None
    drop_cap_distance: str | None = None
    break_asian_latin: bool | None = None
    background_color: str | None = None
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    bidi: bool | None = None
    tab_stops: list[TabStop] | None = None
    column_break_before: bool | None = None


class CellFormat(_Base):
    background_color: str | None = None
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    padding: str | None = None
    padding_top: str | None = None
    padding_bottom: str | None = None
    padding_left: str | None = None
    padding_right: str | None = None
    vertical_align: Literal["top", "middle", "bottom"] | None = None
    text_direction: Literal["horizontal", "vertical"] | None = None
    no_wrap: bool | None = None


# ---------------------------------------------------------------------------
# 미지원 기능 메타데이터
# ---------------------------------------------------------------------------


class PositionInfo(_Base):
    """개체(이미지, 표, 도형 등)의 위치 및 레이어 정보."""

    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    z_order: int | None = None
    like_char: bool | None = None
    flow: Literal["float", "block", "back", "front", "tight", "through"] | None = None
    text_side: Literal["both", "left", "right", "larger"] | None = None
    halign: Literal["left", "center", "right", "inside", "outside"] | None = None
    valign: Literal["top", "middle", "bottom"] | None = None
    hrelto: Literal["paper", "page", "column", "paragraph"] | None = None
    vrelto: Literal["paper", "page", "paragraph"] | None = None
    width_relto: Literal["paper", "page", "column", "paragraph", "absolute"] | None = None
    height_relto: Literal["paper", "page", "absolute"] | None = None
    margin_top: float | None = None
    margin_bottom: float | None = None
    margin_left: float | None = None
    margin_right: float | None = None
    rotation: float | None = None
    opacity: float | None = None
    restrict_in_page: bool | None = None
    overlap_others: bool | None = None
    affect_line_spacing: bool | None = None
    # legacy aliases (deprecated)
    text_wrap: Literal[
        "wrap_both", "wrap_left", "wrap_right", "wrap_largest",
        "square", "behind", "in_front",
    ] | None = None
    allow_overlap: bool | None = None
    flow_with_text: bool | None = None


class UnsupportedFeature(_Base):
    """변환 불가 포맷 고유 기능. 버리지 않고 메타데이터로 보존."""

    feature: str
    value: str | None = None
    reason: str | None = None


class RevisionInfo(_Base):
    """변경추적 메타데이터. DOCX w:ins/w:del, HWP 변경추적."""

    revision_type: Literal["insert", "delete", "format_change", "move"] | None = None
    revision_id: str | None = None
    author: str | None = None
    date: str | None = None


# ---------------------------------------------------------------------------
# 블록 타입
# ---------------------------------------------------------------------------


class HeadingBlock(_Base):
    type: Literal["heading"]
    id: str
    level: int = Field(ge=1, le=6)
    text: str
    inlines: list[Inline] = []
    format: BlockFormat | None = None
    verbatim_ref: str | None = None
    unsupported: UnsupportedFeature | None = None
    revision: RevisionInfo | None = None


class ParagraphBlock(_Base):
    type: Literal["paragraph"]
    id: str
    inlines: list[Inline] = []
    format: BlockFormat | None = None
    verbatim_ref: str | None = None
    unsupported: UnsupportedFeature | None = None
    revision: RevisionInfo | None = None


class TableCell(_Base):
    id: str
    row_span: int = 1
    col_span: int = 1
    width: float | None = None
    height: float | None = None
    content: list[Block] = []
    format: CellFormat | None = None
    is_header: bool | None = None
    verbatim_ref: str | None = None
    unsupported: UnsupportedFeature | None = None


class TableRow(_Base):
    cells: list[TableCell]
    height: str | None = None
    revision: RevisionInfo | None = None


class TableColumnDef(_Base):
    width: str | None = None


class TableBlock(_Base):
    type: Literal["table"]
    id: str
    width: str | None = None
    rows: list[TableRow] = []
    format: BlockFormat | None = None
    position: PositionInfo | None = None
    cell_spacing: str | None = None
    default_padding: str | None = None
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
    verbatim_ref: str | None = None
    unsupported: UnsupportedFeature | None = None


class ListItem(_Base):
    id: str
    inlines: list[Inline] = []
    children: list[ListItem] = []
    checked: bool | None = None
    format: BlockFormat | None = None
    verbatim_ref: str | None = None


class ListBlock(_Base):
    type: Literal["list"]
    id: str
    ordered: bool = False
    start: int | None = None
    items: list[ListItem] = []
    format: BlockFormat | None = None
    numbering_id: str | None = None
    bullet_id: str | None = None
    list_style: str | None = None
    verbatim_ref: str | None = None


class ImageBlock(_Base):
    type: Literal["image"]
    id: str
    src: str
    alt: str | None = None
    width: str | None = None
    height: str | None = None
    caption: list[Inline] | None = None
    position: PositionInfo | None = None
    crop_left: int | None = None
    crop_top: int | None = None
    crop_right: int | None = None
    crop_bottom: int | None = None
    brightness: int | None = None
    contrast: int | None = None
    original_width: str | None = None
    original_height: str | None = None
    verbatim_ref: str | None = None
    unsupported: UnsupportedFeature | None = None


class CodeBlock(_Base):
    type: Literal["code"]
    id: str
    language: str | None = None
    code: str
    verbatim_ref: str | None = None


class QuoteBlock(_Base):
    type: Literal["quote"]
    id: str
    content: list[Block] = []
    verbatim_ref: str | None = None


class EquationBlock(_Base):
    type: Literal["equation"]
    id: str
    latex: str | None = None
    hwp_script: str | None = None
    display: bool = True
    mathml: str | None = None
    verbatim_ref: str | None = None
    unsupported: UnsupportedFeature | None = None


class FootnoteBlock(_Base):
    type: Literal["footnote"]
    id: str
    ref: str
    content: list[Block] = []
    verbatim_ref: str | None = None


class EndnoteBlock(_Base):
    type: Literal["endnote"]
    id: str
    ref: str
    content: list[Block] = []
    verbatim_ref: str | None = None


class HeaderBlock(_Base):
    type: Literal["header"]
    id: str
    apply_to: Literal["all", "odd", "even", "first"] | None = None
    content: list[Block] = []
    verbatim_ref: str | None = None


class FooterBlock(_Base):
    type: Literal["footer"]
    id: str
    apply_to: Literal["all", "odd", "even", "first"] | None = None
    content: list[Block] = []
    verbatim_ref: str | None = None


class FieldBlock(_Base):
    type: Literal["field"]
    id: str
    field_type: str  # "hyperlink" | "page_number" | "date" | "dropdown" | ...
    value: str | None = None
    inlines: list[Inline] = []
    options: list[str] | None = None
    default_value: str | None = None
    required: bool | None = None
    max_length: int | None = None
    verbatim_ref: str | None = None


class TextBoxBlock(_Base):
    type: Literal["text_box"]
    id: str
    content: list[Block] = []
    width: str | None = None
    height: str | None = None
    position: PositionInfo | None = None
    padding_top: str | None = None
    padding_bottom: str | None = None
    padding_left: str | None = None
    padding_right: str | None = None
    vertical_align: Literal["top", "middle", "bottom"] | None = None
    background_color: str | None = None
    background_image: str | None = None
    line_color: str | None = None
    line_width: float | None = None
    border_radius: float | None = None
    verbatim_ref: str | None = None
    unsupported: UnsupportedFeature | None = None


class DrawingBlock(_Base):
    type: Literal["drawing"]
    id: str
    shape_type: str | None = None  # "$lin" | "$rec" | "$ell" | "$pol" | "$con" | ...
    position: PositionInfo | None = None
    background_color: str | None = None
    line_color: str | None = None
    line_width: float | None = None
    line_style: str | None = None
    vertices: list[list[float]] | None = None
    content: list["Block"] = []
    children: list["DrawingBlock"] = []
    verbatim_ref: str | None = None
    unsupported: UnsupportedFeature | None = None


class HorizontalRuleBlock(_Base):
    type: Literal["horizontal_rule"] = "horizontal_rule"
    id: str
    verbatim_ref: str | None = None


class PageBreakBlock(_Base):
    type: Literal["page_break"]
    id: str
    verbatim_ref: str | None = None


class BookmarkBlock(_Base):
    type: Literal["bookmark"] = "bookmark"
    id: str
    name: str
    start_block_id: str | None = None
    end_block_id: str | None = None
    verbatim_ref: str | None = None


class CommentBlock(_Base):
    type: Literal["comment"] = "comment"
    id: str
    author: str | None = None
    date: str | None = None
    content: list["Block"] = []
    anchor_start_id: str | None = None
    anchor_end_id: str | None = None
    resolved: bool | None = None
    color: str | None = None
    opacity: float | None = None
    parent_comment_id: str | None = None
    verbatim_ref: str | None = None


class UnknownBlock(_Base):
    """파서가 인식하지 못한 블록. raw bytes를 verbatim으로 보존."""

    type: Literal["unknown"]
    id: str
    raw_bytes: str
    description: str | None = None
    verbatim_ref: str | None = None


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
        HorizontalRuleBlock,
        PageBreakBlock,
        BookmarkBlock,
        CommentBlock,
        UnknownBlock,
    ],
    Field(discriminator="type"),
]

# 재귀 모델 참조 해결
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


# ---------------------------------------------------------------------------
# 페이지 경계
# ---------------------------------------------------------------------------


class PageBoundary(_Base):
    page: int
    start: str
    end: str | None = None


# ---------------------------------------------------------------------------
# Verbatim 레이어 (S5)
# ---------------------------------------------------------------------------


class VerbatimBlock(_Base):
    raw_tag_id: int | None = None
    level: int | None = None
    raw_bytes: str | None = None
    decoded: dict[str, Any] | None = None


class FontFallbacks(_Base):
    """글꼴 폴백 체계 — HWP의 한글/영문/한자/일본어 7폴백 구조 수용."""

    latin: str | None = None
    hangul: str | None = None
    hanja: str | None = None
    japanese: str | None = None
    other: str | None = None
    symbol: str | None = None
    user_defined: str | None = None
    substitute_name: str | None = None
    panose: str | None = None


class StyleDef(_Base):
    id: str
    name: str
    english_name: str | None = None
    style_type: Literal["paragraph", "character"] | None = None
    parent_id: str | None = None
    next_style_id: str | None = None
    format: BlockFormat | None = None


class NumberingLevel(_Base):
    level: int
    format: str | None = None  # "decimal" | "korean" | "alpha_lower" | ...
    prefix: str | None = None
    suffix: str | None = None
    indent: str | None = None
    start: int | None = None


class NumberingDef(_Base):
    id: str
    levels: list[NumberingLevel] = []


class BulletDef(_Base):
    id: str
    char: str | None = None
    image_ref: str | None = None


class TabDef(_Base):
    id: str
    stops: list[TabStop] = []


class BorderFillDef(_Base):
    id: str
    border_color: str | None = None
    border_style: str | None = None
    border_left_color: str | None = None
    border_left_style: str | None = None
    border_left_width: float | None = None
    border_right_color: str | None = None
    border_right_style: str | None = None
    border_right_width: float | None = None
    border_top_color: str | None = None
    border_top_style: str | None = None
    border_top_width: float | None = None
    border_bottom_color: str | None = None
    border_bottom_style: str | None = None
    border_bottom_width: float | None = None
    fill_color: str | None = None
    fill_type: Literal["solid", "gradient", "pattern", "image"] | None = None
    gradient_type: str | None = None
    gradient_angle: float | None = None
    gradient_colors: list[str] | None = None
    pattern_type: str | None = None
    pattern_color: str | None = None
    image_ref: str | None = None
    image_mode: str | None = None
    diagonal_color: str | None = None
    diagonal_style: str | None = None
    diagonal_width: float | None = None


class CharShapeDef(_Base):
    """글자 모양 정의. HWP 74바이트 CharShape / HWPX charPr / DOCX rPr 공통 모델."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )

    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    underline_type: str | None = None
    underline_color: str | None = None
    strikethrough: bool | None = None
    strikeout_type: str | None = None
    strikeout_color: str | None = None
    outline: bool | None = None
    shadow: bool | None = None
    emboss: bool | None = None
    engrave: bool | None = None
    superscript: bool | None = None
    subscript: bool | None = None
    small_caps: bool | None = None
    hidden: bool | None = None
    font_size_pt: float | None = None
    color: str | None = None
    shade_color: str | None = None
    char_scale: int | None = None
    letter_spacing: str | None = None
    char_offset: str | None = None
    shadow_offset_x: int | None = None
    shadow_offset_y: int | None = None
    border_fill_id: int | None = None
    hangul_face_id: int | None = None
    latin_face_id: int | None = None
    hanja_face_id: int | None = None
    japanese_face_id: int | None = None
    other_face_id: int | None = None
    symbol_face_id: int | None = None
    user_defined_face_id: int | None = None
    outline_type: str | None = None
    shadow_type: str | None = None

    def get(self, key: str, default: Any = None) -> Any:
        """dict-style access for backward compatibility."""
        val = getattr(self, key, _SENTINEL)
        if val is not _SENTINEL:
            return val
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default


class ParaShapeDef(_Base):
    """단락 모양 정의. HWP ParaShape / HWPX paraPr / DOCX pPr 공통 모델."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )

    alignment: str | None = None
    line_spacing_type: str | None = None
    line_spacing_hwp: int | None = None
    indent_left_hwp: int | None = None
    indent_right_hwp: int | None = None
    indent_first_hwp: int | None = None
    space_before_hwp: int | None = None
    space_after_hwp: int | None = None
    protect: bool | None = None
    start_new_page: bool | None = None
    with_next_paragraph: bool | None = None
    tab_def_id: int | None = None
    numbering_bullet_id: int | None = None
    border_fill_id: int | None = None
    level: int | None = None

    def get(self, key: str, default: Any = None) -> Any:
        """dict-style access for backward compatibility."""
        val = getattr(self, key, _SENTINEL)
        if val is not _SENTINEL:
            return val
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default


class BinDataDef(_Base):
    """바이너리 데이터 정의. 임베디드 이미지, OLE 등."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )

    flags: int | None = None
    bin_type: str | None = None
    bin_id: int | None = None
    ext: str | None = None
    stream: str | None = None

    def get(self, key: str, default: Any = None) -> Any:
        """dict-style access for backward compatibility."""
        val = getattr(self, key, _SENTINEL)
        if val is not _SENTINEL:
            return val
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default


_SENTINEL = object()


class GlobalResources(_Base):
    char_shapes: dict[str, CharShapeDef] = {}
    para_shapes: dict[str, ParaShapeDef] = {}
    border_fills: dict[str, BorderFillDef] = {}
    bin_data: dict[str, BinDataDef] = {}
    styles: dict[str, StyleDef] = {}
    face_names: dict[str, FontFallbacks] = {}
    numberings: dict[str, NumberingDef] = {}
    bullets: dict[str, BulletDef] = {}
    tab_defs: dict[str, TabDef] = {}


class VerbatimLayer(_Base):
    format: str
    version: str | None = None
    blocks: dict[str, VerbatimBlock] = {}
    global_resources: GlobalResources = Field(default_factory=GlobalResources)
    unknown_chunks: list[Any] = []
    section_streams: dict[str, str] = {}  # section_name → base64 decompressed bytes
    bindata_streams: dict[str, str] = {}  # BIN0001.jpg → base64 raw bytes


# ---------------------------------------------------------------------------
# 원본 컨테이너 (seed patch용)
# ---------------------------------------------------------------------------


class OriginalContainer(_Base):
    format: Literal["ole2", "zip", "none"]
    path: str
    checksum: str


# ---------------------------------------------------------------------------
# 문서 메타데이터 (S4)
# ---------------------------------------------------------------------------


class PageMargins(_Base):
    top: str
    bottom: str
    left: str
    right: str


class ColumnDef(_Base):
    count: int = 1
    gap: str | None = None
    same_width: bool = True
    widths: list[str] = []
    separator: bool | None = None


class SectionDef(_Base):
    page_width: str | None = None
    page_height: str | None = None
    margins: PageMargins | None = None
    header_margin: str | None = None
    footer_margin: str | None = None
    gutter: str | None = None
    columns: ColumnDef | None = None
    start_page_number: int | None = None
    orientation: Literal["portrait", "landscape"] | None = None
    break_type: Literal["next_page", "continuous", "even_page", "odd_page", "new_column"] | None = None
    page_number_format: Literal[
        "decimal", "roman_lower", "roman_upper",
        "alpha_lower", "alpha_upper", "hangul",
        "ganada", "circled_decimal",
    ] | None = None
    background_color: str | None = None
    background_image: str | None = None
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    line_numbering: bool | None = None


class DocumentMetadata(_Base):
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    keywords: list[str] = []
    language: str | None = None
    page_size: str | None = None
    margins: PageMargins | None = None
    created_at: str | None = None
    modified_at: str | None = None
    header_margin: str | None = None
    footer_margin: str | None = None
    gutter: str | None = None
    paper_width: str | None = None
    paper_height: str | None = None
    start_page_number: int | None = None
    start_footnote_number: int | None = None
    start_endnote_number: int | None = None
    start_picture_number: int | None = None
    start_table_number: int | None = None
    start_equation_number: int | None = None
    footnote_numbering_format: Literal[
        "decimal", "roman_lower", "roman_upper",
        "alpha_lower", "alpha_upper", "symbol",
    ] | None = None
    endnote_numbering_format: Literal[
        "decimal", "roman_lower", "roman_upper",
        "alpha_lower", "alpha_upper", "symbol",
    ] | None = None
    columns: ColumnDef | None = None
    sections: list[SectionDef] = []
    compatibility_target: str | None = None


class ConversionTrace(_Base):
    parsed_at: str
    parser_version: str
    checksum: str | None = None


# ---------------------------------------------------------------------------
# 손실 보고서
# ---------------------------------------------------------------------------


class LossCategory(str, Enum):
    USER_EDITED = "user_edited"
    FORMAT_LIMIT = "format_limit"
    UNINTENDED = "unintended"


class BlockLoss(_Base):
    block_id: str
    loss_type: LossCategory
    description: str


class LossReport(_Base):
    total_blocks: int
    lossless_blocks: int
    lossy_blocks: list[BlockLoss] = []
    dropped_features: list[str] = []
    is_roundtrip_safe: bool


# ---------------------------------------------------------------------------
# 최상위 문서
# ---------------------------------------------------------------------------


class OutlineItem(_Base):
    title: str
    target_block_id: str | None = None
    children: list[OutlineItem] = []


class UdfDocument(_Base):
    udf: str = "1.0"
    source_format: str
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    blocks: list[Block] = []
    page_boundaries: list[PageBoundary] = []
    verbatim: VerbatimLayer | None = None
    original_container: OriginalContainer | None = None
    conversion_trace: ConversionTrace | None = None
    loss_report: LossReport | None = None
    outline: list[OutlineItem] = []

    def __init__(self, path_or_data: Any = None, /, **kwargs: Any) -> None:
        """Initialize a UdfDocument from a file path, dict, or keyword fields.

        If *path_or_data* is a file path string, the document is parsed
        automatically using format detection. If it is a dict, it is
        treated as raw model data.
        """
        if path_or_data is not None and not isinstance(path_or_data, dict):
            path = str(path_or_data)
            from udf.formats import get_registry
            from udf.parsers.detect import detect

            fmt = detect(path).format
            registry = get_registry()
            parser_fn = registry.resolve_parser(fmt)
            parsed = parser_fn(path)
            super().__init__(**parsed.model_dump())
        elif path_or_data is not None:
            super().__init__(**path_or_data, **kwargs)
        else:
            super().__init__(**kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UdfDocument":
        """Construct a UdfDocument from a dictionary (Pydantic validation applied).

        Parameters
        ----------
        data : dict
            Document model data with camelCase or snake_case keys.

        Returns
        -------
        UdfDocument
            Validated document instance.
        """
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> "UdfDocument":
        """Construct a UdfDocument from a JSON string.

        Parameters
        ----------
        json_str : str
            JSON-encoded document model.

        Returns
        -------
        UdfDocument
            Validated document instance.
        """
        return cls.model_validate_json(json_str)

    @classmethod
    def empty(cls, source_format: str = "udf") -> "UdfDocument":
        """Create an empty document with no blocks.

        Parameters
        ----------
        source_format : str, default "udf"
            Format identifier for the empty document.

        Returns
        -------
        UdfDocument
            A document with an empty block list.
        """
        return cls(source_format=source_format, blocks=[])

    # ------------------------------------------------------------------
    # 텍스트 검색/치환
    # ------------------------------------------------------------------

    def replace_text(self, old: str, new: str) -> int:
        """Replace all occurrences of a text substring across all blocks.

        Parameters
        ----------
        old : str
            The substring to search for.
        new : str
            The replacement string.

        Returns
        -------
        int
            Total number of replacements made.
        """
        count = 0
        for block in self.blocks:
            count += _replace_text_in_block(block, old, new)
        return count

    def find_text(self, pattern: str) -> list[dict[str, Any]]:
        """Search for a regex pattern across all blocks and return match locations.

        Parameters
        ----------
        pattern : str
            Regular expression pattern to search for.

        Returns
        -------
        list of dict
            Each dict contains 'block_id', 'text', 'start', and 'end' keys.
        """
        import re
        compiled = re.compile(pattern)
        matches: list[dict[str, Any]] = []
        for block in self.blocks:
            _find_text_in_block(block, compiled, matches)
        return matches

    # ------------------------------------------------------------------
    # 블록 CRUD
    # ------------------------------------------------------------------

    def get_block(self, block_id: str) -> Block | None:
        """Retrieve a top-level block by its ID.

        Parameters
        ----------
        block_id : str
            The block ID to look up.

        Returns
        -------
        Block or None
            The matching block, or None if not found.
        """
        for block in self.blocks:
            if block.id == block_id:
                return block
        return None

    def find_blocks(
        self,
        block_type: str | None = None,
        **filters: Any,
    ) -> list[Block]:
        """Find top-level blocks matching a type and/or attribute filters.

        Parameters
        ----------
        block_type : str or None, optional
            Block type to filter by (e.g. "paragraph", "table").
        **filters : Any
            Additional attribute equality filters (e.g. ``level=2``).

        Returns
        -------
        list of Block
            All matching blocks in document order.
        """
        result: list[Block] = []
        for block in self.blocks:
            if block_type is not None and block.type != block_type:
                continue
            if all(getattr(block, k, None) == v for k, v in filters.items()):
                result.append(block)
        return result

    def add_block(self, block: Block, *, after: str | None = None) -> None:
        """Append or insert a block into the document.

        Parameters
        ----------
        block : Block
            The block to add.
        after : str or None, optional
            If provided, insert the block immediately after the block with
            this ID. Falls back to appending if *after* is not found.
        """
        if after is None:
            self.blocks.append(block)
            return
        for i, b in enumerate(self.blocks):
            if b.id == after:
                self.blocks.insert(i + 1, block)
                return
        self.blocks.append(block)

    def remove_block(self, block_id: str) -> Block | None:
        """Remove a top-level block by ID and return it.

        Parameters
        ----------
        block_id : str
            The ID of the block to remove.

        Returns
        -------
        Block or None
            The removed block, or None if not found.
        """
        for i, b in enumerate(self.blocks):
            if b.id == block_id:
                return self.blocks.pop(i)
        return None

    def move_block(self, block_id: str, *, after: str | None = None) -> bool:
        """Move a block to a new position within the document.

        Parameters
        ----------
        block_id : str
            The ID of the block to move.
        after : str or None, optional
            Place the block after the block with this ID.
            If None, the block is moved to the end.

        Returns
        -------
        bool
            True if the block was found and moved, False otherwise.
        """
        removed = self.remove_block(block_id)
        if removed is None:
            return False
        self.add_block(removed, after=after)
        return True

    # ------------------------------------------------------------------
    # 편의 프로퍼티
    # ------------------------------------------------------------------

    @property
    def tables(self) -> list[TableBlock]:
        """Return all TableBlock instances from the document."""
        return [b for b in self.blocks if isinstance(b, TableBlock)]

    @property
    def images(self) -> list[ImageBlock]:
        """Return all ImageBlock instances from the document."""
        return [b for b in self.blocks if isinstance(b, ImageBlock)]

    @property
    def headings(self) -> list[HeadingBlock]:
        """Return all HeadingBlock instances from the document."""
        return [b for b in self.blocks if isinstance(b, HeadingBlock)]

    @property
    def paragraphs(self) -> list[ParagraphBlock]:
        """Return all ParagraphBlock instances from the document."""
        return [b for b in self.blocks if isinstance(b, ParagraphBlock)]

    # ------------------------------------------------------------------
    # 렌더링 편의 메서드
    # ------------------------------------------------------------------

    def to(self, fmt: str, output_path: str | None = None, **kwargs: Any) -> str | None:
        """Render this document to the specified format.

        Parameters
        ----------
        fmt : str
            Target format name (e.g. "md", "html", "hwp", "docx").
        output_path : str or None, optional
            File path for binary formats. Required for "hwp", "docx", etc.
        **kwargs : Any
            Additional options forwarded to the renderer.

        Returns
        -------
        str or None
            Rendered text content for text formats, or None for binary
            formats (output is written to *output_path*).
        """
        from udf.renderers import render
        return render(self, fmt, output_path=output_path, **kwargs)

    def to_json(self, **kwargs: Any) -> str:
        """Serialize this document to a pretty-printed JSON string.

        Returns
        -------
        str
            JSON representation with 2-space indentation.
        """
        try:
            return self.model_dump_json(indent=2, **kwargs)
        except Exception:
            import json
            return json.dumps(self.model_dump(), indent=2, ensure_ascii=False, default=str)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this document to a plain Python dictionary.

        Returns
        -------
        dict
            Full document model as nested dicts/lists.
        """
        return self.model_dump()

    def save(self, path: str) -> None:
        """Save the document to a file.

        The output format is determined by the file extension:
        - ``.hwp``, ``.docx``, ``.hwpx`` → render to that binary format
        - ``.md``, ``.html`` → render to that text format
        - ``.json`` or other → save as UDF JSON

        Parameters
        ----------
        path : str
            Output file path.
        """
        from pathlib import Path as _P

        ext = _P(path).suffix.lower()
        _RENDER_EXTS = {".hwp", ".docx", ".hwpx", ".md", ".html"}
        if ext in _RENDER_EXTS:
            from udf.renderers import render
            render(self, ext.lstrip("."), output_path=path)
        else:
            _P(path).write_text(self.to_json(), encoding="utf-8")


def _replace_text_in_block(block: Block, old: str, new: str) -> int:
    """Recursively replace text in a single block, returning the replacement count."""
    count = 0
    if isinstance(block, ParagraphBlock):
        for i, inline in enumerate(block.inlines):
            if hasattr(inline, "text") and old in inline.text:
                n = inline.text.count(old)
                count += n
                block.inlines[i] = inline.model_copy(
                    update={"text": inline.text.replace(old, new)}
                )
    elif isinstance(block, HeadingBlock):
        if old in block.text:
            count += block.text.count(old)
            block.text = block.text.replace(old, new)
    elif isinstance(block, TableBlock):
        for row in block.rows:
            for cell in row.cells:
                for cb in cell.content:
                    count += _replace_text_in_block(cb, old, new)
    elif isinstance(block, ListBlock):
        for item in block.items:
            for inline in item.inlines:
                if hasattr(inline, "text") and old in inline.text:
                    n = inline.text.count(old)
                    count += n
                    idx = item.inlines.index(inline)
                    item.inlines[idx] = inline.model_copy(
                        update={"text": inline.text.replace(old, new)}
                    )
            for child in item.children:
                for inline in child.inlines:
                    if hasattr(inline, "text") and old in inline.text:
                        n = inline.text.count(old)
                        count += n
                        idx = child.inlines.index(inline)
                        child.inlines[idx] = inline.model_copy(
                            update={"text": inline.text.replace(old, new)}
                        )
    elif isinstance(block, (TextBoxBlock, FootnoteBlock, EndnoteBlock)):
        content = getattr(block, "content", [])
        for cb in content:
            count += _replace_text_in_block(cb, old, new)
    return count


def _find_text_in_block(
    block: Block,
    pattern: "re.Pattern[str]",
    matches: list[dict[str, Any]],
) -> None:
    """Recursively collect regex matches from a single block into *matches*."""

    if isinstance(block, ParagraphBlock):
        for inline in block.inlines:
            if hasattr(inline, "text"):
                for m in pattern.finditer(inline.text):
                    matches.append({
                        "block_id": block.id,
                        "text": m.group(),
                        "start": m.start(),
                        "end": m.end(),
                    })
    elif isinstance(block, HeadingBlock):
        for m in pattern.finditer(block.text):
            matches.append({
                "block_id": block.id,
                "text": m.group(),
                "start": m.start(),
                "end": m.end(),
            })
    elif isinstance(block, TableBlock):
        for row in block.rows:
            for cell in row.cells:
                for cb in cell.content:
                    _find_text_in_block(cb, pattern, matches)
    elif isinstance(block, (TextBoxBlock, FootnoteBlock, EndnoteBlock)):
        content = getattr(block, "content", [])
        for cb in content:
            _find_text_in_block(cb, pattern, matches)


UdfDocument = UdfDocument


OutlineItem.model_rebuild()
