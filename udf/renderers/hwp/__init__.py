"""HWP binary file renderer with Seed Patch capabilities.

Generates HWP 5.x OLE2 files from a UdfDocument. Prefers Seed Patch
mode (patching only changed streams in the original container) when
the original file is available; falls back to From Scratch mode using
a seed template otherwise.

Seed Patch capabilities (automatic when verbatim data available):
  - Text replacement with CharShape override (e.g., gray placeholder → black)
  - Table like_char toggle (flip "treat as character" for page flow control)
  - Combined single-pass patching (text + equation + table attrs applied
    atomically without offset invalidation)
"""

from __future__ import annotations

import base64
import shutil
import struct
import zlib
from typing import Iterator

from udf.core.loss import build_loss_report, format_limit_loss, user_edited_loss
from udf.core.schema import (
    Block,
    BlockLoss,
    CommentBlock,
    DrawingBlock,
    EndnoteBlock,
    EquationBlock,
    FooterBlock,
    FootnoteBlock,
    HeaderBlock,
    HeadingBlock,
    ImageBlock,
    LossReport,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TableCell,
    TextBoxBlock,
    TextInline,
    UdfDocument,
)
from udf.parsers.hwp.records import extract_plain_text
from udf.renderers.hwp.body_writer import (
    apply_paragraph_patches,
    apply_section_patches,
    inject_image_gso,
)
from udf.renderers.hwp.docinfo_patch import (
    add_bindata_record,
    find_or_add_charshape,
    get_charshape_color,
)
from udf.renderers.hwp.ole_patch import add_hwp_stream, patch_hwp_stream, patch_hwp_streams

_FILE_HEADER_STREAM = "FileHeader"
_FLAGS_OFFSET = 36
_COMPRESS_FLAG_BIT = 0

_RENDERER_VERSION = "0.1.0"

def _find_default_seed() -> str | None:
    """패키지 내장 seed HWP 파일을 찾는다."""
    import pathlib
    pkg_seed = pathlib.Path(__file__).resolve().parent / "seed" / "empty.hwp"
    if pkg_seed.exists():
        return str(pkg_seed)
    base = pathlib.Path(__file__).resolve().parent.parent.parent.parent
    fallback = base / "tests" / "fixtures" / "hwp" / "f01_plain_text.hwp"
    if fallback.exists():
        return str(fallback)
    return None


class HwpRenderError(Exception):
    pass

HwpGenerateError = HwpRenderError


_CONTAINER_TYPES = (
    TextBoxBlock, DrawingBlock, FootnoteBlock, EndnoteBlock,
    HeaderBlock, FooterBlock, QuoteBlock, CommentBlock,
)


def _iter_text_blocks(
    blocks: list[Block],
) -> Iterator[ParagraphBlock | HeadingBlock]:
    """Iterate over text-bearing blocks (paragraphs and headings), including nested containers."""
    for block in blocks:
        if isinstance(block, (ParagraphBlock, HeadingBlock)):
            yield block
        elif isinstance(block, TableBlock):
            for row in block.rows:
                for cell in row.cells:
                    yield from _iter_text_blocks(cell.content)
        elif isinstance(block, _CONTAINER_TYPES):
            yield from _iter_text_blocks(block.content)


def _cell_text(cell: TableCell) -> str:
    """Extract concatenated plain text from a table cell's paragraph blocks."""
    return "".join(
        i.text
        for b in cell.content
        if isinstance(b, ParagraphBlock)
        for i in b.inlines
        if isinstance(i, TextInline)
    )


