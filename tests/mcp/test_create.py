"""Phase 10 MCP create/insert_blocks/remove_blocks/set_page 테스트."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import tempfile

import pytest

from udfp.server import create_server


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def tools():
    server = create_server()
    return {t.fn.__name__: t.fn for t in server._tool_manager._tools.values()}


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# ------------------------------------------------------------------
# create tool
# ------------------------------------------------------------------


class TestCreate:
    def test_create_simple_hwp(self, tools, tmp_dir):
        out = os.path.join(tmp_dir, "test.hwp")
        result = _run(tools["create"](
            blocks=[
                {"type": "heading", "level": 1, "text": "제목"},
                {"type": "paragraph", "text": "본문"},
            ],
            format="hwp",
            output_path=out,
        ))
        assert "Created:" in result
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0

    def test_create_docx(self, tools, tmp_dir):
        out = os.path.join(tmp_dir, "test.docx")
        result = _run(tools["create"](
            blocks=[{"type": "paragraph", "text": "DOCX test"}],
            format="docx",
            output_path=out,
        ))
        assert "Created:" in result
        assert os.path.exists(out)

    def test_create_hwpx(self, tools, tmp_dir):
        out = os.path.join(tmp_dir, "test.hwpx")
        result = _run(tools["create"](
            blocks=[{"type": "paragraph", "text": "HWPX test"}],
            format="hwpx",
            output_path=out,
        ))
        assert "Created:" in result
        assert os.path.exists(out)

    def test_create_md(self, tools, tmp_dir):
        out = os.path.join(tmp_dir, "test.md")
        result = _run(tools["create"](
            blocks=[
                {"type": "heading", "level": 1, "text": "Title"},
                {"type": "paragraph", "text": "Body"},
            ],
            format="md",
            output_path=out,
        ))
        assert "Created:" in result
        content = open(out).read()
        assert "# Title" in content
        assert "Body" in content

    def test_create_with_metadata(self, tools, tmp_dir):
        out = os.path.join(tmp_dir, "meta.hwp")
        result = _run(tools["create"](
            blocks=[{"type": "paragraph", "text": "content"}],
            format="hwp",
            output_path=out,
            metadata={"title": "My Doc", "author": "Author"},
        ))
        assert "Created:" in result
        data = json.loads(result.split("\n\n", 1)[1])
        assert data["metadata"]["title"] == "My Doc"

    def test_create_with_page(self, tools, tmp_dir):
        out = os.path.join(tmp_dir, "page.hwp")
        result = _run(tools["create"](
            blocks=[{"type": "paragraph", "text": "content"}],
            format="hwp",
            output_path=out,
            page={"paper": "B5", "margin_top": 15, "margin_left": 25},
        ))
        assert "Created:" in result

    def test_create_all_block_types(self, tools, tmp_dir):
        out = os.path.join(tmp_dir, "all_types.hwp")
        result = _run(tools["create"](
            blocks=[
                {"type": "heading", "level": 1, "text": "H1"},
                {"type": "heading", "level": 2, "text": "H2"},
                {"type": "paragraph", "text": "Normal paragraph"},
                {"type": "paragraph", "inlines": [
                    {"text": "bold ", "fmt": {"bold": True}},
                    {"text": "italic", "fmt": {"italic": True}},
                ]},
                {"type": "table", "rows": [
                    [{"text": "Header", "fmt": {"bold": True}}, "Value"],
                    ["Row1", "Data1"],
                ], "col_widths": [100, 80], "header_rows": 1},
                {"type": "list", "ordered": True, "items": ["First", "Second"]},
                {"type": "list", "ordered": False, "items": ["Bullet A", "Bullet B"]},
                {"type": "code", "code": "print('hello')", "language": "python"},
                {"type": "quote", "text": "A famous quote"},
                {"type": "equation", "latex": "E=mc^2"},
                {"type": "image", "src": "/tmp/nonexistent.png", "width": 200},
                {"type": "horizontal_rule"},
                {"type": "page_break"},
                {"type": "paragraph", "text": "Page 2"},
            ],
            format="hwp",
            output_path=out,
        ))
        assert "Created:" in result
        data = json.loads(result.split("\n\n", 1)[1])
        assert len(data["blocks"]) == 14

    def test_create_table_with_merge(self, tools, tmp_dir):
        out = os.path.join(tmp_dir, "merge.hwp")
        result = _run(tools["create"](
            blocks=[
                {"type": "table", "rows": [
                    [{"text": "Merged", "colspan": 2}, {"text": "C"}],
                    [{"text": "A"}, {"text": "B"}, {"text": "D"}],
                ]},
            ],
            format="hwp",
            output_path=out,
        ))
        assert "Created:" in result

    def test_create_default_output_path(self, tools):
        result = _run(tools["create"](
            blocks=[{"type": "paragraph", "text": "default path"}],
            format="hwp",
        ))
        assert "/tmp/udf_created.hwp" in result
        os.unlink("/tmp/udf_created.hwp")

    def test_create_returns_simplified_json(self, tools, tmp_dir):
        out = os.path.join(tmp_dir, "json_check.hwp")
        result = _run(tools["create"](
            blocks=[
                {"type": "paragraph", "text": "hello", "fmt": {"bold": True}},
            ],
            format="hwp",
            output_path=out,
        ))
        parts = result.split("\n\n", 1)
        assert len(parts) == 2
        data = json.loads(parts[1])
        assert data["source_format"] == "hwp"
        assert data["blocks"][0]["type"] == "paragraph"


# ------------------------------------------------------------------
# insert_blocks tool
# ------------------------------------------------------------------


class TestInsertBlocks:
    def _create_base(self, tools, tmp_dir) -> str:
        out = os.path.join(tmp_dir, "base.hwp")
        _run(tools["create"](
            blocks=[
                {"type": "heading", "level": 1, "text": "Title"},
                {"type": "paragraph", "text": "Original"},
            ],
            format="hwp",
            output_path=out,
        ))
        return out

    def test_insert_at_end(self, tools, tmp_dir):
        base = self._create_base(tools, tmp_dir)
        out = os.path.join(tmp_dir, "inserted.hwp")
        result = _run(tools["insert_blocks"](
            path=base,
            blocks=[{"type": "paragraph", "text": "Added at end"}],
            output_path=out,
        ))
        assert "Inserted 1 block(s):" in result
        data = json.loads(result.split("\n\n", 1)[1])
        assert len(data["blocks"]) == 3

    def test_insert_after_specific_block(self, tools, tmp_dir):
        base = self._create_base(tools, tmp_dir)
        read_result = _run(tools["read"](path=base))
        data = json.loads(read_result)
        first_id = data["blocks"][0]["id"]

        out = os.path.join(tmp_dir, "after.hwp")
        result = _run(tools["insert_blocks"](
            path=base,
            blocks=[{"type": "paragraph", "text": "Inserted after title"}],
            after=first_id,
            output_path=out,
        ))
        result_data = json.loads(result.split("\n\n", 1)[1])
        assert result_data["blocks"][1]["type"] == "paragraph"
        texts = [b.get("inlines", [{}])[0].get("text", "") if b.get("inlines") else "" for b in result_data["blocks"]]
        assert "Inserted after title" in texts

    def test_insert_multiple_blocks(self, tools, tmp_dir):
        base = self._create_base(tools, tmp_dir)
        out = os.path.join(tmp_dir, "multi.hwp")
        result = _run(tools["insert_blocks"](
            path=base,
            blocks=[
                {"type": "paragraph", "text": "New 1"},
                {"type": "paragraph", "text": "New 2"},
                {"type": "paragraph", "text": "New 3"},
            ],
            output_path=out,
        ))
        assert "Inserted 3 block(s):" in result
        data = json.loads(result.split("\n\n", 1)[1])
        assert len(data["blocks"]) == 5

    def test_insert_nonexistent_file(self, tools):
        result = _run(tools["insert_blocks"](
            path="/tmp/nonexistent_file.hwp",
            blocks=[{"type": "paragraph", "text": "fail"}],
        ))
        assert "Error" in result


# ------------------------------------------------------------------
# remove_blocks tool
# ------------------------------------------------------------------


class TestRemoveBlocks:
    def test_remove_single_block(self, tools, tmp_dir):
        base = os.path.join(tmp_dir, "base.hwp")
        _run(tools["create"](
            blocks=[
                {"type": "paragraph", "text": "Keep"},
                {"type": "paragraph", "text": "Remove"},
                {"type": "paragraph", "text": "Keep2"},
            ],
            format="hwp",
            output_path=base,
        ))
        read_data = json.loads(_run(tools["read"](path=base)))
        remove_id = read_data["blocks"][1]["id"]

        out = os.path.join(tmp_dir, "removed.hwp")
        result = _run(tools["remove_blocks"](
            path=base,
            block_ids=[remove_id],
            output_path=out,
        ))
        assert "Removed 1 block(s):" in result
        result_data = json.loads(result.split("\n\n", 1)[1])
        assert len(result_data["blocks"]) == 2

    def test_remove_multiple_blocks(self, tools, tmp_dir):
        base = os.path.join(tmp_dir, "base.hwp")
        _run(tools["create"](
            blocks=[
                {"type": "paragraph", "text": "A"},
                {"type": "paragraph", "text": "B"},
                {"type": "paragraph", "text": "C"},
            ],
            format="hwp",
            output_path=base,
        ))
        read_data = json.loads(_run(tools["read"](path=base)))
        ids = [b["id"] for b in read_data["blocks"][:2]]

        out = os.path.join(tmp_dir, "removed2.hwp")
        result = _run(tools["remove_blocks"](
            path=base,
            block_ids=ids,
            output_path=out,
        ))
        assert "Removed 2 block(s):" in result

    def test_remove_nonexistent_id(self, tools, tmp_dir):
        base = os.path.join(tmp_dir, "base.hwp")
        _run(tools["create"](
            blocks=[{"type": "paragraph", "text": "Keep"}],
            format="hwp",
            output_path=base,
        ))
        out = os.path.join(tmp_dir, "noop.hwp")
        result = _run(tools["remove_blocks"](
            path=base,
            block_ids=["nonexistent_id"],
            output_path=out,
        ))
        assert "Removed 0 block(s):" in result


# ------------------------------------------------------------------
# set_page tool
# ------------------------------------------------------------------


class TestSetPage:
    def test_set_paper_size(self, tools, tmp_dir):
        base = os.path.join(tmp_dir, "base.hwp")
        _run(tools["create"](
            blocks=[{"type": "paragraph", "text": "content"}],
            format="hwp",
            output_path=base,
        ))
        out = os.path.join(tmp_dir, "b5.hwp")
        result = _run(tools["set_page"](
            path=base,
            paper="B5",
            output_path=out,
        ))
        assert "Page layout updated:" in result
        assert os.path.exists(out)

    def test_set_margins(self, tools, tmp_dir):
        base = os.path.join(tmp_dir, "base.hwp")
        _run(tools["create"](
            blocks=[{"type": "paragraph", "text": "content"}],
            format="hwp",
            output_path=base,
        ))
        out = os.path.join(tmp_dir, "margins.hwp")
        result = _run(tools["set_page"](
            path=base,
            margin_top=10,
            margin_bottom=10,
            margin_left=15,
            margin_right=15,
            output_path=out,
        ))
        assert "Page layout updated:" in result

    def test_set_landscape(self, tools, tmp_dir):
        base = os.path.join(tmp_dir, "base.hwp")
        _run(tools["create"](
            blocks=[{"type": "paragraph", "text": "content"}],
            format="hwp",
            output_path=base,
        ))
        out = os.path.join(tmp_dir, "landscape.hwp")
        result = _run(tools["set_page"](
            path=base,
            orientation="landscape",
            output_path=out,
        ))
        assert "Page layout updated:" in result

    def test_set_columns(self, tools, tmp_dir):
        base = os.path.join(tmp_dir, "base.hwp")
        _run(tools["create"](
            blocks=[{"type": "paragraph", "text": "content"}],
            format="hwp",
            output_path=base,
        ))
        out = os.path.join(tmp_dir, "cols.hwp")
        result = _run(tools["set_page"](
            path=base,
            columns=2,
            gutter=15,
            output_path=out,
        ))
        assert "Page layout updated:" in result

    def test_set_page_nonexistent(self, tools):
        result = _run(tools["set_page"](
            path="/tmp/nonexistent.hwp",
            paper="A4",
        ))
        assert "Error" in result


# ------------------------------------------------------------------
# E2E: create → read → edit → render 파이프라인
# ------------------------------------------------------------------


class TestE2EPipeline:
    def test_create_edit_render(self, tools, tmp_dir):
        """create로 생성 → edit로 수정 → render로 변환."""
        hwp = os.path.join(tmp_dir, "e2e.hwp")
        _run(tools["create"](
            blocks=[
                {"type": "heading", "level": 1, "text": "Original Title"},
                {"type": "paragraph", "text": "Original content"},
            ],
            format="hwp",
            output_path=hwp,
        ))

        read_result = json.loads(_run(tools["read"](path=hwp)))
        heading_id = read_result["blocks"][0]["id"]

        edited_hwp = os.path.join(tmp_dir, "e2e_edited.hwp")
        _run(tools["edit"](
            path=hwp,
            edits=[{"block_id": heading_id, "inline_idx": 0, "text": "Modified Title"}],
            output_path=edited_hwp,
        ))

        md = os.path.join(tmp_dir, "e2e.md")
        _run(tools["render"](
            path=edited_hwp,
            format="md",
            output_path=md,
        ))
        content = open(md).read()
        assert "Modified Title" in content

    def test_create_insert_remove_flow(self, tools, tmp_dir):
        """create → insert → remove 전체 플로우."""
        hwp = os.path.join(tmp_dir, "flow.hwp")
        _run(tools["create"](
            blocks=[{"type": "paragraph", "text": "First"}],
            format="hwp",
            output_path=hwp,
        ))

        data_before = json.loads(_run(tools["read"](path=hwp)))
        n_before = len(data_before["blocks"])

        _run(tools["insert_blocks"](
            path=hwp,
            blocks=[
                {"type": "paragraph", "text": "Second"},
                {"type": "paragraph", "text": "Third"},
            ],
            output_path=hwp,
        ))

        data = json.loads(_run(tools["read"](path=hwp)))
        assert len(data["blocks"]) == n_before + 2

        second_id = data["blocks"][1]["id"]
        _run(tools["remove_blocks"](
            path=hwp,
            block_ids=[second_id],
            output_path=hwp,
        ))

        data2 = json.loads(_run(tools["read"](path=hwp)))
        assert len(data2["blocks"]) == n_before + 1
