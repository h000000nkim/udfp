---
paths:
  - "udf_native/**"
  - "udf/**/_native.pyi"
---

# Rust + PyO3 가속 모듈 규칙

## 핵심 원칙

1. **Python 구현이 항상 fallback이어야 함.** Rust 빌드 실패 시에도 Python으로 동작.
2. **인터페이스 시그니처 동일.** Python/Rust 구현 비교 검증 가능해야 함.
3. **결과 동등성 자동 검증.** `tests/native/test_equivalence.py`에서 동일 입력에 동일 결과 확인.

## 인터페이스 분리 패턴

```python
# udf/parsers/hwp/records.py
from typing import Protocol

class HwpRecordDecoder(Protocol):
    def decode(self, raw: bytes) -> HwpRecord: ...

class PyHwpRecordDecoder:
    def decode(self, raw: bytes) -> HwpRecord: ...

try:
    from udf_native import RustHwpRecordDecoder as HwpRecordDecoder
except ImportError:
    HwpRecordDecoder = PyHwpRecordDecoder
```

## 빌드

```bash
cd udf_native
maturin develop --release           # 개발 중
maturin build --release             # 배포 wheel
```

## Rust 의존성 정책

권장:

- `pyo3` (PyO3 바인딩)
- `nom` (파서 콤비네이터)
- `quick-xml` (XML, OPC/OWPML)
- `flate2` (zlib, HWP 본문)
- `cfb` (OLE2 컨테이너) 또는 자체 구현

GPL/AGPL 크레이트 추가 금지. crates.io에서 라이선스 확인 필수.

## 도입 시점

다음 조건 모두 충족 시:

1. Python 구현 안정화로 비교 기준 확보
2. 프로파일링으로 명확한 핫패스 식별
3. 동등성 테스트 준비 완료

조건 미충족 상태에서 "성능 좋아질 것 같으니" Rust로 옮기지 말 것.

## 1차 후보

- HWPTAG 레코드 비트 단위 디코딩 (rhwp/hwp-rs/hwpers 참조)
- charShape 구조체 디코딩 (수십 필드)
- PDF 콘텐츠 스트림 파서 (lopdf/pdf-inspector 참조)
- HWP BitStream 순회

## 검증

```bash
pytest tests/native/                # 동등성
pytest tests/native/test_equivalence.py -v
```

Python과 결과가 다르면 Rust가 틀린 것임. 테스트를 변경하지 말고 Rust를 수정.
