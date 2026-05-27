# API Reference

The UDF Python API is organized into these layers:

| Module | Purpose |
|--------|---------|
| `udf` | Top-level functions: `parse`, `render`, `convert`, `detect`, `diff` |
| `udf.UdfDocument` | Central document manipulation class |
| `udf.DocumentBuilder` | Fluent API for programmatic document creation |
| `udf.schema` | Block, Inline, Format, and Metadata types |
| `udf.validation` | Structural integrity checks per format |

## Quick Reference

```python
import udf

# Parse
doc = udf.parse("file.hwp")

# Convert
udf.convert("input.hwp", "output.docx")

# Render
md = udf.render(doc, "md")
udf.render(doc, "hwp", output_path="out.hwp")

# Detect
info = udf.detect("file.hwp")

# Diff
report = udf.diff(doc_a, doc_b)

# Version
print(udf.__version__)
```

## Sections

- [Top-Level Functions](functions.md) — `parse`, `render`, `convert`, `detect`, `diff`
- [UdfDocument](document.md) — Document manipulation API
- [DocumentBuilder](builder.md) — Fluent document construction
- [Schema](schema.md) — Block types, Inline types, formatting, metadata
- [Validation](validation.md) — R-rules, HX-rules, D-rules
