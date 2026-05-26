"""UDFP Pipeline — 변환 인프라. 문서 정의(schema)와 분리된 변환/보존 메커니즘."""

from .container import ConversionTrace, OriginalContainer
from .document import UdfDocument
from .loss import BlockLoss, LossCategory, LossReport
from .verbatim import GlobalResources, VerbatimBlock, VerbatimLayer

__all__ = [
    "UdfDocument",
    "VerbatimLayer",
    "VerbatimBlock",
    "GlobalResources",
    "OriginalContainer",
    "ConversionTrace",
    "LossReport",
    "LossCategory",
    "BlockLoss",
]
