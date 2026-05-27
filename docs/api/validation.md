# Validation API

Structural integrity checks for format-specific rules.

```python
from udf.validation import validate_hwp, validate_hwpx, validate_docx
```

## HWP Validation

::: udf.validation.validate_hwp
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false

### Individual Rules

::: udf.validation.check_r1
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false

::: udf.validation.check_r2
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false

::: udf.validation.check_r3
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false

::: udf.validation.check_r4
    options:
      show_root_heading: true
      heading_level: 4
      show_source: false

---

## HWPX Validation

::: udf.validation.validate_hwpx
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false

---

## DOCX Validation

::: udf.validation.validate_docx
    options:
      show_root_heading: true
      heading_level: 3
      show_source: false

---

## Result Types

### ValidationReport

```python
report = validate_hwp(doc)

report.is_valid       # bool
report.violations     # list[RuleViolation]
```

### RuleViolation

```python
for v in report.violations:
    v.rule        # str — "R-1", "R-2", etc.
    v.severity    # str — "error" or "warning"
    v.message     # str — human-readable description
    v.location    # str — where in the document
```
