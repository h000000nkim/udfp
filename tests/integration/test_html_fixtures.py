"""Fixture-based integration tests for HTML renderer.

Parses real document files and renders to HTML, verifying:
- No exceptions
- Non-empty HTML output
- Text content preservation
- Expected HTML elements present
"""

from __future__ import annotations

import pathlib

import pytest

import udf
from udf.renderers.html import render_html

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"

HWP_FILES = sorted(FIXTURES.glob("hwp/*.hwp"))
HWPX_FILES = sorted(FIXTURES.glob("hwpx/*.hwpx"))
PDF_FILES = sorted(FIXTURES.glob("pdf/*.pdf"))
DOCX_FILES = sorted(FIXTURES.glob("docx/*.docx"))
MD_FILES = sorted(FIXTURES.glob("md/*.md"))

ALL_FILES = HWP_FILES + HWPX_FILES + PDF_FILES + DOCX_FILES + MD_FILES


def _file_id(p: pathlib.Path) -> str:
    return f"{p.parent.name}/{p.name}"


@pytest.mark.parametrize("fixture", ALL_FILES, ids=_file_id)
class TestFixtureRender:
    def test_renders_without_error(self, fixture):
        doc = udf.parse(str(fixture))
        html = render_html(doc)
        assert isinstance(html, str)
        assert len(html) > 500

    def test_html5_structure(self, fixture):
        doc = udf.parse(str(fixture))
        html = render_html(doc)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "<article>" in html or '<section class="page"' in html

    def test_text_preserved(self, fixture):
        doc = udf.parse(str(fixture))
        html = render_html(doc)
        words: list[str] = []
        for b in doc.blocks:
            tc = b.text_content().strip()
            if not tc:
                continue
            for w in tc.split():
                w = w.strip()
                if len(w) >= 2 and not any(c in w for c in "<>&"):
                    words.append(w)
        if not words:
            pytest.skip("no text content in fixture")
        sample = words[:50]
        preserved = sum(1 for w in sample if w in html)
        ratio = preserved / len(sample)
        assert ratio >= 0.3, f"only {preserved}/{len(sample)} words found in HTML"


@pytest.mark.parametrize("fixture", HWP_FILES, ids=lambda p: p.name)
class TestHwpSpecific:
    def test_embed_ids(self, fixture):
        doc = udf.parse(str(fixture))
        html = render_html(doc, embed_ids=True)
        assert "data-bid" in html

    def test_embed_images(self, fixture):
        doc = udf.parse(str(fixture))
        html = render_html(doc, embed_images=True)
        assert "<!DOCTYPE html>" in html


@pytest.mark.parametrize("fixture", HWP_FILES, ids=lambda p: p.name)
class TestToHtmlMethod:
    def test_to_html(self, fixture):
        doc = udf.parse(str(fixture))
        html = doc.to_html()
        assert isinstance(html, str)
        assert len(html) > 500

    def test_to_html_with_kwargs(self, fixture):
        doc = udf.parse(str(fixture))
        html = doc.to_html(embed_ids=True)
        assert "data-bid" in html
