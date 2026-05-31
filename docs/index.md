# UDF — Universal Document Format

Parse, transform, and render documents across **HWP, HWPX, DOCX, PDF, and Markdown** through a single unified Document Model.

---

## Why UDF?

Korean document workflows often involve HWP (한컴 한글) files that are incompatible with standard tools. UDF bridges this gap by providing a **universal intermediate representation** that enables lossless round-trip conversion between all major document formats.

```python
import udf

# HWP to DOCX in one line
udf.convert("report.hwp", "report.docx")

# Parse, edit, and render back
doc = udf.parse("template.hwp")
doc.replace_text("PLACEHOLDER", "Actual Value")
udf.render(doc, "hwp", output_path="filled.hwp")
```

## Key Features

- **Multi-format parsing** — HWP (binary), HWPX (OOXML-like ZIP), DOCX, PDF, Markdown, HTML, XML
- **Lossless round-trip** — Same-format conversions preserve content via verbatim layer
- **Cross-format conversion** — Convert between any supported format pair
- **Programmatic editing** — Add, modify, or remove blocks/inlines via `UdfDocument` API
- **Two generation modes** — Seed Patch (modify in-place) and From Scratch (full regeneration)
- **Structural validation** — R-rules (HWP), HX-rules (HWPX), D-rules (DOCX)
- **MCP server** — Claude/LLM integration for AI-powered document manipulation

## Supported Formats

| Format | Parse | Render | Round-trip | Notes |
|--------|:-----:|:------:|:----------:|-------|
| HWP | Full | Full | Lossless | Binary OLE (한컴 한글) |
| HWPX | Full | Full | Lossless | ZIP-based (한컴오피스 NEX) |
| DOCX | Full | Full | Lossless | Office Open XML |
| PDF | Full | — | Parse only | Text extraction via pdfminer |
| Markdown | Full | Full | Text-level | CommonMark-compatible |
| HTML | Full | Full | Text-level | HTML5 output |
| XML | Full | — | Parse only | Generic XML extraction |

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

## Quick Links

<div class="grid cards" markdown>

-   :material-download:{ .lg .middle } **Installation**

    ---

    Install UDF via pip in seconds

    [:octicons-arrow-right-24: Getting started](getting-started/installation.md)

-   :material-rocket-launch:{ .lg .middle } **Quick Start**

    ---

    Parse, convert, and edit documents

    [:octicons-arrow-right-24: Quick start](getting-started/quickstart.md)

-   :material-api:{ .lg .middle } **API Reference**

    ---

    Complete Python API documentation

    [:octicons-arrow-right-24: API reference](api/index.md)

-   :material-console:{ .lg .middle } **CLI**

    ---

    Command-line tools for batch processing

    [:octicons-arrow-right-24: CLI reference](cli.md)

</div>
