"""Loss report — tracks information lost during format conversion."""

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
    """Classification of why information was lost during conversion."""

    USER_EDITED = "user_edited"
    FORMAT_LIMIT = "format_limit"
    UNINTENDED = "unintended"


class BlockLoss(_Base):
    """A single loss entry describing what was lost for a specific block."""

    block_id: str
    loss_type: LossCategory
    description: str


class LossReport(_Base):
    """Summary of information loss for a conversion, with per-block detail."""

    total_blocks: int
    lossless_blocks: int
    lossy_blocks: list[BlockLoss] = []
    dropped_features: list[str] = []
    is_roundtrip_safe: bool
