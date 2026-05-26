"""MCP tool 통합 테스트 — read/edit/render."""

from __future__ import annotations

import asyncio
import json
import pathlib
import shutil

import pytest

from udfp.server import create_server
import udf

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"
HWP_DIR = FIXTURES / "hwp"
HWPX_DIR = FIXTURES / "hwpx"
PDF_DIR = FIXTURES / "pdf"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def mcp_server():
    return create_server()


def _get_tool_fn(server, name: str):
    for tool in server._tool_manager._tools.values():
        if tool.fn.__name__ == name:
            return tool.fn
    raise ValueError(f"Tool {name!r} not found")


# ------------------------------------------------------------------
# read tool
# ------------------------------------------------------------------

class TestRead:
    def test_read_hwp(self, mcp_server):
        fn = _get_tool_fn(mcp_server, "read")
        path = str(HWP_DIR / "f01_plain_text.hwp")
        result = _run(fn(path=path))
        data = json.loads(result)
        assert data["source_format"] == "hwp"
        assert len(data["blocks"]) > 0

    @pytest.mark.parametrize("fixture", [
        "f04_simple_table.hwp",
        "f09_heading_h1h2.hwp",
        "f10_inline_mixed.hwp",
    ])
    def test_read_hwp_fixtures(self, mcp_server, fixture):
        fn = _get_tool_fn(mcp_server, "read")
        path = str(HWP_DIR / fixture)
        if not pathlib.Path(path).exists():
            pytest.skip(f"{fixture} not found")
        result = _run(fn(path=path))
        data = json.loads(result)
        assert "blocks" in data

    def test_read_hwpx(self, mcp_server):
        hwpx_files = list(HWPX_DIR.glob("*.hwpx")) if HWPX_DIR.exists() else []
        if not hwpx_files:
            pytest.skip("no hwpx fixtures")
        fn = _get_tool_fn(mcp_server, "read")
        result = _run(fn(path=str(hwpx_files[0])))
        data = json.loads(result)
        assert data["source_format"] == "hwpx"

    def test_read_pdf(self, mcp_server):
        pdf_files = list(PDF_DIR.glob("*.pdf")) if PDF_DIR.exists() else []
        if not pdf_files:
            pytest.skip("no pdf fixtures")
        fn = _get_tool_fn(mcp_server, "read")
        result = _run(fn(path=str(pdf_files[0])))
        data = json.loads(result)
        assert data["source_format"] == "pdf"

    def test_read_nonexistent(self, mcp_server):
        fn = _get_tool_fn(mcp_server, "read")
        result = _run(fn(path="/nonexistent/file.hwp"))
        assert "Error" in result

    def test_read_table_grid_coords(self, mcp_server):
        path = str(HWP_DIR / "f04_simple_table.hwp")
        if not pathlib.Path(path).exists():
            pytest.skip("f04 not found")
        fn = _get_tool_fn(mcp_server, "read")
        result = _run(fn(path=path))
        data = json.loads(result)
        tables = [b for b in data["blocks"] if b["type"] == "table"]
        assert len(tables) > 0
        first_cell = tables[0]["rows"][0][0]
        assert "row" in first_cell
        assert "col" in first_cell


# ------------------------------------------------------------------
# edit tool
# ------------------------------------------------------------------

