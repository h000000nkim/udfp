"""Legacy v1-to-v2 schema migration (internal, not part of public API)."""

from ._document import v1_to_v2, v2_to_v1

__all__ = ["v1_to_v2", "v2_to_v1"]
