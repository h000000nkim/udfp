---
paths:
  - "udf/parsers/hwp/**"
  - "udf/generators/hwp/**"
  - "udf/validation/hwp/**"
  - "tests/**/test_hwp*.py"
  - "tests/regression/**"
---

# HWP 5.x 바이너리 처리 규칙

## 자산 출처

UDF의 HWP 처리 코드는 PE-generation 프로젝트의 작업 결과를 IR 모델 위에 재구성하여 흡수한 것임. 따라서 다음 자료를 항상 참조:

- `dev/format-specs/hwp.md` — HWP 5.x 바이너리 스펙
- `dev/pe-generation-mapping.md` — 흡수 매핑표
- `dev/known-issues/rhwp-rowspan.md` — rhwp 버그

---

## 함정 모음 (PE-generation 작업 중 누적된 실수, 절대 반복 금지)

### 함정 1: PLS 필드 오프셋 혼동

**PLS offset 0은 vpos가 아니라 tpos(문자 위치)다.**

```python
# 잘못된 코드 (offset 0을 vpos로 읽는 실수)
vpos = struct.unpack_from('<I', pay, k*36+0)[0]  # ← 이건 tpos!

# 올바른 코드
tpos = struct.unpack_from('<I', pay, k*36+0)[0]  # 문자 위치
vpos = struct.unpack_from('<I', pay, k*36+4)[0]  # Y 좌표 (셀 상대)
h    = struct.unpack_from('<I', pay, k*36+8)[0]  # 줄 높이
lh   = struct.unpack_from('<I', pay, k*36+20)[0] # 줄 간격
```

### 함정 2: PAGE_DEF 위치 오해

PAGE_DEF(tag=73)는 **BodyText Section0** 안의 `CTRL_HEADER 'secd'` 자식이다. **DocInfo 안에 없다.**

DocInfo에서 tag=73을 찾으면 못 찾음.

### 함정 3: controlMask 수정

PH offset 4 = `controlMask`. **절대 수정 금지.** rhwp 검증에서 사용됨.

수정 가능한 것은 charCnt(offset 0)뿐.

### 함정 4: 2단 레이아웃(cold)과 vpos 충돌 오해

`CTRL_HEADER 'cold'`로 2단 레이아웃이 정의된 경우, 좌우 단의 단락이 같은 vpos 값을 가질 수 있음. 이는 충돌이 아니라 각 단이 독립적인 좌표계를 사용하기 때문.

### 함정 5: charCnt MSB 보존 누락

```python
# 올바른 코드 (MSB 반드시 보존)
old_dw = struct.unpack_from('<I', payload, 0)[0]
msb    = old_dw & 0x80000000
struct.pack_into('<I', payload, 0, msb | (new_cnt & 0x3FFFFFFF))
```

MSB를 잃으면 한컴이 파일을 손상으로 판단할 수 있음.

### 함정 6: 잘못된 압축 방식

```python
# 올바른 raw deflate (wbits=-15)
data = zlib.decompress(raw, -15)
comp = zlib.compressobj(level, zlib.DEFLATED, -15)  # wbits=-15 필수
```

`wbits=15`(zlib 헤더) 또는 `wbits=31`(gzip) 사용 시 한컴이 파일을 열지 못함.

### 함정 7: 한컴 뷰어로 HWP 검증 금지

한컴 뷰어는 손상된 HWP도 자동 복구하여 열기 때문에 파일 정상 여부를 판단할 수 없음.

→ `rhwp validate` 또는 실제 한컴 한글 앱에서 확인할 것. 단, rhwp는 시각 정확성을 보장하지 않으므로 구조 정합성 검증 용도로만 사용.

### 함정 8: OLE 패치 시 FAT 섹터 충돌

`_alloc_sector()` 호출 전에 virtual free 슬롯을 직접 재사용하면 `_write_fat()`이 그 섹터를 FAT 섹터로 덮어씀.

→ **반드시 `_alloc_sector()`를 통해서만 새 섹터 확보.**

### 함정 9: sizeY 축소 방지

```python
# 늘리는 방향만 허용
if new_sizeY > old_sizeY:
    struct.pack_into('<I', payload, 20, new_sizeY)
```

기존 높이보다 낮아지는 방향으로 수정하면 레이아웃 손상.

### 함정 10: Seed Patch에서 단락 추가/삭제 금지

**BodyText/SectionN 스트림에서 L0 PARA_HEADER 단락을 추가하거나 삭제하면 한컴이 "파일 손상"으로 판정한다.**

