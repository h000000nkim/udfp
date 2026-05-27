"""공통 pytest fixture — 포맷별 fixture 디렉토리 경로."""

from __future__ import annotations

import pathlib

import pytest

_FIXTURE_ROOT = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def hwp_fixtures() -> pathlib.Path:
    return _FIXTURE_ROOT / "hwp"


@pytest.fixture
def hwpx_fixtures() -> pathlib.Path:
    return _FIXTURE_ROOT / "hwpx"


@pytest.fixture
def docx_fixtures() -> pathlib.Path:
    return _FIXTURE_ROOT / "docx"


@pytest.fixture
def pdf_fixtures() -> pathlib.Path:
    return _FIXTURE_ROOT / "pdf"


@pytest.fixture
def xml_fixtures() -> pathlib.Path:
    return _FIXTURE_ROOT / "xml"
