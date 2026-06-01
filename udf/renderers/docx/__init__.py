"""DOCX file renderer.

Generates Office Open XML (.docx) ZIP packages from a UdfDocument. Uses
Seed Patch mode (replacing only changed XML entries) when the original
container is available; falls back to From Scratch mode otherwise.
"""

from __future__ import annotations

import base64
import zipfile
from io import BytesIO

from udf.core.loss import collect_render_losses
from udf.core.schema import (
    FieldBlock,
    FooterBlock,
    FootnoteBlock,
    HeaderBlock,
    ListBlock,
    UdfDocument,
)
from udf.renderers.docx.serialize import (
    blocks_to_document_xml,
    build_content_types_xml,
    build_core_props_xml,
    build_document_rels_xml,
    build_footer_xml,
    build_footnotes_xml,
    build_header_xml,
    build_numbering_xml,
    build_rels_xml,
    build_settings_xml,
    build_styles_xml,
)

_RENDERER_VERSION = "0.1.0"


def _detect_content_changes(doc: UdfDocument) -> bool:
    """Check if the document has been modified since parsing."""
    return getattr(doc, "_content_modified", False)


class DocxRenderError(Exception):
    pass

DocxGenerateError = DocxRenderError


def render_docx(
    doc: UdfDocument,
    output_path: str,
    *,
    seed_path: str | None = None,
) -> None:
    """Render a UdfDocument to a DOCX (Office Open XML) file.

    Automatically selects Seed Patch mode when the original container
    and verbatim XML streams are available; otherwise generates a full
    DOCX package from scratch.

    Parameters
    ----------
    doc : UdfDocument
        The document model to render.
    output_path : str
        Destination path for the generated .docx file.
    seed_path : str or None
        Reserved for future use (explicit seed file for From Scratch).

    Raises
    ------
    DocxRenderError
        If the original ZIP cannot be read in Seed Patch mode, or if
        file writing fails.
    """
    has_verbatim = (
        doc.verbatim is not None
        and doc.verbatim.format == "docx"
        and bool(doc.verbatim.section_streams)
    )
    has_container = (
        doc.original_container is not None
        and doc.original_container.format == "zip"
    )

    has_structural_change = any(
        not getattr(b, "verbatim_ref", None)
        for b in doc.blocks
        if not isinstance(b, (HeaderBlock, FooterBlock))
    )

    has_content_change = _detect_content_changes(doc) if has_verbatim else False

    is_from_scratch = not (has_verbatim and has_container and not has_structural_change and not has_content_change)

    if is_from_scratch:
        _render_from_scratch(doc, output_path)
    else:
        _render_seed_patch(doc, output_path)

    doc.loss_report = collect_render_losses(
        doc, "docx", is_from_scratch=is_from_scratch,
    )

generate_docx = render_docx


def _render_seed_patch(doc: UdfDocument, output_path: str) -> None:
    """Seed Patch: 원본 ZIP에서 변경된 스트림만 교체."""
    assert doc.original_container is not None
    assert doc.verbatim is not None

    original_path = doc.original_container.path

    try:
        with zipfile.ZipFile(original_path, "r") as src_zf:
            original_entries: dict[str, bytes] = {}
            for name in src_zf.namelist():
                original_entries[name] = src_zf.read(name)
    except (zipfile.BadZipFile, OSError) as e:
        raise DocxRenderError(f"원본 ZIP 열기 실패: {original_path}: {e}") from e

    for stream_name, b64_data in doc.verbatim.section_streams.items():
        xml_bytes = base64.b64decode(b64_data)
        original_entries[stream_name] = xml_bytes

    for media_name, b64_data in doc.verbatim.bindata_streams.items():
        media_path = f"word/media/{media_name}"
        original_entries[media_path] = base64.b64decode(b64_data)

    _write_zip(output_path, original_entries)


def _make_page_number_footer() -> FooterBlock:
    import uuid
    return FooterBlock(
        id=str(uuid.uuid4()), type="footer",
        content=[
            FieldBlock(id=str(uuid.uuid4()), type="field", field_type="page_number"),
        ],
    )


