"""Format detection -- extension-first with magic-byte verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_MAGIC: dict[bytes, str] = {
    b"\xd0\xcf\x11\xe0": "hwp",
    b"\x50\x4b\x03\x04": "zip",  # HWPX / DOCX / XLSX 공통
    b"\x25\x50\x44\x46": "pdf",  # %PDF
}

_EXT: dict[str, str] = {
    ".hwp": "hwp",
    ".hwpx": "hwpx",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pdf": "pdf",
    ".md": "md",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
}

_ZIP_MARKERS: list[tuple[str, str]] = [
    ("META-INF/container.xml", "hwpx"),
    ("word/document.xml", "docx"),
    ("xl/workbook.xml", "xlsx"),
]


class DetectError(Exception):
    """Raised when the file format cannot be determined."""

    pass


@dataclass
class DetectResult:
    """Result of format detection.

    Attributes
    ----------
    format : str
        Detected format identifier (e.g. "hwp", "docx", "pdf").
    source : str
        How the format was determined: "extension", "magic_bytes", or "inferred".
    warnings : list[str]
        Non-fatal messages (e.g. extension/magic mismatch).
    """

    format: str
    source: str  # "extension" | "magic_bytes" | "inferred"
    warnings: list[str] = field(default_factory=list)


def _read_magic(path: str) -> bytes | None:
    """Read the first 4 bytes of a file."""
    try:
        with open(path, "rb") as f:
            return f.read(4)
    except OSError:
        return None


def _magic_format(magic: bytes) -> str | None:
    """Map 4-byte magic to a raw format string."""
    return _MAGIC.get(magic[:4])


def _disambiguate_zip(path: str) -> str | None:
    """Distinguish HWPX/DOCX/XLSX by inspecting ZIP entry names."""
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
        for marker, fmt in _ZIP_MARKERS:
            if marker in names:
                return fmt
    except Exception:
        pass
    return None


def detect(path: str) -> DetectResult:
    """Detect the document format of a file.

    Uses the file extension as the primary signal, verified against
    magic bytes. On mismatch a warning is attached but parsing is not
    blocked. Raises only when format cannot be determined at all.

    Parameters
    ----------
    path : str
        Filesystem path to the file.

    Returns
    -------
    DetectResult
        Detected format, detection source, and any warnings.

    Raises
    ------
    DetectError
        If the format cannot be determined from extension or magic bytes.
    """
    p = Path(path)
    ext_fmt = _EXT.get(p.suffix.lower())

    magic = _read_magic(path)
    if magic is None:
        raise DetectError(f"파일을 읽을 수 없음: {path}")

    magic_raw = _magic_format(magic)
    # ZIP 계열은 내부를 봐야 정확한 포맷 확정 가능
    magic_fmt = _disambiguate_zip(path) if magic_raw == "zip" else magic_raw

    warnings: list[str] = []

    if ext_fmt is not None:
        # 확장자로 포맷 확정, magic bytes로 검증
        expected_magic = "zip" if ext_fmt in ("hwpx", "docx", "xlsx") else ext_fmt
        if magic_raw is not None and magic_raw != expected_magic:
            warnings.append(
                f"확장자({ext_fmt})와 magic bytes({magic_raw}) 불일치 — 확장자 기준으로 파싱"
            )
        return DetectResult(format=ext_fmt, source="extension", warnings=warnings)

    # 확장자 미인식 → magic bytes로 추론
    if magic_fmt is not None:
        warnings.append(
            f"알 수 없는 확장자({p.suffix!r}) — magic bytes로 추론: {magic_fmt}"
        )
        return DetectResult(format=magic_fmt, source="magic_bytes", warnings=warnings)

    raise DetectError(
        f"포맷을 판별할 수 없음: 확장자={p.suffix!r}, magic={magic.hex()}"
    )
