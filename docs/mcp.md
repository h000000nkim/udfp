# MCP Server

UDF includes a Model Context Protocol (MCP) server that enables AI assistants like Claude to read, edit, and generate documents.

## Setup

### Install

```bash
pip install udfp[mcp]
```

### Register with Claude

```bash
claude mcp add udfp -- python -m udfp
```

Or configure manually in Claude Desktop:

```json
{
  "mcpServers": {
    "udfp": {
      "command": "python",
      "args": ["-m", "udfp"]
    }
  }
}
```

## Tools

The MCP server exposes 8 tools:

### read

Parse a document and return its content as simplified JSON.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | File path to the document |

Returns a JSON representation with block IDs, types, and inline content, suitable for AI consumption.

### edit

Modify inline text or formatting by block ID and inline index.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | File path |
| `edits` | array | List of edit operations |
| `output_path` | string? | Output path (defaults to overwrite) |

Each edit operation specifies a `block_id`, `inline_idx`, and the changes (text, bold, italic, etc.).

### render

Convert a document to another format.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Source file path |
| `format` | string | Target format (hwp, docx, md, html, etc.) |
| `output_path` | string? | Output file path |

### create

Generate a new document from a JSON block specification.

| Parameter | Type | Description |
|-----------|------|-------------|
| `blocks` | array | Block definitions |
| `format` | string | Output format (default: "hwp") |
| `output_path` | string | Output file path |
| `page` | object? | Page settings (paper, margins, orientation) |
| `metadata` | object? | Document metadata (title, author) |

### insert_blocks

Add new blocks to an existing document.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | File path |
| `blocks` | array | Blocks to insert |

### remove_blocks

Remove blocks from a document by their IDs.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | File path |
| `block_ids` | array | Block IDs to remove |

### set_page

Adjust page layout settings.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | File path |
| `paper` | string? | Paper size (A4, Letter, etc.) |
| `orientation` | string? | portrait or landscape |
| `margins` | object? | Top, bottom, left, right margins |

### describe

Self-documentation tool. Returns detailed information about a topic.

| Parameter | Type | Description |
|-----------|------|-------------|
| `topic` | string | One of: overview, blocks, edit, create, fmt, workflow, api, metadata, loss |

## Example Workflow

A typical AI-assisted document workflow:

1. **Read** the document to understand its structure
2. **Edit** specific fields (fill in blanks, update values)
3. **Render** to the desired output format

```
User: "Fill in the template with company information"

AI: [calls read("template.hwp")]
    → Identifies empty fields at b_0005, b_0012, b_0018

AI: [calls edit("template.hwp", edits=[
      {"block_id": "b_0005", "inline_idx": 0, "text": "Acme Corp"},
      {"block_id": "b_0012", "inline_idx": 0, "text": "2026-01-15"},
      {"block_id": "b_0018", "inline_idx": 0, "text": "Seoul, Korea"},
    ], output_path="filled.hwp")]

AI: [calls render("filled.hwp", "docx", "filled.docx")]
```
