"""최상위 UdfDocument v1↔v2 변환."""

from __future__ import annotations

from udf.core import schema as v1

from sandbox.pipeline.container import ConversionTrace as V2ConversionTrace
from sandbox.pipeline.container import OriginalContainer as V2OriginalContainer
from sandbox.pipeline.document import UdfDocument as V2UdfDocument
from sandbox.schema.document import DocumentSchema
from sandbox.schema.metadata import PageBoundary as V2PageBoundary

from ._blocks import ExtensionCollector, ExtensionLookup, block_to_v1, block_to_v2
from ._metadata import metadata_to_v1, metadata_to_v2
from ._verbatim import verbatim_to_v1, verbatim_to_v2


def _page_boundary_to_v2(pb: v1.PageBoundary) -> V2PageBoundary:
    return V2PageBoundary(page=pb.page, start=pb.start, end=pb.end)


def _page_boundary_to_v1(pb: V2PageBoundary) -> v1.PageBoundary:
    return v1.PageBoundary(page=pb.page, start=pb.start, end=pb.end)


def _container_to_v2(c: v1.OriginalContainer) -> V2OriginalContainer:
    return V2OriginalContainer(format=c.format, path=c.path, checksum=c.checksum)


def _container_to_v1(c: V2OriginalContainer) -> v1.OriginalContainer:
    return v1.OriginalContainer(format=c.format, path=c.path, checksum=c.checksum)


def _trace_to_v2(t: v1.ConversionTrace) -> V2ConversionTrace:
    return V2ConversionTrace(
        parsed_at=t.parsed_at,
        parser_version=t.parser_version,
        checksum=t.checksum,
    )


def _trace_to_v1(t: V2ConversionTrace) -> v1.ConversionTrace:
    return v1.ConversionTrace(
        parsed_at=t.parsed_at,
        parser_version=t.parser_version,
        checksum=t.checksum,
    )


def v1_to_v2(doc: v1.UdfDocument) -> V2UdfDocument:
    collector = ExtensionCollector(doc.source_format)

    v2_meta = metadata_to_v2(doc.metadata)
    v2_blocks = [block_to_v2(b, collector) for b in doc.blocks]
    v2_boundaries = [_page_boundary_to_v2(pb) for pb in doc.page_boundaries]

    document = DocumentSchema(
        metadata=v2_meta,
        blocks=v2_blocks,
        page_boundaries=v2_boundaries,
    )

    return V2UdfDocument(
        udf="2.0",
        source_format=doc.source_format,
        document=document,
        verbatim=verbatim_to_v2(doc.verbatim) if doc.verbatim else None,
        original_container=_container_to_v2(doc.original_container) if doc.original_container else None,
        conversion_trace=_trace_to_v2(doc.conversion_trace) if doc.conversion_trace else None,
        extensions=collector.to_extensions(),
    )


def v2_to_v1(doc: V2UdfDocument) -> v1.UdfDocument:
    ext_lookup = ExtensionLookup(doc.extensions)

    v1_meta = metadata_to_v1(doc.document.metadata)
    v1_blocks = [block_to_v1(b, ext_lookup) for b in doc.document.blocks]
    v1_boundaries = [_page_boundary_to_v1(pb) for pb in doc.document.page_boundaries]

    return v1.UdfDocument(
        udf="1.0",
        source_format=doc.source_format,
        metadata=v1_meta,
        blocks=v1_blocks,
        page_boundaries=v1_boundaries,
        verbatim=verbatim_to_v1(doc.verbatim) if doc.verbatim else None,
        original_container=_container_to_v1(doc.original_container) if doc.original_container else None,
        conversion_trace=_trace_to_v1(doc.conversion_trace) if doc.conversion_trace else None,
    )
