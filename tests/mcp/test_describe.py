"""MCP describe tool tests."""

from __future__ import annotations

import asyncio

import pytest

from udfp.server import create_server, _DESCRIBE_TOPICS


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def describe_fn():
    server = create_server()
    for tool in server._tool_manager._tools.values():
        if tool.fn.__name__ == "describe":
            return tool.fn
    raise ValueError("describe tool not found")


class TestDescribe:
    @pytest.mark.parametrize("topic", list(_DESCRIBE_TOPICS.keys()))
    def test_valid_topics(self, describe_fn, topic):
        result = _run(describe_fn(topic=topic))
        assert len(result) > 100
        assert result.startswith("#")

    def test_unknown_topic(self, describe_fn):
        result = _run(describe_fn(topic="nonexistent"))
        assert "Unknown topic" in result
        assert "overview" in result

    def test_default_topic(self, describe_fn):
        result = _run(describe_fn())
        assert "UDF Document Model" in result

    def test_overview_has_quick_start(self, describe_fn):
        result = _run(describe_fn(topic="overview"))
        assert "Quick Start" in result
        assert "read(" in result
        assert "edit(" in result

    def test_blocks_lists_types(self, describe_fn):
        result = _run(describe_fn(topic="blocks"))
        assert "ParagraphBlock" in result
        assert "TableBlock" in result
        assert "HeadingBlock" in result

    def test_edit_has_patterns(self, describe_fn):
        result = _run(describe_fn(topic="edit"))
        assert "block_id" in result
        assert "inline_idx" in result
        assert "Pattern" in result

    def test_fmt_has_alias_table(self, describe_fn):
        result = _run(describe_fn(topic="fmt"))
        assert "bold" in result
        assert "font_size" in result
        assert "sp_before" in result
        assert "align" in result

    def test_workflow_has_examples(self, describe_fn):
        result = _run(describe_fn(topic="workflow"))
        assert "read(" in result
        assert "render(" in result
        assert "create(" in result

    def test_topic_case_insensitive(self, describe_fn):
        result = _run(describe_fn(topic="OVERVIEW"))
        assert "UDF Document Model" in result

    def test_topic_whitespace_trimmed(self, describe_fn):
        result = _run(describe_fn(topic="  fmt  "))
        assert "Format Key Aliases" in result


class TestErrorTips:
    """Verify error messages include guidance tips."""

    @pytest.fixture
    def tools(self):
        server = create_server()
        return {t.fn.__name__: t.fn for t in server._tool_manager._tools.values()}

    def test_read_error_has_tip(self, tools):
        result = _run(tools["read"](path="/nonexistent.hwp"))
        assert "Error" in result
        assert "File not found" in result

    def test_edit_error_has_tip(self, tools):
        result = _run(tools["edit"](
            path="/nonexistent.hwp",
            edits=[{"block_id": "x", "inline_idx": 0, "text": "y"}],
        ))
        assert "Error" in result
        assert "File not found" in result

    def test_render_error_has_tip(self, tools):
        result = _run(tools["render"](
            path="/nonexistent.hwp",
            format="md",
        ))
        assert "Error" in result
        assert "File not found" in result

    def test_remove_error_has_tip(self, tools):
        result = _run(tools["remove_blocks"](
            path="/nonexistent.hwp",
            block_ids=["x"],
        ))
        assert "Error" in result
        assert "File not found" in result

    def test_insert_error_has_tip(self, tools):
        result = _run(tools["insert_blocks"](
            path="/nonexistent.hwp",
            blocks=[{"type": "paragraph", "text": "x"}],
        ))
        assert "Error" in result
        assert "File not found" in result

    def test_set_page_error_has_tip(self, tools):
        result = _run(tools["set_page"](
            path="/nonexistent.hwp",
            paper="A4",
        ))
        assert "Error" in result
        assert "File not found" in result
