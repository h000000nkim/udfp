"""DocumentSchema — 순수 문서 모델. 변환 인프라와 무관."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .blocks import Block
from .metadata import DocumentMetadata, PageBoundary


class DocumentSchema(BaseModel):
    """문서 자체의 정의.

    UDFP의 변환/보존 메커니즘(verbatim, original_container 등)과 무관.
    이 클래스만으로 문서의 구조와 내용을 완전히 표현할 수 있어야 한다.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    blocks: list[Block] = []
    page_boundaries: list[PageBoundary] = []
