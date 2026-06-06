"""OLE2 인플레이스 패처 단위 테스트 — 4가지 stream 전환을 모두 검증."""

from __future__ import annotations

import tempfile

import olefile
import pytest

from udf.renderers.hwp.ole_patch import patch_hwp_stream

# fixtures/hwp 에서 실제 HWP 파일을 사용
_FIXTURES = "tests/fixtures/hwp"


def _read_stream(path: str, stream: list[str]) -> bytes:
    ole = olefile.OleFileIO(path)
    data = ole.openstream("/".join(stream)).read()
    ole.close()
    return data


def _stream_size(path: str, stream: list[str]) -> int:
    ole = olefile.OleFileIO(path)
    size = ole.get_size("/".join(stream))
    ole.close()
    return size


@pytest.fixture
def f01_path():
    return f"{_FIXTURES}/f01_plain_text.hwp"


class TestMiniToMini:
    def test_same_size_roundtrip(self, f01_path: str):
        original = _read_stream(f01_path, ["BodyText", "Section0"])
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp:
            patch_hwp_stream(f01_path, tmp.name, ["BodyText", "Section0"], original)
            result = _read_stream(tmp.name, ["BodyText", "Section0"])
        assert result == original

    def test_smaller_content(self, f01_path: str):
        new_content = b"\x01\x02\x03\x04"
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp:
            patch_hwp_stream(f01_path, tmp.name, ["BodyText", "Section0"], new_content)
            result = _read_stream(tmp.name, ["BodyText", "Section0"])
        assert result == new_content

    def test_larger_mini_content(self, f01_path: str):
        new_content = b"\xAB" * 2000
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp:
            patch_hwp_stream(f01_path, tmp.name, ["BodyText", "Section0"], new_content)
            result = _read_stream(tmp.name, ["BodyText", "Section0"])
        assert result == new_content


class TestMiniToRegular:
    def test_promotion(self, f01_path: str):
        new_content = b"\xCD" * 5000
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp:
            patch_hwp_stream(f01_path, tmp.name, ["BodyText", "Section0"], new_content)
            result = _read_stream(tmp.name, ["BodyText", "Section0"])
        assert result == new_content
        assert _stream_size(tmp.name, ["BodyText", "Section0"]) == 5000


class TestRegularToRegular:
    def test_same_size(self):
        src = "workspace/math_hanoi.hwp"
        try:
            original = _read_stream(src, ["BodyText", "Section0"])
        except FileNotFoundError:
            pytest.skip("math_hanoi.hwp not available")
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp:
            patch_hwp_stream(src, tmp.name, ["BodyText", "Section0"], original)
            result = _read_stream(tmp.name, ["BodyText", "Section0"])
        assert result == original

    def test_larger_regular(self):
        src = "workspace/math_hanoi.hwp"
        try:
            _read_stream(src, ["BodyText", "Section0"])
        except FileNotFoundError:
            pytest.skip("math_hanoi.hwp not available")
        new_content = b"\xEF" * 20000
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp:
            patch_hwp_stream(src, tmp.name, ["BodyText", "Section0"], new_content)
            result = _read_stream(tmp.name, ["BodyText", "Section0"])
        assert result == new_content


class TestRegularToMini:
    def test_demotion(self):
        src = "workspace/math_hanoi.hwp"
        try:
            old_size = _stream_size(src, ["BodyText", "Section0"])
        except FileNotFoundError:
            pytest.skip("math_hanoi.hwp not available")
        assert old_size >= 4096, f"Source must be regular stream, got {old_size}B"
        new_content = b"\x42" * 500
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp:
            patch_hwp_stream(src, tmp.name, ["BodyText", "Section0"], new_content)
            result = _read_stream(tmp.name, ["BodyText", "Section0"])
            size = _stream_size(tmp.name, ["BodyText", "Section0"])
        assert result == new_content
        assert size == 500

    def test_demotion_preserves_other_streams(self):
        src = "workspace/math_hanoi.hwp"
        try:
            old_docinfo = _read_stream(src, ["DocInfo"])
        except FileNotFoundError:
            pytest.skip("math_hanoi.hwp not available")
        new_content = b"\x42" * 500
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp:
            patch_hwp_stream(src, tmp.name, ["BodyText", "Section0"], new_content)
            new_docinfo = _read_stream(tmp.name, ["DocInfo"])
        assert new_docinfo == old_docinfo


class TestPromotionThenDemotion:
    def test_roundtrip_transition(self, f01_path: str):
        """mini→regular→mini 연속 전환이 올바르게 동작하는지 검증."""
        big = b"\xAA" * 5000
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp1:
            patch_hwp_stream(f01_path, tmp1.name, ["BodyText", "Section0"], big)
            assert _stream_size(tmp1.name, ["BodyText", "Section0"]) == 5000

            small = b"\xBB" * 200
            with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp2:
                patch_hwp_stream(tmp1.name, tmp2.name, ["BodyText", "Section0"], small)
                result = _read_stream(tmp2.name, ["BodyText", "Section0"])
                size = _stream_size(tmp2.name, ["BodyText", "Section0"])
        assert result == small
        assert size == 200
