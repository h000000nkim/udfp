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
