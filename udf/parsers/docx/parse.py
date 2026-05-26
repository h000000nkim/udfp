"""DOCX file parser.

Parse Office Open XML (.docx) ZIP packages into a UdfDocument. Extracts
document body, styles, numbering, footnotes/endnotes, headers/footers,
and embedded media. Preserves raw XML streams in VerbatimLayer for
Seed Patch round-trip.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import zipfile
from typing import Any

from lxml import etree

_HUGE_PARSER = etree.XMLParser(huge_tree=True)

from udf.schema import (
    ColumnDef,
    DocumentMetadata,
    DocumentSchema,
    PageMargins,
    SectionDef,
)
from udf.pipeline import UdfDocument, VerbatimLayer
from udf.pipeline.container import ConversionTrace, OriginalContainer
from udf.pipeline.verbatim import GlobalResources
from udf.parsers.docx.document import (
    extract_all_sections,
    parse_document_body,
    parse_endnotes_xml,
    parse_footer_xml,
    parse_footnotes_xml,
    parse_header_xml,
)
from udf.parsers.docx.styles import NS, parse_style_info

_PARSER_VERSION = "0.1.0"


class DocxParseError(Exception):
    """Raised when DOCX archive parsing fails."""

    pass


def parse_docx(path: str) -> UdfDocument:
    """Parse a DOCX file into a UdfDocument.

    Parameters
    ----------
    path : str
        Filesystem path to the .docx file (ZIP/OOXML package).

    Returns
    -------
    UdfDocument
        Document model with semantic blocks, VerbatimLayer (raw XML
        streams and media), and OriginalContainer for Seed Patch mode.

    Raises
    ------
    DocxParseError
        If the ZIP is invalid or word/document.xml is missing.
    """
    with open(path, "rb") as f:
        raw = f.read()
    checksum = hashlib.sha256(raw).hexdigest()

    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as e:
        raise DocxParseError(f"ZIP 열기 실패: {path}: {e}") from e

    with zf:
        names = set(zf.namelist())

        if "word/document.xml" not in names:
            raise DocxParseError(f"word/document.xml 없음: {path}")

        # 0. document metadata from docProps
        doc_meta = _parse_doc_props(zf, names)

        # 1. relationships
        rels_bytes = _read_optional(zf, "word/_rels/document.xml.rels")

        # 2. styles + numbering
        styles_bytes = _read_optional(zf, "word/styles.xml")
        numbering_bytes = _read_optional(zf, "word/numbering.xml")

        style_info = parse_style_info(styles_bytes, numbering_bytes, rels_bytes)

        # 3. document body
        doc_bytes = zf.read("word/document.xml")
        blocks, verbatim_map = parse_document_body(doc_bytes, style_info)

        # 4. footnotes and endnotes
        fn_bytes = _read_optional(zf, "word/footnotes.xml")
        if fn_bytes is not None:
            blocks.extend(parse_footnotes_xml(fn_bytes, style_info))

        en_bytes = _read_optional(zf, "word/endnotes.xml")
        if en_bytes is not None:
            blocks.extend(parse_endnotes_xml(en_bytes, style_info))

        # 5. headers and footers (referenced from sectPr)
        hdr_ftr_blocks = _parse_headers_footers(zf, doc_bytes, style_info, names)
        blocks.extend(hdr_ftr_blocks)

        # 6. images (word/media/*)
        bindata_streams: dict[str, str] = {}
        for name in sorted(names):
            if name.startswith("word/media/"):
                media_name = name[len("word/media/"):]
                bindata_streams[media_name] = base64.b64encode(zf.read(name)).decode()

        # 7. section properties (page size, margins, orientation, columns, breaks)
        raw_sections = extract_all_sections(doc_bytes)

        # 8. preserve XML streams
        section_streams: dict[str, str] = {}
        for xml_name in (
            "word/document.xml",
            "word/styles.xml",
            "word/numbering.xml",
            "word/settings.xml",
            "word/footnotes.xml",
            "word/endnotes.xml",
        ):
            if xml_name in names:
                section_streams[xml_name] = base64.b64encode(zf.read(xml_name)).decode()

    # Build metadata
    sections: list[SectionDef] = []
    for sect_props in raw_sections:
        margins = None
        if any(sect_props.get(f"margin_{s}") for s in ("top", "bottom", "left", "right")):
            margins = PageMargins(
                top=sect_props.get("margin_top", 0.0),
                bottom=sect_props.get("margin_bottom", 0.0),
                left=sect_props.get("margin_left", 0.0),
                right=sect_props.get("margin_right", 0.0),
            )
        col_data = sect_props.get("columns")
        columns = None
        if col_data:
            columns = ColumnDef(**col_data)
        sections.append(SectionDef(
            page_width=sect_props.get("page_width"),
            page_height=sect_props.get("page_height"),
            margins=margins,
            header_margin=sect_props.get("margin_header"),
            footer_margin=sect_props.get("margin_footer"),
            gutter=sect_props.get("margin_gutter"),
            orientation=sect_props.get("orientation"),
            break_type=sect_props.get("break_type"),
            columns=columns,
            start_page_number=sect_props.get("start_page_number"),
            page_number_format=sect_props.get("page_number_format"),
            border_top=sect_props.get("border_top"),
            border_bottom=sect_props.get("border_bottom"),
            border_left=sect_props.get("border_left"),
            border_right=sect_props.get("border_right"),
            line_numbering=sect_props.get("line_numbering"),
        ))

    metadata = DocumentMetadata(
        title=doc_meta.get("title"),
        author=doc_meta.get("author"),
        created_at=doc_meta.get("created_at"),
        modified_at=doc_meta.get("modified_at"),
        sections=sections,
    )

    # Build global resources from styles
    global_resources = GlobalResources(
        styles={
            sid: sdef
            for sid, sdef in {**style_info.paragraph_styles, **style_info.character_styles}.items()
        },
        numberings={
            nid: ndef
            for nid, ndef in style_info.numbering_defs.items()
        },
    )

    verbatim_layer = VerbatimLayer(
        format="docx",
        blocks=verbatim_map,
        global_resources=global_resources,
        section_streams=section_streams,
        bindata_streams=bindata_streams,
    )

    original_container = OriginalContainer(
        format="zip",
        path=path,
        checksum=checksum,
    )

    return UdfDocument(
        source_format="docx",
        document=DocumentSchema(
            metadata=metadata,
            blocks=blocks,
        ),
        verbatim=verbatim_layer,
        original_container=original_container,
        conversion_trace=ConversionTrace(
            parsed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            parser_version=_PARSER_VERSION,
            checksum=checksum,
        ),
    )


_W_NS = NS["w"]

_HDR_FTR_TYPE_MAP = {
    "default": "all",
    "first": "first",
    "even": "even",
}

_HDR_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header"
_FTR_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer"


def _parse_headers_footers(
    zf: zipfile.ZipFile,
    doc_bytes: bytes,
    style_info: Any,
    names: set[str],
) -> list[Any]:
    """Discover header/footer references from sectPr and parse them."""
    _RECOVER = etree.XMLParser(huge_tree=True, recover=True)
    try:
        root = etree.fromstring(doc_bytes, parser=_HUGE_PARSER)
    except etree.XMLSyntaxError:
        root = etree.fromstring(doc_bytes, parser=_RECOVER)
    body = root.find("w:body", NS)
    if body is None:
        return []

    sect_pr = body.find("w:sectPr", NS)
    if sect_pr is None:
        return []

    # Build rId → target from relationships
    rels = style_info.relationships

    blocks: list[Any] = []

    for ref_el in sect_pr.findall("w:headerReference", NS):
        rid = ref_el.get(f"{{{NS['r']}}}id", "")
        hdr_type = ref_el.get(f"{{{_W_NS}}}type", "default")
        apply_to = _HDR_FTR_TYPE_MAP.get(hdr_type, "all")
        target = rels.get(rid, "")
        if target:
            xml_path = f"word/{target}" if not target.startswith("word/") else target
            if xml_path in names:
                hdr_bytes = zf.read(xml_path)
                blocks.append(parse_header_xml(hdr_bytes, style_info, apply_to=apply_to))

    for ref_el in sect_pr.findall("w:footerReference", NS):
        rid = ref_el.get(f"{{{NS['r']}}}id", "")
        ftr_type = ref_el.get(f"{{{_W_NS}}}type", "default")
        apply_to = _HDR_FTR_TYPE_MAP.get(ftr_type, "all")
        target = rels.get(rid, "")
        if target:
            xml_path = f"word/{target}" if not target.startswith("word/") else target
            if xml_path in names:
                ftr_bytes = zf.read(xml_path)
                blocks.append(parse_footer_xml(ftr_bytes, style_info, apply_to=apply_to))

    return blocks


def _parse_doc_props(zf: zipfile.ZipFile, names: set[str]) -> dict[str, str]:
    """Extract document metadata from docProps/core.xml."""
    result: dict[str, str] = {}
    if "docProps/core.xml" not in names:
        return result

    _DC = "http://purl.org/dc/elements/1.1/"
    _DCTERMS = "http://purl.org/dc/terms/"
    _CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"

    try:
        root = etree.fromstring(zf.read("docProps/core.xml"), parser=_HUGE_PARSER)
    except Exception:
        return result

    title = root.find(f"{{{_DC}}}title")
    if title is not None and title.text:
        result["title"] = title.text

    creator = root.find(f"{{{_DC}}}creator")
    if creator is not None and creator.text:
        result["author"] = creator.text

    created = root.find(f"{{{_DCTERMS}}}created")
    if created is not None and created.text:
        result["created_at"] = created.text

    modified = root.find(f"{{{_DCTERMS}}}modified")
    if modified is not None and modified.text:
        result["modified_at"] = modified.text

    return result


def _read_optional(zf: zipfile.ZipFile, name: str) -> bytes | None:
    """Read a ZIP entry, returning None if it does not exist."""
    try:
        return zf.read(name)
    except KeyError:
        return None
