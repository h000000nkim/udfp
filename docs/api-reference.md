# UDF API Reference

## Top-Level Functions

### `udf.parse(path, *, fmt=None) -> UdfDocument`

Parse a document file into a UdfDocument.

```python
import udf

doc = udf.parse("report.hwp")             # auto-detect format
doc = udf.parse("report.hwp", fmt="hwp")  # explicit format
```

### `udf.render(doc, fmt, output_path=None) -> str | None`

Render a UdfDocument to the specified format.

- Text formats (md, html): returns string
- Binary formats (hwp, docx, hwpx): writes to `output_path`, returns None

```python
md_text = udf.render(doc, "md")
udf.render(doc, "docx", output_path="output.docx")
```

### `udf.convert(input_path, output_path, *, input_fmt=None, output_fmt=None)`

Parse input → render to output in one call.

```python
udf.convert("input.hwp", "output.docx")
udf.convert("paper.pdf", "paper.md")
```

### `udf.detect(path) -> dict`

Detect file format by extension and magic bytes.

```python
result = udf.detect("file.hwp")
# {"format": "hwp", "source": "extension", "warnings": []}
```

### `udf.diff(a, b) -> LossReport`

Semantic diff between two UdfDocuments.

```python
report = udf.diff(original, modified)
print(report.is_roundtrip_safe)
```

### `udf.__version__`

Package version string.

```python
import udf
print(udf.__version__)  # "1.0.0"
```

---

## UdfDocument

The central API for document manipulation.

### Construction

```python
from udf import UdfDocument

doc = UdfDocument("path.hwp")           # parse from file
doc = UdfDocument.from_json(json_str)   # deserialize
doc = UdfDocument.from_dict(data)       # from dict
doc = UdfDocument.empty()               # blank document
```

### Text Operations

```python
doc.replace_text("old", "new")          # find and replace across all blocks
matches = doc.find_text(r"regex")       # returns list of (block_id, match)
```

### Block CRUD (deep — searches entire tree)

```python
block = doc.get_block("b_0003")         # find anywhere in tree
paragraphs = doc.find_blocks("paragraph")
tables = doc.find_blocks("table")

doc.add_block(new_block, after="b_0003")
doc.add_block(new_block, parent_id="cell_id")  # inside container
doc.remove_block("b_0003")
doc.move_block("b_0003", after="b_0010")
```

### Inline Operations

```python
inline = doc.get_inline("b_0003", 0)
doc.set_inline_text("b_0003", 0, "new text")    # preserves formatting
doc.set_inline_format("b_0003", 0, bold=True)
doc.add_inline("b_0003", TextInline(text="added"))
doc.remove_inline("b_0003", 1)
doc.split_inline("b_0003", 0, offset=5)         # split at character 5
```

### Table Operations

```python
cell = doc.get_cell("table_id", row=0, col=1)
doc.add_table_row("table_id", at=2)
doc.remove_table_row("table_id", 0)
doc.add_table_column("table_id", at=1)
doc.remove_table_column("table_id", 2)
doc.merge_cells("table_id", r1=0, c1=0, r2=1, c2=1)
doc.split_cell("table_id", row=0, col=0)    # unmerge (reset spans to 1)
```

### Block Format

```python
fmt = doc.get_block_format("b_0003")
doc.set_block_format("b_0003", alignment="center", space_before=12.0)
```

### Metadata

```python
doc.set_metadata(title="Report", author="Kim")
```

### Convenience Properties

```python
doc.blocks          # top-level block list
doc.tables          # all TableBlocks (deep)
doc.images          # all ImageBlocks (deep)
doc.headings        # all HeadingBlocks (deep)
doc.paragraphs      # all ParagraphBlocks (deep)
doc.metadata        # DocumentMetadata
doc.outline         # table of contents structure
doc.page_boundaries # page break positions
```

### Rendering

