"""Inline content types — elements that appear within paragraph text. Lengths are always in pt."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .formats import RevisionInfo
from .types import Color, Ratio


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class TextInline(_Base):
    """A run of styled text within a paragraph."""

    type: Literal["text"] = "text"
    text: str
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    strikethrough: bool | None = None
    superscript: bool | None = None
    subscript: bool | None = None
    small_caps: bool | None = None
    hidden: bool | None = None
    outline: bool | None = None
    shadow: bool | None = None
    emboss: bool | None = None
    engrave: bool | None = None
    color: Color | None = None
    background_color: Color | None = None
    font_name: str | None = None
    font_size: float | None = None
    letter_spacing: float | None = None
    char_scale: Ratio | None = None
    char_offset: float | None = None
    underline_type: str | None = None
    underline_color: Color | None = None
    strikeout_type: str | None = None
    strikeout_color: Color | None = None
    all_caps: bool | None = None
    highlight_color: Color | None = None
    emphasis_mark: Literal["dot", "circle", "comma", "under_dot", "none"] | None = None
    rtl: bool | None = None
    revision: RevisionInfo | None = None


class LinkInline(_Base):
    """A hyperlink with display text and target URL."""

    type: Literal["link"] = "link"
    text: str
    url: str
    title: str | None = None


class ImageInline(_Base):
    """An inline image embedded within text flow."""

    type: Literal["image_inline"] = "image_inline"
    src: str
    alt: str | None = None
    width: float | None = None
    height: float | None = None
    original_width: float | None = None
    original_height: float | None = None


class FootnoteRefInline(_Base):
    """An inline reference marker pointing to a FootnoteBlock."""

    type: Literal["footnote_ref"] = "footnote_ref"
    ref_id: str
    number: int | None = None


class EndnoteRefInline(_Base):
    """An inline reference marker pointing to an EndnoteBlock."""

    type: Literal["endnote_ref"] = "endnote_ref"
    ref_id: str
    number: int | None = None


class EquationInline(_Base):
    """An inline equation (LaTeX, HWP script, or MathML)."""

    type: Literal["equation_inline"] = "equation_inline"
    latex: str | None = None
    hwp_script: str | None = None
    mathml: str | None = None
    verbatim_ref: str | None = None
    _eq_trailing: bytes | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )


class RubyInline(_Base):
    """Ruby annotation — small text above/below base characters for pronunciation."""

    type: Literal["ruby"] = "ruby"
    base_text: str
    ruby_text: str
    position: Literal["above", "below"] | None = None


class CodeInline(_Base):
    """An inline code span."""

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
