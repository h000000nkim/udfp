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
| Template fill (`fill_template()`) | Yes |
| Text color/style override | Yes |
| Adding new blocks (image, paragraph) | No (From Scratch fallback) |
| Removing blocks | No |

### Example: Template Fill

```python
import udf

# HWP 양식에 {{이름}}, {{학번}} 등을 미리 입력해두고:
doc = udf.parse("template.hwp")
doc.fill_template({
    "이름": "김훈",
    "학번": "30217",
    "희망진로": "AI 엔지니어",
})

# Seed Patch auto-selected: text-only changes → 양식 100% 보존
doc.to("hwp", "filled.hwp")
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
    For form-filling and template workflows, use `fill_template()` or `replace_text()`. These keep all `verbatim_ref` intact, so Seed Patch stays active and the original layout is preserved bit-perfectly.

!!! warning "Adding images triggers From Scratch"
    Adding an `ImageBlock` creates a block without `verbatim_ref`, which triggers From Scratch mode. Use `tbl.freeze_labels()` or `layout_type="fixed"` to preserve table layouts in this case.

## Table Layout Preservation

When From Scratch generates a table, it auto-calculates cell sizes based on text content by default. To preserve original form layouts:

```python
doc = udf.parse("form.hwp")
tbl = doc.tables[0]

# Option 1: Default behavior — cell sizes are automatically preserved
# (layout_type=None defaults to freeze since 2026-06-05)

# Option 2: Selective freeze
tbl.freeze_labels(label_col=0)      # fix label column only
for row in tbl.rows:
    row.cells[1].fixed_width = True  # fix input column width, auto height

# Option 3: Explicit auto-sizing
tbl.layout_type = "auto"            # text-based size calculation
```
