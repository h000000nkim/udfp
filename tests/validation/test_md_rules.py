"""Markdown M-규칙 검증 테스트.

M1-M3 양성(정상 입력 통과) + 음성(문제 입력 감지) 테스트.
"""

from __future__ import annotations

import pathlib

import pytest

from udf.validation.md.rules import (
    check_m1,
    check_m2,
    check_m3,
    validate_md,
)

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "md"
ALL_FIXTURES = sorted(p.name for p in FIXTURES.glob("*.md"))


def _read_fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# M1: raw HTML 블록 감지
# ---------------------------------------------------------------------------


class TestM1:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_no_errors_on_fixture(self, filename: str) -> None:
        content = _read_fixture(filename)
        violations = check_m1(content)
        errors = [v for v in violations if v.severity == "error"]
        assert errors == [], f"M1 errors: {[v.message for v in errors]}"

    def test_detects_raw_html_block(self) -> None:
        content = "# Title\n\n<div>raw html block</div>\n\nSome text.\n"
        violations = check_m1(content)
        assert len(violations) >= 1
        assert any("raw HTML" in v.message for v in violations)

    def test_passes_on_clean_markdown(self) -> None:
        content = "# Title\n\nSome **bold** text.\n\n- item 1\n- item 2\n"
        violations = check_m1(content)
        assert violations == []


# ---------------------------------------------------------------------------
# M2: 빈 문서 감지
# ---------------------------------------------------------------------------


class TestM2:
    def test_detects_empty_string(self) -> None:
        violations = check_m2("")
        assert len(violations) == 1
        assert "빈 문서" in violations[0].message

    def test_detects_whitespace_only(self) -> None:
        violations = check_m2("   \n\n  \t  \n")
        assert len(violations) == 1

    def test_passes_on_content(self) -> None:
        violations = check_m2("# Title\n\nContent here.\n")
        assert violations == []


# ---------------------------------------------------------------------------
# M3: 깨진 헤딩 감지
# ---------------------------------------------------------------------------


class TestM3:
    def test_detects_missing_space_after_hash(self) -> None:
        content = "#Title without space\n\n##Also broken\n"
        violations = check_m3(content)
        assert len(violations) == 2

    def test_passes_on_correct_headings(self) -> None:
        content = "# Title\n\n## Subtitle\n\n### H3\n"
        violations = check_m3(content)
        assert violations == []

    def test_ignores_non_heading_hash(self) -> None:
        content = "Use `#` in code.\n\nC# is a language.\n"
        violations = check_m3(content)
        assert violations == []


# ---------------------------------------------------------------------------
# validate_md 통합
# ---------------------------------------------------------------------------


class TestValidateMd:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_no_errors_on_fixture(self, filename: str) -> None:
        content = _read_fixture(filename)
        report = validate_md(content)
        assert report.error_count == 0, (
            f"MD validation errors: {[v.message for v in report.all_violations if v.severity == 'error']}"
        )

    def test_detects_multiple_issues(self) -> None:
        content = "#Broken heading\n\n<div>html</div>\n"
        report = validate_md(content)
        assert report.warning_count >= 2
