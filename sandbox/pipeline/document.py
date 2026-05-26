"""UdfDocument v2 — DocumentSchema + 변환 인프라 조립."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from sandbox.schema import DocumentSchema
from sandbox.schema.extensions import FormatExtension

from .container import ConversionTrace, OriginalContainer
from .loss import LossReport
from .verbatim import VerbatimLayer


class UdfDocument(BaseModel):
    """변환 파이프라인의 전체 컨텍스트.

    document: 문서 자체 (포맷 무관, 보편적 정의)
    verbatim: 같은 포맷 왕복을 위한 원본 보존
    original_container: seed patch를 위한 원본 백업
    conversion_trace: 파싱 이력
    extensions: 포맷 고유 속성 (HWP emboss, DOCX tracked changes 등)
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    udf: str = "2.0"
    source_format: str
    document: DocumentSchema = Field(default_factory=DocumentSchema)
    verbatim: VerbatimLayer | None = None
    original_container: OriginalContainer | None = None
    conversion_trace: ConversionTrace | None = None
    loss_report: LossReport | None = None
    extensions: dict[str, FormatExtension] = {}
