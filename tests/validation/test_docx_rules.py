"""DOCX D-규칙 검증 테스트.

D1-D3 양성(정상 fixture 통과) + 음성(corruption 주입 → 감지) 테스트.
"""

from __future__ import annotations

import pathlib
import zipfile

import pytest

from udf.validation.docx.rules import (
    check_d1,
    check_d2,
    check_d3,
    validate_docx,
)

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "docx"
ALL_FIXTURES = sorted(p.name for p in FIXTURES.glob("*.docx"))


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


def _corrupt_zip(src: str, dest: str, remove_entries: list[str] | None = None,
                  replace_entries: dict[str, bytes] | None = None) -> str:
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
# D1: 필수 파트
# ---------------------------------------------------------------------------


class TestD1:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_d1(_fixture(filename))
        assert violations == [], f"D1 violations: {[v.message for v in violations]}"

    def test_detects_missing_document_xml(self, tmp_path: pathlib.Path) -> None:
        dest = str(tmp_path / "no_doc.docx")
        _corrupt_zip(
            _fixture(ALL_FIXTURES[0]), dest,
            remove_entries=["word/document.xml"],
        )
        violations = check_d1(dest)
        assert any("document.xml" in v.message for v in violations)

    def test_detects_missing_styles(self, tmp_path: pathlib.Path) -> None:
        dest = str(tmp_path / "no_styles.docx")
        _corrupt_zip(
            _fixture(ALL_FIXTURES[0]), dest,
            remove_entries=["word/styles.xml"],
        )
        violations = check_d1(dest)
        assert any("styles.xml" in v.message for v in violations)


# ---------------------------------------------------------------------------
# D2: Content_Types 일관성
# ---------------------------------------------------------------------------


class TestD2:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_d2(_fixture(filename))
        assert violations == [], f"D2 violations: {[v.message for v in violations]}"

    def test_detects_override_pointing_to_missing_part(self, tmp_path: pathlib.Path) -> None:
        """Content_Types에 Override가 있는 파트를 ZIP에서 제거."""
        dest = str(tmp_path / "broken_ct.docx")
        _corrupt_zip(
            _fixture(ALL_FIXTURES[0]), dest,
            remove_entries=["word/styles.xml"],
        )
        violations = check_d2(dest)
        assert any("존재하지 않는 파트" in v.message or "필수 Override" in v.message
                    for v in violations)


# ---------------------------------------------------------------------------
# D3: Relationships 참조 무결성
# ---------------------------------------------------------------------------


class TestD3:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        violations = check_d3(_fixture(filename))
        assert violations == [], f"D3 violations: {[v.message for v in violations]}"

    def test_detects_broken_relationship_target(self, tmp_path: pathlib.Path) -> None:
        """document.xml.rels에서 참조하는 styles.xml을 제거."""
        dest = str(tmp_path / "broken_rels.docx")
        _corrupt_zip(
            _fixture(ALL_FIXTURES[0]), dest,
            remove_entries=["word/styles.xml"],
        )
        violations = check_d3(dest)
        assert any("styles.xml" in v.message for v in violations)


# ---------------------------------------------------------------------------
# validate_docx 통합
# ---------------------------------------------------------------------------


class TestValidateDocx:
    @pytest.mark.parametrize("filename", ALL_FIXTURES)
    def test_passes_on_fixture(self, filename: str) -> None:
        report = validate_docx(_fixture(filename))
        assert report.is_passing(), (
            f"DOCX validation failed: {[v.message for v in report.all_violations]}"
        )