def _match_table_cell_patches(
    original_doc: UdfDocument,
    edited_doc: UdfDocument,
    orig_ph_offset_by_id: dict[str, int],
    orig_section_by_id: dict[str, str],
    patches_by_section: dict[str, list[tuple[int, str]]],
    lossy: list[BlockLoss],
    edited_ids: set[str],
) -> None:
    """Compare table cell text between original and edited docs, generating patches for changed cells."""
    orig_tables = {b.id: b for b in original_doc.blocks if isinstance(b, TableBlock)}
    edited_tables = {b.id: b for b in edited_doc.blocks if isinstance(b, TableBlock)}

    for tbl_id, orig_tbl in orig_tables.items():
        if tbl_id not in edited_tables:
            continue
        edited_tbl = edited_tables[tbl_id]
        edited_ids.add(tbl_id)

        for ri, (orow, erow) in enumerate(
            zip(orig_tbl.rows, edited_tbl.rows)
        ):
            for ci, (ocell, ecell) in enumerate(zip(orow.cells, erow.cells)):
                orig_ct = _cell_text(ocell)
                edited_ct = _cell_text(ecell)
                if orig_ct.rstrip() == edited_ct.rstrip():
                    continue

                for b in ocell.content:
                    if not isinstance(b, ParagraphBlock):
                        continue
                    if b.id not in orig_ph_offset_by_id:
                        continue
                    ph_offset = orig_ph_offset_by_id[b.id]
                    section = orig_section_by_id.get(b.id, "Section0")
                    patches_by_section.setdefault(section, []).append(
                        (ph_offset, edited_ct)
                    )
                    lossy.append(
                        user_edited_loss(
                            b.id,
                            f"셀[{ri},{ci}] 변경: {orig_ct!r} → {edited_ct!r}",
                        )
                    )
                    edited_ids.add(b.id)
                    break


def _collect_orig_text_info(
    original_doc: UdfDocument,
) -> tuple[dict[str, str], dict[str, int], dict[str, str]]:
    """원본 문서에서 블록별 텍스트, PH 오프셋, 섹션 정보를 수집한다."""
    orig_text_by_id: dict[str, str] = {}
    orig_ph_offset_by_id: dict[str, int] = {}
    orig_section_by_id: dict[str, str] = {}

    if original_doc.verbatim:
        for block in _iter_text_blocks(original_doc.blocks):
            if isinstance(block, ParagraphBlock):
                blk_id = block.id
                text = "".join(
                    i.text for i in block.inlines if isinstance(i, TextInline)
                )
            elif isinstance(block, HeadingBlock):
                blk_id = block.id
                text = block.text
            else:
                continue
            orig_text_by_id[blk_id] = text

            vb_ref = block.verbatim_ref
            if vb_ref and vb_ref in original_doc.verbatim.blocks:
                vb = original_doc.verbatim.blocks[vb_ref]
                decoded = vb.decoded or {}
                if "ph_offset" in decoded:
                    orig_ph_offset_by_id[blk_id] = int(decoded["ph_offset"])
                if "section" in decoded:
                    orig_section_by_id[blk_id] = str(decoded["section"])

    return orig_text_by_id, orig_ph_offset_by_id, orig_section_by_id


def _match_block_patches(
    edited_doc: UdfDocument,
    orig_text_by_id: dict[str, str],
    orig_ph_offset_by_id: dict[str, int],
    orig_section_by_id: dict[str, str],
    patches_by_section: dict[str, list[tuple[int, str]]],
    lossy: list[BlockLoss],
    edited_ids: set[str],
) -> None:
    """편집된 문서의 블록을 원본과 비교하여 텍스트 패치를 생성한다."""
    for block in _iter_text_blocks(edited_doc.blocks):
        if isinstance(block, ParagraphBlock):
            blk_id = block.id
            new_text = "".join(
                i.text for i in block.inlines if isinstance(i, TextInline)
            )
        elif isinstance(block, HeadingBlock):
            blk_id = block.id
            new_text = block.text
        else:
            continue
        edited_ids.add(blk_id)
        if blk_id not in orig_text_by_id:
            continue
        orig_text = orig_text_by_id[blk_id]
        if new_text.rstrip() == orig_text.rstrip():
            continue
        if blk_id not in orig_ph_offset_by_id:
            continue

        ph_offset = orig_ph_offset_by_id[blk_id]
        section = orig_section_by_id.get(blk_id, "Section0")
        patches_by_section.setdefault(section, []).append((ph_offset, new_text))
        lossy.append(
            user_edited_loss(
                blk_id,
                f"{orig_text!r} → {new_text!r}",
            )
        )


def _extract_text_from_pt_bytes(pt_b64: str) -> str:
    """verbatim pt_bytes(base64)에서 순수 텍스트를 추출한다 (인라인 오브젝트 제외)."""
    return extract_plain_text(base64.b64decode(pt_b64))


def _iter_all_blocks(blocks: list[Block]) -> Iterator[Block]:
    """모든 블록을 재귀적으로 순회한다 (테이블 셀, 텍스트박스 등 컨테이너 포함)."""
    for block in blocks:
        yield block
        if isinstance(block, TableBlock):
            for row in block.rows:
                for cell in row.cells:
                    yield from _iter_all_blocks(cell.content)
        elif isinstance(block, _CONTAINER_TYPES):
            yield from _iter_all_blocks(block.content)


