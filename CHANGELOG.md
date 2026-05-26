# Changelog

## 1.0.0

First public release.

### Added
- PyPI distribution as `udfp` (`pip install udfp`)
- MCP `describe` tool for AI self-documentation
- `__version__` attribute (`udf.__version__`)
- Full numpy-style docstrings on all 316 public functions
- Visual Fidelity rendering: DOCX table/cell/paragraph formatting, HTML inline/block styling
- **Seed Patch enhancements (HWP renderer)**:
  - CharShape override: change text color/style in place (e.g., gray placeholder → black)
  - Table `like_char` toggle: flip "treat as character" bit for page flow control
  - Combined single-pass patching via `apply_section_patches()` (avoids offset invalidation)
  - New module `udf.renderers.hwp.docinfo_patch` for DocInfo binary patching
  - Demo: `scripts/demo_form_fill.py` — MD→HWP form filling with all three capabilities

### Changed
- Schema version field set to `"1.0"` (first public version)
- Removed `v1_to_v2` / `v2_to_v1` from public API surface (still available via `udf.migration`)
- Updated `docs/architecture.md` directory structure to match codebase
- Marked non-HWP validation rules (HX/P/D) as planned, not implemented

### Removed
- `UdfpDocument` alias (use `UdfDocument` directly)