class TestEdit:
    def _copy_fixture(self, fixture_name: str, tmp_path: pathlib.Path) -> str:
        src = HWP_DIR / fixture_name
        dst = tmp_path / fixture_name
        shutil.copy2(src, dst)
        return str(dst)

    def test_edit_text_replacement(self, mcp_server, tmp_path):
        path = self._copy_fixture("f01_plain_text.hwp", tmp_path)
        fn_read = _get_tool_fn(mcp_server, "read")
        fn_edit = _get_tool_fn(mcp_server, "edit")

        before = json.loads(_run(fn_read(path=path)))
        para = next(b for b in before["blocks"] if b["type"] == "paragraph" and b.get("inlines"))
        block_id = para["id"]

        result = _run(fn_edit(
            path=path,
            edits=[{"block_id": block_id, "inline_idx": 0, "text": "REPLACED"}],
        ))
        after = json.loads(result)
        edited_para = next(b for b in after["blocks"] if b["id"] == block_id)
        assert edited_para["inlines"][0]["text"] == "REPLACED"

    def test_edit_preserves_other_inlines(self, mcp_server, tmp_path):
        path = self._copy_fixture("f10_inline_mixed.hwp", tmp_path)
        if not pathlib.Path(HWP_DIR / "f10_inline_mixed.hwp").exists():
            pytest.skip("f10 not found")
        fn_read = _get_tool_fn(mcp_server, "read")
        fn_edit = _get_tool_fn(mcp_server, "edit")

        before = json.loads(_run(fn_read(path=path)))
        para = None
        for b in before["blocks"]:
            if b["type"] == "paragraph" and len(b.get("inlines", [])) >= 2:
                para = b
                break
        if para is None:
            pytest.skip("no multi-inline paragraph found")

        block_id = para["id"]
        second_text = para["inlines"][1]["text"]

        _run(fn_edit(
            path=path,
            edits=[{"block_id": block_id, "inline_idx": 0, "text": "CHANGED"}],
        ))
        after = json.loads(_run(fn_read(path=path)))
        edited = next(b for b in after["blocks"] if b["id"] == block_id)
        assert edited["inlines"][0]["text"] == "CHANGED"
        assert edited["inlines"][1]["text"] == second_text

    def test_edit_format_change(self, mcp_server, tmp_path):
        path = self._copy_fixture("f01_plain_text.hwp", tmp_path)
        fn_read = _get_tool_fn(mcp_server, "read")
        fn_edit = _get_tool_fn(mcp_server, "edit")

        before = json.loads(_run(fn_read(path=path)))
        para = next(b for b in before["blocks"] if b["type"] == "paragraph" and b.get("inlines"))
        block_id = para["id"]

        result = _run(fn_edit(
            path=path,
            edits=[{"block_id": block_id, "inline_idx": 0, "fmt": {"bold": True, "size": 16.0}}],
        ))
        after = json.loads(result)
        edited = next(b for b in after["blocks"] if b["id"] == block_id)
        assert edited["inlines"][0]["fmt"]["bold"] is True
        assert edited["inlines"][0]["fmt"]["size"] == 16.0

    def test_edit_block_format(self, mcp_server, tmp_path):
        path = self._copy_fixture("f01_plain_text.hwp", tmp_path)
        fn_read = _get_tool_fn(mcp_server, "read")
        fn_edit = _get_tool_fn(mcp_server, "edit")

        before = json.loads(_run(fn_read(path=path)))
        para = next(b for b in before["blocks"] if b["type"] == "paragraph")
        block_id = para["id"]

        result = _run(fn_edit(
            path=path,
            edits=[{"block_id": block_id, "block_fmt": {"align": "center"}}],
        ))
        after = json.loads(result)
        edited = next(b for b in after["blocks"] if b["id"] == block_id)
        assert edited["fmt"]["align"] == "center"

    def test_edit_invalid_block_id(self, mcp_server, tmp_path):
        path = self._copy_fixture("f01_plain_text.hwp", tmp_path)
        fn_edit = _get_tool_fn(mcp_server, "edit")
        result = _run(fn_edit(
            path=path,
            edits=[{"block_id": "nonexistent_block", "inline_idx": 0, "text": "x"}],
        ))
        assert "Error" in result

    def test_edit_invalid_inline_idx(self, mcp_server, tmp_path):
        path = self._copy_fixture("f01_plain_text.hwp", tmp_path)
        fn_read = _get_tool_fn(mcp_server, "read")
        fn_edit = _get_tool_fn(mcp_server, "edit")

        before = json.loads(_run(fn_read(path=path)))
        para = next(b for b in before["blocks"] if b["type"] == "paragraph" and b.get("inlines"))
        block_id = para["id"]

        result = _run(fn_edit(
            path=path,
            edits=[{"block_id": block_id, "inline_idx": 999, "text": "x"}],
        ))
        assert "Error" in result

    def test_edit_custom_output_path(self, mcp_server, tmp_path):
        path = self._copy_fixture("f01_plain_text.hwp", tmp_path)
        out = str(tmp_path / "edited.hwp")
        fn_read = _get_tool_fn(mcp_server, "read")
        fn_edit = _get_tool_fn(mcp_server, "edit")

        before = json.loads(_run(fn_read(path=path)))
        para = next(b for b in before["blocks"] if b["type"] == "paragraph" and b.get("inlines"))

        _run(fn_edit(
            path=path,
            edits=[{"block_id": para["id"], "inline_idx": 0, "text": "OUT"}],
            output_path=out,
        ))
        assert pathlib.Path(out).exists()
        assert pathlib.Path(out).stat().st_size > 0

    def test_edit_new_text_in_empty_block(self, mcp_server, tmp_path):
        """inline_idx=null로 빈 블록에 텍스트 삽입."""
        path = self._copy_fixture("f01_plain_text.hwp", tmp_path)
        fn_read = _get_tool_fn(mcp_server, "read")
        fn_edit = _get_tool_fn(mcp_server, "edit")

        before = json.loads(_run(fn_read(path=path)))
        empty_para = None
        for b in before["blocks"]:
            if b["type"] == "paragraph" and not b.get("inlines"):
                empty_para = b
                break
        if empty_para is None:
            pytest.skip("no empty paragraph in fixture")

        result = _run(fn_edit(
            path=path,
            edits=[{"block_id": empty_para["id"], "inline_idx": None, "text": "INSERTED"}],
        ))
        after = json.loads(result)
        edited = next(b for b in after["blocks"] if b["id"] == empty_para["id"])
        assert any(i["text"] == "INSERTED" for i in edited.get("inlines", []))


