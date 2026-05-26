# 라이선스 정책

UDF는 MIT 또는 Apache 2.0 라이선스 배포를 목표로 함. 외부 코드 참조 시 다음 규칙을 엄격히 따를 것.

## AGPL / GPL 라이브러리 (코드 직접 인용 금지)

다음 라이브러리는 알고리즘과 자료구조만 학습하고, **코드는 직접 작성**할 것:

- `pyhwp`, `hwp5` (AGPL-3.0)
- `PyMuPDF` (fitz), `pymupdf4llm` (AGPL-3.0)
- `python-ooxml` (AGPL)
- `Pandoc` (GPL)

이들의 함수 본문, 변수 명명, 주석을 그대로 복사하거나 약간만 수정하여 사용하면 라이선스 전염이 발생함. 학습 → 이해 → 자신의 표현으로 다시 작성하는 clean room 방식을 따를 것.

## PE-generation 자산 (사용자 본인 코드)

PE-generation 프로젝트의 코드는 사용자 본인 작성이므로 라이선스 자유. UDF 흡수 시:

1. `THIRD_PARTY_NOTICES.md`에 출처 명시
2. 흡수 매핑은 `dev/pe-generation-mapping.md` 참조
3. IR 모델 위에 재구성하여 흡수 (단순 이식 금지)

## 의존성 추가 시 라이선스 확인

새 라이브러리를 `pyproject.toml`에 추가하기 전에:

1. 해당 라이브러리의 `LICENSE` 파일을 확인
2. MIT/BSD/Apache 2.0/MPL 2.0 → 안전, 진행 가능
3. LGPL → 동적 링크만 허용
4. GPL/AGPL → **추가 금지**, 알고리즘만 참조
5. 비공개/상용 → 추가 금지

## seed 파일 라이선스

From Scratch 모드에서 사용하는 seed 파일은 라이선스 클린해야 함:

- 한컴 한글 등 상용 도구가 만든 빈 문서를 동봉하면 위험
- UDF 자체 생성한 최소 seed를 `seed/` 디렉토리에 동봉
- PE-generation의 `seed.hwpx`는 출처 미확인, **그대로 흡수 금지**

## THIRD_PARTY_NOTICES.md 갱신

알고리즘을 참조한 모든 외부 프로젝트 또는 흡수한 코드는 다음 형식으로 기록:

```markdown
## <프로젝트명>
- 라이선스: <라이선스>
- URL: <github URL>
- 참조 부분: <어떤 알고리즘/자료구조를 참조했는지>
- 참조 방식: 알고리즘 학습 / 자료구조 참조 / 코드 흡수
```

## 검증 명령

```bash
pip-licenses --format=markdown --with-urls
```
