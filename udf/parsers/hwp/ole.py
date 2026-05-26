"""OLE2 container reader for HWP 5.x binary files."""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import olefile

from udf.pipeline.container import OriginalContainer

_FILE_HEADER_STREAM = "FileHeader"
_FLAGS_OFFSET = 36
_COMPRESS_FLAG_BIT = 0  # flags 비트0 = 스트림 압축 여부

StreamPath = list[str]


class OleReaderError(Exception):
    """Raised on OLE2 read / decompression failures."""

    pass


@dataclass
class StreamInfo:
    """Metadata for a single OLE2 stream."""

    name: StreamPath
    compressed: bool


class OleReader:
    """Reads and decompresses streams from an HWP OLE2 container.

    Use :meth:`open` as the primary constructor; supports context-manager
    protocol for deterministic cleanup.
    """

    def __init__(
        self,
        ole: Any,
        path: str,
        checksum: str,
        compressed: bool,
    ) -> None:
        """Initialize with a pre-opened olefile handle."""
        self._ole = ole
        self._path = path
        self._checksum = checksum
        self._compressed = compressed

    @classmethod
    def open(cls, path: str) -> OleReader:
        """Open an HWP file and return an OleReader.

        Parameters
        ----------
        path : str
            Filesystem path to the ``.hwp`` file.

        Returns
        -------
        OleReader
            Ready-to-use reader instance.

        Raises
        ------
        OleReaderError
            If the file cannot be opened as OLE2.
        """
        try:
            ole = olefile.OleFileIO(path)
        except Exception as e:
            raise OleReaderError(f"OLE2 파일 열기 실패: {path}") from e

        checksum = cls._sha256(path)
        compressed = cls._read_compress_flag(ole)
        return cls(ole, path, checksum, compressed)

    @staticmethod
    def _sha256(path: str) -> str:
        """Compute SHA-256 hex digest of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return f"sha256:{h.hexdigest()}"

    @staticmethod
    def _read_compress_flag(ole: Any) -> bool:
        """Read the stream-compression flag from FileHeader."""
        if not ole.exists(_FILE_HEADER_STREAM):
            raise OleReaderError("FileHeader 스트림 없음 — HWP 파일이 아닐 수 있음")
        try:
            raw: bytes = ole.openstream(_FILE_HEADER_STREAM).read()
        except Exception as e:
            raise OleReaderError("FileHeader 읽기 실패") from e
        if len(raw) < _FLAGS_OFFSET + 4:
            raise OleReaderError(f"FileHeader 크기 부족: {len(raw)}바이트")
        (flags,) = struct.unpack_from("<I", raw, _FLAGS_OFFSET)
        return bool(flags & (1 << _COMPRESS_FLAG_BIT))

    @property
    def original_container(self) -> OriginalContainer:
        """Build an :class:`OriginalContainer` reference for seed-patch mode."""
        return OriginalContainer(
            format="ole2", path=self._path, checksum=self._checksum
        )

    def stream_names(self) -> list[StreamPath]:
        """Return all stream paths in the OLE2 container.

        Returns
        -------
        list[StreamPath]
            Each entry is a list of path segments (e.g. ``["BodyText", "Section0"]``).
        """
        return self._ole.listdir(streams=True, storages=False)  # type: ignore[no-any-return]

    def stream_info(self, name: StreamPath) -> StreamInfo:
        """Return metadata for a stream.

        Parameters
        ----------
        name : StreamPath
            Path segments identifying the stream.

        Returns
        -------
        StreamInfo
            Name and compression flag for the stream.
        """
        is_compressed = self._compressed and name != [_FILE_HEADER_STREAM]
        return StreamInfo(name=name, compressed=is_compressed)

    def read_raw(self, name: StreamPath) -> bytes:
        """Read raw (possibly compressed) bytes of a stream.

        Parameters
        ----------
        name : StreamPath
            Path segments identifying the stream.

        Returns
        -------
        bytes
            Raw stream content without decompression.

        Raises
        ------
        OleReaderError
            If the stream does not exist or cannot be read.
        """
        if not self._ole.exists(name):
            raise OleReaderError(f"스트림 없음: {name}")
        try:
            result: bytes = self._ole.openstream(name).read()
            return result
        except Exception as e:
            raise OleReaderError(f"스트림 읽기 실패: {name}") from e

    def read_stream(self, name: StreamPath) -> bytes:
        """Read and decompress a stream.

        If the HWP file has stream compression enabled (FileHeader flag),
        applies raw deflate (``wbits=-15``) except for ``FileHeader`` itself.

        Parameters
        ----------
        name : StreamPath
            Path segments identifying the stream.

        Returns
        -------
        bytes
            Decompressed stream content.

        Raises
        ------
        OleReaderError
            If reading or decompression fails.
        """
        raw = self.read_raw(name)
        if not self.stream_info(name).compressed:
            return raw
        try:
            return zlib.decompress(raw, wbits=-15)
        except zlib.error as e:
            raise OleReaderError(f"압축 해제 실패: {name}") from e

    def close(self) -> None:
        """Close the underlying OLE2 file handle."""
        self._ole.close()

    def __enter__(self) -> OleReader:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
