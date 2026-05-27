# CLI Reference

UDF provides a command-line interface via the `udf` command.

```bash
udf <command> [options]
```

## Commands

### convert

Convert a document to another format.

```bash
udf convert INPUT -o OUTPUT [--format FORMAT]
```

| Argument | Description |
|----------|-------------|
| `INPUT` | Source file path |
| `-o`, `--output` | Output file path |
| `-f`, `--format` | Target format (auto-detected from extension if omitted) |

**Examples:**

```bash
# HWP to DOCX
udf convert report.hwp -o report.docx

# PDF to Markdown
udf convert paper.pdf -o paper.md

# Explicit format
udf convert data.bin -o output.docx --format hwp
```

---

### patch

Apply Markdown edits back to an HWP file using Seed Patch mode.

```bash
udf patch ORIGINAL --md EDITED -o OUTPUT
```

| Argument | Description |
|----------|-------------|
| `ORIGINAL` | Original HWP file (used as seed) |
| `--md` | Edited Markdown file |
| `-o`, `--output` | Output HWP file path |

**Example workflow:**

```bash
# 1. Convert HWP to Markdown for editing
udf convert template.hwp -o template.md

# 2. Edit the Markdown file (fill in form fields, etc.)
# ... edit template.md ...

# 3. Patch edits back into the HWP
udf patch template.hwp --md template.md -o filled.hwp
```

---

### validate

Check HWP structural integrity via R-rules.

```bash
udf validate DOCUMENT
```

**Example:**

```bash
udf validate report.hwp
# ✓ R-1 (charCnt): PASS
# ✓ R-2 (count): PASS
# ✓ R-3 (lineSeg): PASS
# ✓ R-4 (OOB charShape): PASS
```

---

### diff

Semantic comparison of two documents.

```bash
udf diff ORIGINAL MODIFIED
```

**Example:**

```bash
udf diff v1.hwp v2.hwp
```

---

### inspect

Print a structural summary of a document.

```bash
udf inspect DOCUMENT [--json]
```

| Argument | Description |
|----------|-------------|
| `DOCUMENT` | File to inspect |
| `--json` | Output in JSON format |

**Example:**

```bash
udf inspect report.hwp
udf inspect report.hwp --json
```

---

### info

List supported formats and their capabilities.

```bash
udf info [FORMAT]
```

**Examples:**

```bash
# List all formats
udf info

# Details for a specific format
udf info hwp
```
