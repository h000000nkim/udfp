"""HWP R-규칙 검증 함수.

hwp.md §6 기준:
  R1: PH.charCnt == len(PT) // 2
  R2: PH.csCount == len(PCS) // 8  &&  PH.lsCount == len(PLS) // 36
  R3: PLS 엔트리 >= 1 (텍스트 있는 단락)
  R4: 모든 PCS pos < len(PT) // 2

각 함수는 RuleViolation 리스트를 반환한다. 빈 리스트 = 통과.
"""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass
from typing import Literal

from udf.core.schema import HeadingBlock, ParagraphBlock, TableBlock, UdfDocument, VerbatimBlock
from udf.parsers.hwp.records import HWPTAG_PARA_HEADER


@dataclass
class RuleViolation:
    rule_id: str
    block_id: str
    message: str
    severity: Literal["error", "warning"] = "error"


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _b64d(b64: str | None) -> bytes:
    """Decode a base64 string to bytes, returning empty bytes if None."""
    return base64.b64decode(b64) if b64 else b""


def _para_verbatim_pairs(
    doc: UdfDocument,
) -> list[tuple[ParagraphBlock, VerbatimBlock, dict[str, object]]]:
    """ParagraphBlock + VerbatimBlock + decoded dict 쌍을 반환한다."""
    if doc.verbatim is None:
        return []
    pairs: list[tuple[ParagraphBlock, VerbatimBlock, dict[str, object]]] = []

    def _collect(blocks: list) -> None:
        for block in blocks:
            if isinstance(block, (ParagraphBlock, HeadingBlock)) and block.verbatim_ref:
                vb = doc.verbatim.blocks.get(block.verbatim_ref)
                if vb is not None and vb.decoded is not None and vb.raw_tag_id == HWPTAG_PARA_HEADER:
                    pairs.append((block, vb, vb.decoded))
            if isinstance(block, TableBlock):
                for row in block.rows:
                    for cell in row.cells:
                        _collect(cell.content)

    _collect(doc.blocks)
    return pairs


# ---------------------------------------------------------------------------
# R1
# ---------------------------------------------------------------------------


def check_r1(doc: UdfDocument) -> list[RuleViolation]:
    """Validate R1: PARA_HEADER.charCnt must equal len(PARA_TEXT) // 2.

    Checks that every paragraph header's character count field matches
    the actual length of the paragraph text stream.

    Parameters
    ----------
    doc : UdfDocument
        The parsed HWP document with verbatim layer.

    Returns
    -------
    list[RuleViolation]
        Violations found. Empty list means R1 passes.
    """
    violations: list[RuleViolation] = []
    for blk, vb, decoded in _para_verbatim_pairs(doc):
        pt_b64 = decoded.get("pt_bytes")
        if not pt_b64:
            continue  # PT 없는 단락 (끝맺음 단락 등) — 스킵
        pt_len = len(_b64d(str(pt_b64)))
        ph = _b64d(vb.raw_bytes)
        if len(ph) < 4:
            continue
        (char_cnt_raw,) = struct.unpack_from("<I", ph, 0)
        char_cnt = char_cnt_raw & 0x3FFFFFFF
        if char_cnt != pt_len // 2:
            violations.append(
                RuleViolation(
                    rule_id="R1",
                    block_id=blk.id,
                    message=f"charCnt={char_cnt} != len(PT)//2={pt_len // 2}",
                )
            )
    return violations


# ---------------------------------------------------------------------------
# R2
# ---------------------------------------------------------------------------


def check_r2(doc: UdfDocument) -> list[RuleViolation]:
    """Validate R2: csCount and lsCount must match PCS and PLS lengths.

    Verifies that the paragraph header's char-shape count equals
    len(PCS) // 8 and line-segment count equals len(PLS) // 36.

    Parameters
    ----------
    doc : UdfDocument
        The parsed HWP document with verbatim layer.

    Returns
    -------
    list[RuleViolation]
        Violations found. Empty list means R2 passes.
    """
    violations: list[RuleViolation] = []
    for blk, vb, decoded in _para_verbatim_pairs(doc):
        ph = _b64d(vb.raw_bytes)
        if len(ph) < 18:
            continue

        pt_b64 = decoded.get("pt_bytes")
        if not pt_b64:
            continue

        pcs_b64 = decoded.get("pcs_bytes")
        pcs = _b64d(str(pcs_b64) if pcs_b64 else None)
        (cs_count,) = struct.unpack_from("<H", ph, 12)
        expected_cs = len(pcs) // 8
        if cs_count != expected_cs:
            violations.append(
                RuleViolation(
                    rule_id="R2",
                    block_id=blk.id,
                    message=f"csCount={cs_count} != len(PCS)//8={expected_cs}",
                )
            )

        pls_b64 = decoded.get("pls_bytes")
        if not pls_b64:
            continue
        pls = _b64d(str(pls_b64))
        (ls_count,) = struct.unpack_from("<H", ph, 16)
        expected_ls = len(pls) // 36
        if ls_count != expected_ls:
            violations.append(
                RuleViolation(
                    rule_id="R2",
                    block_id=blk.id,
                    message=f"lsCount={ls_count} != len(PLS)//36={expected_ls}",
                )
            )
    return violations


