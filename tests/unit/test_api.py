"""통합 API + DocumentBuilder + UdfDocument 편의 메서드 테스트."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from udf import DocumentBuilder, UdfDocument


# ---------------------------------------------------------------------------
# FormatRegistry
# ---------------------------------------------------------------------------


class TestFormatRegistry:
    def test_registry_lists_all_formats(self):
        from udf.formats import get_registry
        r = get_registry()
        names = {s.name for s in r.list()}
        assert {"hwp", "hwpx", "docx", "pdf", "md", "html", "xml"} <= names

    def test_detect_by_ext(self):
        from udf.formats import get_registry
        r = get_registry()
        assert r.detect_by_ext(".hwp") == "hwp"
        assert r.detect_by_ext(".PDF") == "pdf"
        assert r.detect_by_ext(".unknown") is None

    def test_can_parse_and_render(self):
        from udf.formats import get_registry
        r = get_registry()
        assert r.can_parse("hwp")
        assert r.can_render("md")
        assert r.can_render("pdf")

    def test_resolve_parser(self):
        from udf.formats import get_registry
        r = get_registry()
        fn = r.resolve_parser("hwp")
        assert callable(fn)
        assert fn.__name__ == "parse_hwp"

    def test_resolve_renderer_error(self):
        from udf.formats import get_registry
        r = get_registry()
        with pytest.raises(ValueError):
            r.resolve_renderer("xml")


# ---------------------------------------------------------------------------
# UdfDocument 리네이밍 + 하위호환
# ---------------------------------------------------------------------------


class TestUdfDocumentNaming:
    def test_udf_field(self):
        doc = UdfDocument(source_format="test", blocks=[])
        assert doc.udf == "1.0"

    def test_kwargs_construction(self):
        doc = UdfDocument(source_format="test", blocks=[])
        assert doc.source_format == "test"
        assert len(doc.blocks) == 0


# ---------------------------------------------------------------------------
# UdfDocument auto-parsing
# ---------------------------------------------------------------------------


_HWP_FIXTURE = "tests/fixtures/hwp/f01_plain_text.hwp"


@pytest.mark.skipif(not os.path.exists(_HWP_FIXTURE), reason="fixture not found")
class TestAutoParseInit:
    def test_string_path(self):
        doc = UdfDocument(_HWP_FIXTURE)
        assert doc.source_format == "hwp"
        assert len(doc.blocks) > 0

    def test_pathlib_path(self):
        from pathlib import Path
        doc = UdfDocument(Path(_HWP_FIXTURE))
        assert doc.source_format == "hwp"

    def test_factory_empty(self):
        doc = UdfDocument.empty()
        assert doc.source_format == "udf"
        assert len(doc.blocks) == 0

    def test_factory_from_dict(self):
        orig = UdfDocument(source_format="test", blocks=[])
        d = orig.model_dump()
        doc = UdfDocument.from_dict(d)
        assert doc.source_format == "test"

    def test_factory_from_json(self):
        orig = UdfDocument(source_format="test", blocks=[])
        j = orig.model_dump_json()
        doc = UdfDocument.from_json(j)
        assert doc.source_format == "test"


# ---------------------------------------------------------------------------
# Top-level API
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not os.path.exists(_HWP_FIXTURE), reason="fixture not found")
class TestTopLevelAPI:
    def test_parse(self):
        import udf
        doc = udf.parse(_HWP_FIXTURE)
        assert isinstance(doc, UdfDocument)
        assert doc.source_format == "hwp"

    def test_render_md(self):
        import udf
        doc = udf.parse(_HWP_FIXTURE)
        md = udf.render(doc, "md")
        assert isinstance(md, str)
        assert len(md) > 0

    def test_render_binary_requires_output_path(self):
        import udf
        doc = udf.parse(_HWP_FIXTURE)
        with pytest.raises(ValueError, match="output_path"):
            udf.render(doc, "hwp")

    def test_detect(self):
        import udf
        info = udf.detect(_HWP_FIXTURE)
        assert info["format"] == "hwp"

    def test_convert(self):
        import udf
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            out = f.name
        try:
            udf.convert(_HWP_FIXTURE, out)
            with open(out, encoding="utf-8") as f:
                content = f.read()
            assert len(content) > 0
        finally:
            os.unlink(out)


# ---------------------------------------------------------------------------
# Editing API
# ---------------------------------------------------------------------------


class TestEditingAPI:
    def _make_doc(self):
        return (
            DocumentBuilder()
            .heading(1, "제목")
            .paragraph("첫 번째 단락입니다.")
            .paragraph("두 번째 단락입니다.")
            .build()
        )

    def test_replace_text(self):
        doc = self._make_doc()
        count = doc.replace_text("단락", "문단")
        assert count == 2
        texts = [
            "".join(i.text for i in b.inlines if hasattr(i, "text"))
            for b in doc.paragraphs
        ]
        assert all("문단" in t for t in texts)
        assert all("단락" not in t for t in texts)

    def test_replace_text_heading(self):
        doc = self._make_doc()
        count = doc.replace_text("제목", "타이틀")
        assert count == 1
        assert doc.headings[0].text == "타이틀"

    def test_find_text(self):
        doc = self._make_doc()
        matches = doc.find_text("단락")
        assert len(matches) == 2
        assert all(m["text"] == "단락" for m in matches)

    def test_get_block(self):
        doc = self._make_doc()
        bid = doc.blocks[0].id
        found = doc.get_block(bid)
        assert found is not None
        assert found.id == bid

    def test_get_block_not_found(self):
        doc = self._make_doc()
        assert doc.get_block("nonexistent") is None

    def test_find_blocks(self):
        doc = self._make_doc()
        headings = doc.find_blocks("heading")
        assert len(headings) == 1
        paras = doc.find_blocks("paragraph")
        assert len(paras) == 2

    def test_add_block(self):
        from udf.core.schema import ParagraphBlock, TextInline
        doc = self._make_doc()
        new_block = ParagraphBlock(
            type="paragraph", id="b_new",
            inlines=[TextInline(text="새 단락")],
        )
        doc.add_block(new_block, after=doc.blocks[0].id)
        assert doc.blocks[1].id == "b_new"

    def test_remove_block(self):
        doc = self._make_doc()
        bid = doc.blocks[1].id
        removed = doc.remove_block(bid)
        assert removed is not None
        assert removed.id == bid
        assert doc.get_block(bid) is None

    def test_move_block(self):
        doc = self._make_doc()
        last_id = doc.blocks[-1].id
        first_id = doc.blocks[0].id
        doc.move_block(last_id, after=first_id)
        assert doc.blocks[1].id == last_id

    def test_convenience_properties(self):
        doc = self._make_doc()
        assert len(doc.headings) == 1
        assert len(doc.paragraphs) == 2
        assert len(doc.tables) == 0
        assert len(doc.images) == 0


# ---------------------------------------------------------------------------
# Rendering convenience
# ---------------------------------------------------------------------------


class TestRenderingConvenience:
    def test_to_md(self):
        doc = DocumentBuilder().paragraph("hello").build()
        md = doc.to("md")
        assert "hello" in md

    def test_to_json(self):
        doc = DocumentBuilder().paragraph("hello").build()
        j = doc.to_json()
        parsed = json.loads(j)
        assert parsed["source_format"] == "udf"
        assert len(parsed["document"]["blocks"]) == 1

    def test_to_dict(self):
        doc = DocumentBuilder().paragraph("hello").build()
        d = doc.to_dict()
        assert isinstance(d, dict)
        assert d["source_format"] == "udf"

    def test_save_and_load(self):
        doc = DocumentBuilder().heading(1, "Title").paragraph("Body").build()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            doc.save(path)
            loaded = UdfDocument.from_json(open(path, encoding="utf-8").read())
            assert loaded.source_format == "udf"
            assert len(loaded.blocks) == 2
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# DocumentBuilder
# ---------------------------------------------------------------------------


class TestDocumentBuilder:
    def test_empty_build(self):
        doc = DocumentBuilder().build()
        assert isinstance(doc, UdfDocument)
        assert len(doc.blocks) == 0

    def test_metadata(self):
        doc = DocumentBuilder().title("T").author("A").build()
        assert doc.metadata.title == "T"
        assert doc.metadata.author == "A"

    def test_heading(self):
        doc = DocumentBuilder().heading(1, "Title").build()
        assert len(doc.blocks) == 1
        assert doc.blocks[0].type == "heading"
        assert doc.blocks[0].level == 1
        assert doc.blocks[0].text == "Title"

    def test_heading_level_clamped(self):
        doc = DocumentBuilder().heading(10, "Deep").build()
        assert doc.blocks[0].level == 6

    def test_paragraph(self):
        doc = DocumentBuilder().paragraph("Hello", bold=True).build()
        assert doc.blocks[0].type == "paragraph"
        assert doc.blocks[0].inlines[0].text == "Hello"
        assert doc.blocks[0].inlines[0].bold is True

    def test_paragraph_alignment(self):
        doc = DocumentBuilder().paragraph("Centered", alignment="center").build()
        assert doc.blocks[0].format.alignment == "center"

    def test_table(self):
        doc = DocumentBuilder().table([["A", "B"], ["C", "D"]]).build()
        tbl = doc.blocks[0]
        assert tbl.type == "table"
        assert len(tbl.rows) == 2
        assert len(tbl.rows[0].cells) == 2

    def test_list_ordered(self):
        doc = DocumentBuilder().list(["a", "b"], ordered=True).build()
        lb = doc.blocks[0]
        assert lb.type == "list"
        assert lb.ordered is True
        assert len(lb.items) == 2

    def test_list_unordered(self):
        doc = DocumentBuilder().list(["x", "y"]).build()
        assert doc.blocks[0].ordered is False

    def test_code(self):
        doc = DocumentBuilder().code("x = 1", language="python").build()
        assert doc.blocks[0].type == "code"
        assert doc.blocks[0].code == "x = 1"
        assert doc.blocks[0].language == "python"

    def test_quote(self):
        doc = DocumentBuilder().quote("인용").build()
        assert doc.blocks[0].type == "quote"

    def test_equation(self):
        doc = DocumentBuilder().equation("E=mc^2").build()
        assert doc.blocks[0].type == "equation"
        assert doc.blocks[0].latex == "E=mc^2"

    def test_image(self):
        doc = DocumentBuilder().image("pic.png", alt="Photo").build()
        assert doc.blocks[0].type == "image"
        assert doc.blocks[0].src == "pic.png"
        assert doc.blocks[0].alt == "Photo"

    def test_horizontal_rule(self):
        doc = DocumentBuilder().horizontal_rule().build()
        assert doc.blocks[0].type == "horizontal_rule"

    def test_page_break(self):
        doc = DocumentBuilder().page_break().build()
        assert doc.blocks[0].type == "page_break"

    def test_custom_block(self):
        from udf.core.schema import ParagraphBlock, TextInline
        custom = ParagraphBlock(
            type="paragraph", id="custom_1",
            inlines=[TextInline(text="custom")],
        )
        doc = DocumentBuilder().block(custom).build()
        assert doc.blocks[0].id == "custom_1"

    def test_chaining_produces_correct_order(self):
        doc = (
            DocumentBuilder()
            .heading(1, "H1")
            .paragraph("P1")
            .table([["A"]])
            .paragraph("P2")
            .build()
        )
        types = [b.type for b in doc.blocks]
        assert types == ["heading", "paragraph", "table", "paragraph"]

    def test_unique_ids(self):
        doc = (
            DocumentBuilder()
            .paragraph("a")
            .paragraph("b")
            .paragraph("c")
            .build()
        )
        ids = [b.id for b in doc.blocks]
        assert len(ids) == len(set(ids))

    def test_build_then_render(self):
        doc = (
            DocumentBuilder()
            .heading(1, "Title")
            .paragraph("Body text")
            .build()
        )
        md = doc.to("md")
        assert "# Title" in md
        assert "Body text" in md

    def test_build_then_edit(self):
        doc = (
            DocumentBuilder()
            .paragraph("old text")
            .build()
        )
        doc.replace_text("old", "new")
        assert doc.paragraphs[0].inlines[0].text == "new text"

    # ------------------------------------------------------------------
    # Phase 15h: 새 Builder 메서드
    # ------------------------------------------------------------------

    def test_field(self):
        doc = DocumentBuilder().field("clickhere", value="입력하세요").build()
        b = doc.blocks[0]
        assert b.type == "field"
        assert b.field_type == "clickhere"
        assert b.value == "입력하세요"

    def test_field_with_options(self):
        doc = DocumentBuilder().field(
            "dropdown", options=["A", "B", "C"], default_value="A",
        ).build()
        b = doc.blocks[0]
        assert b.options == ["A", "B", "C"]
        assert b.default_value == "A"

    def test_text_box(self):
        from udf.core.schema import ParagraphBlock, TextInline
        inner = ParagraphBlock(
            type="paragraph", id="inner_1",
            inlines=[TextInline(text="박스 내부")],
        )
        doc = DocumentBuilder().text_box(inner, width=200, height=100).build()
        b = doc.blocks[0]
        assert b.type == "text_box"
        assert b.width == 200
        assert b.height == 100
        assert len(b.content) == 1
        assert b.content[0].inlines[0].text == "박스 내부"

    def test_text_box_empty(self):
        doc = DocumentBuilder().text_box().build()
        assert doc.blocks[0].type == "text_box"
        assert len(doc.blocks[0].content) == 0

    def test_footnote(self):
        doc = (
            DocumentBuilder()
            .paragraph("본문 텍스트")
            .footnote("각주 내용")
            .build()
        )
        assert len(doc.blocks) == 2
        para = doc.blocks[0]
        fn = doc.blocks[1]
        assert fn.type == "footnote"
        assert fn.content[0].inlines[0].text == "각주 내용"
        # FootnoteRefInline이 이전 단락에 삽입됨
        ref = para.inlines[-1]
        assert ref.type == "footnote_ref"
        assert ref.ref_id == fn.id

    def test_footnote_no_previous_block(self):
        doc = DocumentBuilder().footnote("독립 각주").build()
        assert len(doc.blocks) == 1
        assert doc.blocks[0].type == "footnote"

    def test_bookmark(self):
        doc = DocumentBuilder().bookmark("section-1").build()
        b = doc.blocks[0]
        assert b.type == "bookmark"
        assert b.name == "section-1"

    def test_link(self):
        doc = DocumentBuilder().link("구글", "https://google.com").build()
        b = doc.blocks[0]
        assert b.type == "paragraph"
        assert b.inlines[0].type == "link"
        assert b.inlines[0].text == "구글"
        assert b.inlines[0].url == "https://google.com"

    def test_new_methods_chaining(self):
        doc = (
            DocumentBuilder()
            .heading(1, "제목")
            .paragraph("본문")
            .footnote("각주")
            .field("clickhere", value="입력")
            .bookmark("bk1")
            .link("링크", "https://example.com")
            .build()
        )
        types = [b.type for b in doc.blocks]
        assert types == ["heading", "paragraph", "footnote", "field", "bookmark", "paragraph"]
