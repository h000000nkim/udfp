"""HTML H-규칙 검증 모듈."""

from udf.validation.html.rules import (
    HtmlValidationReport,
    RuleViolation,
    check_h1,
    check_h2,
    check_h3,
    check_h4,
    validate_html,
)

__all__ = [
    "HtmlValidationReport",
    "RuleViolation",
    "check_h1",
    "check_h2",
    "check_h3",
    "check_h4",
    "validate_html",
]
