# Changelog

## 1.0.2 (2026-06-05)

### Added
- `fill_template()`: `{{placeholder}}` 기반 HWP 양식 자동화. Seed Patch 호환으로 양식 바이너리 100% 보존
- `TableCell.fixed_width` / `fixed_height`: 셀 단위 크기 고정 속성
- `TableBlock.freeze_columns()`, `freeze_rows()`, `freeze_cell()`, `freeze_labels()`: 테이블 레이아웃 고정 래퍼 메서드
- `patch_hwp_streams()`: 배치 OLE 패칭 (N+2회 → 2회 파일 I/O)
- `add_bindata_record()`: Seed Patch 모드에서 DocInfo BIN_DATA 레코드 추가
- `inject_image_gso()`: 기존 단락에 이미지 GSO 인라인 컨트롤 삽입
- `build_image_gso_records()`: 호스트 단락 없이 GSO 자식 레코드 생성
- PCS 다중 편집: ctrl 앵커 + per-inline PCS remap으로 서식 경계 정확 보존
- HWP R5-R7, HTML H1-H4, MD M1-M3, DOCX D4-D6 검증 규칙
- 90개 external HWP fixture

### Changed
- 테이블 기본 동작이 `freeze` (원본 셀 크기 보존). `layout_type="auto"`로 텍스트 기반 자동 크기
- 이미지 추가 시 From Scratch fallback (Seed Patch OLE 호환성 이슈)
- `udf/layout/` 모듈 제거 → `udf/renderers/_font_utils.py`로 실사용 함수만 이동
- OCR 모듈(`ocr.py`) public 레포에서 제외 (dev 전용)

### Fixed
- From Scratch: 파서 수식 캡처 (f15 EQEDIT 82→86), 중첩 테이블 보존, 테이블 호스트 병합 (f19 xfail→PASSED)
- Seed Patch: BIN_DATA level=0→1, controlMask offset 4, OLE root entry 정렬
- row_span 셀 높이 계산 (single-span 셀 우선)
- freeze_layout 열 너비 균등분배 버그
- 크로스 렌더러 공통 갭 43건 (이미지 crop, PositionInfo, text_wrap 등)
- HTML 렌더러 시각 정확도 (페이지 분할, 다단, 테이블 높이)
- HWP 라운드트립 파이프라인 감사 11건
- 245건 버그 추적, 230+ fixed

### Dependencies
- `markdown-it-py>=3.0` 추가
- `html5lib>=1.1` 추가
- `freetype-py` 필수→optional 변경

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
