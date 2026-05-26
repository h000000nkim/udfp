"""XML to UdfDocument conversion entry point."""

from __future__ import annotations

import hashlib
import itertools
from datetime import datetime, timezone

from lxml import etree

from udf.schema import DocumentMetadata, DocumentSchema
from udf.pipeline import UdfDocument
from udf.pipeline.container import ConversionTrace

from .docbook import parse_docbook
from .generic import parse_generic

_DOCBOOK_NS = "http://docbook.org/ns/docbook"


def parse_xml(path: str) -> UdfDocument:
    """Parse an XML file into a UdfDocument.

    Auto-detects the XML profile (DocBook vs. generic) and dispatches
    to the appropriate sub-parser.

    Parameters
    ----------
    path : str
        Filesystem path to the XML file.

    Returns
    -------
    UdfDocument
        Parsed document model with conversion trace metadata.
    """
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    tree = etree.parse(path, parser)
    root = tree.getroot()

    with open(path, "rb") as f:
        checksum = hashlib.sha256(f.read()).hexdigest()

    counter = itertools.count(1)
    profile = _detect_profile(root)

    if profile == "docbook":
        blocks = parse_docbook(root, counter)
        metadata = _extract_docbook_metadata(root)
    else:
        blocks = parse_generic(root, counter)
        metadata = DocumentMetadata()

    return UdfDocument(
        source_format="xml",
        document=DocumentSchema(
            metadata=metadata,
            blocks=blocks,
        ),
        conversion_trace=ConversionTrace(
            parsed_at=datetime.now(timezone.utc).isoformat(),
            parser_version="0.1.0",
            checksum=checksum,
        ),
    )


def _detect_profile(root: etree._Element) -> str:
    """Determine XML profile from the root element's namespace."""
    ns = root.nsmap.get(None, "")
    if ns == _DOCBOOK_NS:
        return "docbook"
    tag = root.tag
    if tag.startswith(f"{{{_DOCBOOK_NS}}}"):
        return "docbook"
    return "generic"


def _extract_docbook_metadata(root: etree._Element) -> DocumentMetadata:
    """Extract title and author from a DocBook info element."""
    ns = f"{{{_DOCBOOK_NS}}}"
    title = None
    author = None

    info = root.find(f"{ns}info")
    if info is not None:
        title_el = info.find(f"{ns}title")
        if title_el is not None and title_el.text:
            title = title_el.text.strip()
        author_el = info.find(f"{ns}author")
        if author_el is not None:
            parts = []
            for name_tag in ("firstname", "surname", "othername"):
                el = author_el.find(f"{ns}personname/{ns}{name_tag}")
                if el is not None and el.text:
                    parts.append(el.text.strip())
            if parts:
                author = " ".join(parts)

    if title is None:
        title_el = root.find(f"{ns}title")
        if title_el is not None and title_el.text:
            title = title_el.text.strip()

    return DocumentMetadata(title=title, author=author)
