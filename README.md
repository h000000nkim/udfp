# UDF — Universal Document Format

Parse, transform, and render documents across HWP, HWPX, DOCX, PDF, and Markdown through a single unified **Document Model**.

## Features

- **Multi-format parsing** — HWP (binary), HWPX (OOXML-like ZIP), DOCX, PDF, Markdown, HTML, XML
- **Lossless round-trip** — Same-format conversions preserve content via verbatim layer
- **Cross-format conversion** — Convert between any supported format pair (e.g., HWP to DOCX)
- **Programmatic editing** — Add, modify, or remove blocks/inlines via `UdfDocument` API
- **Two generation modes** — Seed Patch (modify in-place) and From Scratch (full regeneration)
- **Structural validation** — R-rules (HWP), HX-rules (HWPX), D-rules (DOCX), P-rules (PDF)
- **MCP server** — Claude/LLM integration for document manipulation

## Installation

```bash
pip install udfp
```

For development:

```bash
pip install udfp[dev]
```

For MCP server support:

```bash
pip install udfp[mcp]
```

## Quick Start

### Parse a document

```python
import udf

doc = udf.parse("report.hwp")
print(f"{len(doc.blocks)} blocks parsed")
```

### Convert between formats

```python
import udf

# HWP to DOCX
udf.convert("input.hwp", "output.docx")

# PDF to Markdown
udf.convert("paper.pdf", "paper.md")
```

### Programmatic editing

```python
import udf
from udf.core.schema import ParagraphBlock, TextInline

doc = udf.parse("template.hwp")

# Find and replace text
doc.replace_text("PLACEHOLDER", "Actual Value")

# Add a new paragraph
new_block = ParagraphBlock(
    type="paragraph",
    id="new-1",
    inlines=[TextInline(type="text", text="New content")],
)
doc.add_block(new_block)

# Render to file (auto-selects From Scratch when structure changes)
udf.render(doc, "hwp", output_path="filled.hwp")
```

### CLI

```bash
# Convert
udf convert input.hwp -o output.docx

# Inspect document structure
udf inspect document.hwp

# Validate HWP structure (R-rules)
udf validate document.hwp

# Semantic diff
udf diff original.hwp modified.hwp
```

## Document Model

UDF normalizes all formats into a common block tree:

| Block Type | Description |
|-----------|-------------|
| `ParagraphBlock` | Text with inline formatting |
| `HeadingBlock` | Heading levels 1-6 |
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
| `FootnoteBlock` | Footnote content |
| `EndnoteBlock` | Endnote content |
| `HeaderBlock` | Page header content |
| `FooterBlock` | Page footer content |
| `TOCBlock` | Table of contents |

## Generation Modes

### Seed Patch (default when original exists)

Preserves the original binary/ZIP, replacing only modified streams. Guarantees bit-perfect preservation of unmodified regions.

**Best for:** Form filling, text replacement, content updates without structural changes.

### From Scratch (automatic fallback)

Regenerates the entire output file from the Document Model. Required when blocks are added, removed, or restructured.

**Automatic detection:** If any block lacks a `verbatim_ref` (i.e., was programmatically added), the renderer automatically falls back to From Scratch mode.

## Supported Formats

| Format | Parse | Render | Round-trip |
|--------|-------|--------|-----------|
| HWP | Full | Full | Lossless |
| HWPX | Full | Full | Lossless |
| DOCX | Full | Full | Lossless |
| PDF | Full | - | Parse only |
| Markdown | Full | Full | Lossless |
| HTML | Full | Full | Lossless |
| XML | Full | - | Parse only |

## Architecture

```
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
# Run all tests
pytest

# Round-trip tests only
pytest tests/roundtrip/

# Validation tests
pytest tests/validation/

# Lint + format
ruff check . && ruff format .

# Type check
mypy udf/
```

## License

MIT
