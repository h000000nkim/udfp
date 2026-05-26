"""손실 보고서 — 변환 시 발생한 정보 손실 추적."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


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
