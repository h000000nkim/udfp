"""UDF — Universal Document Format.

A Python library for lossless document conversion across heterogeneous
formats (HWP, HWPX, DOCX, PDF, Markdown, HTML, XML).  Any supported
document is parsed into a unified Document Model, then rendered back to
any target format.

Key design principles:

* Format-common features are normalised into a block tree.
* Format-specific features are preserved as ``unsupported`` metadata.
* Same-format round-trip (라운드트립) is guaranteed lossless via the
  verbatim layer.

Top-level API
-------------
parse      Parse a file into a UdfDocument.
render     Render a UdfDocument to a target format.
convert    One-shot parse-then-render convenience.
detect     Detect a file's format by extension / magic bytes.
diff       Compute a semantic diff between two UdfDocuments.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from udf.builder import DocumentBuilder
from udf.pipeline.document import UdfDocument

try:
    from importlib.metadata import version as _get_version
    __version__ = _get_version("udfp")
except Exception:
    __version__ = "0.0.0.dev"

if TYPE_CHECKING:
    from udf.core.loss import LossReport

__all__ = [
    "__version__",
    "UdfDocument",
    "DocumentBuilder",
    "parse",
    "render",
    "convert",
    "detect",
    "diff",
    "merge_diff",
]


def parse(path: str, *, fmt: str | None = None, **kwargs: object) -> UdfDocument:
    """Parse a document file into a UdfDocument.

    Parameters
    ----------
    path : str
        Path to the input file.
    fmt : str, optional
        Explicit format identifier (e.g. ``"hwp"``, ``"docx"``).
        If *None*, the format is auto-detected from extension / magic bytes.
    **kwargs
        Passed through to the format-specific parser.

    Returns
    -------
    UdfDocument
        The parsed document model.

    Raises
    ------
    ValueError
        If the format cannot be detected or is unsupported.
    """
    from udf.formats import get_registry
    from udf.parsers.detect import detect as _detect

    if fmt is None:
        fmt = _detect(path).format

    registry = get_registry()
    spec = registry.get(fmt)
    parser_fn = registry.resolve_parser(fmt)

    if spec and not spec.is_binary and fmt in ("md", "html"):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return parser_fn(content, **kwargs)

    return parser_fn(path, **kwargs)


def render(
    doc: UdfDocument,
    fmt: str,
    output_path: str | None = None,
    **kwargs: object,
) -> str | None:
    """Render a UdfDocument to the specified format.

    Parameters
    ----------
    doc : UdfDocument
        The document model to render.
    fmt : str
        Target format identifier (e.g. ``"md"``, ``"hwp"``, ``"docx"``).
    output_path : str, optional
        Destination file path for binary formats.
    **kwargs
        Passed through to the format-specific renderer.

    Returns
    -------
    str or None
        Text content for text formats (md, html); *None* for binary
        formats (hwp, docx, hwpx) which are written to *output_path*.
    """
    from udf.renderers import render as _render

    return _render(doc, fmt, output_path=output_path, **kwargs)


def convert(
    input_path: str,
    output_path: str,
    *,
    input_fmt: str | None = None,
    output_fmt: str | None = None,
    **kwargs: object,
) -> None:
    """Parse a file and render it to another format in one step.

    Parameters
    ----------
    input_path : str
        Source file path.
    output_path : str
        Destination file path.
    input_fmt : str, optional
        Source format override; auto-detected if *None*.
    output_fmt : str, optional
        Target format override; inferred from *output_path* extension if *None*.
    **kwargs
        Passed through to the renderer.

    Raises
    ------
    ValueError
        If the output format cannot be determined.
    """
    from pathlib import Path

    from udf.formats import get_registry

    doc = parse(input_path, fmt=input_fmt)

    if output_fmt is None:
        ext = Path(output_path).suffix.lower()
        registry = get_registry()
        output_fmt = registry.detect_by_ext(ext)
        if output_fmt is None:
            raise ValueError(f"출력 포맷을 감지할 수 없음: {output_path}")

    result = render(doc, output_fmt, output_path=output_path, **kwargs)

    if result is not None:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result)


def detect(path: str) -> dict[str, str]:
    """Detect the format of a document file.

    Uses file extension first, then falls back to magic-byte sniffing.

    Parameters
    ----------
    path : str
        Path to the file to inspect.

    Returns
    -------
    dict
        Keys: ``"format"`` (e.g. ``"hwp"``), ``"source"`` (detection
        method), ``"warnings"`` (any non-fatal issues).
    """
    from udf.parsers.detect import detect as _detect

    result = _detect(path)
    return {
        "format": result.format,
        "source": result.source,
        "warnings": result.warnings,
    }


def diff(
    a: UdfDocument,
    b: UdfDocument,
    **kwargs: object,
) -> "LossReport":
    """Compute a semantic diff between two UdfDocuments.

    Compares block-level content and metadata to identify meaningful
    differences, ignoring format-specific verbatim noise.

    Parameters
    ----------
    a : UdfDocument
        The reference (original) document.
    b : UdfDocument
        The document to compare against *a*.

    Returns
    -------
    LossReport
        Report detailing any semantic losses or differences.
    """
    from udf.core.loss import diff_documents

    return diff_documents(a, b, **kwargs)


def merge_diff(
    original: UdfDocument,
    edited: UdfDocument,
) -> "MergeDiffResult":  # noqa: F821
    """Diff edited document against original and apply changes.

    Compares an edited UdfDocument (typically parsed from user-edited
    Markdown) against the original, and returns a patched deep copy of
    the original with changes applied.  Verbatim layer and blocks not
    representable in Markdown are preserved from the original.

    Parameters
    ----------
    original : UdfDocument
        The original document (with verbatim layer).
    edited : UdfDocument
        The document parsed from edited Markdown.

    Returns
    -------
    MergeDiffResult
        Patched document, list of changes, and preserved block IDs.
    """
    from udf.merge_diff import merge_diff as _merge_diff

    return _merge_diff(original, edited)
