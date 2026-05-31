# Validation

UDF includes a structural validation system that checks document integrity after conversion.

## Overview

Every round-trip must pass two conditions simultaneously:

1. **Semantic diff = 0** — No meaningful content changes
2. **R-rules pass** — Format-specific structural integrity

## HWP R-Rules

| Rule | Check | Description |
|------|-------|-------------|
| R-1 | `charCnt` | Character count in paragraph header matches actual text bytes |
| R-2 | `count` | Record counts in section match actual record entries |
| R-3 | `lineSeg` | Line segment metadata is consistent with paragraph content |
| R-4 | OOB charShape | CharShape references don't exceed DocInfo table bounds |

### Usage

```python
from udf.validation import validate_hwp

doc = udf.parse("document.hwp")
report = validate_hwp(doc)

print(f"Valid: {report.is_passing()}")
for v in report.all_violations:
    print(f"  {v.rule_id}: {v.message}")
```

Individual rule checks:

```python
from udf.validation import check_r1, check_r2, check_r3, check_r4

violations = check_r1(doc)  # charCnt consistency
violations = check_r2(doc)  # record counts
violations = check_r3(doc)  # line segments
violations = check_r4(doc)  # charShape bounds
```

## HWPX HX-Rules

| Rule | Check | Description |
|------|-------|-------------|
| HX-1 | mimetype entry | First ZIP entry is `mimetype`, uncompressed (STORED), contains `application/hwp+zip` |
| HX-2 | Required parts | Mandatory entries exist: mimetype, version.xml, container.xml, content.hpf, header.xml, section*.xml |
| HX-3 | Manifest consistency | content.hpf manifest items match actual ZIP entries and vice versa |
| HX-4 | Header structure | header.xml contains fontfaces (7 language slots), charPr, paraPr, and style definitions |

```python
from udf.validation import validate_hwpx

report = validate_hwpx("document.hwpx")  # takes a file path
```

## DOCX D-Rules

| Rule | Check | Description |
|------|-------|-------------|
| D-1 | Required parts | Mandatory entries exist: [Content_Types].xml, _rels/.rels, document.xml, styles.xml, document.xml.rels |
| D-2 | Content type consistency | Override PartNames in [Content_Types].xml match actual ZIP entries with correct MIME types |
| D-3 | Relationship integrity | Internal relationship targets in .rels files exist in the ZIP |

```python
from udf.validation import validate_docx

report = validate_docx("document.docx")  # takes a file path
```

## CLI Validation

```bash
# Validate HWP structural integrity
udf validate document.hwp

# Semantic diff between two documents
udf diff original.hwp modified.hwp
```

## Validation Report

All validators return a report with a consistent interface:

```python
report = validate_hwp(doc)

report.is_passing()       # bool — all rules passed (zero errors + zero warnings)
report.all_violations     # list[RuleViolation]
report.error_count        # int
report.warning_count      # int

for v in report.all_violations:
    v.rule_id         # str — rule ID (e.g., "R1", "HX1", "D1")
    v.block_id        # str — which block is affected
    v.severity        # str — "error" or "warning"
    v.message         # str — human-readable description
```