def _detect_color_override(block: ParagraphBlock | HeadingBlock) -> str | None:
    """Return the target color hex if all inlines specify a uniform non-None color."""
    if isinstance(block, HeadingBlock):
        return None
    colors = set()
    for i in block.inlines:
        if isinstance(i, TextInline) and i.text.strip():
            c = str(i.color) if i.color else None
            if c:
                colors.add(c)
    if len(colors) == 1:
        return colors.pop()
    return None


def _detect_per_inline_colors(
    block: ParagraphBlock,
) -> list[tuple[int, str]] | None:
    """Detect per-inline color overrides.

    Returns list of (inline_index, color_hex) for inlines with non-None
    color, or None if no colors are set.
    """
    result = []
    for idx, il in enumerate(block.inlines):
        if isinstance(il, TextInline) and il.color:
            result.append((idx, str(il.color)))
    return result or None


def _get_pcs_entries(pcs_b64: str | None) -> list[tuple[int, int]]:
    """Extract all (pos, cs_id) pairs from base64-encoded PCS bytes."""
    if not pcs_b64:
        return []
    pcs = base64.b64decode(pcs_b64)
    entries = []
    for i in range(0, len(pcs) - 7, 8):
        pos, cs_id = struct.unpack_from("<II", pcs, i)
        entries.append((pos, cs_id))
    return entries


def _map_pcs_to_inlines(
    pt_b64: str, pcs_entries: list[tuple[int, int]],
) -> dict[int, int]:
    """Map PCS entry indices to TextInline indices.

    PCS entries covering only control characters don't produce
    TextInlines and are skipped in the mapping.
    """
    if not pt_b64 or not pcs_entries:
        return {}
    pt = base64.b64decode(pt_b64)
    total_chars = len(pt) // 2

    result: dict[int, int] = {}
    inline_idx = 0
    for pcs_idx, (pos, _) in enumerate(pcs_entries):
        end = pcs_entries[pcs_idx + 1][0] if pcs_idx + 1 < len(pcs_entries) else total_chars
        has_text = False
        cp = pos
        while cp < end and cp < total_chars:
            byte_off = cp * 2
            if byte_off + 2 > len(pt):
                break
            code = struct.unpack_from("<H", pt, byte_off)[0]
            if code > 0x001F and code != 0xFFFF:
                has_text = True
                break
            if code not in (0x0000, 0x0009, 0x000A, 0x000D):
                cp += 8
            else:
                cp += 1
        if has_text:
            result[pcs_idx] = inline_idx
            inline_idx += 1
    return result


def _get_pcs_first_cs_id(pcs_b64: str | None) -> int | None:
    """Extract the first charShapeId from base64-encoded PCS bytes."""
    if not pcs_b64:
        return None
    pcs = base64.b64decode(pcs_b64)
    if len(pcs) >= 8:
        return struct.unpack_from("<I", pcs, 4)[0]
    return None


