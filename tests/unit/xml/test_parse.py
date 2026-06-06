"""XML → UDFP 파서 단위 테스트."""

from __future__ import annotations

import os

import pytest

from udf.parsers.xml.parse import parse_xml, _detect_profile
from udf.core.schema import (
    CodeBlock,
    EquationBlock,
    FootnoteBlock,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
)


_FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "fixtures", "xml")

pytestmark = pytest.mark.skipif(
    not os.path.isdir(_FIXTURES), reason="XML fixtures not available"
)


def _fixture(name: str) -> str:
    return os.path.join(_FIXTURES, name)


# ── Profile detection ──


class TestProfileDetection:
    def test_docbook_detected(self):
        from lxml import etree
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        tree = etree.parse(_fixture("docbook_sample.xml"), parser)
        assert _detect_profile(tree.getroot()) == "docbook"

    def test_generic_detected(self):
        from lxml import etree
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        tree = etree.parse(_fixture("generic_sample.xml"), parser)
        assert _detect_profile(tree.getroot()) == "generic"


# ── DocBook parsing ──


class TestDocBook:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.doc = parse_xml(_fixture("docbook_sample.xml"))

    def test_source_format(self):
        assert self.doc.source_format == "xml"

    def test_metadata_title(self):
        assert self.doc.metadata.title == "Sample DocBook Article"

    def test_metadata_author(self):
        assert self.doc.metadata.author == "John Doe"

    def test_checksum_present(self):
        assert self.doc.conversion_trace is not None
        assert len(self.doc.conversion_trace.checksum) == 64

    def test_has_headings(self):
        headings = [b for b in self.doc.blocks if isinstance(b, HeadingBlock)]
        assert len(headings) >= 5
        assert headings[0].text == "Introduction"

    def test_heading_levels(self):
        headings = [b for b in self.doc.blocks if isinstance(b, HeadingBlock)]
        for h in headings:
            assert 1 <= h.level <= 6

    def test_has_paragraphs(self):
        paras = [b for b in self.doc.blocks if isinstance(b, ParagraphBlock)]
        assert len(paras) >= 3

    def test_emphasis_inlines(self):
        paras = [b for b in self.doc.blocks if isinstance(b, ParagraphBlock)]
        first_para = paras[0]
        texts = [i.text for i in first_para.inlines if hasattr(i, "text")]
        combined = "".join(texts)
        assert "simple" in combined
        assert "bold" in combined

    def test_link_inline(self):
        from udf.core.schema import LinkInline
        paras = [b for b in self.doc.blocks if isinstance(b, ParagraphBlock)]
        first_para = paras[0]
        links = [i for i in first_para.inlines if isinstance(i, LinkInline)]
        assert len(links) == 1
        assert links[0].url == "https://example.com"

    def test_code_blocks(self):
        codes = [b for b in self.doc.blocks if isinstance(b, CodeBlock)]
        assert len(codes) == 2
        assert codes[0].language == "python"
        assert "hello" in codes[0].code.lower()
        assert codes[1].language is None

    def test_lists(self):
        lists = [b for b in self.doc.blocks if isinstance(b, ListBlock)]
        assert len(lists) >= 3
        unordered = [ln for ln in lists if not ln.ordered]
        ordered = [ln for ln in lists if ln.ordered]
        assert len(unordered) >= 1
        assert len(ordered) >= 1

    def test_table(self):
        tables = [b for b in self.doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) >= 1
        tbl = tables[0]
        assert len(tbl.rows) >= 2
        assert len(tbl.rows[0].cells) >= 2

    def test_table_colspan(self):
        tables = [b for b in self.doc.blocks if isinstance(b, TableBlock)]
        tbl = tables[0]
        last_row = tbl.rows[-1]
        assert any(c.col_span == 2 for c in last_row.cells)

    def test_image(self):
        images = [b for b in self.doc.blocks if isinstance(b, ImageBlock)]
        assert len(images) >= 1
        assert images[0].src == "images/sample.png"

    def test_image_caption(self):
        images = [b for b in self.doc.blocks if isinstance(b, ImageBlock)]
        assert images[0].caption is not None
        assert len(images[0].caption) > 0

    def test_blockquote(self):
        quotes = [b for b in self.doc.blocks if isinstance(b, QuoteBlock)]
        assert len(quotes) >= 1
        assert len(quotes[0].content) >= 1

    def test_equation(self):
        eqs = [b for b in self.doc.blocks if isinstance(b, EquationBlock)]
        assert len(eqs) >= 1
        assert eqs[0].latex is not None
        assert "mc" in eqs[0].latex

    def test_footnote_inline_skipped(self):
        """DocBook footnotes are inline children — they don't become top-level blocks."""
        footnotes = [b for b in self.doc.blocks if isinstance(b, FootnoteBlock)]
        assert len(footnotes) == 0

    def test_variable_list(self):
        lists = [b for b in self.doc.blocks if isinstance(b, ListBlock)]
        var_lists = [ln for ln in lists if not ln.ordered and any(
            any(getattr(i, "bold", False) for i in item.inlines)
            for item in ln.items
        )]
        assert len(var_lists) >= 1

    def test_all_blocks_have_ids(self):
        for b in self.doc.blocks:
            assert b.id is not None
            assert b.id.startswith("b_")


