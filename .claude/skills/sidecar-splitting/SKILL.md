---
name: sidecar-splitting
description: (v3.2에서 deprecated) 사이드카 모델(MD+JSON)은 JSON Document AST 단일 소스 모델로 교체됨. 이 스킬은 레거시 참조용으로만 보존.
---

# ⚠️ Deprecated (v3.2)

v3.2에서 사이드카 모델(MD + JSON 분리)은 **JSON Document AST 단일 소스 모델**로 전면 교체됨.

- 이전: `document.md` + `document.udfp.json` (2파일)
- 현재: `document.udfp.json` 단일 파일 (AST)
- HTML/MD는 뷰(view)로 렌더링되며 IR 자체가 아님

## 대체 모듈

| 구 모듈 | 대체 |
|---------|------|
| `udfp/sidecar/splitter.py` | `udfp/renderer/html.py`, `udfp/renderer/md.py` |
| `udfp/sidecar/merger.py` | `udfp/editor/md_merge.py` |

## 상세 아키텍처

`@docs/architecture.md` §3, §4 참조.