def _apply_ast_patches(
    doc: UdfDocument,
) -> tuple[dict[str, list[tuple[int, int]]], bytes | None, set[str]]:
    """Compare current AST to verbatim originals and patch changed blocks.

    Modifies verbatim.section_streams in-place.
    Returns (cs_override_result, pending_docinfo_patch, modified_sections) where:
    - cs_override_result: {section: [(ph_offset, target_cs_id), ...]}
    - pending_docinfo_patch: compressed DocInfo bytes if modified, else None.
    - modified_sections: set of section names that were actually patched.
    """
    if not doc.verbatim or not doc.verbatim.section_streams:
        return {}

    text_patches: dict[str, list[tuple[int, str]]] = {}
    eq_patches: dict[str, list[tuple[int, str]]] = {}
    tbl_attr_patches: dict[str, list[tuple[int, dict[str, bool]]]] = {}
    multi_style_requests: list[tuple[str, int, list[tuple[int, str, int]]]] = []
    pcs_remap_by_section: dict[str, dict[int, bytes]] = {}

    for block in _iter_all_blocks(doc.blocks):
        ref = getattr(block, "verbatim_ref", None)
        if not ref or ref not in doc.verbatim.blocks:
            continue
        vb = doc.verbatim.blocks[ref]
        decoded = vb.decoded or {}

        if isinstance(block, (ParagraphBlock, HeadingBlock)):
            pt_b64 = decoded.get("pt_bytes")
            ph_offset = decoded.get("ph_offset")
            if ph_offset is None:
                continue
            if pt_b64 is None:
                pt_b64 = ""
            orig_text = _extract_text_from_pt_bytes(pt_b64) if pt_b64 else ""
            if isinstance(block, ParagraphBlock):
                curr_text = "".join(
                    i.text for i in block.inlines if isinstance(i, TextInline)
                )
            else:
                curr_text = block.text

            text_changed = orig_text.rstrip() != curr_text.rstrip()

            per_inline_colors: list[tuple[int, str, int]] | None = None
            if isinstance(block, ParagraphBlock):
                inline_colors = _detect_per_inline_colors(block)
                if inline_colors:
                    pcs_entries = _get_pcs_entries(decoded.get("pcs_bytes"))
                    pcs_to_inline = _map_pcs_to_inlines(pt_b64 or "", pcs_entries)
                    inline_to_pcs = {v: k for k, v in pcs_to_inline.items()}
                    per_inline_colors = []
                    for il_idx, color_hex in inline_colors:
                        pcs_idx = inline_to_pcs.get(il_idx)
                        if pcs_idx is not None and pcs_idx < len(pcs_entries):
                            _, base_cs = pcs_entries[pcs_idx]
                            per_inline_colors.append((pcs_entries[pcs_idx][0], color_hex, base_cs))
                    if not per_inline_colors and pcs_entries:
                        per_inline_colors = [(-1, inline_colors[0][1], pcs_entries[0][1])]

            if text_changed:
                section = decoded.get("section", "Section0")
                text_patches.setdefault(section, []).append(
                    (int(ph_offset), curr_text)
                )
                if isinstance(block, ParagraphBlock):
                    pcs_entries_t = _get_pcs_entries(decoded.get("pcs_bytes"))
                    if len(pcs_entries_t) > 1:
                        pcs_to_inline_t = _map_pcs_to_inlines(pt_b64 or "", pcs_entries_t)
                        text_ils = [i for i in block.inlines if isinstance(i, TextInline)]
                        if pcs_to_inline_t and len(text_ils) >= len(pcs_to_inline_t):
                            cum = [0]
                            for til in text_ils:
                                cum.append(cum[-1] + len(til.text))
                            new_pcs_bytes = b""
                            for pi, (_, cs_id) in enumerate(pcs_entries_t):
                                il_idx = pcs_to_inline_t.get(pi)
                                if il_idx is not None and il_idx < len(cum):
                                    new_pos = cum[il_idx]
                                else:
                                    new_pos = 0
                                new_pcs_bytes += struct.pack("<II", new_pos, cs_id)
                            pcs_remap_by_section.setdefault(section, {})[int(ph_offset)] = new_pcs_bytes
                if per_inline_colors:
                    multi_style_requests.append((section, int(ph_offset), per_inline_colors))
            elif per_inline_colors:
                multi_style_requests.append((decoded.get("section", "Section0"), int(ph_offset), per_inline_colors))

        elif isinstance(block, EquationBlock):
            ph_offset = decoded.get("ph_offset")
            section = decoded.get("section", "Section0")
            if ph_offset is None:
                continue
            curr_script = block.hwp_script or ""
            eq_patches.setdefault(section, []).append(
                (int(ph_offset), curr_script)
            )

        elif isinstance(block, TableBlock):
            pos = getattr(block, "position", None)
            if pos is None:
                continue
            ph_offset = decoded.get("ph_offset")
            section = decoded.get("section", "Section0")
            if ph_offset is None:
                continue
            orig_like_char = decoded.get("like_char")
            curr_like_char = pos.like_char
            if curr_like_char is not None and orig_like_char is not None:
                if bool(curr_like_char) != bool(orig_like_char):
                    tbl_attr_patches.setdefault(section, []).append(
                        (int(ph_offset), {"like_char": bool(curr_like_char)})
                    )

    cs_override_result: dict[str, list[tuple[int, int]]] = {}
    cs_overrides_by_section: dict[str, dict[int, dict[int, int]]] = {}
    pending_docinfo_result: bytes | None = None

    if multi_style_requests and doc.original_container:
        import zlib
        docinfo_raw = None
        if doc.verbatim and doc.verbatim.docinfo_stream:
            docinfo_raw = base64.b64decode(doc.verbatim.docinfo_stream)
        if docinfo_raw is None:
            from udf.parsers.hwp.ole import OleReader
            try:
                with OleReader.open(doc.original_container.path) as ole:
                    docinfo_raw = ole.read_stream(["DocInfo"])
            except Exception:
                pass

        if docinfo_raw is not None:
            docinfo_modified = docinfo_raw
            for section, ph_off, per_entry_colors in multi_style_requests:
                entry_overrides: dict[int, int] = {}
                for pcs_pos, target_color, base_cs_id in per_entry_colors:
                    orig_color = get_charshape_color(docinfo_modified, base_cs_id)
                    if orig_color and orig_color.lower() == target_color.lower():
                        continue
                    docinfo_modified, new_cs_id = find_or_add_charshape(
                        docinfo_modified, base_cs_id, target_color
                    )
                    entry_overrides[pcs_pos] = new_cs_id
                    cs_override_result.setdefault(section, []).append((ph_off, new_cs_id))

                if entry_overrides:
                    if -1 in entry_overrides and len(entry_overrides) == 1:
                        cs_overrides_by_section.setdefault(section, {})[ph_off] = entry_overrides[-1]
                    else:
                        cleaned = {k: v for k, v in entry_overrides.items() if k >= 0}
                        if cleaned:
                            cs_overrides_by_section.setdefault(section, {})[ph_off] = cleaned
                    if ph_off not in {off for off, _ in text_patches.get(section, [])}:
                        vb_block = next(
                            (b for b in _iter_all_blocks(doc.blocks)
                             if isinstance(b, ParagraphBlock)
                             and getattr(b, "verbatim_ref", None)
                             and b.verbatim_ref in doc.verbatim.blocks
                             and (doc.verbatim.blocks[b.verbatim_ref].decoded or {}).get("ph_offset") == ph_off),
                            None,
                        )
                        if vb_block:
                            curr_text = "".join(
                                i.text for i in vb_block.inlines if isinstance(i, TextInline)
                            )
                            text_patches.setdefault(section, []).append((ph_off, curr_text))

            if docinfo_modified != docinfo_raw:
                compressed = _read_compress_flag(doc.original_container.path)
                if compressed:
                    comp = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
                    docinfo_bytes = comp.compress(docinfo_modified) + comp.flush()
                else:
                    docinfo_bytes = docinfo_modified
                pending_docinfo_result = docinfo_bytes

    modified_sections: set[str] = set()
    all_sections = set(text_patches) | set(eq_patches) | set(tbl_attr_patches)
    for section_name in all_sections:
        b64 = doc.verbatim.section_streams.get(section_name)
        if not b64:
            continue
        decompressed = base64.b64decode(b64)
        patched = apply_section_patches(
            decompressed,
            text_patches=text_patches.get(section_name),
            eq_patches=eq_patches.get(section_name),
            tbl_attr_patches=tbl_attr_patches.get(section_name),
            cs_overrides=cs_overrides_by_section.get(section_name),
            pcs_remap=pcs_remap_by_section.get(section_name),
        )
        if patched != decompressed:
            doc.verbatim.section_streams[section_name] = base64.b64encode(
                patched
            ).decode()
            modified_sections.add(section_name)

    return cs_override_result, pending_docinfo_result, modified_sections


