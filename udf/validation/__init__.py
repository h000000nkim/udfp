"""UDF 검증 모듈 — 포맷별 R-규칙 + ValidationReport."""

from udf.validation.hwp.rules import (
    RuleViolation,
    ValidationReport,
    check_r1,
    check_r2,
    check_r3,
    check_r4,
    validate_hwp,
)

from udf.validation.docx.rules import (
    DocxValidationReport,
    check_d1,
    check_d2,
    check_d3,
    validate_docx,
)

from udf.validation.hwpx.rules import (
    HwpxValidationReport,
    check_hx1,
    check_hx2,
    check_hx3,
    check_hx4,
    validate_hwpx,
)

__all__ = [
    # HWP
    "RuleViolation",
    "ValidationReport",
    "check_r1",
    "check_r2",
    "check_r3",
    "check_r4",
    "validate_hwp",
    # DOCX
    "DocxValidationReport",
    "check_d1",
    "check_d2",
    "check_d3",
    "validate_docx",
    # HWPX
    "HwpxValidationReport",
    "check_hx1",
    "check_hx2",
    "check_hx3",
    "check_hx4",
    "validate_hwpx",
]
