# Format Conversion

UDF supports both same-format round-trips and cross-format conversions.

## One-Shot Conversion

The simplest way to convert between formats:

```python
import udf

udf.convert("input.hwp", "output.docx")
udf.convert("paper.pdf", "paper.md")
udf.convert("document.hwp", "document.html")
```

Formats are auto-detected from file extensions. Override with explicit format parameters:

```python
udf.convert("input.hwp", "output.xml", input_fmt="hwp", output_fmt="docx")
```

## Two-Step Conversion

For more control, parse and render separately:

```python
import udf

# Step 1: Parse
doc = udf.parse("input.hwp")

# (optional) Inspect or modify the document
print(f"{len(doc.blocks)} blocks")
doc.replace_text("DRAFT", "FINAL")

# Step 2: Render
udf.render(doc, "docx", output_path="output.docx")
md_text = udf.render(doc, "md")  # text formats return a string
```

## Conversion Matrix

|  | → HWP | → HWPX | → DOCX | → MD | → HTML |
|--|:-----:|:------:|:------:|:----:|:------:|
| **HWP →** | Lossless | Full | Full | Full | Full |
| **HWPX →** | Full | Lossless | Full | Full | Full |
| **DOCX →** | Full | Full | Lossless | Full | Full |
| **PDF →** | — | — | — | Full | Full |
| **MD →** | Full | Full | Full | Text-level | Full |
| **HTML →** | Full | Full | Full | Full | Text-level |

**Lossless** = same-format round-trip via verbatim layer, no information loss.
**Text-level** = same-format round-trip preserves text content but not binary-level formatting.
**Full** = cross-format conversion with loss tracking.

## Loss Tracking

Every conversion carries a `LossReport` that documents what was preserved and what was lost:

```python
doc = udf.parse("complex.hwp")
udf.render(doc, "md", output_path="output.md")

report = doc.loss_report
if report:
    print(f"Total blocks: {report.total_blocks}")
    print(f"Lossless: {report.lossless_blocks}")
    print(f"Lossy: {len(report.lossy_blocks)}")

    for loss in report.lossy_blocks:
        print(f"  [{loss.loss_type}] {loss.block_id}: {loss.description}")
```

Loss categories:

| Category | Meaning |
|----------|---------|
| `FORMAT_LIMIT` | Target format cannot represent this feature (e.g., HWP equations in Markdown) |
| `USER_EDITED` | User intentionally changed this block |
| `UNINTENDED` | Unexpected loss — indicates a bug |

## Semantic Diff

Compare two documents to see what changed:

```python
original = udf.parse("v1.hwp")
modified = udf.parse("v2.hwp")

report = udf.diff(original, modified)
print(f"Roundtrip safe: {report.is_roundtrip_safe}")
```

## Best Practices

!!! tip "Use Seed Patch for minimal changes"
    When editing text in existing documents, use `replace_text()` or `set_inline_text()` to keep Seed Patch mode active. This preserves the original binary and only patches what changed.

!!! warning "PDF is parse-only"
    PDF rendering is not supported. Use PDF → MD or PDF → DOCX for editable output.

!!! info "Round-trip validation"
    After any conversion, validate with:
    ```python
    udf.convert("input.hwp", "output.hwp")
    original = udf.parse("input.hwp")
    roundtripped = udf.parse("output.hwp")
    report = udf.diff(original, roundtripped)
    assert report.is_roundtrip_safe
    ```