def _collect_new_images(doc: UdfDocument) -> list[dict]:
    """Identify new ImageBlocks without verbatim_ref and resolve insertion context.

    Returns a list of dicts with keys:
      block, section, anchor_ph_offset, extension, data
    """
    if not doc.verbatim:
        return []

    result = []
    blocks = doc.blocks
    for idx, block in enumerate(blocks):
        if not isinstance(block, ImageBlock):
            continue
        if getattr(block, "verbatim_ref", None):
            continue

        anchor_section = "Section0"
        anchor_ph_offset: int | None = None
        for prev_idx in range(idx - 1, -1, -1):
            prev = blocks[prev_idx]
            ref = getattr(prev, "verbatim_ref", None)
            if ref and ref in doc.verbatim.blocks:
                decoded = doc.verbatim.blocks[ref].decoded or {}
                anchor_section = decoded.get("section", "Section0")
                anchor_ph_offset = decoded.get("ph_offset")
                if anchor_ph_offset is not None:
                    anchor_ph_offset = int(anchor_ph_offset)
                break

        src = block.src or ""
        ext = "jpg"
        if "." in src:
            ext = src.rsplit(".", 1)[-1].lower()
        if ext not in ("jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "wmf", "emf"):
            ext = "jpg"

        from udf.renderers.hwp.scratch import _read_image_data
        data = _read_image_data(src, doc=doc)

        result.append({
            "block": block,
            "section": anchor_section,
            "anchor_ph_offset": anchor_ph_offset,
            "extension": ext,
            "data": data,
        })

    return result


def _apply_image_patches(
    doc: UdfDocument,
    new_images: list[dict],
    pending_docinfo: bytes | None,
    modified_sections: set[str],
    compressed: bool,
) -> tuple[bytes | None, set[str]]:
    """Apply image insertions: add BIN_DATA to DocInfo, inject GSO into sections."""
    from udf.parsers.hwp.ole import OleReader
    from udf.renderers.hwp.body_builder import build_image_gso_records
    from udf.schema.types import pt_to_hwpunit

    docinfo_raw = None
    if pending_docinfo:
        docinfo_raw = zlib.decompress(pending_docinfo, -15) if compressed else pending_docinfo
    elif doc.verbatim and doc.verbatim.docinfo_stream:
        docinfo_raw = base64.b64decode(doc.verbatim.docinfo_stream)
    if docinfo_raw is None and doc.original_container:
        try:
            with OleReader.open(doc.original_container.path) as ole:
                docinfo_raw = ole.read_stream(["DocInfo"])
        except Exception:
            pass
    if docinfo_raw is None:
        return pending_docinfo, modified_sections

    docinfo_modified = docinfo_raw

    image_injections: dict[str, list[tuple[int, list]]] = {}

    for img_info in new_images:
        if img_info["data"] is None:
            continue

        docinfo_modified, bin_item_id = add_bindata_record(
            docinfo_modified, img_info["extension"],
        )
        img_info["bin_item_id"] = bin_item_id

        block = img_info["block"]
        img_w = pt_to_hwpunit(block.width or 100.0)
        img_h = pt_to_hwpunit(block.height or 100.0)
        orig_w = pt_to_hwpunit(block.original_width) if block.original_width else img_w
        orig_h = pt_to_hwpunit(block.original_height) if block.original_height else img_h

        gso_records = build_image_gso_records(
            bin_item_id, img_w, img_h,
            orig_width=orig_w, orig_height=orig_h,
            position=getattr(block, "position", None),
        )

        section = img_info["section"]
        ph_offset = img_info["anchor_ph_offset"]
        if ph_offset is not None:
            image_injections.setdefault(section, []).append((ph_offset, gso_records))

    if docinfo_modified != docinfo_raw:
        if compressed:
            comp = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
            pending_docinfo = comp.compress(docinfo_modified) + comp.flush()
        else:
            pending_docinfo = docinfo_modified

    for section_name, injections in image_injections.items():
        b64 = doc.verbatim.section_streams.get(section_name)
        if not b64:
            continue
        decompressed = base64.b64decode(b64)
        for ph_offset, gso_records in injections:
            decompressed = inject_image_gso(decompressed, ph_offset, gso_records)
        doc.verbatim.section_streams[section_name] = base64.b64encode(
            decompressed,
        ).decode()
        modified_sections.add(section_name)

    return pending_docinfo, modified_sections


def render_hwp(
    doc: UdfDocument,
    output_path: str,
    *,
    validate: bool = True,
    seed_path: str | None = None,
    _force_modified_sections: set[str] | None = None,
) -> None:
    """Render a UdfDocument to an HWP 5.x binary file.

    Automatically selects Seed Patch mode when the original container
    and verbatim data are available; otherwise falls back to From Scratch
    mode using a seed template.

    Parameters
    ----------
    doc : UdfDocument
        The document model to render.
    output_path : str
        Destination path for the generated .hwp file.
    validate : bool, default True
        If True, run R-rule validation and auto-fix before writing.
    seed_path : str or None
        Explicit seed file for From Scratch mode. If None, a default
        seed is located automatically.

    Raises
    ------
    HwpRenderError
        If validation fails after auto-fix, or the seed file is missing
        in From Scratch mode.
    """
    has_verbatim = doc.verbatim is not None and bool(doc.verbatim.section_streams)
    has_container = (
        doc.original_container is not None
        and doc.original_container.format == "ole2"
    )

    new_images = _collect_new_images(doc)
    has_structural_change = any(
        not getattr(b, "verbatim_ref", None)
        for b in _iter_all_blocks(doc.blocks)
    )

    if not has_verbatim or not has_container or has_structural_change:
        from udf.renderers.hwp.scratch import generate_hwp_scratch
        actual_seed = seed_path or _find_default_seed()
        if not actual_seed:
            raise HwpRenderError(
                "From Scratch 모드에 필요한 seed HWP 파일을 찾을 수 없습니다."
            )
        generate_hwp_scratch(doc, output_path, actual_seed)
        return

    original_path = doc.original_container.path

    shutil.copy2(original_path, output_path)

    compressed = _read_compress_flag(original_path)

    orig_streams = dict(doc.verbatim.section_streams)
    _, pending_docinfo, modified_sections = _apply_ast_patches(doc)
    for sn, b64 in doc.verbatim.section_streams.items():
        if orig_streams.get(sn) != b64:
            modified_sections.add(sn)
    if _force_modified_sections:
        modified_sections |= _force_modified_sections

    # --- Seed Patch image insertion ---
    if new_images:
        pending_docinfo, modified_sections = _apply_image_patches(
            doc, new_images, pending_docinfo, modified_sections, compressed,
        )

    if validate:
        from udf.validation.validation_loop import validate_and_fix

        doc, report = validate_and_fix(doc)
        if not report.is_passing():
            violations = ", ".join(
                f"{v.rule_id}:{v.message}" for v in report.all_violations
            )
            raise HwpRenderError(f"검증 자동수정 후에도 R-규칙 위반: {violations}")

    if validate and pending_docinfo:
        from udf.validation.hwp.integrity import (
            check_i3_body,
            check_i3_docinfo,
            validate_hwp_integrity,
        )
        di_raw = pending_docinfo
        if compressed:
            di_raw = zlib.decompress(pending_docinfo, -15)
        i1i2_violations = validate_hwp_integrity(di_raw)
        if i1i2_violations:
            msgs = ", ".join(v.message for v in i1i2_violations)
            raise HwpRenderError(f"DocInfo I1/I2 위반: {msgs}")
        cs_count, ps_count, bf_count = check_i3_docinfo(di_raw)
        for _sn, _b64 in doc.verbatim.section_streams.items():
            i3_violations = check_i3_body(base64.b64decode(_b64), cs_count, ps_count, bf_count)
            if i3_violations:
                msgs = ", ".join(v.message for v in i3_violations)
                raise HwpRenderError(f"I3 위반 ({_sn}): {msgs}")

    # Batch all stream patches into a single read-write cycle (BUG-216).
    ole_patches: dict[tuple[str, ...], bytes] = {}
    if pending_docinfo:
        ole_patches[("DocInfo",)] = pending_docinfo
    for section_name in modified_sections:
        b64_bytes = doc.verbatim.section_streams.get(section_name)
        if not b64_bytes:
            continue
        decompressed = base64.b64decode(b64_bytes)

        if compressed:
            comp = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
            stream_bytes = comp.compress(decompressed) + comp.flush()
        else:
            stream_bytes = decompressed

        ole_patches[("BodyText", section_name)] = stream_bytes
    if ole_patches:
        patch_hwp_streams(output_path, output_path, ole_patches)

    # --- OLE BinData streams for new images ---
    if new_images:
        for img_info in new_images:
            if img_info.get("data") and img_info.get("bin_item_id"):
                stream_name = f"BIN{img_info['bin_item_id']:04X}.{img_info['extension']}"
                add_hwp_stream(output_path, ["BinData", stream_name], img_info["data"])

    if validate:
        from udf.validation.hwp.integrity import validate_hwp_file
        file_violations = validate_hwp_file(output_path)
        if file_violations:
            errors = [v for v in file_violations if v.severity == "error"]
            if errors:
                msgs = ", ".join(f"{v.rule_id}:{v.message}" for v in errors)
                raise HwpRenderError(f"출력 파일 검증 실패: {msgs}")

generate_hwp = render_hwp


def _apply_text_to_ast(
    original_doc: UdfDocument,
    edited_doc: UdfDocument,
    orig_text_by_id: dict[str, str],
) -> None:
    """Update AST block text in original_doc to match edited_doc."""
    edited_text_by_id: dict[str, str] = {}
    for block in _iter_text_blocks(edited_doc.blocks):
        if isinstance(block, ParagraphBlock):
            edited_text_by_id[block.id] = "".join(
                i.text for i in block.inlines if isinstance(i, TextInline)
            )
        elif isinstance(block, HeadingBlock):
            edited_text_by_id[block.id] = block.text

    for block in _iter_text_blocks(original_doc.blocks):
        bid = block.id
        if bid not in edited_text_by_id or bid not in orig_text_by_id:
            continue
        new_text = edited_text_by_id[bid]
        if new_text.rstrip() == orig_text_by_id[bid].rstrip():
            continue
        if isinstance(block, ParagraphBlock):
            if block.inlines and isinstance(block.inlines[0], TextInline):
                block.inlines[0] = block.inlines[0].model_copy(
                    update={"text": new_text}
                )
                block.inlines[:] = block.inlines[:1]
            else:
                block.inlines = [TextInline(type="text", text=new_text)]
        elif isinstance(block, HeadingBlock):
            block.text = new_text

    for block in _iter_all_blocks(edited_doc.blocks):
        if not isinstance(block, TableBlock):
            continue
        orig_tbl = next(
            (b for b in _iter_all_blocks(original_doc.blocks)
             if isinstance(b, TableBlock) and b.id == block.id), None
        )
        if not orig_tbl:
            continue
        for orow, erow in zip(orig_tbl.rows, block.rows):
            for ocell, ecell in zip(orow.cells, erow.cells):
                orig_ct = _cell_text(ocell)
                edited_ct = _cell_text(ecell)
                if orig_ct.rstrip() == edited_ct.rstrip():
                    continue
                for b in ocell.content:
                    if isinstance(b, ParagraphBlock) and b.inlines:
                        if isinstance(b.inlines[0], TextInline):
                            b.inlines[0] = b.inlines[0].model_copy(
                                update={"text": edited_ct}
                            )
                            b.inlines[:] = b.inlines[:1]
                        break


def _patch_hwp_from_parsed(
    original_path: str,
    edited_doc: UdfDocument,
    output_path: str,
    format_label: str,
) -> LossReport:
    """Common patch logic for MD/HTML → HWP Seed Patch."""
    from udf.parsers.hwp.parse import parse_hwp

    original_doc = parse_hwp(original_path)

    orig_text_by_id, orig_ph_offset_by_id, orig_section_by_id = (
        _collect_orig_text_info(original_doc)
    )

    patches_by_section: dict[str, list[tuple[int, str]]] = {}
    lossy: list[BlockLoss] = []

    edited_ids: set[str] = set()
    _match_block_patches(
        edited_doc, orig_text_by_id, orig_ph_offset_by_id, orig_section_by_id,
        patches_by_section, lossy, edited_ids,
    )

    _match_table_cell_patches(
        original_doc, edited_doc, orig_ph_offset_by_id, orig_section_by_id,
        patches_by_section, lossy, edited_ids,
    )

    for blk_id in orig_text_by_id:
        if blk_id not in edited_ids:
            lossy.append(format_limit_loss(
                blk_id, f"{format_label}에 미포함 (seed patch로 보존)"
            ))

    if not patches_by_section:
        render_hwp(original_doc, output_path)
        return build_loss_report(original_doc, lossy)

    _apply_text_to_ast(original_doc, edited_doc, orig_text_by_id)

    render_hwp(original_doc, output_path)
    return build_loss_report(original_doc, lossy)


def patch_hwp_from_md(
    original_path: str, md_content: str, output_path: str
) -> LossReport:
    """Patch an HWP file with text changes from edited Markdown content."""
    from udf.parsers.md.parse import parse_md

    return _patch_hwp_from_parsed(
        original_path, parse_md(md_content), output_path, "MD"
    )


def patch_hwp_from_html(
    original_path: str, html_content: str, output_path: str
) -> LossReport:
    """Patch an HWP file with text changes from edited HTML content."""
    from udf.parsers.html.parse import parse_html

    return _patch_hwp_from_parsed(
        original_path, parse_html(html_content), output_path, "HTML"
    )

    render_hwp(original_doc, output_path)
    return build_loss_report(original_doc, lossy)


def _read_compress_flag(path: str) -> bool:
    """HWP FileHeader에서 스트림 압축 여부를 읽는다."""
    import olefile

    try:
        with olefile.OleFileIO(path) as ole:
            raw: bytes = ole.openstream(_FILE_HEADER_STREAM).read()
    except Exception as e:
        raise HwpRenderError(f"FileHeader 읽기 실패: {path}") from e
    if len(raw) < _FLAGS_OFFSET + 4:
        raise HwpRenderError(f"FileHeader 크기 부족: {len(raw)}")
    (flags,) = struct.unpack_from("<I", raw, _FLAGS_OFFSET)
    return bool(flags & (1 << _COMPRESS_FLAG_BIT))
