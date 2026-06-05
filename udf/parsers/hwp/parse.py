"""HWP binary file parser.

Parse HWP 5.x OLE2 compound documents into a UdfDocument, extracting
DocInfo, BodyText sections, and BinData streams. Preserves all binary
data in the VerbatimLayer for lossless round-trip.
"""

from __future__ import annotations

import base64
import datetime
from typing import Any

from udf.schema import (
    ColumnDef,
    DocumentMetadata,
    PageMargins,
    SectionDef,
)
from udf.schema.document import DocumentSchema
from udf.pipeline import UdfDocument, VerbatimLayer
from udf.pipeline.container import ConversionTrace
from udf.parsers.hwp.doc_info import parse_doc_info
from udf.parsers.hwp.body import extract_columns_def, extract_page_def, parse_section
from udf.parsers.hwp.ole import OleReader, OleReaderError

_PARSER_VERSION = "0.1.0"
_BODY_TEXT_PREFIX = "BodyText"
_BINDATA_PREFIX = "BinData"


class HwpParseError(Exception):
    """Raised when HWP binary parsing fails."""

    pass


def parse_hwp(path: str) -> UdfDocument:
    """Parse an HWP 5.x binary file into a UdfDocument.

    Parameters
    ----------
    path : str
        Filesystem path to the .hwp file (OLE2 compound document).

    Returns
    -------
    UdfDocument
        Document model with semantic blocks, VerbatimLayer (raw section
        streams and BinData), and OriginalContainer for Seed Patch mode.

    Raises
    ------
    HwpParseError
        If the file cannot be opened or has an invalid OLE2 structure.
    """
    try:
        with OleReader.open(path) as ole:
            original_container = ole.original_container

            # DocInfo 파싱
            doc_info_data = ole.read_stream(["DocInfo"])
            docinfo_b64 = base64.b64encode(doc_info_data).decode()
            info = parse_doc_info(doc_info_data)

            # BodyText 섹션 스트림 목록 탐색
            all_streams = ole.stream_names()
            section_streams = sorted(
                [s for s in all_streams if len(s) >= 2 and s[0] == _BODY_TEXT_PREFIX],
                key=lambda s: _section_index(s[-1]),
            )

            all_blocks: list[Any] = []
            all_verbatim: dict[str, Any] = {}
            all_section_streams: dict[str, str] = {}
            page_def: dict[str, Any] | None = None
            columns_def: dict[str, Any] | None = None
            _block_start = 0
            _verb_start = 0

            for stream_path in section_streams:
                try:
                    data = ole.read_stream(stream_path)
                except OleReaderError:
                    continue
                section_name = stream_path[-1]
                all_section_streams[section_name] = base64.b64encode(data).decode()
                blocks, verb_map = parse_section(
                    data, info, section=section_name,
                    block_start=_block_start, verb_start=_verb_start,
                )
                all_blocks.extend(blocks)
                all_verbatim.update(verb_map)
                _block_start += len(blocks)
                _verb_start += len(verb_map)
                if page_def is None:
                    page_def = extract_page_def(data)
                if columns_def is None:
                    columns_def = extract_columns_def(data)

            # BinData 스트림 추출 (이미지 등)
            bindata_streams = sorted(
                [s for s in all_streams if len(s) >= 2 and s[0] == _BINDATA_PREFIX],
                key=lambda s: s[-1],
            )
            bindata_map: dict[str, str] = {}
            for stream_path in bindata_streams:
                try:
                    raw = ole.read_stream(stream_path)
                except OleReaderError:
                    # BinData는 이미 압축된 이미지(PNG/JPEG)일 수 있어 decompression 실패 가능
                    try:
                        raw = ole.read_raw(stream_path)
                    except OleReaderError:
                        continue
                bindata_map[stream_path[-1]] = base64.b64encode(raw).decode()

    except OleReaderError as e:
        raise HwpParseError(str(e)) from e

    verbatim_layer = VerbatimLayer(
        format="hwp",
        blocks=all_verbatim,
        global_resources=info.global_resources,
        section_streams=all_section_streams,
        bindata_streams=bindata_map,
        docinfo_stream=docinfo_b64,
    )

    sections: list[SectionDef] = []
    if page_def:
        sections.append(SectionDef(
            page_width=page_def["page_width"],
            page_height=page_def["page_height"],
            margins=PageMargins(
                top=page_def["margin_top"],
                bottom=page_def["margin_bottom"],
                left=page_def["margin_left"],
                right=page_def["margin_right"],
            ),
            header_margin=page_def.get("header_offset"),
            footer_margin=page_def.get("footer_offset"),
            columns=ColumnDef(**columns_def) if columns_def else None,
        ))

    dp = info.doc_properties
    language: str | None = None
    if info.face_names:
        for fn in info.face_names:
            if fn:
                language = "ko"
                break
    metadata = DocumentMetadata(
        sections=sections,
        language=language,
        start_page_number=dp.get("start_page"),
        start_footnote_number=dp.get("start_footnote"),
        start_endnote_number=dp.get("start_endnote"),
        start_picture_number=dp.get("start_picture"),
        start_table_number=dp.get("start_table"),
        start_equation_number=dp.get("start_equation"),
    )

    return UdfDocument(
        source_format="hwp",
        document=DocumentSchema(
            metadata=metadata,
            blocks=all_blocks,
        ),
        verbatim=verbatim_layer,
        original_container=original_container,
        conversion_trace=ConversionTrace(
            parsed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            parser_version=_PARSER_VERSION,
            checksum=original_container.checksum,
        ),
    )


def _section_index(name: str) -> int:
    """'Section0' → 0, 'Section1' → 1 ..."""
    stripped = name.replace("Section", "")
    try:
        return int(stripped)
    except ValueError:
        return 0
