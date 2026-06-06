"""Block and verbatim ID generation and validation utilities."""

import re


def make_block_id(index: int) -> str:
    """Generate a block ID from a numeric index.

    Parameters
    ----------
    index : int
        Zero-based or one-based block index.

    Returns
    -------
    str
        Block ID in the form "b_NNNN" (zero-padded to at least 4 digits).
    """
    return f"b_{index:04d}"


def make_verbatim_id(index: int) -> str:
    """Generate a verbatim reference ID from a numeric index.

    Parameters
    ----------
    index : int
        Zero-based or one-based verbatim index.

    Returns
    -------
    str
        Verbatim ID in the form "v_NNNN" (zero-padded to at least 4 digits).
    """
    return f"v_{index:04d}"


def is_valid_block_id(id_: str) -> bool:
    """Check whether a string matches the block ID format ("b_" + 4+ digits).

    Parameters
    ----------
    id_ : str
        String to validate.

    Returns
    -------
    bool
        True if the string is a valid block ID.
    """
    return bool(re.match(r"^b_\d{4,}$", id_))


_BLOCK_INDEX_RE = re.compile(r"^b_(\d+)$")


def max_block_index(blocks: list) -> int:
    """Recursively scan all block IDs and return the maximum numeric index.

    Parameters
    ----------
    blocks : list
        Top-level block list from a UdfDocument.

    Returns
    -------
    int
        Maximum numeric index found (0 if none).
    """
    max_idx = 0
    for b in blocks:
        max_idx = max(max_idx, _extract_index(getattr(b, "id", None)))
        rows = getattr(b, "rows", None)
        if rows:
            for row in rows:
                for cell in getattr(row, "cells", []):
                    max_idx = max(max_idx, _extract_index(getattr(cell, "id", None)))
                    max_idx = max(max_idx, max_block_index(getattr(cell, "content", [])))
        items = getattr(b, "items", None)
        if items:
            for item in items:
                max_idx = max(max_idx, _extract_index(getattr(item, "id", None)))
                max_idx = max(max_idx, max_block_index(getattr(item, "children", [])))
        content = getattr(b, "content", None)
        if isinstance(content, list):
            max_idx = max(max_idx, max_block_index(content))
        children = getattr(b, "children", None)
        if isinstance(children, list) and children is not items:
            max_idx = max(max_idx, max_block_index(children))
    return max_idx


def _extract_index(bid: str | None) -> int:
    if not bid or not isinstance(bid, str):
        return 0
    m = _BLOCK_INDEX_RE.match(bid)
    return int(m.group(1)) if m else 0


def is_valid_verbatim_id(id_: str) -> bool:
    """Check whether a string matches the verbatim ID format ("v_" + 4+ digits).

    Parameters
    ----------
    id_ : str
        String to validate.

    Returns
    -------
    bool
        True if the string is a valid verbatim ID.
    """
    return bool(re.match(r"^v_\d{4,}$", id_))
