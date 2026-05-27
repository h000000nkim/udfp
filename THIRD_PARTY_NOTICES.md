# Third-Party Notices

This file documents external projects whose algorithms or data structures were
referenced during UDF development. Per project policy, no AGPL/GPL code was
directly copied — all implementations were written from scratch after studying
the referenced algorithms.

## pyhwp / hwp5
- License: AGPL-3.0
- URL: https://github.com/mete0r/pyhwp
- Referenced: HWP 5.x binary record structure, HWPTAG decoding, OLE stream layout
- Method: Algorithm study only; clean-room implementation

## PyMuPDF (fitz) / pymupdf4llm
- License: AGPL-3.0
- URL: https://github.com/pymupdf/PyMuPDF
- Referenced: PDF text extraction layout analysis, column detection heuristics
- Method: Algorithm study only; implementation uses pdfminer.six (MIT)

## python-docx
- License: MIT
- URL: https://github.com/python-openxml/python-docx
- Referenced: OOXML document.xml structure, styles.xml parsing patterns, numbering.xml schema
- Method: Algorithm study; direct lxml-based implementation

## rhwp
- License: MIT
- URL: https://github.com/niceduckdev/rhwp (unofficial reference)
- Referenced: HWP IR model design, CQRS validation approach
- Method: Architecture reference; Rust→Python reimplementation

## hwp-rs / libhwp
- License: Apache-2.0
- URL: https://github.com/niceduckdev/hwp-rs
- Referenced: HWP record parsing verification, binary format cross-reference
- Method: Algorithm cross-reference

## PE-generation (internal)
- License: Author's own code (Hoon Kim)
- Referenced: HWP parser, OLE patch logic, body stream serialization
- Method: Code absorbed and restructured onto UDF Document Model
- Mapping: See `docs/pe-generation-mapping.md`
