"""Markdown M-규칙 검증 함수.

M1: 예기치 않은 raw HTML 블록 검출 — markdown-it-py 토큰 타입 검사
M2: 빈 문서 검출 — 내용 없는 MD 출력 감지
M3: 깨진 헤딩 검출 — `#` 뒤 공백 누락 패턴

각 함수는 RuleViolation 리스트를 반환한다. 빈 리스트 = 통과.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from markdown_it import MarkdownIt


@dataclass
class RuleViolation:
    rule_id: str
    block_id: str
    message: str
    severity: Literal["error", "warning"] = "warning"


def check_m1(content: str) -> list[RuleViolation]:
    """M-1: detect unexpected raw HTML blocks in rendered markdown."""
    violations: list[RuleViolation] = []
    md = MarkdownIt()
    tokens = md.parse(content)
    for tok in tokens:
        if tok.type == "html_block" and tok.map:
            violations.append(
                RuleViolation(
                    "M1",
                    "",
                    f"L{tok.map[0] + 1}: 예기치 않은 raw HTML 블록",
                )
            )
    return violations


def check_m2(content: str) -> list[RuleViolation]:
    """M-2: detect empty document output."""
    if not content.strip():
        return [RuleViolation("M2", "", "빈 문서 출력")]
    return []


_BROKEN_HEADING_RE = re.compile(r"^#{1,6}(?=[A-Z가-힣ㄱ-ㆎ])", re.MULTILINE)
_FENCED_BLOCK_RE = re.compile(r"^(`{3,}|~{3,}).*?^\1", re.MULTILINE | re.DOTALL)


def _remove_code_blocks(content: str) -> str:
    return _FENCED_BLOCK_RE.sub("", content)


def check_m3(content: str) -> list[RuleViolation]:
    """M-3: detect broken headings (missing space after #)."""
    violations: list[RuleViolation] = []
    cleaned = _remove_code_blocks(content)
    lines = cleaned.splitlines()
    for m in _BROKEN_HEADING_RE.finditer(cleaned):
        lineno = cleaned[: m.start()].count("\n") + 1
        line_text = lines[lineno - 1] if lineno <= len(lines) else ""
        violations.append(
            RuleViolation(
                "M3", "", f"L{lineno}: 헤딩 `#` 뒤 공백 누락: {line_text[:40]}"
            )
        )
    return violations


@dataclass
class MdValidationReport:
    """Aggregated result of M1-M3 validation checks."""

    m1: list[RuleViolation] = field(default_factory=list)
    m2: list[RuleViolation] = field(default_factory=list)
    m3: list[RuleViolation] = field(default_factory=list)

    @property
    def all_violations(self) -> list[RuleViolation]:
        return self.m1 + self.m2 + self.m3

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.all_violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.all_violations if v.severity == "warning")

    def is_passing(self) -> bool:
        return self.error_count == 0 and self.warning_count == 0


def validate_md(content: str) -> MdValidationReport:
    """Run all Markdown M-rules (M1-M3) and return a consolidated report.

    Parameters
    ----------
    content : str
        Markdown text to validate.

    Returns
    -------
    MdValidationReport
        Report containing violations for each rule.
    """
    return MdValidationReport(
        m1=check_m1(content),
        m2=check_m2(content),
        m3=check_m3(content),
    )