# ------------------------------------------------------------------
# Deep search
# ------------------------------------------------------------------

class TestDeepSearch:
    def test_find_block_in_table(self):
        doc = udf.parse(str(HWP_DIR / "f04_simple_table.hwp"))
        tables = [b for b in doc.blocks if isinstance(b, udf.pipeline.document.TableBlock)]
        if not tables:
            pytest.skip("no tables")
        first_cell = tables[0].rows[0].cells[0]
        if not first_cell.content:
            pytest.skip("empty cell")
        inner_id = first_cell.content[0].id
        found = doc.get_block(inner_id)
        assert found is not None
        assert found.id == inner_id

    def test_find_nonexistent(self):
        doc = udf.parse(str(HWP_DIR / "f01_plain_text.hwp"))
        found = doc.get_block("nonexistent")
        assert found is None


# ------------------------------------------------------------------
# render tool
# ------------------------------------------------------------------

class TestRender:
    def test_render_hwp_to_md(self, mcp_server, tmp_path):
        path = str(HWP_DIR / "f01_plain_text.hwp")
        out = str(tmp_path / "output.md")
        fn = _get_tool_fn(mcp_server, "render")
        result = _run(fn(path=path, format="md", output_path=out))
        assert "Rendered:" in result
        assert pathlib.Path(out).exists()
        content = pathlib.Path(out).read_text(encoding="utf-8")
        assert len(content) > 0

    def test_render_hwp_to_html(self, mcp_server, tmp_path):
        path = str(HWP_DIR / "f01_plain_text.hwp")
        out = str(tmp_path / "output.html")
        fn = _get_tool_fn(mcp_server, "render")
        result = _run(fn(path=path, format="html", output_path=out))
        assert "Rendered:" in result
        assert pathlib.Path(out).exists()

    def test_render_default_output_path(self, mcp_server, tmp_path):
        src = HWP_DIR / "f01_plain_text.hwp"
        path = str(tmp_path / "test.hwp")
        shutil.copy2(src, path)
        fn = _get_tool_fn(mcp_server, "render")
        result = _run(fn(path=path, format="md"))
        expected_out = str(tmp_path / "test.md")
        assert expected_out in result
        assert pathlib.Path(expected_out).exists()

    def test_render_unsupported_format(self, mcp_server):
        path = str(HWP_DIR / "f01_plain_text.hwp")
        fn = _get_tool_fn(mcp_server, "render")
        result = _run(fn(path=path, format="xyz", output_path="/tmp/test.xyz"))
        assert "Error" in result

    def test_render_nonexistent(self, mcp_server):
        fn = _get_tool_fn(mcp_server, "render")
        result = _run(fn(path="/nonexistent.hwp", format="md"))
        assert "Error" in result


# ------------------------------------------------------------------
# E2E pipeline
# ------------------------------------------------------------------

class TestE2EPipeline:
    def test_read_edit_render(self, mcp_server, tmp_path):
        """Full pipeline: read → identify → edit → render to MD."""
        src = HWP_DIR / "f01_plain_text.hwp"
        hwp_path = str(tmp_path / "doc.hwp")
        shutil.copy2(src, hwp_path)

        fn_read = _get_tool_fn(mcp_server, "read")
        fn_edit = _get_tool_fn(mcp_server, "edit")
        fn_render = _get_tool_fn(mcp_server, "render")

        read_result = json.loads(_run(fn_read(path=hwp_path)))
        para = next(
            (b for b in read_result["blocks"]
             if b["type"] == "paragraph" and b.get("inlines")),
            None,
        )
        assert para is not None

        _run(fn_edit(
            path=hwp_path,
            edits=[{"block_id": para["id"], "inline_idx": 0, "text": "E2E_TEST"}],
        ))

        md_path = str(tmp_path / "output.md")
        _run(fn_render(path=hwp_path, format="md", output_path=md_path))

        md_content = pathlib.Path(md_path).read_text(encoding="utf-8")
        assert "E2E" in md_content and "TEST" in md_content

    def test_read_edit_same_format(self, mcp_server, tmp_path):
        """Edit HWP → save as HWP → read back."""
        src = HWP_DIR / "f01_plain_text.hwp"
        path = str(tmp_path / "doc.hwp")
        shutil.copy2(src, path)

        fn_read = _get_tool_fn(mcp_server, "read")
        fn_edit = _get_tool_fn(mcp_server, "edit")

        before = json.loads(_run(fn_read(path=path)))
        para = next(b for b in before["blocks"] if b["type"] == "paragraph" and b.get("inlines"))

        _run(fn_edit(
            path=path,
            edits=[{"block_id": para["id"], "inline_idx": 0, "text": "ROUNDTRIP"}],
        ))

        after = json.loads(_run(fn_read(path=path)))
        edited = next(b for b in after["blocks"] if b["id"] == para["id"])
        assert edited["inlines"][0]["text"] == "ROUNDTRIP"
