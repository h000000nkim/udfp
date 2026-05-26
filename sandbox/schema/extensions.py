"""포맷 고유 확장 — 포맷별 단일 클래스 아래 세부 속성 클래스 중첩.

계층:
  XmlExtension ← DocxExtension, HwpxExtension  (XML 기반 공통)
  HwpExtension                                  (바이너리 HWP 전용)
  PdfExtension                                  (PDF 전용)

키 규약:
  - inline: "blockId:inlineIdx"  (예: "b_0001:0")
  - block / position: blockId   (예: "b_0001")
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# ===================================================================
# XML 공통 기반 (DOCX · HWPX 공유)
# ===================================================================

class XmlExtension(_Base):
    """XML 기반 포맷의 공통 확장 기반.

    DOCX(OOXML)와 HWPX(OWPML) 모두 ZIP+XML 구조를 공유하므로
    네임스페이스, 커스텀 XML 파트, 미인식 요소 보존 등을 공통 처리.
    """

    class UnknownElement(_Base):
        """파서가 인식하지 못한 XML 요소 원본 보존."""
        tag: str
        xml: str

    namespaces: dict[str, str] = {}
    custom_xml: dict[str, str] = {}
    unknown_elements: dict[str, list[UnknownElement]] = {}


# ===================================================================
# HWP (바이너리 OLE)
# ===================================================================

class HwpExtension(_Base):
    """HWP 바이너리(OLE compound) 포맷 고유 속성."""

    # --- inline layer ---

    class TextExt(_Base):
        emboss: bool | None = None
        engrave: bool | None = None

    class EquationExt(_Base):
        hwp_script: str | None = None

    # --- block layer ---

    class BlockExt(_Base):
        char_shape_id: int | None = None
        para_shape_id: int | None = None
        border_fill_id: int | None = None

    # --- position layer ---

    class PositionExt(_Base):
        like_char: bool | None = None
        width_relto: Literal["paper", "page", "column", "paragraph", "absolute"] | None = None
        height_relto: Literal["paper", "page", "absolute"] | None = None
        restrict_in_page: bool | None = None
        overlap_others: bool | None = None
        affect_line_spacing: bool | None = None

    # --- fields ---

    format: Literal["hwp"] = "hwp"
    inline_text: dict[str, TextExt] = {}
    inline_equations: dict[str, EquationExt] = {}
    blocks: dict[str, BlockExt] = {}
    positions: dict[str, PositionExt] = {}


# ===================================================================
# HWPX (OWPML — XML 기반 HWP)
# ===================================================================

class HwpxExtension(XmlExtension):
    """HWPX(OWPML) 포맷 고유 속성. HWP와 동일 개념이지만 XML IDRef 참조 체계."""

    # --- inline layer ---

    class TextExt(_Base):
        emboss: bool | None = None
        engrave: bool | None = None

    class EquationExt(_Base):
        hwp_script: str | None = None

    # --- block layer ---

    class BlockExt(_Base):
        char_pr_id_ref: int | None = None
        para_pr_id_ref: int | None = None
        style_id_ref: int | None = None
        border_fill_id_ref: int | None = None

    class ImageRefExt(_Base):
        bin_item_id_ref: str | None = None

    # --- position layer ---

    class PositionExt(_Base):
        like_char: bool | None = None
        width_relto: Literal["paper", "page", "column", "paragraph", "absolute"] | None = None
        height_relto: Literal["paper", "page", "absolute"] | None = None
        restrict_in_page: bool | None = None
        overlap_others: bool | None = None
        affect_line_spacing: bool | None = None

    # --- fields ---

    format: Literal["hwpx"] = "hwpx"
    inline_text: dict[str, TextExt] = {}
    inline_equations: dict[str, EquationExt] = {}
    blocks: dict[str, BlockExt] = {}
    image_refs: dict[str, ImageRefExt] = {}
    positions: dict[str, PositionExt] = {}


# ===================================================================
# DOCX (OOXML)
# ===================================================================

class DocxExtension(XmlExtension):
    """DOCX(OOXML) 포맷 고유 속성."""

    # --- inline layer ---

    class RevisionExt(_Base):
        """변경 내역 (tracked changes). w:ins / w:del / w:rPrChange."""
        author: str | None = None
        date: str | None = None
        revision_type: Literal["insert", "delete", "format"] | None = None

    # --- block layer ---

    class ContentControlExt(_Base):
        """구조화 문서 태그 (w:sdt)."""
        tag: str | None = None
        alias: str | None = None

    class CompatExt(_Base):
        """호환성 설정 (w:compat)."""
        space_for_ul: bool | None = None
        balance_single_byte_double_byte_width: bool | None = None

    # --- fields ---

    format: Literal["docx"] = "docx"
    revisions: dict[str, RevisionExt] = {}
    content_controls: dict[str, ContentControlExt] = {}
    compat: CompatExt | None = None


# ===================================================================
# PDF
# ===================================================================

class PdfExtension(_Base):
    """PDF 포맷 고유 속성."""

    # --- block layer ---

    class ImageExt(_Base):
        crop_left: int | None = None
        crop_top: int | None = None
        crop_right: int | None = None
        crop_bottom: int | None = None
        brightness: int | None = None
        contrast: int | None = None

    # --- fields ---

    format: Literal["pdf"] = "pdf"
    images: dict[str, ImageExt] = {}


# ===================================================================
# rebuild (중첩 클래스 → Pydantic forward ref 해결)
# ===================================================================

HwpExtension.model_rebuild()
HwpxExtension.model_rebuild()
DocxExtension.model_rebuild()
PdfExtension.model_rebuild()


# ===================================================================
# Union + factory
# ===================================================================

FormatExtension = Annotated[
    Union[HwpExtension, HwpxExtension, DocxExtension, PdfExtension],
    Field(discriminator="format"),
]

_EXTENSION_REGISTRY: dict[str, type] = {
    "hwp": HwpExtension,
    "hwpx": HwpxExtension,
    "docx": DocxExtension,
    "pdf": PdfExtension,
}


def create_extension(format_name: str, **kwargs: Any) -> HwpExtension | HwpxExtension | DocxExtension | PdfExtension:
    cls = _EXTENSION_REGISTRY.get(format_name)
    if cls is None:
        raise ValueError(f"Unknown format: {format_name!r}. Available: {list(_EXTENSION_REGISTRY)}")
    return cls(**kwargs)
