[한국어](./README.ko.md) | English

# udfp — Universal Document Format Protocol

Parse, transform, and render HWP/HWPX/DOCX/PDF/MD documents through a unified Document Model.

**UDF** (Universal Document Format) is the format — a unified document model that normalizes heterogeneous file formats into a common block tree. **UDFP** (Universal Document Format Protocol) is the protocol layer — an MCP server that lets AI agents read, edit, and generate documents through UDF.

`pip install udfp` installs both:

- **`udf`** — Core library. Parsers, renderers, Document Model, validation, CLI.
- **`udfp`** — MCP server. Exposes `udf` to Claude and other LLM agents via the [Model Context Protocol](https://modelcontextprotocol.io/).

```text
pip install udfp        →  import udf       (library)
pip install udfp[mcp]   →  udfp             (MCP server)
```

## Features

- **Multi-format parsing** — HWP (binary), HWPX (OOXML-like ZIP), DOCX, PDF, Markdown, HTML, XML
- **Lossless round-trip** — HWP/HWPX/DOCX same-format conversions preserve content via verbatim layer
- **Cross-format conversion** — Convert between supported format pairs (e.g., HWP → DOCX, PDF → MD)
- **Programmatic editing** — Add, modify, or remove blocks/inlines via `UdfDocument` API
- **Two generation modes** — Seed Patch (modify in-place) and From Scratch (full regeneration)
- **Structural validation** — R-rules for HWP (R1–R4), HX-rules for HWPX (HX1–HX4), D-rules for DOCX (D1–D3) — all implemented
- **MCP server** — Claude/LLM integration for reading, editing, and generating documents

## Installation

```bash
pip install udfp
```

With MCP server:

```bash
pip install udfp[mcp]
```

For development:

```bash
pip install udfp[dev]
```

## `udf` — Core Library

### Parse a document

```python
import udf

doc = udf.parse("report.hwp")
print(f"{len(doc.blocks)} blocks parsed")
```

### Convert between formats

```python
import udf

udf.convert("input.hwp", "output.docx")
udf.convert("paper.pdf", "paper.md")
```

### Programmatic editing

```python
import udf
from udf.schema.blocks import ParagraphBlock
from udf.schema.inlines import TextInline

doc = udf.parse("template.hwp")

doc.replace_text("PLACEHOLDER", "Actual Value")

new_block = ParagraphBlock(
    type="paragraph",
    id="new-1",
    inlines=[TextInline(type="text", text="New content")],
)
doc.add_block(new_block)

udf.render(doc, "hwp", output_path="filled.hwp")
```

### CLI

```bash
udf convert input.hwp -o output.docx
udf inspect document.hwp
udf validate document.hwp
udf diff original.hwp modified.hwp
```

## `udfp` — MCP Server

The MCP server lets LLMs read, edit, and generate documents through tool calls.

### Start the server

```bash
udfp                                          # stdio (default)
udfp --transport streamable-http --port 8000  # HTTP
```

### Available tools

| Tool | Description |
| ---- | ----------- |
| `read(path)` | Parse a document into simplified JSON with block IDs |
| `edit(path, edits)` | Modify text/formatting at specific block+inline positions |
| `render(path, format)` | Convert a document to another format |
| `create(blocks, format)` | Build a new document from a block array |
| `insert_blocks(path, blocks)` | Add blocks to an existing document |
| `remove_blocks(path, block_ids)` | Delete blocks by ID |
| `set_page(path, ...)` | Change page layout (paper size, margins, columns) |
| `export_md(path)` | Export document as editable Markdown with block IDs |
| `import_md(path, edited_md)` | Apply edited Markdown back, preserving original formatting |
| `describe(topic)` | Get schema documentation (start with `describe('overview')`) |

### Claude Desktop config

```json
{
  "mcpServers": {
    "udfp": {
      "command": "udfp"
    }
  }
}
```

## Document Model

All formats are normalized into a common block tree:

| Block Type | Description |
| ---------- | ----------- |
| `ParagraphBlock` | Text with inline formatting |
| `HeadingBlock` | Heading levels 1–6 |
| `TableBlock` | Rows, cells, merged spans |
| `ImageBlock` | Embedded or referenced images |
| `ListBlock` | Ordered/unordered lists |
| `EquationBlock` | Mathematical equations |
| `CodeBlock` | Source code blocks |
| `QuoteBlock` | Block quotations |
| `PageBreakBlock` | Explicit page breaks |
| `HorizontalRuleBlock` | Horizontal rules |
| `DrawingBlock` | Vector shapes |
| `TextBoxBlock` | Floating text containers |
| `FootnoteBlock` / `EndnoteBlock` | Notes |
| `HeaderBlock` / `FooterBlock` | Page header/footer content |
| `FieldBlock` | Form fields, hyperlinks, bookmarks |
| `BookmarkBlock` | Named bookmarks |
| `CommentBlock` | Review comments |
| `ChartBlock` | Embedded charts |
| `TextArtBlock` | Decorative text (WordArt) |
| `UnknownBlock` | Unrecognized format-specific content |

## Generation Modes

### Seed Patch (default when original exists)

Preserves the original binary/ZIP, replacing only modified streams. Guarantees bit-perfect preservation of unmodified regions.

**Best for:** Form filling, text replacement, content updates without structural changes.

### From Scratch (automatic fallback)

Regenerates the entire output file from the Document Model. Required when blocks are added, removed, or restructured.

**Automatic detection:** If any block lacks a `verbatim_ref` (i.e., was programmatically added), the renderer automatically falls back to From Scratch mode.

## Supported Formats

| Format | Parse | Render | Same-format Round-trip |
| ------ | ----- | ------ | ---------------------- |
| HWP | Full | Full (Seed Patch + From Scratch) | Lossless (verbatim) |
| HWPX | Full | Full (Seed Patch + From Scratch) | Lossless (verbatim) |
| DOCX | Full | Full (Seed Patch + From Scratch) | Lossless (verbatim) |
| PDF | Full | — | Parse only |
| Markdown | Full | Full | Text-level |
| HTML | Full | Full | Text-level |
| XML | Full | — | Parse only |

### Cross-format Conversion Matrix

| From \ To | HWP | HWPX | DOCX | MD | HTML |
| --------- | --- | ---- | ---- | -- | ---- |
| **HWP** | Lossless | Semantic | Semantic | Text-level | Text-level |
| **HWPX** | Semantic | Lossless | Semantic | Text-level | Text-level |
| **DOCX** | Semantic | Semantic | Lossless | Text-level | Text-level |
| **PDF** | — | — | — | Text-level | Text-level |
| **MD** | From Scratch | — | — | — | Full |
| **HTML** | From Scratch | — | — | Full | — |

- **Lossless**: Verbatim layer preserves all binary content (Seed Patch mode)
- **Semantic**: Block structure and text preserved; format-specific styling may differ (From Scratch mode)
- **Text-level**: Text content preserved; formatting, page layout, images lost
- **From Scratch**: Generates new binary from Document Model; requires original for best results

## Known Limitations

**From Scratch mode** (used for cross-format and structural edits):

- `DrawingBlock`, `ChartBlock`, `TextArtBlock` cannot be regenerated without the original file — reported as `FORMAT_LIMIT` loss
- Complex table structures (merged cells, nested tables) may not fully survive HWPX/DOCX → HWP conversion

**Validation rules**:

- HWP: R1–R4 structural rules + I1–I3 integrity checks — fully implemented with auto-fixers
- HWPX: HX1–HX4 structural rules — fully implemented
- DOCX: D1–D3 structural rules — fully implemented
- PDF: format-specific rules planned (not needed until PDF rendering is added)

**Text-level formats** (MD, HTML):

- Formatting (fonts, colors, margins), images, and page layout are not preserved
- Useful for text extraction and content editing, not visual fidelity

## Architecture

```text
Input File ──▶ Parser ──▶ UdfDocument ──▶ Renderer ──▶ Output File
                              │
                              ▼
                     Document Model (blocks/inlines)
                              +
                     Verbatim Layer (binary preservation)
                              +
                     Loss Report (what was dropped)
```

## Development

```bash
pytest                        # all tests
pytest tests/roundtrip/       # round-trip tests
pytest tests/validation/      # R-rule validation
ruff check . && ruff format . # lint + format
mypy udf/                     # type check
```

## License

MIT
