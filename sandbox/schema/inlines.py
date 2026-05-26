"""인라인 콘텐츠 — 텍스트 안에 들어가는 것들. 길이 값은 항상 pt."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .types import Color, Ratio


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class TextInline(_Base):
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


class LinkInline(_Base):
    type: Literal["link"] = "link"
    text: str
    url: str


class ImageInline(_Base):
    type: Literal["image_inline"] = "image_inline"
    src: str
    alt: str | None = None
    width: float | None = None
    height: float | None = None


class FootnoteRefInline(_Base):
    type: Literal["footnote_ref"] = "footnote_ref"
    ref_id: str
    number: int | None = None


class EquationInline(_Base):
    type: Literal["equation_inline"] = "equation_inline"
    latex: str | None = None


Inline = Annotated[
    Union[TextInline, LinkInline, ImageInline, FootnoteRefInline, EquationInline],
    Field(discriminator="type"),
]
