# Schema

The `udf.schema` module defines all data types used in the Document Model.

```python
from udf.schema import ParagraphBlock, TextInline, BlockFormat, DocumentMetadata
```

## Document

::: udf.schema.DocumentSchema
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

## Block Types

All blocks inherit from `BlockBase` and have at minimum `type: str` and `id: str` fields.

### Structural Blocks

::: udf.schema.ParagraphBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.HeadingBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.ListBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.TableBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

#### TableCell Layout Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `fixed_width` | `bool` | `False` | Fix this cell's width (skip auto-calculation) |
| `fixed_height` | `bool` | `False` | Fix this cell's height (skip auto-expansion) |
| `width` | `float` | `None` | Cell width in points |
| `height` | `float` | `None` | Cell height in points |

#### TableBlock Layout Methods

| Method | Description |
|--------|-------------|
| `freeze_columns()` | Fix all cell widths |
| `freeze_rows(indices)` | Fix specific (or all) row heights |
| `freeze_cell(row, col)` | Fix a specific cell's width and height |
| `freeze_labels(col=0)` | Fix label column width and height |

`layout_type`: `None` (default, freeze) / `"fixed"` (explicit freeze) / `"auto"` (text-based sizing)

### Content Blocks

::: udf.schema.ImageBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.CodeBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.EquationBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.QuoteBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

### Layout Blocks

::: udf.schema.PageBreakBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.HorizontalRuleBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.TextBoxBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.DrawingBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

### Document Parts

::: udf.schema.HeaderBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.FooterBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.FootnoteBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.EndnoteBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

### Special Blocks

::: udf.schema.BookmarkBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.CommentBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.FieldBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

::: udf.schema.UnknownBlock
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false
      members: false

---

## Inline Types

Inlines represent content runs within blocks (paragraphs, headings).

::: udf.schema.TextInline
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

::: udf.schema.LinkInline
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

::: udf.schema.ImageInline
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

::: udf.schema.FootnoteRefInline
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

::: udf.schema.EndnoteRefInline
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

::: udf.schema.EquationInline
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

::: udf.schema.RubyInline
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

::: udf.schema.CodeInline
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

---

## Formatting

::: udf.schema.BlockFormat
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

::: udf.schema.CellFormat
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

---

## Metadata

::: udf.schema.DocumentMetadata
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

::: udf.schema.PageMargins
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

---

## Unit Converters

All converters are available from `udf.schema`:

```python
from udf.schema import hwpunit_to_pt, pt_to_hwpunit, emu_to_pt, twip_to_pt, mm_to_pt
```

| Function | Conversion | Example |
|----------|-----------|---------|
| `hwpunit_to_pt(v)` | HWPUNIT → pt | `hwpunit_to_pt(1200)` → `12.0` |
| `pt_to_hwpunit(v)` | pt → HWPUNIT | `pt_to_hwpunit(12.0)` → `1200` |
| `emu_to_pt(v)` | EMU → pt | `emu_to_pt(914400)` → `72.0` |
| `pt_to_emu(v)` | pt → EMU | |
| `twip_to_pt(v)` | Twip → pt | `twip_to_pt(240)` → `12.0` |
| `pt_to_twip(v)` | pt → Twip | |
| `halfpt_to_pt(v)` | Half-point → pt | `halfpt_to_pt(24)` → `12.0` |
| `pt_to_halfpt(v)` | pt → Half-point | |
| `mm_to_pt(v)` | mm → pt | `mm_to_pt(25.4)` → `72.0` |
| `pt_to_mm(v)` | pt → mm | |
| `px_to_pt(v)` | px → pt | `px_to_pt(16)` → `12.0` |
| `pt_to_px(v)` | pt → px | |

---

## Types

::: udf.schema.Color
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false

::: udf.schema.Ratio
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false
      members: false
