"""HWPX file renderer.

Generates HWPX (OWPML) ZIP packages from a UdfDocument. Uses Seed Patch
mode (replacing only changed ZIP entries) when the original container is
available; falls back to From Scratch mode otherwise.
"""

from __future__ import annotations

import base64
import zipfile
from io import BytesIO

from udf.core.loss import collect_render_losses
from udf.core.schema import UdfDocument
from udf.renderers.hwpx.serialize import (
    blocks_to_section_xml,
    build_container_rdf,
    build_container_xml,
    build_content_hpf,
    build_manifest_xml,
    build_minimal_header_xml,
    build_settings_xml,
    build_version_xml,
)

_MIMETYPE = b"application/hwp+zip"

_HANCOM_EXTERNAL_ATTR = 0x81800020
_HANCOM_SCRIPT_ATTR = 0x80000000


def _make_zipinfo(filename: str, *, stored: bool = False, script: bool = False) -> zipfile.ZipInfo:
    """Hancom 호환 ZipInfo 생성."""
    info = zipfile.ZipInfo(filename)
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.create_system = 11
    info.create_version = 23
    info.extract_version = 20
    info.external_attr = _HANCOM_SCRIPT_ATTR if script else _HANCOM_EXTERNAL_ATTR
    if not stored:
        info.flag_bits = 4
    if stored:
        info.extra = b""
    return info


class HwpxRenderError(Exception):
    pass

HwpxGenerateError = HwpxRenderError


def render_hwpx(
    doc: UdfDocument,
    output_path: str,
    *,
    seed_path: str | None = None,
) -> None:
    """Render a UdfDocument to an HWPX (OWPML) ZIP package.

    Automatically selects Seed Patch mode when the original container
    and verbatim section streams are available; otherwise generates the
    full ZIP from scratch.

    Parameters
    ----------
    doc : UdfDocument
        The document model to render.
    output_path : str
        Destination path for the generated .hwpx file.
    seed_path : str or None
        Reserved for future use (explicit seed file for From Scratch).

    Raises
    ------
    HwpxRenderError
        If the original container cannot be read in Seed Patch mode.
    """
    has_verbatim = (
        doc.verbatim is not None
        and doc.verbatim.format == "hwpx"
        and bool(doc.verbatim.section_streams)
    )
    has_container = (
        doc.original_container is not None
        and doc.original_container.format == "zip"
    )

    n_blocks = len(doc.blocks)
    n_without_ref = sum(1 for b in doc.blocks if not getattr(b, "verbatim_ref", None))
    has_structural_change = n_blocks > 0 and n_without_ref > n_blocks * 0.5

    has_content_change = getattr(doc, "_content_modified", False)

    is_from_scratch = not (has_verbatim and has_container and not has_structural_change and not has_content_change)

    if is_from_scratch:
        _render_from_scratch(doc, output_path)
    else:
        _render_seed_patch(doc, output_path)

    doc.loss_report = collect_render_losses(
        doc, "hwpx", is_from_scratch=is_from_scratch,
    )

generate_hwpx = render_hwpx


def _render_seed_patch(doc: UdfDocument, output_path: str) -> None:
    """Seed Patch 모드: 원본 ZIP에서 변경된 entry만 교체."""
    assert doc.original_container is not None
    assert doc.verbatim is not None

    original_path = doc.original_container.path

    try:
        with zipfile.ZipFile(original_path, "r") as src_zf:
            original_entries: dict[str, tuple[zipfile.ZipInfo, bytes]] = {}
            for info in src_zf.infolist():
                original_entries[info.filename] = (info, src_zf.read(info.filename))
    except (zipfile.BadZipFile, OSError) as e:
        raise HwpxRenderError(f"원본 HWPX 읽기 실패: {e}") from e

    replacements: dict[str, bytes] = {}

    for stream_name, b64_data in doc.verbatim.section_streams.items():
        decoded = base64.b64decode(b64_data)
        if stream_name == "header.xml":
            zip_path = "Contents/header.xml"
        else:
            zip_path = f"Contents/{stream_name}"
        replacements[zip_path] = decoded

    for bin_name, b64_data in doc.verbatim.bindata_streams.items():
        decoded = base64.b64decode(b64_data)
        zip_path = f"BinData/{bin_name}"
        replacements[zip_path] = decoded

    _write_hwpx_zip(output_path, original_entries, replacements)