# ── Generic parsing ──


class TestGeneric:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.doc = parse_xml(_fixture("generic_sample.xml"))

    def test_source_format(self):
        assert self.doc.source_format == "xml"

    def test_has_headings(self):
        headings = [b for b in self.doc.blocks if isinstance(b, HeadingBlock)]
        titles = {h.text for h in headings}
        assert "Main Heading" in titles
        assert "Sub Heading" in titles

    def test_heading_levels(self):
        headings = [b for b in self.doc.blocks if isinstance(b, HeadingBlock)]
        levels = {h.text: h.level for h in headings}
        assert levels.get("Main Heading") == 1
        assert levels.get("Sub Heading") == 2
        assert levels.get("Generic Document") == 1

    def test_has_paragraphs(self):
        paras = [b for b in self.doc.blocks if isinstance(b, ParagraphBlock)]
        texts = [" ".join(i.text for i in p.inlines if hasattr(i, "text")) for p in paras]
        assert any("simple paragraph" in t for t in texts)

    def test_code_block(self):
        codes = [b for b in self.doc.blocks if isinstance(b, CodeBlock)]
        assert len(codes) >= 1
        assert codes[0].language == "javascript"

    def test_lists(self):
        lists = [b for b in self.doc.blocks if isinstance(b, ListBlock)]
        assert len(lists) >= 2
        unordered = [ln for ln in lists if not ln.ordered]
        ordered = [ln for ln in lists if ln.ordered]
        assert len(unordered) >= 1
        assert len(ordered) >= 1

    def test_table(self):
        tables = [b for b in self.doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) >= 1
        tbl = tables[0]
        assert len(tbl.rows) >= 2

    def test_image(self):
        images = [b for b in self.doc.blocks if isinstance(b, ImageBlock)]
        assert len(images) >= 1
        assert images[0].src == "photo.jpg"
        assert images[0].width == 640.0

    def test_link_inline(self):
        from udf.core.schema import LinkInline
        paras = [b for b in self.doc.blocks if isinstance(b, ParagraphBlock)]
        all_links = []
        for p in paras:
            all_links.extend(i for i in p.inlines if isinstance(i, LinkInline))
        assert len(all_links) >= 1
        assert all_links[0].url == "https://example.com"

    def test_unknown_element_as_paragraph(self):
        """Elements with text but unknown tag names become ParagraphBlocks."""
        paras = [b for b in self.doc.blocks if isinstance(b, ParagraphBlock)]
        texts = [" ".join(i.text for i in p.inlines if hasattr(i, "text")) for p in paras]
        assert any("Unknown content" in t for t in texts)

    def test_empty_unknown_becomes_unknown_block(self):
        """An unknown element with no text content becomes UnknownBlock."""
        from lxml import etree
        import itertools
        from udf.parsers.xml.generic import parse_generic
        from udf.schema import UnknownBlock as V2UnknownBlock
        root = etree.fromstring("<root><mystery-empty/></root>")
        blocks = parse_generic(root, itertools.count(1))
        unknowns = [b for b in blocks if isinstance(b, V2UnknownBlock)]
        assert len(unknowns) == 1
        assert "mystery-empty" in unknowns[0].raw_bytes


# ── Security ──


class TestSecurity:
    def test_xxe_blocked(self):
        doc = parse_xml(_fixture("xxe_attack.xml"))
        all_text = ""
        for b in doc.blocks:
            if isinstance(b, ParagraphBlock):
                all_text += " ".join(
                    i.text for i in b.inlines if hasattr(i, "text")
                )
        assert "root:" not in all_text


# ── Format detection ──


class TestDetect:
    def test_xml_extension_detected(self):
        from udf.parsers.detect import detect
        result = detect(_fixture("docbook_sample.xml"))
        assert result.format == "xml"
