"""v1↔v2 스키마 마이그레이션 어댑터."""

from ._document import v1_to_v2, v2_to_v1

__all__ = ["v1_to_v2", "v2_to_v1"]
