"""LossReport helpers -- track information loss during parsing/rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from udf.core.schema import BlockLoss, LossCategory, LossReport, UdfDocument

if TYPE_CHECKING:
    from udf.core.schema import ParagraphBlock, TableBlock


def build_loss_report(doc: UdfDocument, lossy: list[BlockLoss]) -> LossReport:
    """Build a LossReport from a document and its list of lossy blocks.

    Parameters
    ----------
    doc : UdfDocument
        The document whose total block count is used as the denominator.
    lossy : list of BlockLoss
        Individual block-level loss entries collected during conversion.

    Returns
    -------
    LossReport
        Summarized report including roundtrip safety determination.
    """
    total = len(doc.blocks)
    lossless = total - len(lossy)
    unintended = [b for b in lossy if b.loss_type == LossCategory.UNINTENDED]
    return LossReport(
        total_blocks=total,
        lossless_blocks=lossless,
        lossy_blocks=lossy,
        is_roundtrip_safe=len(unintended) == 0,
    )


def format_limit_loss(block_id: str, description: str) -> BlockLoss:
    """Create a BlockLoss entry for an inherent format limitation.

    Parameters
    ----------
    block_id : str
        The affected block's ID.
    description : str
        Human-readable explanation of the format limitation.

    Returns
    -------
    BlockLoss
        Loss entry with category FORMAT_LIMIT.
    """
    return BlockLoss(
        block_id=block_id,
        loss_type=LossCategory.FORMAT_LIMIT,
        description=description,
    )


def unintended_loss(block_id: str, description: str) -> BlockLoss:
    """Create a BlockLoss entry for unintended (bug-level) information loss.

    Parameters
    ----------
    block_id : str
        The affected block's ID.
    description : str
        Human-readable explanation of what was lost.

    Returns
    -------
    BlockLoss
        Loss entry with category UNINTENDED.
    """
    return BlockLoss(
        block_id=block_id,
        loss_type=LossCategory.UNINTENDED,
        description=description,
    )


def user_edited_loss(block_id: str, description: str) -> BlockLoss:
    """Create a BlockLoss entry for user-intentional edits (not a bug).

    Parameters
    ----------
    block_id : str
        The affected block's ID.
    description : str
        Human-readable explanation of the user edit.

    Returns
    -------
    BlockLoss
        Loss entry with category USER_EDITED.
    """
    return BlockLoss(
        block_id=block_id,
        loss_type=LossCategory.USER_EDITED,
        description=description,
    )


def _extract_para_text(blk: "ParagraphBlock") -> str:
    """Extract concatenated plain text from a paragraph's text inlines."""
    from udf.core.schema import TextInline as _TI

    return "".join(i.text for i in blk.inlines if isinstance(i, _TI))


_FORMAT_ATTRS = (
    "bold", "italic", "color", "font_size", "font_name",
    "underline", "strikethrough", "background_color",
    "underline_color", "letter_spacing", "char_scale",
)


def _compare_paragraph_formatting(oblk: "ParagraphBlock", rblk: "ParagraphBlock") -> list[str]:
    """Compare inline formatting attributes between two paragraphs."""
    from udf.core.schema import TextInline as _TI

    diffs: list[str] = []
    o_inlines = [i for i in oblk.inlines if isinstance(i, _TI)]
    r_inlines = [i for i in rblk.inlines if isinstance(i, _TI)]
    if len(o_inlines) != len(r_inlines):
        diffs.append(f"인라인 수 변경: {len(o_inlines)} → {len(r_inlines)}")
        return diffs
    for idx, (oi, ri) in enumerate(zip(o_inlines, r_inlines)):
        for attr in _FORMAT_ATTRS:
            ov = getattr(oi, attr, None)
            rv = getattr(ri, attr, None)
            if ov != rv:
                diffs.append(f"inline[{idx}].{attr}: {ov!r} → {rv!r}")
    return diffs


