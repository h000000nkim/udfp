# Document Model

UDF normalizes all document formats into a common **block tree**. This page explains the structure.

## Overview

Every document parsed by UDF becomes a `UdfDocument` containing:

```
UdfDocument
├── document: DocumentSchema
│   ├── metadata: DocumentMetadata
│   ├── blocks: list[Block]         ← the content tree
│   └── page_boundaries: list[PageBoundary]
├── verbatim: VerbatimLayer         ← binary preservation for round-trip
├── original_container              ← seed for Seed Patch mode
├── loss_report: LossReport         ← what was lost in conversion
└── extensions: dict[str, FormatExtension]
```

## Block Types

Blocks are the fundamental units of document content. Each block has a `type`, a unique `id`, and type-specific fields.

### Structural Blocks

| Block | Description | Key Fields |
|-------|-------------|------------|
| `ParagraphBlock` | Text with inline formatting | `inlines` |
| `HeadingBlock` | Heading levels 1-6 | `level`, `inlines` |
| `ListBlock` | Ordered/unordered lists | `items`, `ordered` |
| `TableBlock` | Rows, cells, merged spans | `rows`, `col_widths` |

### Content Blocks

| Block | Description | Key Fields |
|-------|-------------|------------|
| `ImageBlock` | Embedded or referenced images | `src`, `width`, `height` |
| `CodeBlock` | Source code | `code`, `language` |
| `EquationBlock` | Mathematical equations | `script` (HWP) or `latex` |
| `QuoteBlock` | Block quotations | `inlines` |

### Layout Blocks

| Block | Description |
|-------|-------------|
| `PageBreakBlock` | Explicit page break |
| `HorizontalRuleBlock` | Horizontal rule |
| `TextBoxBlock` | Floating text container |
| `DrawingBlock` | Vector shapes (GSO) |

### Document Parts

| Block | Description |
|-------|-------------|
| `HeaderBlock` | Page header content |
| `FooterBlock` | Page footer content |
| `FootnoteBlock` | Footnote content |
| `EndnoteBlock` | Endnote content |

### Special Blocks

| Block | Description |
|-------|-------------|
| `BookmarkBlock` | Named anchor |
| `CommentBlock` | Annotation |
| `FieldBlock` | Dynamic field (date, page number, etc.) |
| `ChartBlock` | Embedded chart |
| `TextArtBlock` | Decorative text (WordArt) |
| `UnknownBlock` | Unrecognized content (preserved as-is) |

## Inline Types

Inlines represent runs of content within a block (typically paragraphs and headings).

| Inline | Description | Key Fields |
|--------|-------------|------------|
| `TextInline` | Plain text run | `text`, `bold`, `italic`, `font_name`, `font_size` |
| `LinkInline` | Hyperlink | `text`, `url` |
| `ImageInline` | Inline image | `src`, `width`, `height` |
| `FootnoteRefInline` | Footnote reference | `note_id` |
| `EndnoteRefInline` | Endnote reference | `note_id` |
| `EquationInline` | Inline equation | `script` |
| `RubyInline` | Ruby annotation (furigana) | `base_text`, `ruby_text` |
| `CodeInline` | Inline code | `code` |

## Block Format

Any block can carry a `BlockFormat` with styling properties:

```python
from udf.schema import BlockFormat

fmt = BlockFormat(
    alignment="center",
    space_before=12.0,    # points
    space_after=6.0,
    line_spacing=1.5,
    font_name="Malgun Gothic",
    font_size=11.0,
    bold=True,
)
```

## Metadata

```python
from udf.schema import DocumentMetadata

metadata = DocumentMetadata(
    title="Report Title",
    author="Author Name",
    subject="Monthly Review",
    keywords=["report", "Q1"],
    created="2026-01-15T09:00:00",
    modified="2026-01-20T14:30:00",
)
```

## Unit Conversion

UDF provides converters between format-specific units:

```python
from udf.schema import hwpunit_to_pt, emu_to_pt, twip_to_pt, mm_to_pt

# HWP uses HWPUNIT (100 = 1pt)
pt = hwpunit_to_pt(1200)  # 12.0pt

# DOCX uses EMU (914400 = 1in) and half-points
pt = emu_to_pt(914400)    # 72.0pt
pt = twip_to_pt(240)      # 12.0pt

# Metric
pt = mm_to_pt(25.4)       # 72.0pt
```

## Tree Traversal

Blocks form a tree. Tables contain rows, rows contain cells, cells contain blocks:

```python
doc = udf.parse("complex.hwp")

# Deep search — finds blocks at any nesting depth
all_paragraphs = doc.find_blocks("paragraph")
all_tables = doc.find_blocks("table")

# Or use convenience properties
for heading in doc.headings:
    print(f"H{heading.level}: {heading.inlines[0].text}")

for table in doc.tables:
    for row in table.rows:
        for cell in row.cells:
            print(f"Cell ({cell.row_span}x{cell.col_span}): {len(cell.blocks)} blocks")
```

## Format Extensions

Format-specific properties that don't map to the universal model are preserved in extensions:

```python
doc = udf.parse("report.hwp")

if "hwp" in doc.extensions:
    hwp_ext = doc.extensions["hwp"]
    print(hwp_ext.extra)  # format-specific properties
```

This ensures lossless round-trip: universal properties live in the Document Model, format-specific properties live in extensions, and raw binary data lives in the Verbatim Layer.
