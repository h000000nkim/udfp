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

print(f"Valid: {report.is_valid}")
for violation in report.violations:
    print(f"  {violation.rule}: {violation.message}")
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
| HX-1 | XML well-formedness | All XML files in ZIP are valid |
| HX-2 | Content reference integrity | Internal references resolve correctly |
| HX-3 | Resource completeness | All referenced resources exist in ZIP |
| HX-4 | Schema conformance | XML conforms to HWPX schema |

```python
from udf.validation import validate_hwpx

report = validate_hwpx(doc)
```

## DOCX D-Rules

| Rule | Check | Description |
|------|-------|-------------|
| D-1 | Relationship integrity | .rels files reference existing parts |
| D-2 | Content type coverage | All parts have declared content types |
| D-3 | Style reference validity | Referenced styles exist in styles.xml |

```python
from udf.validation import validate_docx

report = validate_docx(doc)
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

report.is_valid       # bool — all rules passed
report.violations     # list[RuleViolation]

for v in report.violations:
    v.rule            # str — rule ID (e.g., "R-1")
    v.severity        # str — "error" or "warning"
    v.message         # str — human-readable description
    v.location        # str — where in the document
```
