# DocumentBuilder

Fluent API for constructing documents programmatically.

::: udf.builder.DocumentBuilder
    options:
      show_root_heading: true
      heading_level: 2
      members_order: source
      show_source: false

---

## Full Example

```python
from udf import DocumentBuilder
import udf

doc = (
    DocumentBuilder()
    # Metadata
    .title("Monthly Report")
    .author("Hoon Kim")
    .subject("Q1 2026 Results")

    # Content
    .heading(1, "Executive Summary")
    .paragraph("This report covers the first quarter of 2026.")

    .heading(2, "Revenue")
    .table([
        ["Category", "Q1 Amount", "YoY Change"],
        ["Product A", "1,200,000", "+15%"],
        ["Product B", "850,000", "+8%"],
        ["Total", "2,050,000", "+12%"],
    ], header_rows=1)

    .heading(2, "Key Highlights")
    .list([
        "Record revenue in Product A category",
        "New market expansion completed",
        "Customer satisfaction improved to 4.8/5.0",
    ])

    .heading(2, "Outlook")
    .paragraph(
        "We expect continued growth in Q2.",
        font_size=12,
        bold=True,
    )

    .horizontal_rule()

    .heading(2, "Appendix")
    .code("SELECT SUM(revenue) FROM sales WHERE quarter = 'Q1'", language="sql")
    .image("chart.png", width=400, height=300, alt="Revenue chart")
    .equation("R = \\frac{\\sum_{i=1}^{n} r_i}{n}")
    .quote("Growth is never by mere chance; it is the result of forces working together.")

    .page_break()
    .heading(1, "Detailed Data")
    .paragraph("See attached spreadsheet for full breakdown.")

    .build()
)

# Render to multiple formats
udf.render(doc, "hwp", output_path="report.hwp")
udf.render(doc, "docx", output_path="report.docx")
md_text = udf.render(doc, "md")
```

## Available Methods

### Metadata

| Method | Description |
|--------|-------------|
| `.title(text)` | Set document title |
| `.author(text)` | Set document author |
| `.subject(text)` | Set document subject |

### Content Blocks

| Method | Description |
|--------|-------------|
| `.heading(level, text, **fmt)` | Add heading (level 1-6) |
| `.paragraph(text, **fmt)` | Add paragraph with optional formatting |
| `.table(rows, col_widths=, header_rows=)` | Add table from 2D list |
| `.image(src, width=, height=, alt=)` | Add image block |
| `.list(items, ordered=)` | Add ordered or unordered list |
| `.code(code, language=)` | Add code block |
| `.equation(latex)` | Add equation block |
| `.quote(text)` | Add block quotation |

### Layout

| Method | Description |
|--------|-------------|
| `.horizontal_rule()` | Add horizontal rule |
| `.page_break()` | Add page break |

### Build

| Method | Returns |
|--------|---------|
| `.build()` | `UdfDocument` |

All content methods accept `**fmt` keyword arguments for inline formatting: `bold`, `italic`, `underline`, `font_name`, `font_size`, `color`.
