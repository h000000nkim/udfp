"""UDF 렌더러 — UdfDocument를 각 포맷으로 변환."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from udf.core.schema import UdfDocument


def render(doc: UdfDocument, fmt: str, output_path: str | None = None, **kwargs: object) -> str | None:
    """Dispatch a UdfDocument to the appropriate format-specific renderer.

    Parameters
    ----------
    doc : UdfDocument
        The document model to render.
    fmt : str
        Target format identifier (e.g. ``"hwp"``, ``"docx"``, ``"md"``).
    output_path : str or None
        Required for binary formats (hwp, hwpx, docx). Ignored for text
        formats (md, html) which return their output as a string.
    **kwargs
        Passed through to the underlying renderer function.

    Returns
    -------
    str or None
        For text formats, the rendered string. For binary formats, None
        (output is written to ``output_path``).

    Raises
    ------
    ValueError
        If the format is unsupported or ``output_path`` is missing for a
        binary format.
    """
    from udf.formats import get_registry

    fmt = fmt.lower().strip().lstrip(".")
    registry = get_registry()
    spec = registry.get(fmt)

    if spec is None or spec.renderer is None:
        raise ValueError(f"지원하지 않는 포맷: {fmt!r}")

    renderer = registry.resolve_renderer(fmt)

    if spec.is_binary:
        if not output_path:
            raise ValueError(f"{fmt.upper()} 렌더링에는 output_path가 필요합니다.")
        renderer(doc, output_path, **kwargs)
        return None
    else:
        if output_path and fmt in ("md", "markdown"):
            kwargs["output_path"] = output_path
        return renderer(doc, **kwargs)  # type: ignore[return-value]