```python
md = doc.to("md")                          # render to string
doc.to("hwp", output_path="out.hwp")      # render to file
json_str = doc.to_json()                   # serialize to JSON
data = doc.to_dict()                       # serialize to dict
doc.save("out.udf.json")                   # save JSON representation
```

---

## DocumentBuilder

Fluent API for constructing documents programmatically.

```python
from udf import DocumentBuilder

doc = (
    DocumentBuilder()
    .title("Report Title")
    .author("Author Name")
    .heading(1, "Introduction")
    .paragraph("Body text here.", bold=True, font_size=12)
    .table([
        ["Name", "Age"],
        ["Kim", "30"],
    ])
    .image("photo.png", width=200, height=150)
    .list(["Item 1", "Item 2"], ordered=True)
    .code("print('hello')", language="python")
    .equation("E=mc^2")
    .quote("A wise quote.")
    .horizontal_rule()
    .page_break()
    .block(custom_block)          # append a pre-constructed Block instance
    .build()
)
```

---

## Generation Modes

### Automatic Mode Selection

UDF automatically selects the best generation mode:

1. **Seed Patch** — when original container exists AND no structural changes detected
2. **From Scratch** — when blocks were added/removed OR no original container

Detection logic:
```python
has_structural_change = any(
    not getattr(b, "verbatim_ref", None)
    for b in doc.blocks
)
```

Any block without `verbatim_ref` was programmatically created → forces From Scratch.

### Seed Patch Capabilities

| Operation | Supported |
|-----------|-----------|
| Text replacement in existing paragraphs | Yes |
| Text addition to empty paragraphs | Yes |
| Table cell text modification | Yes |
| Equation script replacement | Yes |
| CharShape override (e.g., text color change) | Yes |
| Table `like_char` toggle (page flow control) | Yes |
| Combined single-pass patching (`apply_section_patches`) | Yes |
| Adding new blocks | No (triggers From Scratch) |
| Removing blocks | No (triggers From Scratch) |
| Other format changes | No (triggers From Scratch) |

### From Scratch Capabilities

All operations supported. Generates complete output from Document Model.

**Limitations**: The following block types cannot be fully regenerated in From Scratch mode (reported as `FORMAT_LIMIT` loss):

| Block Type | Reason |
|-----------|--------|
| `DrawingBlock` | Requires GSO ShapeComponent data only available in the original file |
| `ChartBlock` | Requires embedded chart data only available in the original file |
| `TextArtBlock` | Requires WordArt rendering data only available in the original file |
| `UnknownBlock` | Format-specific content that cannot be interpreted |

---

## LossReport

Every conversion produces a `LossReport` tracking what information was preserved or lost.

```python
report = udf.diff(original, modified)

report.total_blocks          # total block count
report.lossless_blocks       # blocks with no loss
report.lossy_blocks          # list of BlockLoss entries
report.dropped_features      # list of dropped feature names
report.is_roundtrip_safe     # True if no UNINTENDED losses
```

### BlockLoss

Each entry in `lossy_blocks` describes a specific loss:

```python
loss.block_id                # affected block's ID
loss.loss_type               # LossCategory enum
loss.description             # human-readable explanation
```

### LossCategory

