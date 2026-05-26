"""SHA-256 checksum utilities for document integrity verification."""

import hashlib
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    """Compute a SHA-256 checksum of a file, reading in 64 KB chunks.

    Parameters
    ----------
    path : str or Path
        Path to the file to hash.

    Returns
    -------
    str
        Prefixed hex digest in the form "sha256:<hex>".
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def sha256_bytes(data: bytes) -> str:
    """Compute a SHA-256 checksum of raw bytes.

    Parameters
    ----------
    data : bytes
        The byte sequence to hash.

    Returns
    -------
    str
        Prefixed hex digest in the form "sha256:<hex>".
    """
    return f"sha256:{hashlib.sha256(data).hexdigest()}"
