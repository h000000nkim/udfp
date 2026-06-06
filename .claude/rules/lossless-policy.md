---
paths:
  - "udf/parsers/**"
  - "udf/generators/**"
  - "udf/sidecar/**"
---

# 무손실 라운드트립 정책 (파서/제너레이터/사이드카 모듈)

이 디렉토리의 코드를 작성하거나 수정할 때 다음 규칙을 엄격히 따를 것.

## 파서 작성 규칙

1. **모든 입력 바이트는 어디로든 매핑되어야 함.** 파서가 인식하지 못하는 영역은 폐기하지 말고 `verbatim.unknownChunks`에 raw bytes로 보존.
2. **시맨틱 계층은 lossy 허용, Verbatim 계층은 무손실.** 예: HWP 글자 모양 #12345의 외곽선 효과를 시맨틱 `style.bold`로 단순화하더라도 Verbatim에는 charShape 전체가 보존되어야 함.
3. **각 시맨틱 블록에 `verbatimRef`를 채울 것.** 양방향 추적 가능해야 함.
4. **체크섬 기록.** 원본 SHA-256을 `conversionTrace.checksum`에 저장.
5. **`originalContainer` 백업.** Seed Patch 모드를 위해 원본 컨테이너 자체를 보존.
6. **미문서화 필드도 보존.** controlMask, instanceId, 알 수 없는 비트 등 모두 Verbatim으로.

## 제너레이터 작성 규칙

### Seed Patch 모드 (기본 권장)

1. **원본 컨테이너에서 시작.** `ir.originalContainer`의 백업본을 그대로 출력 경로로 복사.
2. **변경된 IR 블록만 식별.** 시맨틱 diff로 사이드카 사이드의 `modified` 플래그 확인.
3. **변경된 스트림만 재생성.** HWP의 BodyText/Section0, HWPX의 Contents/section0.xml 등.
4. **재생성된 스트림으로 원본 교체.** OLE의 경우 FAT/Mini FAT 갱신, ZIP의 경우 해당 entry만 교체.
5. **미수정 영역은 절대 건드리지 않음.** 비트 단위 일치를 자연 보장.

### From Scratch 모드 (fallback)

1. **자체 seed에서 시작.** `seed/<format>/empty.<ext>`.
2. **IR의 모든 정보를 사용하여 재구성.** Verbatim 계층의 모든 필드 포함.
3. **controlMask, instanceId 같은 미문서화 필드도 정확히 재현.** 이를 놓치면 손실.

### 공통 규칙

- `unknownChunks`는 그대로 재기록
- 손실 발생 시 LossReport에 명시
- R-규칙 통과 보장 (자동 수정 적용 후 재검증)

## 사이드카 모듈 규칙

1. **MD 본문은 시맨틱 정보만.** Verbatim은 사이드카 JSON으로 분리.
2. **블록 ID 매핑 유지.** MD 편집 후에도 사이드카 JSON의 ID와 1:1.
3. **MD 변경 감지는 AST 비교로.** 단순 텍스트 비교 금지 (공백 차이로 잘못된 변경 감지 방지).

## 작성 후 검증

```bash
pytest tests/roundtrip/                   # 라운드트립
pytest tests/validation/                  # R-규칙
pytest tests/unit/test_loss.py            # 손실 추적
pytest tests/regression/                  # PE-generation 회귀 (HWP 트랙 변경 시)
```

검증 실패 시 사용자에게 "통과"로 보고하지 말 것.

## 절대 금지

- `unknownChunks` 무시 또는 비우기
- "어차피 안 쓰는 정보 같다"는 추정으로 필드 폐기
- 라운드트립 테스트 비활성화로 통과 표시
- 손실을 LossReport에 기록하지 않고 침묵 처리
- Seed Patch 가능한데 From Scratch로 강제 (사용자 명시 제외)
- 원본 미수정 영역을 재생성으로 덮어씀