| Value | Meaning | Passes validation? |
|-------|---------|-------------------|
| `USER_EDITED` | User intentionally changed content | Yes |
| `FORMAT_LIMIT` | Inherent format limitation (e.g., MD can't store font info) | Yes |
| `UNINTENDED` | Bug-level loss — something was dropped that shouldn't have been | **No** |

---

## DocumentMetadata

Accessible via `doc.metadata`. All lengths are in **points (pt)**.

```python
doc.set_metadata(title="Report", author="Kim", page_size="A4")
```

### Basic Properties

| Field | Type | Description |
|-------|------|-------------|
| `title` | `str \| None` | Document title |
| `author` | `str \| None` | Author name |
| `subject` | `str \| None` | Document subject |
| `keywords` | `list[str]` | Keyword list |
| `language` | `str \| None` | Language code |
| `created_at` | `str \| None` | ISO creation timestamp |
| `modified_at` | `str \| None` | ISO modification timestamp |

### Page Layout

| Field | Type | Description |
|-------|------|-------------|
| `page_size` | `str \| None` | Page size name (e.g., `"A4"`, `"Letter"`) |
| `page_width` | `float \| None` | Page width in pt |
| `page_height` | `float \| None` | Page height in pt |
| `margins` | `PageMargins \| None` | Top/bottom/left/right margins in pt |
| `header_margin` | `float \| None` | Header margin in pt |
| `footer_margin` | `float \| None` | Footer margin in pt |
| `gutter` | `float \| None` | Binding/gutter margin in pt |
| `columns` | `ColumnDef \| None` | Multi-column layout (count, gap, widths) |

### Numbering

| Field | Type | Description |
|-------|------|-------------|
| `start_page_number` | `int \| None` | Starting page number |
| `start_footnote_number` | `int \| None` | Starting footnote number |
| `start_endnote_number` | `int \| None` | Starting endnote number |
| `start_picture_number` | `int \| None` | Starting picture number |
| `start_table_number` | `int \| None` | Starting table number |
| `start_equation_number` | `int \| None` | Starting equation number |
| `footnote_numbering_format` | `str \| None` | Footnote numbering style (e.g., `"decimal"`, `"roman_lower"`) |
| `endnote_numbering_format` | `str \| None` | Endnote numbering style |
| `compatibility_target` | `str \| None` | Target application compatibility version |

### Sections

Documents can have multiple sections with independent geometry:

```python
doc.metadata.sections        # list[SectionDef]
```

Each `SectionDef` has its own `page_width`, `page_height`, `margins`, `columns`, `orientation` (`"portrait"` / `"landscape"`), `break_type`, and `background_color`.

---

## Supported Formats

| Format | Extensions | Parse | Render | Same-format Round-trip | Validation |
|--------|-----------|-------|--------|----------------------|------------|
| HWP | .hwp | Full | Full (Seed Patch + From Scratch) | Lossless (verbatim) | R1–R4, I1–I3 |
| HWPX | .hwpx | Full | Full (Seed Patch + From Scratch) | Lossless (verbatim) | Semantic diff |
| DOCX | .docx | Full | Full (Seed Patch + From Scratch) | Lossless (verbatim) | Semantic diff |
| PDF | .pdf | Full | — | Parse only | — |
| Markdown | .md | Full | Full | Text-level | Semantic diff |
| HTML | .html, .htm | Full | Full | Text-level | Semantic diff |
| XML | .xml | Full | — | Parse only | — |

---

## CLI

```bash
# Convert between formats
udf convert input.hwp -o output.docx
udf convert paper.pdf -o paper.md

# Inspect document structure
udf inspect document.hwp
udf inspect document.hwp --json

# Validate HWP structural integrity
udf validate document.hwp

# Semantic diff
udf diff original.hwp modified.hwp

# Format info
udf info
udf info hwp

# Patch HWP from edited Markdown
udf patch original.hwp --md edited.md -o output.hwp
```

---

## MCP Server (udfp)

AI-integrated document manipulation via Model Context Protocol.

### Setup

```bash
pip install udfp[mcp]
claude mcp add udfp -- python -m udfp
```

### Tools

| Tool | Description |
|------|-------------|
| `read` | Parse document → Simplified JSON (structure + formatting) |
| `edit` | Modify inline text/format by block_id + inline_idx |
| `render` | Convert document to any supported format |
| `create` | Generate new document from blocks JSON |
| `insert_blocks` | Add blocks to existing document |
| `remove_blocks` | Remove blocks from existing document |
| `set_page` | Change page layout (paper, margins, orientation) |
| `describe` | Self-documentation (topics: overview, blocks, edit, create, fmt, workflow, api, metadata, loss) |

### Example Workflow

```
AI reads document → identifies empty fields → fills content → renders to desired format
```
