"""HWPX file renderer.

Generates HWPX (OWPML) ZIP packages from a UdfDocument. Uses Seed Patch
mode (replacing only changed ZIP entries) when the original container is
available; falls back to From Scratch mode otherwise.
"""

from __future__ import annotations

import base64
import zipfile
from io import BytesIO

from udf.core.schema import UdfDocument
from udf.renderers.hwpx.serialize import (
    blocks_to_section_xml,
    build_container_xml,
    build_content_hpf,
    build_minimal_header_xml,
    build_version_xml,
)

_MIMETYPE = b"application/hwp+zip"


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

    has_structural_change = any(
        not getattr(b, "verbatim_ref", None)
        for b in doc.blocks
    )

    if has_verbatim and has_container and not has_structural_change:
        _render_seed_patch(doc, output_path)
    else:
        _render_from_scratch(doc, output_path)

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

    mi = zipfile.ZipInfo("mimetype")
    mi.compress_type = zipfile.ZIP_STORED
    mi.extra = b""
    entries["mimetype"] = (mi, _MIMETYPE)

    vi = zipfile.ZipInfo("version.xml")
    vi.compress_type = zipfile.ZIP_STORED
    entries["version.xml"] = (vi, build_version_xml())

    ci = zipfile.ZipInfo("META-INF/container.xml")
    ci.compress_type = zipfile.ZIP_DEFLATED
    entries["META-INF/container.xml"] = (ci, build_container_xml())

    hi = zipfile.ZipInfo("Contents/header.xml")
    hi.compress_type = zipfile.ZIP_DEFLATED
    entries["Contents/header.xml"] = (hi, build_minimal_header_xml(doc))

    section_xml = blocks_to_section_xml(doc.blocks, doc)
    si = zipfile.ZipInfo("Contents/section0.xml")
    si.compress_type = zipfile.ZIP_DEFLATED
    entries["Contents/section0.xml"] = (si, section_xml)

    hpf = build_content_hpf(section_count=1)
    pi = zipfile.ZipInfo("Contents/content.hpf")
    pi.compress_type = zipfile.ZIP_DEFLATED
    entries["Contents/content.hpf"] = (pi, hpf)

    if doc.verbatim:
        for bin_name, b64_data in doc.verbatim.bindata_streams.items():
            decoded = base64.b64decode(b64_data)
            bi = zipfile.ZipInfo(f"BinData/{bin_name}")
            bi.compress_type = zipfile.ZIP_DEFLATED
            entries[f"BinData/{bin_name}"] = (bi, decoded)

    _write_hwpx_zip(output_path, entries, replacements={})


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
            new_info = zipfile.ZipInfo("mimetype")
            new_info.compress_type = zipfile.ZIP_STORED
            new_info.extra = b""
            zf.writestr(new_info, data)

        for name in original_entries:
            if name == "mimetype":
                continue
            info, data = original_entries[name]
            if name in replacements:
                data = replacements[name]

            new_info = zipfile.ZipInfo(name)
            new_info.compress_type = info.compress_type
            new_info.external_attr = info.external_attr
            if info.date_time != (1980, 1, 1, 0, 0, 0):
                new_info.date_time = info.date_time
            zf.writestr(new_info, data)

    with open(output_path, "wb") as f:
        f.write(buf.getvalue())
