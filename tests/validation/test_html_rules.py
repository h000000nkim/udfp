"""HTML H-규칙 검증 테스트.

H1-H4 양성(정상 입력 통과) + 음성(문제 입력 감지) 테스트.
"""

from __future__ import annotations


from udf.validation.html.rules import (
    check_h1,
    check_h2,
    check_h3,
    check_h4,
    validate_html,
)

_VALID_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Test</title>
</head>
<body>
<h1>Hello</h1>
<p>World</p>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# H1: WHATWG 파싱 에러
# ---------------------------------------------------------------------------


class TestH1:
    def test_passes_on_valid_html(self) -> None:
        violations = check_h1(_VALID_HTML)
        assert violations == [], f"H1 violations: {[v.message for v in violations]}"

    def test_detects_invalid_nesting(self) -> None:
        bad = "<!DOCTYPE html><html><body><p><div>nested block</div></p></body></html>"
        violations = check_h1(bad)
        assert len(violations) >= 1


# ---------------------------------------------------------------------------
# H2: DOCTYPE 존재
# ---------------------------------------------------------------------------


class TestH2:
    def test_passes_with_doctype(self) -> None:
        violations = check_h2(_VALID_HTML)
        assert violations == []

    def test_detects_missing_doctype(self) -> None:
        no_doctype = "<html><head></head><body>Hello</body></html>"
        violations = check_h2(no_doctype)
        assert len(violations) == 1
        assert "DOCTYPE" in violations[0].message

    def test_passes_with_whitespace_before_doctype(self) -> None:
        content = "\n  <!DOCTYPE html>\n<html><body></body></html>"
        violations = check_h2(content)
        assert violations == []


# ---------------------------------------------------------------------------
# H3: id 유일성
# ---------------------------------------------------------------------------


class TestH3:
    def test_passes_with_unique_ids(self) -> None:
        content = '<!DOCTYPE html><html><body><div id="a"></div><div id="b"></div></body></html>'
        violations = check_h3(content)
        assert violations == []

    def test_detects_duplicate_ids(self) -> None:
        content = '<!DOCTYPE html><html><body><div id="x"></div><div id="x"></div></body></html>'
        violations = check_h3(content)
        assert len(violations) == 1
        assert "x" in violations[0].message
        assert "2" in violations[0].message

    def test_passes_with_no_ids(self) -> None:
        content = "<!DOCTYPE html><html><body><p>text</p></body></html>"
        violations = check_h3(content)
        assert violations == []


# ---------------------------------------------------------------------------
# H4: void element 닫힘 태그
# ---------------------------------------------------------------------------


class TestH4:
    def test_passes_without_void_close_tags(self) -> None:
        content = "<!DOCTYPE html><html><body><br><hr><img src='x.png'></body></html>"
        violations = check_h4(content)
        assert violations == []

    def test_detects_void_close_tag(self) -> None:
        content = "<!DOCTYPE html><html><body><br></br><hr></hr></body></html>"
        violations = check_h4(content)
        assert len(violations) == 2
        assert any("br" in v.message for v in violations)
        assert any("hr" in v.message for v in violations)

    def test_ignores_non_void_close_tags(self) -> None:
        content = "<!DOCTYPE html><html><body><div></div><p></p></body></html>"
        violations = check_h4(content)
        assert violations == []


# ---------------------------------------------------------------------------
# validate_html 통합
# ---------------------------------------------------------------------------


class TestValidateHtml:
    def test_passes_on_valid_html(self) -> None:
        report = validate_html(_VALID_HTML)
        assert report.error_count == 0, (
            f"HTML validation errors: {[v.message for v in report.all_violations if v.severity == 'error']}"
        )

    def test_detects_multiple_issues(self) -> None:
        bad = '<html><body><div id="a"></div><div id="a"></div></body></html>'
        report = validate_html(bad)
        assert report.warning_count >= 2

    def test_real_renderer_output(self) -> None:
        """Test with output similar to what the HTML renderer produces."""
        import udf

        doc = udf.parse("tests/fixtures/hwp/f01_plain_text.hwp")
        html = udf.render(doc, "html")
        report = validate_html(html)
        assert report.error_count == 0, (
            f"Renderer output has errors: {[v.message for v in report.all_violations if v.severity == 'error']}"
        )
