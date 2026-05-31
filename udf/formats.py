"""UDF Format Registry — 포맷별 파서/렌더러 디스패치."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from udf.core.schema import UdfDocument


@dataclass(frozen=True)
class FormatSpec:
    """Immutable descriptor for a supported document format.

    Parameters
    ----------
    name : str
        Canonical format identifier (e.g. "hwp", "docx").
    extensions : list of str
        File extensions including the leading dot (e.g. [".hwp"]).
    mime_types : list of str, optional
        Associated MIME types.
    parser : str or None, optional
        Dotted import path to the parser function (e.g. "udf.parsers.hwp.parse.parse_hwp").
    renderer : str or None, optional
        Dotted import path to the renderer function.
    is_binary : bool, default True
        Whether the format is binary (as opposed to text-based).
    roundtrip : bool, default False
        Whether lossless same-format roundtrip (verbatim layer) is supported.
    schema_version : int, default 1
        Document Model schema version this format targets.
    """

    name: str
    extensions: list[str]
    mime_types: list[str] = field(default_factory=list)
    parser: str | None = None
    renderer: str | None = None
    is_binary: bool = True
    roundtrip: bool = False
    schema_version: int = 1


class FormatRegistry:
    """Central format dispatch system for parsers and renderers.

    Maintains a mapping of format names to ``FormatSpec`` instances and provides
    lookup by name or file extension, as well as lazy-import resolution of
    parser/renderer callables.
    """

    def __init__(self) -> None:
        self._formats: dict[str, FormatSpec] = {}
        self._ext_map: dict[str, str] = {}

    def register(self, spec: FormatSpec) -> None:
        """Register a format spec and index its extensions.

        Parameters
        ----------
        spec : FormatSpec
            Format descriptor to register.
        """
        self._formats[spec.name] = spec
        for ext in spec.extensions:
            self._ext_map[ext.lower()] = spec.name

    def get(self, name: str) -> FormatSpec | None:
        """Return the FormatSpec for *name*, or None if not registered."""
        return self._formats.get(name)

    def list(self) -> list[FormatSpec]:
        """Return all registered format specs."""
        return list(self._formats.values())

    def detect_by_ext(self, ext: str) -> str | None:
        """Detect format name from a file extension (case-insensitive).

        Parameters
        ----------
        ext : str
            File extension including the dot (e.g. ".hwp").

        Returns
        -------
        str or None
            Canonical format name, or None if unrecognized.
        """
        return self._ext_map.get(ext.lower())

    def can_parse(self, name: str) -> bool:
        """Return True if a parser is available for the given format."""
        spec = self._formats.get(name)
        return spec is not None and spec.parser is not None

    def can_render(self, name: str) -> bool:
        """Return True if a renderer is available for the given format."""
        spec = self._formats.get(name)
        return spec is not None and spec.renderer is not None

    def resolve_parser(self, name: str) -> Callable[..., "UdfDocument"]:
        """Lazily import and return the parser callable for *name*.

        Parameters
        ----------
        name : str
            Registered format name.

        Returns
        -------
        Callable[..., UdfDocument]
            The parser function.

        Raises
        ------
        ValueError
            If the format has no registered parser.
        """
        spec = self._formats.get(name)
        if spec is None or spec.parser is None:
            raise ValueError(f"파서 없음: {name!r}")
        module_path, func_name = spec.parser.rsplit(".", 1)
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, func_name)

    def resolve_renderer(self, name: str) -> Callable[..., Any]:
        """Lazily import and return the renderer callable for *name*.

        Parameters
        ----------
        name : str
            Registered format name.

        Returns
        -------
        Callable[..., Any]
            The renderer function.

        Raises
        ------
        ValueError
            If the format has no registered renderer.
        """
        spec = self._formats.get(name)
        if spec is None or spec.renderer is None:
            raise ValueError(f"렌더러 없음: {name!r}")
        module_path, func_name = spec.renderer.rsplit(".", 1)
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, func_name)


_registry = FormatRegistry()


def _init_registry() -> None:
    """Register all built-in format specs into the module-level registry."""
    _registry.register(FormatSpec(
        name="hwp",
        extensions=[".hwp"],
        mime_types=["application/x-hwp"],
        parser="udf.parsers.hwp.parse.parse_hwp",
        renderer="udf.renderers.hwp.render_hwp",
        is_binary=True,
        roundtrip=True,
        schema_version=2,
    ))
    _registry.register(FormatSpec(
        name="hwpx",
        extensions=[".hwpx"],
        mime_types=["application/hwp+zip"],
        parser="udf.parsers.hwpx.parse.parse_hwpx",
        renderer="udf.renderers.hwpx.render_hwpx",
        is_binary=True,
        roundtrip=True,
        schema_version=2,
    ))
    _registry.register(FormatSpec(
        name="docx",
        extensions=[".docx"],
        mime_types=["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
        parser="udf.parsers.docx.parse.parse_docx",
        renderer="udf.renderers.docx.render_docx",
        is_binary=True,
        roundtrip=True,
        schema_version=2,
    ))
    _registry.register(FormatSpec(
        name="pdf",
        extensions=[".pdf"],
        mime_types=["application/pdf"],
        parser="udf.parsers.pdf.parse.parse_pdf",
        renderer=None,
        is_binary=True,
        roundtrip=False,
        schema_version=2,
    ))
    _registry.register(FormatSpec(
        name="md",
        extensions=[".md"],
        mime_types=["text/markdown"],
        parser="udf.parsers.md.parse.parse_md",
        renderer="udf.renderers.md.render_md",
        is_binary=False,
        roundtrip=False,
        schema_version=2,
    ))
    _registry.register(FormatSpec(
        name="html",
        extensions=[".html", ".htm"],
        mime_types=["text/html"],
        parser="udf.parsers.html.parse.parse_html",
        renderer="udf.renderers.html.render_html",
        is_binary=False,
        roundtrip=False,
        schema_version=2,
    ))
    _registry.register(FormatSpec(
        name="xml",
        extensions=[".xml"],
        mime_types=["application/xml"],
        parser="udf.parsers.xml.parse.parse_xml",
        renderer=None,
        is_binary=False,
        roundtrip=False,
        schema_version=2,
    ))


_init_registry()


def get_registry() -> FormatRegistry:
    """Return the module-level singleton FormatRegistry instance.

    Returns
    -------
    FormatRegistry
        The pre-initialized global registry with all built-in formats.
    """
    return _registry
