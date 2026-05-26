"""Top-level UdfDocument v1 to v2 (and v2 to v1) conversion.

Converts the entire document structure including metadata, blocks,
page boundaries, verbatim layer, and conversion trace between schema versions.
"""

from __future__ import annotations

from udf.core import _schema_v1 as v1

from udf.pipeline.container import ConversionTrace as V2ConversionTrace
from udf.pipeline.container import OriginalContainer as V2OriginalContainer
from udf.pipeline.document import UdfDocument as V2UdfDocument
from udf.schema.document import DocumentSchema
from udf.schema.metadata import PageBoundary as V2PageBoundary

from ._blocks import ExtensionCollector, ExtensionLookup, block_to_v1, block_to_v2
from ._metadata import metadata_to_v1, metadata_to_v2
from ._verbatim import verbatim_to_v1, verbatim_to_v2


def _page_boundary_to_v2(pb: v1.PageBoundary) -> V2PageBoundary:
    """Convert a v1 page boundary to v2."""
    return V2PageBoundary(page=pb.page, start=pb.start, end=pb.end)


def _page_boundary_to_v1(pb: V2PageBoundary) -> v1.PageBoundary:
    """Convert a v2 page boundary to v1."""
    return v1.PageBoundary(page=pb.page, start=pb.start, end=pb.end)


def _container_to_v2(c: v1.OriginalContainer) -> V2OriginalContainer:
    """Convert a v1 original container reference to v2."""
    return V2OriginalContainer(format=c.format, path=c.path, checksum=c.checksum)


def _container_to_v1(c: V2OriginalContainer) -> v1.OriginalContainer:
    """Convert a v2 original container reference to v1."""
    return v1.OriginalContainer(format=c.format, path=c.path, checksum=c.checksum)


def _trace_to_v2(t: v1.ConversionTrace) -> V2ConversionTrace:
    """Convert a v1 conversion trace to v2."""
    return V2ConversionTrace(
        parsed_at=t.parsed_at,
        parser_version=t.parser_version,
        checksum=t.checksum,
    )


def _trace_to_v1(t: V2ConversionTrace) -> v1.ConversionTrace:
    """Convert a v2 conversion trace to v1."""
    return v1.ConversionTrace(
        parsed_at=t.parsed_at,
        parser_version=t.parser_version,
        checksum=t.checksum,
    )


def v1_to_v2(doc: v1.UdfDocument) -> V2UdfDocument:
    """Convert a v1 UdfDocument to v2 schema.

    Migrates all blocks, metadata, page boundaries, verbatim layer,
    and conversion trace. Format-specific fields are extracted into
    the v2 extensions dict via ExtensionCollector.

    Parameters
    ----------
    doc : v1.UdfDocument
        The v1 document to convert.

    Returns
    -------
    V2UdfDocument
        The fully converted v2 document.
    """
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
        udf="1.0",
        source_format=doc.source_format,
        document=document,
        verbatim=verbatim_to_v2(doc.verbatim) if doc.verbatim else None,
        original_container=_container_to_v2(doc.original_container) if doc.original_container else None,
        conversion_trace=_trace_to_v2(doc.conversion_trace) if doc.conversion_trace else None,
        extensions=collector.to_extensions(),
    )


def v2_to_v1(doc: V2UdfDocument) -> v1.UdfDocument:
    """Convert a v2 UdfDocument back to v1 schema.

    Restores format-specific extension fields into v1 block models
    via ExtensionLookup.

    Parameters
    ----------
    doc : V2UdfDocument
        The v2 document to convert.

    Returns
    -------
    v1.UdfDocument
        The fully converted v1 document.
    """
    ext_lookup = ExtensionLookup(doc.extensions)

    v1_meta = metadata_to_v1(doc.document.metadata)
    v1_blocks = [block_to_v1(b, ext_lookup) for b in doc.document.blocks]
    v1_boundaries = [_page_boundary_to_v1(pb) for pb in doc.document.page_boundaries]

    v1_loss = None
    if doc.loss_report is not None:
        v1_loss = v1.LossReport(**doc.loss_report.model_dump())

    return v1.UdfDocument(
        udf="1.0",
        source_format=doc.source_format,
        metadata=v1_meta,
        blocks=v1_blocks,
        page_boundaries=v1_boundaries,
        verbatim=verbatim_to_v1(doc.verbatim) if doc.verbatim else None,
        original_container=_container_to_v1(doc.original_container) if doc.original_container else None,
        conversion_trace=_trace_to_v1(doc.conversion_trace) if doc.conversion_trace else None,
        loss_report=v1_loss,
    )
