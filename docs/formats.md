# Supported Formats

## Format Overview

| Format | Extensions | MIME Type | Binary | Parse | Render | Round-trip |
|--------|-----------|-----------|:------:|:-----:|:------:|:----------:|
| HWP | `.hwp` | `application/x-hwp` | Yes | Full | Full | Lossless |
| HWPX | `.hwpx` | `application/hwp+zip` | Yes | Full | Full | Lossless |
| DOCX | `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | Yes | Full | Full | Lossless |
| PDF | `.pdf` | `application/pdf` | Yes | Full | — | Parse only |
| Markdown | `.md` | `text/markdown` | No | Full | Full | Lossless |
| HTML | `.html`, `.htm` | `text/html` | No | Full | Full | Lossless |
| XML | `.xml` | `application/xml` | No | Full | — | Parse only |

## HWP

**한컴 한글 (Hangul Word Processor)** binary format based on OLE2 Compound File (Microsoft CFB).

- **Versions:** HWP 5.x (revision 1.3, 2018)
- **Container:** OLE2 with streams (FileHeader, DocInfo, BodyText, BinData, etc.)
- **Encoding:** Records with 4-byte headers (tag_id, level, size), zlib compression
- **Generation:** Seed Patch (default) + From Scratch
- **Validation:** R-1 through R-4 rules

## HWPX

**한컴오피스 NEX** open document format, ZIP-based with XML content.

- **Versions:** Introduced in 한컴오피스 NEX (5.0.3+)
- **Container:** ZIP archive with XML files
- **Based on:** OWPML (Open Word Processor Markup Language)
- **Generation:** Seed Patch + From Scratch
- **Validation:** HX-1 through HX-4 rules

## DOCX

**Office Open XML** word processing format by Microsoft.

- **Container:** ZIP archive with XML parts
- **Standard:** ECMA-376 / ISO/IEC 29500
- **Generation:** Seed Patch + From Scratch
- **Validation:** D-1 through D-3 rules

## PDF

**Portable Document Format** — parse only (no rendering).

- **Parser:** pdfminer.six for text extraction, pypdf for page handling
- **Capability:** Text, tables, and basic structure extraction
- **Limitation:** No PDF generation; convert to MD/DOCX/HTML for editable output

## Markdown

Standard Markdown with UDF extensions for lossless round-trip.

- **Parser:** CommonMark-compatible
- **Sidecar:** JSON metadata file for verbatim preservation
- **Best for:** Text editing workflows (HWP → MD → edit → MD → HWP)

## HTML

HTML5 output with semantic markup.

- **Parser:** lxml-based HTML parser
- **Output:** Clean HTML5 with block-level structure
- **Use case:** Web publishing, preview, intermediate format

## XML

Generic XML text extraction — parse only.

- **Parser:** lxml with recovery mode
- **Capability:** Text content extraction from arbitrary XML
- **Limitation:** No XML generation
