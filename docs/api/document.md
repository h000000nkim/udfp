# UdfDocument

The central class for document manipulation.

::: udf.pipeline.document.UdfDocument
    options:
      show_root_heading: true
      heading_level: 2
      members_order: source
      show_source: false
      docstring_section_style: spacy

---

## Usage Examples

### Construction

```python
from udf import UdfDocument

doc = UdfDocument("path.hwp")           # parse from file
doc = UdfDocument.from_json(json_str)   # deserialize from JSON
doc = UdfDocument.from_dict(data)       # from dict
doc = UdfDocument.empty()               # blank document
```

### Text Operations

```python
doc.replace_text("old", "new")          # global find and replace
matches = doc.find_text(r"\d{4}-\d{2}") # regex search → list of (block_id, match)
```

### Block CRUD

All block operations perform deep tree search (including inside table cells, text boxes, etc.).

```python
block = doc.get_block("b_0003")
paragraphs = doc.find_blocks("paragraph")

doc.add_block(new_block, after="b_0003")
doc.add_block(new_block, parent_id="cell_id")  # inside a container
doc.remove_block("b_0003")
doc.move_block("b_0003", after="b_0010")
```

### Inline Operations

```python
inline = doc.get_inline("b_0003", 0)
doc.set_inline_text("b_0003", 0, "new text")
doc.set_inline_format("b_0003", 0, bold=True, font_size=14.0)
doc.add_inline("b_0003", TextInline(type="text", text="added"))
doc.remove_inline("b_0003", 1)
doc.split_inline("b_0003", 0, offset=5)
```

### Table Operations

```python
cell = doc.get_cell("table_id", row=0, col=1)
doc.add_table_row("table_id", at=2)
doc.remove_table_row("table_id", 0)
doc.add_table_column("table_id", at=1)
doc.remove_table_column("table_id", 2)
doc.merge_cells("table_id", r1=0, c1=0, r2=1, c2=1)
```

### Rendering

```python
md = doc.to("md")                          # render to string
doc.to("hwp", output_path="out.hwp")      # render to file
json_str = doc.to_json()                   # serialize to JSON
data = doc.to_dict()                       # serialize to dict
doc.save("out.udf.json")                   # save JSON file
```

### Convenience Properties

```python
doc.blocks          # top-level block list
doc.tables          # all TableBlocks (deep search)
doc.images          # all ImageBlocks (deep search)
doc.headings        # all HeadingBlocks (deep search)
doc.paragraphs      # all ParagraphBlocks (deep search)
doc.metadata        # DocumentMetadata
doc.outline         # table of contents
doc.page_boundaries # page break positions
```