def _render_from_scratch(doc: UdfDocument, output_path: str) -> None:
    """From Scratch: Document Model에서 모든 XML을 생성."""
    entries: dict[str, bytes] = {}

    # Seed verbatim streams first (everything except document.xml).
    # Only use DOCX verbatim — HWP/HWPX streams must not leak into DOCX.
    if doc.verbatim and doc.verbatim.format == "docx" and doc.verbatim.section_streams:
        for stream_name, b64_data in doc.verbatim.section_streams.items():
            if stream_name == "word/document.xml":
                continue
            entries[stream_name] = base64.b64decode(b64_data)

    any(isinstance(b, ListBlock) for b in doc.blocks)

    headers = [b for b in doc.blocks if isinstance(b, HeaderBlock)]
    footers = [b for b in doc.blocks if isinstance(b, FooterBlock)]
    footnotes = [b for b in doc.blocks if isinstance(b, FootnoteBlock)]

    if not footers and any(
        isinstance(b, FieldBlock) and b.field_type == "page_number"
        for b in doc.blocks
    ):
        footers = [_make_page_number_footer()]

    _REL_HDR = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header"
    _REL_FTR = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer"

    hf_rels: dict[str, tuple[str, str]] = {}
    for i, hdr in enumerate(headers, start=1):
        entries[f"word/header{i}.xml"] = build_header_xml(hdr)
        hf_rels[f"rHdr{i}"] = (_REL_HDR, f"header{i}.xml")
    for i, ftr in enumerate(footers, start=1):
        entries[f"word/footer{i}.xml"] = build_footer_xml(ftr)
        hf_rels[f"rFtr{i}"] = (_REL_FTR, f"footer{i}.xml")
    if footnotes:
        entries["word/footnotes.xml"] = build_footnotes_xml(footnotes)

    header_rids = [f"rHdr{i}" for i in range(1, len(headers) + 1)]
    footer_rids = [f"rFtr{i}" for i in range(1, len(footers) + 1)]
    doc_xml, hyperlink_rels, image_rels = blocks_to_document_xml(
        doc.blocks, doc,
        header_rids=header_rids or None,
        footer_rids=footer_rids or None,
    )
    entries["word/document.xml"] = doc_xml

    if "word/styles.xml" not in entries:
        entries["word/styles.xml"] = build_styles_xml()

    if "word/numbering.xml" not in entries:
        numbering_bytes = build_numbering_xml(doc.blocks)
        if numbering_bytes is not None:
            entries["word/numbering.xml"] = numbering_bytes

    has_numbering = "word/numbering.xml" in entries
    has_footnotes = bool(footnotes) or "word/footnotes.xml" in entries
    has_endnotes = "word/endnotes.xml" in entries
    has_font_table = "word/fontTable.xml" in entries
    has_theme = "word/theme/theme1.xml" in entries
    has_web_settings = "word/webSettings.xml" in entries
    has_app_props = "docProps/app.xml" in entries

    entries["[Content_Types].xml"] = build_content_types_xml(
        has_numbering=has_numbering,
        has_footnotes=has_footnotes,
        has_endnotes=has_endnotes,
        has_font_table=has_font_table,
        has_theme=has_theme,
        has_web_settings=has_web_settings,
        has_app_props=has_app_props,
        header_count=len(headers),
        footer_count=len(footers),
    )
    entries["_rels/.rels"] = build_rels_xml(has_app_props=has_app_props)
    entries["word/_rels/document.xml.rels"] = build_document_rels_xml(
        has_styles=True,
        has_numbering=has_numbering,
        has_footnotes=has_footnotes,
        has_endnotes=has_endnotes,
        has_font_table=has_font_table,
        has_theme=has_theme,
        has_web_settings=has_web_settings,
        image_rels=image_rels or None,
        hyperlink_rels=hyperlink_rels,
        header_footer_rels=hf_rels,
    )

    if "word/settings.xml" not in entries:
        entries["word/settings.xml"] = build_settings_xml()

    title = ""
    creator = ""
    if doc.metadata:
        title = doc.metadata.title or ""
        creator = doc.metadata.author or ""
    entries["docProps/core.xml"] = build_core_props_xml(
        title=title, creator=creator,
    )

    if doc.verbatim and doc.verbatim.bindata_streams:
        for media_name, b64_data in doc.verbatim.bindata_streams.items():
            entries[f"word/media/{media_name}"] = base64.b64decode(b64_data)

    _write_zip(output_path, entries)


def _write_zip(output_path: str, entries: dict[str, bytes]) -> None:
    """Write a dictionary of entry-name to bytes as a ZIP file."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in sorted(entries.items()):
            zf.writestr(name, data)
    try:
        with open(output_path, "wb") as f:
            f.write(buf.getvalue())
    except OSError as e:
        raise DocxRenderError(f"파일 쓰기 실패: {output_path}: {e}") from e
