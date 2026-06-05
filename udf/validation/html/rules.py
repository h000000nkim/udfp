"""HTML H-규칙 검증 함수.

H1: WHATWG 파싱 에러 검출 — html5lib 파서 에러 수집
H2: DOCTYPE 존재 확인 — 없으면 quirks mode
H3: id 속성 유일성 — 문서 내 중복 id 검출
H4: void element 닫힘 태그 금지 — br/hr/img 등

각 함수는 RuleViolation 리스트를 반환한다. 빈 리스트 = 통과.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import html5lib
from lxml import etree


@dataclass
class RuleViolation:
    rule_id: str
    block_id: str
    message: str
    severity: Literal["error", "warning"] = "warning"


def check_h1(content: str) -> list[RuleViolation]:
    """H-1: detect WHATWG parsing errors via html5lib."""
    violations: list[RuleViolation] = []
    parser = html5lib.HTMLParser()
    parser.parse(content)
    for (line, col), code, _data in parser.errors:
        violations.append(RuleViolation("H1", "", f"L{line}:C{col} {code}"))
    return violations


def check_h2(content: str) -> list[RuleViolation]:
    """H-2: DOCTYPE must be present at the start."""
    stripped = content.lstrip()
    if not stripped.lower().startswith("<!doctype"):
        return [RuleViolation("H2", "", "<!DOCTYPE html> 누락 — quirks mode 위험")]
    return []


def check_h3(content: str) -> list[RuleViolation]:
    """H-3: id attributes must be unique within the document."""
    violations: list[RuleViolation] = []
    try:
        doc = etree.HTML(content)
    except etree.XMLSyntaxError:
        return []
    ids: dict[str, int] = {}
    for elem in doc.iter():
        id_val = elem.get("id")
        if id_val:
            ids[id_val] = ids.get(id_val, 0) + 1
    for id_val, count in ids.items():
        if count > 1:
            violations.append(RuleViolation("H3", "", f'id="{id_val}" {count}회 중복'))
    return violations


_VOID_ELEMENTS = frozenset(
    [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]
)
_VOID_CLOSE_RE = re.compile(r"</(" + "|".join(_VOID_ELEMENTS) + r")\s*>", re.IGNORECASE)


def check_h4(content: str) -> list[RuleViolation]:
    """H-4: void elements must not have closing tags."""
    violations: list[RuleViolation] = []
    for m in _VOID_CLOSE_RE.finditer(content):
        tag = m.group(1).lower()
        pos = content[: m.start()].count("\n") + 1
        violations.append(
            RuleViolation("H4", "", f"L{pos}: void element <{tag}> 닫힘 태그 금지")
        )
    return violations


@dataclass
class HtmlValidationReport:
    """Aggregated result of H1-H4 validation checks."""

    h1: list[RuleViolation] = field(default_factory=list)
    h2: list[RuleViolation] = field(default_factory=list)
    h3: list[RuleViolation] = field(default_factory=list)
    h4: list[RuleViolation] = field(default_factory=list)

    @property
    def all_violations(self) -> list[RuleViolation]:
        return self.h1 + self.h2 + self.h3 + self.h4

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.all_violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.all_violations if v.severity == "warning")

    def is_passing(self) -> bool:
        return self.error_count == 0 and self.warning_count == 0


def validate_html(content: str) -> HtmlValidationReport:
    """Run all HTML H-rules (H1-H4) and return a consolidated report.

    Parameters
    ----------
    content : str
        HTML text to validate.

    Returns
    -------
    HtmlValidationReport
        Report containing violations for each rule.
    """
    return HtmlValidationReport(
        h1=check_h1(content),
        h2=check_h2(content),
        h3=check_h3(content),
        h4=check_h4(content),
    )
