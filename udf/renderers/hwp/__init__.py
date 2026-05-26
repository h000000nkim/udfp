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
    LossReport,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TableCell,
    TextBoxBlock,
    TextInline,
    UdfDocument,
)
from udf.renderers.hwp.body_writer import (
    apply_paragraph_patches,
    apply_section_patches,
)
from udf.renderers.hwp.docinfo_patch import find_or_add_charshape, get_charshape_color
from udf.renderers.hwp.ole_patch import patch_hwp_stream

_FILE_HEADER_STREAM = "FileHeader"
_FLAGS_OFFSET = 36
_COMPRESS_FLAG_BIT = 0

_RENDERER_VERSION = "0.1.0"

_DEFAULT_SEED_CANDIDATES = [
    "tests/fixtures/hwp/f01_plain_text.hwp",
]


def _find_default_seed() -> str | None:
    """프로젝트 루트 기준으로 기본 seed HWP 파일을 찾는다."""
    import pathlib
    base = pathlib.Path(__file__).resolve().parent.parent.parent.parent
    for candidate in _DEFAULT_SEED_CANDIDATES:
        p = base / candidate
        if p.exists():
            return str(p)
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
                if not orig_ct.strip():
                    continue
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
        if not orig_text.strip():
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
    pt = base64.b64decode(pt_b64)
    chars: list[str] = []
    i = 0
    while i + 2 <= len(pt):
        ch = struct.unpack_from("<H", pt, i)[0]
        if ch == 0x000D:
            break
        if ch <= 0x001F:
            i += 2 if ch in (0x0000, 0x0009, 0x000A) else 16
        else:
            chars.append(chr(ch))
            i += 2
    return "".join(chars)


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


def _get_pcs_first_cs_id(pcs_b64: str | None) -> int | None:
    """Extract the first charShapeId from base64-encoded PCS bytes."""
    if not pcs_b64:
        return None
    pcs = base64.b64decode(pcs_b64)
    if len(pcs) >= 8:
        return struct.unpack_from("<I", pcs, 4)[0]
    return None


def _apply_ast_patches(doc: UdfDocument) -> dict[str, list[tuple[int, int]]]:
    """Compare current AST to verbatim originals and patch changed blocks.

    Modifies verbatim.section_streams in-place.
    Returns a dict of {section: [(ph_offset, target_cs_id), ...]} for
    paragraphs that need CharShape overrides (style changes).
    """
    if not doc.verbatim or not doc.verbatim.section_streams:
        return {}

    text_patches: dict[str, list[tuple[int, str]]] = {}
    eq_patches: dict[str, list[tuple[int, str]]] = {}
    tbl_attr_patches: dict[str, list[tuple[int, dict[str, bool]]]] = {}
    style_requests: list[tuple[str, int, str, int | None]] = []

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
            target_color = _detect_color_override(block) if isinstance(block, ParagraphBlock) else None
            orig_cs_id = _get_pcs_first_cs_id(decoded.get("pcs_bytes"))

            if text_changed:
                section = decoded.get("section", "Section0")
                text_patches.setdefault(section, []).append(
                    (int(ph_offset), curr_text)
                )
                if target_color and orig_cs_id is not None:
                    style_requests.append((section, int(ph_offset), target_color, orig_cs_id))
            elif target_color and orig_cs_id is not None:
                style_requests.append((decoded.get("section", "Section0"), int(ph_offset), target_color, orig_cs_id))

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
    cs_overrides_by_section: dict[str, dict[int, int]] = {}

    if style_requests and doc.original_container:
        import zlib
        from udf.parsers.hwp.ole import OleReader
        try:
            with OleReader.open(doc.original_container.path) as ole:
                docinfo_raw = ole.read_stream(["DocInfo"])
        except Exception:
            docinfo_raw = None

        if docinfo_raw is not None:
            docinfo_modified = docinfo_raw
            for section, ph_off, target_color, base_cs_id in style_requests:
                orig_color = get_charshape_color(docinfo_modified, base_cs_id)
                if orig_color and orig_color.lower() == target_color.lower():
                    continue
                docinfo_modified, new_cs_id = find_or_add_charshape(
                    docinfo_modified, base_cs_id, target_color
                )
                cs_overrides_by_section.setdefault(section, {})[ph_off] = new_cs_id
                cs_override_result.setdefault(section, []).append((ph_off, new_cs_id))
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
                doc._pending_docinfo_patch = docinfo_bytes

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
        )
        doc.verbatim.section_streams[section_name] = base64.b64encode(
            patched
        ).decode()

    return cs_override_result