- 마지막 단락 1개만 제거해도 손상 판정
- null padding으로 decompressed 크기를 맞춰도 손상 판정
- 레코드 내용(payload) 수정은 OK (스크립트 교체, 텍스트 변경 등)
- 압축 방식/크기 변경도 OK

원인: 한컴 내부적으로 단락 구조를 DOC_DATA 등 메타데이터와 교차 검증하는 것으로 추정 (메커니즘 미공개).

→ **Seed Patch 모드에서는 기존 단락의 내용만 수정할 것. 단락 수 변경은 From Scratch 모드에서만.**

상세: `dev/known-issues/hwp-paragraph-deletion.md`

### 함정 11: ID_MAPPINGS 카운트 불일치 = 손상

**DocInfo에 CS/PS/BF/BinData 레코드를 추가/삭제할 때 ID_MAPPINGS의 해당 카운트를 반드시 업데이트해야 한다.**

```python
# 올바른 코드 (build_docinfo에서 자동 처리됨)
idmap = bytearray(rec.payload)
struct.pack_into('<I', idmap, 36, old_cs_count + n_new_cs)  # CharShape
struct.pack_into('<I', idmap, 52, old_ps_count + n_new_ps)  # ParaShape
struct.pack_into('<I', idmap, 32, old_bf_count + n_new_bf)  # BorderFill
```

ID_MAPPINGS 72바이트 구조: `[0]=BinData, [4-28]=FaceName×7, [32]=BF, [36]=CS, [40]=TabDef, [44]=Numbering, [48]=Bullet, [52]=PS, [56]=Style`

상세: `dev/known-issues/hwp-idmappings-corruption.md`

---

## R-규칙 처리 (구조 정합성)

| 규칙 | 조건 | 자동 수정자 |
|------|------|-------------|
| R1 | `PH.charCnt ≠ len(PT) // 2` | `normalize_para_headers()` |
| R2 | `PH.csCount ≠ len(PCS) // 8` 또는 `PH.lsCount ≠ len(PLS) // 36` | `normalize_para_headers()` |
| R3 | PLS 엔트리 1개 + 텍스트 길이 > 40 + `\n` 없음 | `fix_lineseg_r3()` |
| R4 | PCS의 `pos >= len(PT) // 2` | `fix_oob_charshape()` |

R-규칙 통과는 라운드트립 통과의 **필수 조건**임 (시맨틱 diff = 0과 동급).

---

## Seed Patch 모드 우선

UDF는 원본 HWP가 있을 때 항상 Seed Patch 모드를 먼저 시도. 변경된 스트림만 재생성하여 미수정 영역의 비트 단위 무결성을 자연 보장.

```python
# 권장
ir = udf.parse("input.hwp")          # originalContainer가 자동 보존됨
ir = modify_some_blocks(ir)
udf.generate(ir, "hwp", "output.hwp", mode="auto")  # seed-patch 자동 선택

# From scratch는 원본이 없을 때만 fallback
```

---

## 참조 가능 라이브러리 (알고리즘만)

코드 작성 시 다음 라이브러리의 알고리즘을 참조하되 코드는 직접 작성:

- **rhwp** (Rust, edwardkim/rhwp): IR 모델 + CQRS 구조, 단 시각 렌더링은 신뢰 불가
- **hwpers** (Rust, Indosaram/hwpers): HWP 5.0 read/write 자료
- **hwp-rs** (Rust, hahnlee/hwp-rs, Apache 2.0): 안정적, libhwp Python 래퍼
- **pyhwp / hwp5** (Python, **AGPL** — 코드 직접 인용 금지): HWPTAG 디코딩 알고리즘
- **한컴테크 공식 블로그**: olefile + bitstring 기반 신뢰 가능 출발점
- **PE-generation 자체 자산** (사용자 본인 코드, 라이선스 자유): IR 모델 위에 재구성하여 흡수

---

## 작성 후 검증

이 디렉토리의 코드를 변경한 후 반드시 다음을 통과:

```bash
pytest tests/roundtrip/test_hwp_md_hwp.py
pytest tests/validation/test_hwp_rules.py
pytest tests/regression/test_pe_generation_compat.py  # PE-generation 회귀
```

검증을 통과하지 못하면 변경사항을 사용자에게 "통과"로 보고하지 말 것. 어느 테스트가 실패했고 원인이 무엇인지 함께 보고할 것.

---

## 절대 금지

- 함정 1~9 중 어느 하나라도 위반
- `rhwp validate rc=0`을 근거로 "시각적으로 정상"이라고 보고
- R-규칙 위반을 무시하거나 테스트 비활성화
- Seed Patch 가능한 상황에서 From Scratch 사용 (사용자 명시적 강제 제외)
- `unknownChunks` 폐기
