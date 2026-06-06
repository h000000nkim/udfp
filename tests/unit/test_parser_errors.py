"""M3: 파서 에러 핸들링 테스트 — 손상/비정상 입력에 대한 방어."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


class TestHwpParserErrors:
    def test_empty_file_raises(self, tmp_path: Path):
        from udf.parsers.hwp.parse import parse_hwp
        f = tmp_path / "empty.hwp"
        f.write_bytes(b"")
        with pytest.raises(Exception):
            parse_hwp(str(f))

    def test_random_bytes_raises(self, tmp_path: Path):
        from udf.parsers.hwp.parse import parse_hwp
        f = tmp_path / "garbage.hwp"
        f.write_bytes(b"\x00\x01\x02\x03" * 100)
        with pytest.raises(Exception):
            parse_hwp(str(f))

    def test_truncated_ole_raises(self, tmp_path: Path):
        from udf.parsers.hwp.parse import parse_hwp
        f = tmp_path / "truncated.hwp"
        f.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
        with pytest.raises(Exception):
            parse_hwp(str(f))

    def test_nonexistent_file_raises(self):
        from udf.parsers.hwp.parse import parse_hwp
        with pytest.raises(Exception):
            parse_hwp("/nonexistent/path/file.hwp")


class TestHwpxParserErrors:
    def test_empty_file_raises(self, tmp_path: Path):
        from udf.parsers.hwpx.parse import parse_hwpx
        f = tmp_path / "empty.hwpx"
        f.write_bytes(b"")
        with pytest.raises(Exception):
            parse_hwpx(str(f))

    def test_invalid_zip_raises(self, tmp_path: Path):
        from udf.parsers.hwpx.parse import parse_hwpx
        f = tmp_path / "notzip.hwpx"
        f.write_bytes(b"this is not a zip file")
        with pytest.raises(Exception):
            parse_hwpx(str(f))


class TestDocxParserErrors:
    def test_empty_file_raises(self, tmp_path: Path):
        from udf.parsers.docx.parse import parse_docx
        f = tmp_path / "empty.docx"
        f.write_bytes(b"")
        with pytest.raises(Exception):
            parse_docx(str(f))

    def test_invalid_zip_raises(self, tmp_path: Path):
        from udf.parsers.docx.parse import parse_docx
        f = tmp_path / "notzip.docx"
        f.write_bytes(b"this is not a zip file")
        with pytest.raises(Exception):
            parse_docx(str(f))


class TestMdParserErrors:
    def test_empty_string_returns_doc(self):
        from udf.parsers.md.parse import parse_md
        doc = parse_md("")
        assert doc is not None
        assert len(doc.blocks) == 0 or doc.blocks is not None
