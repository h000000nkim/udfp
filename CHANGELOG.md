# Changelog

## 1.1.0 (2026-06-01)

### Added

- **DOCX/HWPX validation rules**: D1-D3 (DOCX) and HX1-HX4 (HWPX) structural integrity checks
- **OMML-to-LaTeX converter**: equation parsing for DOCX documents
- **MD Merge-Diff engine**: round-trip editing via Markdown with semantic change detection
- **MCP export_md/import_md tools**: Markdown-based document editing through MCP protocol
- **Phase 15 programmatic editing**: CharShape/ParaShape override, native numbering, LossReport enhancements
- **Universal HTML renderer**: 22 block types + 8 inline types with full CSS styling
- **PDF parser enhancements**: hyperlinks, headers/footers, footnotes, multi-column detection

### Fixed

- CI: resolve 16+ ruff lint errors, upgrade GitHub Actions to Node.js 24
- HWP: page margin transfer, inline image positioning, line spacing, color bugs (falsy black, byte order), OLE DIFAT corruption, minimum column width for wide tables, heading font sizes by level, per-inline color override, PCS position adjustment
- HWPX: standard header.xml styles, hyperlink ctrl structure, image size fallback (curSz/orgSz), container position/color propagation, content-modified detection, fontface language case
- DOCX: Word compatibility (effectExtent, letter spacing, auto footer), table column span calculation, verbatim streams, heading sizes, cell merge, highlight, ImageInline
- MD parser: thematic break, hard line break
- Security: escape HTML attributes in MD renderer to prevent XSS
- Packaging: include seed HWP files in wheel, skip MCP tests when package not installed

### Changed

- GitHub Actions: checkout v4→v6, setup-python v5→v6, upload-artifact v4→v7, github-script v7→v9
- HWP seed (empty.hwp) updated with complete DocInfo for From Scratch mode
- Schema serialization robustness and smart save dispatch improvements
- UDFP→UDF rename throughout (UDF=format+library, UDFP=Protocol/MCP server)

## 1.0.0 (2026-05-26)

First public release.

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
- Marked non-HWP validation rules (HX/P/D) as planned, not implemented

### Removed

- `UdfpDocument` alias (use `UdfDocument` directly)
