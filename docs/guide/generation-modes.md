# Generation Modes

UDF has two modes for generating binary output files (HWP, HWPX, DOCX): **Seed Patch** and **From Scratch**.

## Seed Patch Mode

When an original container exists and no structural changes are detected, UDF uses Seed Patch. It preserves the original binary/ZIP and replaces only modified streams.

```
Original HWP ──▶ [Patch modified streams] ──▶ Output HWP
                  (text, metadata only)
```

**Advantages:**

- Bit-perfect preservation of unmodified regions
- Preserves format-specific features UDF doesn't model (macros, scripts, etc.)
- Fastest generation mode

**Supported operations:**

| Operation | Supported |
|-----------|:---------:|
| Text replacement in existing paragraphs | Yes |
| Text addition to empty paragraphs | Yes |
| Table cell text modification | Yes |
| Equation script replacement | Yes |
| Adding new blocks | No |
| Removing blocks | No |
| Format/style changes | No |

### Example

```python
import udf

doc = udf.parse("template.hwp")  # original container preserved
doc.replace_text("{{NAME}}", "Kim")
doc.replace_text("{{DATE}}", "2026-01-15")

# Seed Patch is auto-selected: original exists + text-only changes
udf.render(doc, "hwp", output_path="filled.hwp")
```

## From Scratch Mode

When blocks are added, removed, or restructured, UDF regenerates the entire output from the Document Model.

```
Document Model ──▶ [Build all streams] ──▶ Output HWP
```

**Advantages:**

- Supports all operations (add, remove, reorder blocks)
- Works without an original file

**Trade-offs:**

- Cannot preserve format features UDF doesn't model
- Slightly larger output (no byte-level reuse)

### Example

```python
from udf import DocumentBuilder

doc = (
    DocumentBuilder()
    .heading(1, "New Document")
    .paragraph("Created from scratch.")
    .build()
)

# From Scratch: no original container exists
udf.render(doc, "hwp", output_path="new.hwp")
```

## Automatic Mode Selection

UDF automatically picks the best mode. The decision logic:

```
Has original container?
├── No ──▶ From Scratch
└── Yes
    └── Any block without verbatim_ref?
        ├── Yes ──▶ From Scratch (structural change detected)
        └── No ──▶ Seed Patch
```

A block without `verbatim_ref` was programmatically created, which means the document structure has changed and Seed Patch cannot be used.

!!! tip "Keep Seed Patch active"
    For form-filling and template workflows, use only text-level operations (`replace_text`, `set_inline_text`). These keep all `verbatim_ref` intact, so Seed Patch stays active.

!!! warning "Avoid mixing modes"
    If you add a new block to a parsed document, ALL blocks will be regenerated via From Scratch — not just the new one. Plan your edits accordingly.
