"""CLI 통합 테스트."""

from __future__ import annotations

import pathlib
import subprocess
import sys

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwp"


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


class TestCliConvert:
    def test_convert_to_stdout(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "udf.cli",
                "convert",
                _fixture("f01_plain_text.hwp"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0
        assert len(result.stdout.strip()) > 0

    def test_convert_to_file(self, tmp_path: pathlib.Path) -> None:
        out = str(tmp_path / "out.md")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "udf.cli",
                "convert",
                _fixture("f01_plain_text.hwp"),
                "-o",
                out,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0
        assert pathlib.Path(out).exists()
        assert pathlib.Path(out).stat().st_size > 0

    def test_convert_embed_ids(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "udf.cli",
                "convert",
                "--embed-ids",
                _fixture("f01_plain_text.hwp"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0
        assert "<!-- id:" in result.stdout


class TestCliValidate:
    def test_valid_file_exits_0(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "udf.cli",
                "validate",
                _fixture("f01_plain_text.hwp"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0
        assert "통과" in result.stdout

    def test_nonexistent_file_exits_1(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "udf.cli", "validate", "/nonexistent/file.hwp"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 1


class TestCliPatch:
    def test_patch_roundtrip(self, tmp_path: pathlib.Path) -> None:
        orig = _fixture("f01_plain_text.hwp")
        md_path = str(tmp_path / "doc.md")
        out_path = str(tmp_path / "out.hwp")

        # convert
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "udf.cli",
                "convert",
                "--embed-ids",
                orig,
                "-o",
                md_path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r.returncode == 0

        # patch with no changes
        r2 = subprocess.run(
            [
                sys.executable,
                "-m",
                "udf.cli",
                "patch",
                orig,
                "--md",
                md_path,
                "-o",
                out_path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r2.returncode == 0
        assert pathlib.Path(out_path).exists()


class TestCliDiff:
    def test_same_file_diff(self) -> None:
        f = _fixture("f01_plain_text.hwp")
        result = subprocess.run(
            [sys.executable, "-m", "udf.cli", "diff", f, f],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0
        assert "동일" in result.stdout

    def test_different_files_diff(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "udf.cli",
                "diff",
                _fixture("f01_plain_text.hwp"),
                _fixture("f06_multiline.hwp"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert "차이" in result.stdout
