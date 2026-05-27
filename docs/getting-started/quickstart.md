# Quick Start

## Parse a Document

```python
import udf

doc = udf.parse("report.hwp")
print(f"Format: {doc.source_format}")
print(f"Blocks: {len(doc.blocks)}")
```

Format is auto-detected from the file extension and magic bytes. You can also specify it explicitly:

```python
doc = udf.parse("report.hwp", fmt="hwp")
```

## Convert Between Formats

```python
import udf

# HWP to DOCX
udf.convert("input.hwp", "output.docx")

# PDF to Markdown
udf.convert("paper.pdf", "paper.md")

# HWP to HTML
udf.convert("document.hwp", "document.html")
```

## Edit a Document

### Find and Replace

```python
import udf

doc = udf.parse("template.hwp")
doc.replace_text("COMPANY_NAME", "Acme Corp")
doc.replace_text("DATE", "2026-01-15")
udf.render(doc, "hwp", output_path="filled.hwp")
```

### Programmatic Block Editing

```python
import udf
from udf.schema import ParagraphBlock, TextInline

doc = udf.parse("report.hwp")

# Access blocks
for block in doc.paragraphs:
    print(block.id, [i.text for i in block.inlines if hasattr(i, "text")])

# Modify inline text
doc.set_inline_text("b_0003", 0, "Updated text")
doc.set_inline_format("b_0003", 0, bold=True, font_size=14.0)

# Add a new block
new_para = ParagraphBlock(
    type="paragraph",
    id="new-1",
    inlines=[TextInline(type="text", text="Appended paragraph")],
)
doc.add_block(new_para)

udf.render(doc, "hwp", output_path="modified.hwp")
```

### Table Operations

```python
doc = udf.parse("table_doc.hwp")

# Read a cell
cell = doc.get_cell("table_0", row=0, col=1)

# Modify table structure
doc.add_table_row("table_0", at=2)
doc.merge_cells("table_0", r1=0, c1=0, r2=0, c2=1)
```

## Build a Document from Scratch

```python
from udf import DocumentBuilder

doc = (
    DocumentBuilder()
    .title("Monthly Report")
    .author("Hoon Kim")
    .heading(1, "Summary")
    .paragraph("This report covers Q1 results.", font_size=12)
    .heading(2, "Revenue")
    .table([
        ["Category", "Amount"],
        ["Product A", "1,200,000"],
        ["Product B", "850,000"],
    ])
    .heading(2, "Appendix")
    .image("chart.png", width=400)
    .build()
)

udf.render(doc, "hwp", output_path="report.hwp")
udf.render(doc, "docx", output_path="report.docx")
```

## Detect Format

```python
import udf

result = udf.detect("mystery_file.hwp")
print(result)
# {"format": "hwp", "source": "extension", "warnings": []}
```

## Compare Documents

```python
import udf

original = udf.parse("v1.hwp")
modified = udf.parse("v2.hwp")
report = udf.diff(original, modified)

print(f"Roundtrip safe: {report.is_roundtrip_safe}")
for loss in report.lossy_blocks:
    print(f"  {loss.block_id}: {loss.description}")
```

## Next Steps

- [Document Model](../guide/document-model.md) — Understand blocks, inlines, and the tree structure
- [Format Conversion](../guide/conversion.md) — Cross-format conversion details
- [Generation Modes](../guide/generation-modes.md) — Seed Patch vs From Scratch
- [API Reference](../api/index.md) — Complete API documentation
- [CLI](../cli.md) — Command-line usage