# ---------------------------------------------------------------------------
# R3
# ---------------------------------------------------------------------------


def check_r3(doc: UdfDocument) -> list[RuleViolation]:
    """Validate R3: paragraphs with text must have at least one PLS entry.

    A paragraph that contains visible text must have a non-empty
    PARA_LINE_SEG record (at least 36 bytes for one entry).

    Parameters
    ----------
    doc : UdfDocument
        The parsed HWP document with verbatim layer.

    Returns
    -------
    list[RuleViolation]
        Violations found. Empty list means R3 passes.
    """
    violations: list[RuleViolation] = []
    for blk, vb, decoded in _para_verbatim_pairs(doc):
        if isinstance(blk, HeadingBlock):
            has_text = bool(blk.text)
        else:
            has_text = any(getattr(i, "text", "") for i in blk.inlines)
        if not has_text:
            continue
        pls_b64 = decoded.get("pls_bytes")
        pls = _b64d(str(pls_b64) if pls_b64 else None)
        if len(pls) < 36:
            violations.append(
                RuleViolation(
                    rule_id="R3",
                    block_id=blk.id,
                    message="PLS 없음 (텍스트 있는 단락)",
                )
            )
    return violations


# ---------------------------------------------------------------------------
# R4
# ---------------------------------------------------------------------------


def check_r4(doc: UdfDocument) -> list[RuleViolation]:
    """Validate R4: all PCS position values must be within PARA_TEXT bounds.

    Every PARA_CHAR_SHAPE entry's position field must be strictly less
    than the paragraph text length (len(PT) // 2).

    Parameters
    ----------
    doc : UdfDocument
        The parsed HWP document with verbatim layer.

    Returns
    -------
    list[RuleViolation]
        Violations found. Empty list means R4 passes.
    """
    violations: list[RuleViolation] = []
    for blk, vb, decoded in _para_verbatim_pairs(doc):
        pt_b64 = decoded.get("pt_bytes")
        pcs_b64 = decoded.get("pcs_bytes")
        pt = _b64d(str(pt_b64) if pt_b64 else None)
        pcs = _b64d(str(pcs_b64) if pcs_b64 else None)
        pt_len = len(pt) // 2
        for off in range(0, len(pcs) - 7, 8):
            (pos,) = struct.unpack_from("<I", pcs, off)
            if pos >= pt_len and pt_len > 0:
                violations.append(
                    RuleViolation(
                        rule_id="R4",
                        block_id=blk.id,
                        message=f"PCS pos={pos} >= pt_len={pt_len}",
                    )
                )
    return violations


# ---------------------------------------------------------------------------
# 통합 진입점
# ---------------------------------------------------------------------------


@dataclass
class ValidationReport:
    """Aggregated result of R1-R4 validation checks.

    Attributes
    ----------
    r1 : list[RuleViolation]
        R1 (charCnt) violations.
    r2 : list[RuleViolation]
        R2 (csCount/lsCount) violations.
    r3 : list[RuleViolation]
        R3 (empty PLS) violations.
    r4 : list[RuleViolation]
        R4 (OOB PCS position) violations.
    """

    r1: list[RuleViolation]
    r2: list[RuleViolation]
    r3: list[RuleViolation]
    r4: list[RuleViolation]

    @property
    def all_violations(self) -> list[RuleViolation]:
        """All violations from all rules combined."""
        return self.r1 + self.r2 + self.r3 + self.r4

    @property
    def error_count(self) -> int:
        """Number of error-severity violations."""
        return sum(1 for v in self.all_violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        """Number of warning-severity violations."""
        return sum(1 for v in self.all_violations if v.severity == "warning")

    def is_passing(self) -> bool:
        """Check whether all rules pass (zero errors and zero warnings).

        Returns
        -------
        bool
            True if no violations of any severity exist.
        """
        return self.error_count == 0 and self.warning_count == 0


def validate_hwp(doc: UdfDocument) -> ValidationReport:
    """Run all HWP R-rules (R1-R4) and return a consolidated report.

    Parameters
    ----------
    doc : UdfDocument
        The parsed HWP document with verbatim layer.

    Returns
    -------
    ValidationReport
        Report containing violations for each rule. Use ``is_passing()``
        to check overall success.
    """
    return ValidationReport(
        r1=check_r1(doc),
        r2=check_r2(doc),
        r3=check_r3(doc),
        r4=check_r4(doc),
    )
