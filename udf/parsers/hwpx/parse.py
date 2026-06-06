"""HWPX file parser.

Parse HWPX (OWPML) ZIP packages into a UdfDocument. Reads header.xml
for DocInfo, section XML files for block content, and BinData entries
for embedded media. Preserves raw XML in VerbatimLayer for lossless
round-trip.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import re
import zipfile
from typing import Any

from lxml import etree

from udf.schema import ColumnDef, DocumentMetadata, PageMargins, SectionDef
from udf.schema.document import DocumentSchema
from udf.pipeline import UdfDocument, VerbatimLayer
from udf.pipeline.container import ConversionTrace, OriginalContainer
from udf.parsers.hwpx.header import parse_header_xml
from udf.parsers.hwpx.section import extract_page_def, parse_section_xml

_PARSER_VERSION = "0.1.0"
_SECTION_RE = re.compile(r"^Contents/section(\d+)\.xml$")


class HwpxParseError(Exception):
    """Raised when HWPX archive parsing fails."""

    pass


def parse_hwpx(path: str) -> UdfDocument:
    """Parse an HWPX (OWPML) file into a UdfDocument.

    Parameters
    ----------
    path : str
        Filesystem path to the .hwpx file (ZIP package).

    Returns
    -------
    UdfDocument
        Document model with semantic blocks, VerbatimLayer (raw section
        XML and BinData), and OriginalContainer for Seed Patch mode.

    Raises
    ------
    HwpxParseError
        If the ZIP is invalid or required entries are missing.
    """
    # SHA-256 checksum
    with open(path, "rb") as f:
        raw = f.read()
    checksum = hashlib.sha256(raw).hexdigest()

    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as e:
        raise HwpxParseError(f"ZIP 열기 실패: {e}") from e

    with zf:
        # header.xml → DocInfoResult
        try:
            header_bytes = zf.read("Contents/header.xml")
        except KeyError as e:
            raise HwpxParseError("Contents/header.xml 없음") from e

        info = parse_header_xml(header_bytes)

        # section 스트림 탐색
        section_names = sorted(
            [n for n in zf.namelist() if _SECTION_RE.match(n)],
            key=lambda n: int(_SECTION_RE.match(n).group(1)),  # type: ignore[union-attr]
        )

        if not section_names:
            raise HwpxParseError("section XML 없음")

        all_blocks: list[Any] = []
        all_verbatim: dict[str, Any] = {}
        all_section_streams: dict[str, str] = {}
        all_page_defs: list[dict[str, str]] = []

        for section_path in section_names:
            section_bytes = zf.read(section_path)
            section_name = section_path.split("/")[-1]

            all_section_streams[section_name] = base64.b64encode(section_bytes).decode()

            blocks, verb_map = parse_section_xml(section_bytes, info, section_name)
            all_blocks.extend(blocks)
            all_verbatim.update(verb_map)

            page_def = extract_page_def(section_bytes)
            if page_def is not None:
                all_page_defs.append(page_def)

        # BinData 스트림 추출
        bindata_map: dict[str, str] = {}
        for name in zf.namelist():
            if name.startswith("BinData/"):
                bin_name = name.split("/", 1)[1]
                if bin_name:
                    bindata_map[bin_name] = base64.b64encode(zf.read(name)).decode()

        # header.xml도 verbatim 보존
        all_section_streams["header.xml"] = base64.b64encode(header_bytes).decode()

        # content.hpf에서 메타데이터 추출
        title, language = _parse_content_hpf(zf)
        author, created_at, modified_at = _parse_meta_inf(zf)

    verbatim_layer = VerbatimLayer(
        format="hwpx",
        blocks=all_verbatim,
        global_resources=info.global_resources,
        section_streams=all_section_streams,
        bindata_streams=bindata_map,
    )

    original_container = OriginalContainer(
        format="zip",
        path=path,
        checksum=checksum,
    )

    sections: list[SectionDef] = []
    for page_def in all_page_defs:
        columns = None
        col_count = page_def.get("column_count")
        if col_count and col_count > 1:
            columns = ColumnDef(
                count=col_count,
                gap=page_def.get("column_gap"),
                same_width=page_def.get("column_same_width", True),
            )

        orientation = page_def.get("orientation")

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
            gutter=page_def.get("gutter"),
            columns=columns,
            orientation=orientation,
        ))

    dp = info.doc_properties
    metadata = DocumentMetadata(
        title=title,
        author=author,
        created_at=created_at,
        modified_at=modified_at,
        sections=sections,
        start_page_number=dp.get("start_page"),
        start_footnote_number=dp.get("start_footnote"),
        start_endnote_number=dp.get("start_endnote"),
        start_picture_number=dp.get("start_picture"),
        start_table_number=dp.get("start_table"),
        start_equation_number=dp.get("start_equation"),
    )

    return UdfDocument(
        source_format="hwpx",
        document=DocumentSchema(
            metadata=metadata,
            blocks=all_blocks,
        ),
        verbatim=verbatim_layer,
        original_container=original_container,
        conversion_trace=ConversionTrace(
            parsed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            parser_version=_PARSER_VERSION,
            checksum=checksum,
        ),
    )


def _parse_meta_inf(zf: zipfile.ZipFile) -> tuple[str | None, str | None, str | None]:
    """META-INF/container.xml 또는 docInfo.xml에서 author/dates 추출."""
    _DC = "http://purl.org/dc/elements/1.1/"
    _DCTERMS = "http://purl.org/dc/terms/"

    for meta_path in ("docInfo.xml", "META-INF/container.xml", "Contents/content.hpf"):
        try:
            meta_bytes = zf.read(meta_path)
        except KeyError:
            continue
        try:
            root = etree.fromstring(meta_bytes)
        except etree.XMLSyntaxError:
            continue

        author = None
        created_at = None
        modified_at = None

        for el in root.iter():
            local = etree.QName(el.tag).localname if isinstance(el.tag, str) else ""
            if local == "creator" and el.text:
                author = el.text
            elif local == "created" and el.text:
                created_at = el.text
            elif local == "modified" and el.text:
                modified_at = el.text
            elif local == "author" and el.text and not author:
                author = el.text

        if author or created_at or modified_at:
            return author, created_at, modified_at

    return None, None, None


def _parse_content_hpf(zf: zipfile.ZipFile) -> tuple[str | None, str | None]:
    """content.hpf에서 title, language 추출. 없거나 비어있으면 None."""
    try:
        hpf_bytes = zf.read("Contents/content.hpf")
    except KeyError:
        return None, None

    try:
        root = etree.fromstring(hpf_bytes)
    except etree.XMLSyntaxError:
        return None, None

    opf_ns = {"opf": "http://www.idpf.org/2007/opf/"}

    title_el = root.find(".//opf:title", opf_ns)
    title = title_el.text if title_el is not None and title_el.text else None

    lang_el = root.find(".//opf:language", opf_ns)
    language = lang_el.text if lang_el is not None and lang_el.text else None

    return title, language
