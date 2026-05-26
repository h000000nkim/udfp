---
name: HWP fixture CharShape attr=0xffffffff
description: f01~f08 fixture 파일의 모든 CharShape attr이 0xffffffff — 파서 오프셋 버그가 아닌 fixture 생성 방식의 특성
type: project
---

모든 fixture 파일(f01~f08)의 CharShape(DocInfo 스트림) attr 필드가 0xffffffff로 설정되어 있어, 파싱 시 bold=True, italic=True, underline=True, strikethrough=True로 나타남.

**Why:** fixture 파일이 프로그래밍 방식으로 생성될 때 attr 필드를 초기화하지 않았거나 의도적으로 0xff로 채운 것으로 추정. HWP CharShape 스펙 (offset 60: DWORD attr)에 따라 파서는 이 값을 정확하게 디코딩하고 있음 — 파서 로직 자체의 오프셋 버그 없음.

**How to apply:** 향후 fixture 파일의 서식 속성이 모두 True로 나오는 경우, 파서 버그로 의심하기 전에 원본 파일의 CharShape.attr raw bytes를 hex로 확인할 것. base_size=0 (font_size=None)도 fixture 특성임.