def _extract_table_cells(blk: "TableBlock") -> list[list[str]]:
    """TableBlock → [[cell_text, ...], ...] 행렬."""
    from udf.core.schema import ParagraphBlock as _PB
    from udf.core.schema import TextInline as _TI

    rows: list[list[str]] = []
    for row in blk.rows:
        cells: list[str] = []
        for cell in row.cells:
            parts: list[str] = []
            for b in cell.content:
                if isinstance(b, _PB):
                    parts.append(
                        "".join(i.text for i in b.inlines if isinstance(i, _TI))
                    )
            cells.append(" ".join(parts))
        rows.append(cells)
    return rows


def diff_documents(orig: UdfDocument, result: UdfDocument) -> LossReport:
    """Perform a semantic diff between two documents and produce a LossReport.

    Compares blocks by ID and classifies differences as UNINTENDED (block
    missing, type changed, table structure changed) or USER_EDITED (text
    content changed, heading level changed).

    Parameters
    ----------
    orig : UdfDocument
        The original (reference) document.
    result : UdfDocument
        The transformed (result) document to compare against *orig*.

    Returns
    -------
    LossReport
        A report listing all detected semantic differences.
    """
    from udf.core.schema import HeadingBlock, ParagraphBlock, TableBlock

    lossy: list[BlockLoss] = []

    orig_blocks = {b.id: b for b in orig.blocks if hasattr(b, "id")}
    result_blocks = {b.id: b for b in result.blocks if hasattr(b, "id")}

    for bid, oblk in orig_blocks.items():
        if bid not in result_blocks:
            lossy.append(unintended_loss(bid, f"블록 {bid} 소실"))
            continue

        rblk = result_blocks[bid]

        # 블록 타입 불일치
        if type(oblk) is not type(rblk):
            lossy.append(
                unintended_loss(
                    bid,
                    f"블록 타입 변경: {oblk.type} → {rblk.type}",
                )
            )
            continue

        # ParagraphBlock
        if isinstance(oblk, ParagraphBlock) and isinstance(rblk, ParagraphBlock):
            orig_text = _extract_para_text(oblk)
            res_text = _extract_para_text(rblk)
            if orig_text != res_text:
                lossy.append(
                    user_edited_loss(bid, f"텍스트 변경: {orig_text!r} → {res_text!r}")
                )
            for d in _compare_paragraph_formatting(oblk, rblk):
                lossy.append(unintended_loss(bid, f"포매팅 변경: {d}"))

        # HeadingBlock
        elif isinstance(oblk, HeadingBlock) and isinstance(rblk, HeadingBlock):
            if oblk.text != rblk.text:
                lossy.append(
                    user_edited_loss(
                        bid, f"헤딩 텍스트 변경: {oblk.text!r} → {rblk.text!r}"
                    )
                )
            if oblk.level != rblk.level:
                lossy.append(
                    user_edited_loss(
                        bid, f"헤딩 레벨 변경: {oblk.level} → {rblk.level}"
                    )
                )

        # TableBlock
        elif isinstance(oblk, TableBlock) and isinstance(rblk, TableBlock):
            orig_rows = _extract_table_cells(oblk)
            res_rows = _extract_table_cells(rblk)

            if len(orig_rows) != len(res_rows):
                lossy.append(
                    unintended_loss(
                        bid,
                        f"테이블 행 수 변경: {len(orig_rows)} → {len(res_rows)}",
                    )
                )
            else:
                for ri, (orow, rrow) in enumerate(zip(orig_rows, res_rows)):
                    if len(orow) != len(rrow):
                        lossy.append(
                            unintended_loss(
                                bid,
                                f"테이블 행{ri} 열 수 변경: {len(orow)} → {len(rrow)}",
                            )
                        )
                        continue
                    for ci, (oc, rc) in enumerate(zip(orow, rrow)):
                        if oc != rc:
                            lossy.append(
                                user_edited_loss(
                                    bid,
                                    f"셀[{ri},{ci}] 변경: {oc!r} → {rc!r}",
                                )
                            )

    return build_loss_report(result, lossy)
