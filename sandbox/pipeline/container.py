"""원본 컨테이너 + 변환 추적 — seed patch 및 이력 관리."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class OriginalContainer(_Base):
    format: Literal["ole2", "zip", "none"]
    path: str
    checksum: str


class ConversionTrace(_Base):
    parsed_at: str
    parser_version: str
    checksum: str | None = None
