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

from udf.validation.hwp.integrity import (
    check_r5,
    check_r6,
    check_r7,
    validate_hwp_file,
)

from udf.validation.docx.rules import (
    DocxValidationReport,
    check_d1,
    check_d2,
    check_d3,
    check_d4,
    check_d5,
    check_d6,
    validate_docx,
)

from udf.validation.hwpx.rules import (
    HwpxValidationReport,
    check_hx1,
    check_hx2,
    check_hx3,
    check_hx4,
    check_hx5,
    check_hx6,
    check_hx7,
    validate_hwpx,
)

from udf.validation.md.rules import (
    MdValidationReport,
    check_m1,
    check_m2,
    check_m3,
    validate_md,
)

from udf.validation.html.rules import (
    HtmlValidationReport,
    check_h1,
    check_h2,
    check_h3,
    check_h4,
    validate_html,
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
    # HWP file-level
    "check_r5",
    "check_r6",
    "check_r7",
    "validate_hwp_file",
    # DOCX
    "DocxValidationReport",
    "check_d1",
    "check_d2",
    "check_d3",
    "check_d4",
    "check_d5",
    "check_d6",
    "validate_docx",
    # HWPX
    "HwpxValidationReport",
    "check_hx1",
    "check_hx2",
    "check_hx3",
    "check_hx4",
    "check_hx5",
    "check_hx6",
    "check_hx7",
    "validate_hwpx",
    # MD
    "MdValidationReport",
    "check_m1",
    "check_m2",
    "check_m3",
    "validate_md",
    # HTML
    "HtmlValidationReport",
    "check_h1",
    "check_h2",
    "check_h3",
    "check_h4",
    "validate_html",
]
