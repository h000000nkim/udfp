# Changelog

## 1.0.0a1 (unreleased)

First public pre-release.

### Added
- PyPI distribution as `udfp` (`pip install udfp`)
- MCP `describe` tool for AI self-documentation
- `__version__` attribute (`udf.__version__`)
- Full numpy-style docstrings on all 316 public functions
- Visual Fidelity rendering: DOCX table/cell/paragraph formatting, HTML inline/block styling

### Changed
- Schema version field set to `"1.0"` (first public version)
- Removed `v1_to_v2` / `v2_to_v1` from public API surface (still available via `udf.migration`)
- Updated `docs/architecture.md` directory structure to match codebase
- Documented HWPX (HX-1~4) and DOCX (D-1~3) validation rules; PDF (P-rules) remain planned

### Removed
- `UdfpDocument` alias (use `UdfDocument` directly)