def _render_from_scratch(doc: UdfDocument, output_path: str) -> None:
    """From Scratch 모드: Document Model에서 새 HWPX ZIP을 생성한다."""
    entries: dict[str, tuple[zipfile.ZipInfo, bytes]] = {}

    entries["mimetype"] = (_make_zipinfo("mimetype", stored=True), _MIMETYPE)
    entries["version.xml"] = (_make_zipinfo("version.xml", stored=True), build_version_xml())
    entries["META-INF/container.xml"] = (_make_zipinfo("META-INF/container.xml"), build_container_xml())
    section_xml = blocks_to_section_xml(doc.blocks, doc)
    entries["Contents/header.xml"] = (_make_zipinfo("Contents/header.xml"), build_minimal_header_xml(doc))
    entries["Contents/section0.xml"] = (_make_zipinfo("Contents/section0.xml"), section_xml)
    bindata_names: list[str] = []
    if doc.verbatim:
        bindata_names = list(doc.verbatim.bindata_streams.keys())
    entries["Contents/content.hpf"] = (_make_zipinfo("Contents/content.hpf"), build_content_hpf(section_count=1, bindata_names=bindata_names))
    entries["settings.xml"] = (_make_zipinfo("settings.xml"), build_settings_xml())

    prv_text = ""
    for b in doc.blocks:
        t = getattr(b, "text", None)
        if t:
            prv_text += t + "\n"
        if len(prv_text) > 200:
            break
    entries["Preview/PrvText.txt"] = (_make_zipinfo("Preview/PrvText.txt"), prv_text.encode("utf-8"))

    entries["META-INF/container.rdf"] = (_make_zipinfo("META-INF/container.rdf"), build_container_rdf(section_count=1))
    entries["META-INF/manifest.xml"] = (_make_zipinfo("META-INF/manifest.xml"), build_manifest_xml())

    _HEADER_SCRIPT = (
        "var Documents = XHwpDocuments;\r\n"
        "var Document = Documents.Active_XHwpDocument;\r\n"
    ).encode("utf-16-le")
    _SOURCE_SCRIPT = (
        "function OnDocument_New()\r\n"
        "{\r\n"
        "\t//todo : \r\n"
        "}\r\n"
    ).encode("utf-16-le")
    entries["Scripts/headerScripts.js"] = (_make_zipinfo("Scripts/headerScripts.js", script=True), _HEADER_SCRIPT)
    entries["Scripts/sourceScripts.js"] = (_make_zipinfo("Scripts/sourceScripts.js", script=True), _SOURCE_SCRIPT)

    if doc.verbatim:
        for bin_name, b64_data in doc.verbatim.bindata_streams.items():
            decoded = base64.b64decode(b64_data)
            entries[f"BinData/{bin_name}"] = (_make_zipinfo(f"BinData/{bin_name}"), decoded)

    _write_hwpx_zip(output_path, entries, replacements={})


def _clone_zipinfo(orig: zipfile.ZipInfo) -> zipfile.ZipInfo:
    """원본 ZipInfo의 모든 메타데이터를 보존한 복제본을 생성."""
    clone = zipfile.ZipInfo(orig.filename)
    clone.compress_type = orig.compress_type
    clone.external_attr = orig.external_attr
    clone.create_system = orig.create_system
    clone.create_version = orig.create_version
    clone.extract_version = orig.extract_version
    clone.flag_bits = orig.flag_bits
    clone.extra = orig.extra
    if orig.date_time != (1980, 1, 1, 0, 0, 0):
        clone.date_time = orig.date_time
    if orig.comment:
        clone.comment = orig.comment
    return clone


def _write_hwpx_zip(
    output_path: str,
    original_entries: dict[str, tuple[zipfile.ZipInfo, bytes]],
    replacements: dict[str, bytes],
) -> None:
    """Write HWPX ZIP ensuring mimetype is first and uncompressed."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if "mimetype" in original_entries:
            info, data = original_entries["mimetype"]
            if "mimetype" in replacements:
                data = replacements["mimetype"]
            mi = _clone_zipinfo(info)
            mi.compress_type = zipfile.ZIP_STORED
            mi.extra = b""
            zf.writestr(mi, data)

        for name in original_entries:
            if name == "mimetype":
                continue
            info, data = original_entries[name]
            if name in replacements:
                data = replacements[name]
            zf.writestr(_clone_zipinfo(info), data)

    with open(output_path, "wb") as f:
        f.write(buf.getvalue())