def render_hwp(
    doc: UdfDocument,
    output_path: str,
    *,
    validate: bool = True,
    seed_path: str | None = None,
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

    has_structural_change = any(
        not getattr(b, "verbatim_ref", None)
        for b in doc.blocks
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

    _apply_ast_patches(doc)

    pending_docinfo = getattr(doc, "_pending_docinfo_patch", None)
    if pending_docinfo:
        patch_hwp_stream(output_path, output_path, ["DocInfo"], pending_docinfo)
        del doc._pending_docinfo_patch

    if validate:
        from udf.validation.validation_loop import validate_and_fix

        doc, report = validate_and_fix(doc)
        if not report.is_passing():
            violations = ", ".join(
                f"{v.rule_id}:{v.message}" for v in report.all_violations
            )
            raise HwpRenderError(f"검증 자동수정 후에도 R-규칙 위반: {violations}")

    for section_name, b64_bytes in doc.verbatim.section_streams.items():
        decompressed = base64.b64decode(b64_bytes)

        if compressed:
            comp = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
            stream_bytes = comp.compress(decompressed) + comp.flush()
        else:
            stream_bytes = decompressed

        stream_path = ["BodyText", section_name]
        patch_hwp_stream(output_path, output_path, stream_path, stream_bytes)

generate_hwp = render_hwp


def patch_hwp_from_md(
    original_path: str, md_content: str, output_path: str
) -> LossReport:
    """Patch an HWP file with text changes from edited Markdown content.

    Parses the original HWP and the edited Markdown, diffs the text
    blocks, and applies only the changed paragraphs back to the HWP
    binary via Seed Patch mode.

    Parameters
    ----------
    original_path : str
        Path to the original HWP file.
    md_content : str
        Edited Markdown string.
    output_path : str
        Destination path for the patched HWP file.

    Returns
    -------
    LossReport
        Report detailing which blocks were modified, missing, or lossy.
    """
    from udf.parsers.hwp.parse import parse_hwp
    from udf.parsers.md.parse import parse_md

    original_doc = parse_hwp(original_path)
    edited_doc = parse_md(md_content)

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
            lossy.append(format_limit_loss(blk_id, "MD에 미포함 (seed patch로 보존)"))

    if not patches_by_section:
        render_hwp(original_doc, output_path)
        return build_loss_report(original_doc, lossy)

    assert original_doc.verbatim is not None
    for section_name, patch_list in patches_by_section.items():
        b64 = original_doc.verbatim.section_streams.get(section_name)
        if b64 is None:
            continue
        decompressed = base64.b64decode(b64)
        patched = apply_paragraph_patches(decompressed, patch_list)
        original_doc.verbatim.section_streams[section_name] = base64.b64encode(
            patched
        ).decode()

    render_hwp(original_doc, output_path)
    return build_loss_report(original_doc, lossy)


def patch_hwp_from_html(
    original_path: str, html_content: str, output_path: str
) -> LossReport:
    """Patch an HWP file with text changes from edited HTML content.

    Parses the original HWP and the edited HTML, diffs the text
    blocks, and applies only the changed paragraphs back to the HWP
    binary via Seed Patch mode.

    Parameters
    ----------
    original_path : str
        Path to the original HWP file.
    html_content : str
        Edited HTML string.
    output_path : str
        Destination path for the patched HWP file.

    Returns
    -------
    LossReport
        Report detailing which blocks were modified, missing, or lossy.
    """
    from udf.parsers.html.parse import parse_html
    from udf.parsers.hwp.parse import parse_hwp

    original_doc = parse_hwp(original_path)
    edited_doc = parse_html(html_content)

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
            lossy.append(format_limit_loss(blk_id, "HTML에 미포함 (seed patch로 보존)"))

    if not patches_by_section:
        render_hwp(original_doc, output_path)
        return build_loss_report(original_doc, lossy)

    assert original_doc.verbatim is not None
    for section_name, patch_list in patches_by_section.items():
        b64 = original_doc.verbatim.section_streams.get(section_name)
        if b64 is None:
            continue
        decompressed = base64.b64decode(b64)
        patched = apply_paragraph_patches(decompressed, patch_list)
        original_doc.verbatim.section_streams[section_name] = base64.b64encode(
            patched
        ).decode()

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
