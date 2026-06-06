"""HWPX HX-규칙 검증 테스트.

HX1-HX4 양성(정상 fixture 통과) + 음성(corruption 주입 → 감지) 테스트.
"""

from __future__ import annotations

import pathlib
import zipfile

import pytest

from udf.validation.hwpx.rules import (
    check_hx1,
    check_hx2,
    check_hx3,
    check_hx4,
    check_hx5,
    check_hx6,
    check_hx7,
    validate_hwpx,
)

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwpx"
ALL_FIXTURES = sorted(p.name for p in FIXTURES.glob("*.hwpx"))


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


def _corrupt_zip(src: str, dest: str, remove_entries: list[str] | None = None,
                  replace_entries: dict[str, bytes] | None = None) -> str:
    """Copy a ZIP file and optionally remove/replace entries."""
    with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(dest, "w") as zout:
        for item in zin.infolist():
            if remove_entries and item.filename in remove_entries:
                continue
            if replace_entries and item.filename in replace_entries:
                zout.writestr(item, replace_entries[item.filename])
            else:
                zout.writestr(item, zin.read(item.filename))
    return dest


# ---------------------------------------------------------------------------
# HX1: mimetype
# ---------------------------------------------------------------------------


class TestHX1:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_hx1(_fixture(filename))
        assert violations == [], f"HX1 violations: {[v.message for v in violations]}"

    def test_detects_wrong_mimetype_content(self, tmp_path: pathlib.Path) -> None:
        dest = str(tmp_path / "bad_mime.hwpx")
        _corrupt_zip(
            _fixture(ALL_FIXTURES[0]), dest,
            replace_entries={"mimetype": b"application/wrong"},
        )
        violations = check_hx1(dest)
        assert any("내용 불일치" in v.message for v in violations)

    def test_detects_missing_mimetype(self, tmp_path: pathlib.Path) -> None:
        dest = str(tmp_path / "no_mime.hwpx")
        _corrupt_zip(
            _fixture(ALL_FIXTURES[0]), dest,
            remove_entries=["mimetype"],
        )
        violations = check_hx1(dest)
        assert len(violations) >= 1
        assert any(v.rule_id == "HX1" for v in violations)


# ---------------------------------------------------------------------------
# HX2: 필수 파트
# ---------------------------------------------------------------------------


class TestHX2:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_hx2(_fixture(filename))
        assert violations == [], f"HX2 violations: {[v.message for v in violations]}"

    def test_detects_missing_header_xml(self, tmp_path: pathlib.Path) -> None:
        dest = str(tmp_path / "no_header.hwpx")
        _corrupt_zip(
            _fixture(ALL_FIXTURES[0]), dest,
            remove_entries=["Contents/header.xml"],
        )
        violations = check_hx2(dest)
        assert any("header.xml" in v.message for v in violations)


# ---------------------------------------------------------------------------
# HX3: manifest ↔ ZIP 일관성
# ---------------------------------------------------------------------------


class TestHX3:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_hx3(_fixture(filename))
        assert violations == [], f"HX3 violations: {[v.message for v in violations]}"

    def test_detects_manifest_referencing_missing_file(self, tmp_path: pathlib.Path) -> None:
        """manifest에 있는 section 파일을 ZIP에서 제거."""
        src = _fixture(ALL_FIXTURES[0])
        with zipfile.ZipFile(src, "r") as zf:
            sections = [n for n in zf.namelist()
                        if n.startswith("Contents/section") and n.endswith(".xml")]
        if not sections:
            pytest.skip("no section files in fixture")
        dest = str(tmp_path / "missing_section.hwpx")
        _corrupt_zip(src, dest, remove_entries=[sections[0]])
        violations = check_hx3(dest)
        assert len(violations) >= 1
        assert any("ZIP에 없음" in v.message for v in violations)


# ---------------------------------------------------------------------------
# HX4: header.xml 필수 구조
# ---------------------------------------------------------------------------


class TestHX4:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_hx4(_fixture(filename))
        assert violations == [], f"HX4 violations: {[v.message for v in violations]}"

    def test_detects_empty_header(self, tmp_path: pathlib.Path) -> None:
        """header.xml을 빈 XML로 교체 → charPr/paraPr/style/fontface 누락 감지."""
        dest = str(tmp_path / "empty_header.hwpx")
        empty_header = b'<?xml version="1.0" encoding="UTF-8"?><hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"></hh:head>'
        _corrupt_zip(
            _fixture(ALL_FIXTURES[0]), dest,
            replace_entries={"Contents/header.xml": empty_header},
        )
        violations = check_hx4(dest)
        assert len(violations) >= 3, f"Expected charPr+paraPr+style+fontface violations, got {len(violations)}"


# ---------------------------------------------------------------------------
# HX5: 네임스페이스 정확성
# ---------------------------------------------------------------------------


class TestHX5:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_hx5(_fixture(filename))
        assert violations == [], f"HX5 violations: {[v.message for v in violations]}"

    def test_detects_wrong_header_namespace(self, tmp_path: pathlib.Path) -> None:
        dest = str(tmp_path / "bad_ns.hwpx")
        bad_header = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<hh:head xmlns:hh="http://wrong.namespace/"></hh:head>'
        )
        _corrupt_zip(
            _fixture(ALL_FIXTURES[0]), dest,
            replace_entries={"Contents/header.xml": bad_header},
        )
        violations = check_hx5(dest)
        assert any("ns=" in v.message for v in violations)


# ---------------------------------------------------------------------------
# HX6: BinData 참조 무결성
# ---------------------------------------------------------------------------


class TestHX6:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_hx6(_fixture(filename))
        assert violations == [], f"HX6 violations: {[v.message for v in violations]}"


# ---------------------------------------------------------------------------
# HX7: XML well-formedness
# ---------------------------------------------------------------------------


class TestHX7:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_hx7(_fixture(filename))
        assert violations == [], f"HX7 violations: {[v.message for v in violations]}"

    def test_detects_malformed_xml(self, tmp_path: pathlib.Path) -> None:
        dest = str(tmp_path / "bad_xml.hwpx")
        _corrupt_zip(
            _fixture(ALL_FIXTURES[0]), dest,
            replace_entries={"Contents/header.xml": b"<not-closed>"},
        )
        violations = check_hx7(dest)
        assert any("header.xml" in v.message for v in violations)


# ---------------------------------------------------------------------------
# validate_hwpx 통합
# ---------------------------------------------------------------------------


class TestValidateHwpx:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        report = validate_hwpx(_fixture(filename))
        assert report.is_passing(), (
            f"HWPX validation failed: {[v.message for v in report.all_violations]}"
        )
