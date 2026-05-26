#!/usr/bin/env python3
"""E2E test: 섹션 헤더 유사도로 MD 드래프트를 HWP 템플릿에 매칭하여 채운다.

기존 e2e_hwp_fill.py의 순차적 빈 단락 채우기 대신,
TextBox 헤더 ↔ MD 헤딩을 매칭하여 올바른 섹션에 올바른 내용을 주입한다.

Usage:
    python scripts/e2e_hwp_fill_matched.py [case_dir] [--output /tmp/filled.hwp]
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import udf
from udf.core.schema import (
    DrawingBlock,
    FooterBlock,
    HeaderBlock,
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    TableBlock,
    TextBoxBlock,
    TextInline,
)


# ---------------------------------------------------------------------------
# 1. 템플릿 섹션 추출
# ---------------------------------------------------------------------------

def _textbox_header(block: TextBoxBlock) -> str:
    """TextBox 내부의 중첩 TextBox까지 재귀하여 텍스트를 수집, 슬래시로 연결."""
    parts: list[str] = []

    def _collect(children):
        for c in children:
            if isinstance(c, TextBoxBlock):
                _collect(c.content)
            elif isinstance(c, ParagraphBlock):
                t = "".join(i.text for i in c.inlines if isinstance(i, TextInline))
                if t.strip():
                    parts.append(t.strip())

    _collect(block.content)
    return " / ".join(parts)


def _table_content_paras(table: TableBlock) -> list[ParagraphBlock]:
    """테이블 셀 안의 모든 ParagraphBlock을 순서대로 반환."""
    paras: list[ParagraphBlock] = []
    for row in table.rows:
        for cell in row.cells:
            for c in cell.content:
                if isinstance(c, ParagraphBlock):
                    paras.append(c)
    return paras


def _is_structured_table(table: TableBlock) -> bool:
    """구조화된 데이터 테이블인지 판별 (품명/수량 같은 다중 컬럼·다중 행 표).

    조건: 5행 이상이면서 3열 이상 — 명백한 데이터 격자만 건너뜀.
    연구자 정보표(4행 5열)나 동료 평가표(2행 5열)는 통과.
    """
    if not table.rows:
        return False
    max_cells = max(len(r.cells) for r in table.rows)
    return len(table.rows) >= 5 and max_cells >= 3


def extract_template_sections(blocks: list) -> list[dict]:
    """TextBox 헤더 → 바로 뒤 Table의 (헤더, 내용 단락들) 쌍 목록을 추출한다."""
    sections = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if isinstance(b, TextBoxBlock):
            header = _textbox_header(b)
            # 바로 뒤에서 가장 가까운 Table 찾기 (최대 5칸)
            tables = []
            j = i + 1
            while j < len(blocks) and j < i + 20:
                nxt = blocks[j]
                if isinstance(nxt, TextBoxBlock):
                    break
                if isinstance(nxt, TableBlock):
                    tables.append(nxt)
                j += 1

            if tables:
                # 구조화된 테이블(다중 컬럼)은 주입 대상에서 제외
                content_tables = [t for t in tables if not _is_structured_table(t)]
                all_structured = len(content_tables) == 0

                paras = []
                for t in content_tables:
                    paras.extend(_table_content_paras(t))

                sections.append({
                    "header_raw": header,
                    "header_norm": _normalize_header(header),
                    "block_idx": i,
                    "tables": tables,
                    "paras": paras,
                    "structured": all_structured,
                })
        i += 1
    return sections


# ---------------------------------------------------------------------------
# 2. MD 섹션 추출
# ---------------------------------------------------------------------------

def extract_md_sections(doc) -> list[dict]:
    """MD 문서를 헤딩 기준으로 섹션 분리한다.

    각 섹션에 paragraphs_deep을 추가: 자기 + 하위 헤딩의 모든 텍스트를 포함.
    """
    sections: list[dict] = []
    current: dict | None = None

    for block in doc.blocks:
        if isinstance(block, HeadingBlock):
            if current is not None:
                sections.append(current)
            current = {
                "heading": block.text,
                "heading_norm": _normalize_header(block.text),
                "level": block.level,
                "paragraphs": [],
            }
        elif isinstance(block, ParagraphBlock):
            text = "".join(i.text for i in block.inlines if isinstance(i, TextInline))
            if text.strip():
                if current is None:
                    current = {
                        "heading": "(preamble)",
                        "heading_norm": "",
                        "level": 0,
                        "paragraphs": [],
                    }
                current["paragraphs"].append(text)
        elif isinstance(block, ListBlock):
            if current is not None:
                for item in block.items:
                    t = "".join(i.text for i in item.inlines if isinstance(i, TextInline))
                    if t.strip():
                        current["paragraphs"].append(t)
        elif isinstance(block, TableBlock):
            table_text = _table_to_text(block)
            if table_text and current is not None:
                current["paragraphs"].append(table_text)

    if current is not None:
        sections.append(current)

    # paragraphs_deep: 자기 단락 + 자기보다 레벨이 높은(하위) 연속 섹션들의 단락
    for i, sec in enumerate(sections):
        deep = list(sec["paragraphs"])
        for j in range(i + 1, len(sections)):
            child = sections[j]
            if child["level"] <= sec["level"] and child["level"] > 0:
                break
            deep.extend(child["paragraphs"])
        sec["paragraphs_deep"] = deep

    return sections


def _table_to_text(table: TableBlock) -> str:
    """간단한 테이블 → 텍스트 변환."""
    rows = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            parts = []
            for c in cell.content:
                if isinstance(c, ParagraphBlock):
                    t = "".join(i.text for i in c.inlines if isinstance(i, TextInline))
                    parts.append(t)
            cells.append(" ".join(parts))
        rows.append(" | ".join(cells))
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# 3. 헤더 정규화 & 매칭
# ---------------------------------------------------------------------------

_ROMAN_RE = re.compile(r"^(Ⅰ|Ⅱ|Ⅲ|Ⅳ|Ⅴ|Ⅵ|Ⅶ|Ⅷ|Ⅸ|Ⅹ|I{1,3}|IV|VI{0,3}|IX|X)\b\.?\s*", re.IGNORECASE)
_NUM_PREFIX_RE = re.compile(r"^\d+\.?\s*")
_DECORATIVE = {"AFE", "The Best Educational Camp"}

# 템플릿 ↔ MD 헤더 간 동의어 매핑 (정규화된 형태)
_SYNONYMS: dict[str, list[str]] = {
    "실험 시 고려 사항": ["변인 통제 및 실험 환경 설정", "변인 통제", "실험 환경"],
    "실험 준비물": ["실험 재료", "실험 설계"],
}


def _normalize_header(raw: str) -> str:
    """헤더에서 로마숫자, 번호, 장식 텍스트 제거 후 핵심 키워드만 남긴다."""
    parts = raw.split(" / ")
    cleaned = []
    for p in parts:
        p = p.strip()
        if p in _DECORATIVE:
            continue
        if p.isdigit():
            continue
        p = _ROMAN_RE.sub("", p)
        p = _NUM_PREFIX_RE.sub("", p)
        p = p.strip()
        if p:
            cleaned.append(p)
    return " ".join(cleaned).lower()


def _word_set(s: str) -> set[str]:
    return set(s.split())


def match_sections(
    tmpl_sections: list[dict],
    md_sections: list[dict],
) -> list[tuple[dict, dict | None]]:
    """템플릿 섹션에 가장 적합한 MD 섹션을 매칭한다.

    매칭 전략:
    1. 정규화된 헤더의 부분문자열 포함 여부
    2. 단어 Jaccard 유사도
    3. 매칭 안 되면 None
    """
    used_md: set[int] = set()
    result: list[tuple[dict, dict | None]] = []

    for ts in tmpl_sections:
        t_norm = ts["header_norm"]
        if not t_norm:
            result.append((ts, None))
            continue

        best_idx = -1
        best_score = 0.0

        for mi, ms in enumerate(md_sections):
            if mi in used_md:
                continue
            m_norm = ms["heading_norm"]
            if not m_norm:
                continue

            # synonym check
            synonyms = _SYNONYMS.get(t_norm, [])
            if any(syn in m_norm or m_norm in syn for syn in synonyms):
                score = 0.95
            elif t_norm in m_norm or m_norm in t_norm:
                score = 1.0
            else:
                tw = _word_set(t_norm)
                mw = _word_set(m_norm)
                intersection = tw & mw
                union = tw | mw
                score = len(intersection) / len(union) if union else 0.0

            if score > best_score:
                best_score = score
                best_idx = mi

        if best_score >= 0.3 and best_idx >= 0:
            used_md.add(best_idx)
            result.append((ts, md_sections[best_idx]))
        else:
            result.append((ts, None))

    return result


# ---------------------------------------------------------------------------
# 4. 섹션별 콘텐츠 주입
# ---------------------------------------------------------------------------

def _para_text(block: ParagraphBlock) -> str:
    return "".join(i.text for i in block.inlines if isinstance(i, TextInline))


def inject_section(tmpl_paras: list[ParagraphBlock], md_texts: list[str]) -> int:
    """템플릿 단락들에 MD 텍스트를 주입한다.

    - 텍스트가 있는 기존 단락만 교체 대상으로 삼는다.
    - 단락 수가 부족하면 마지막 단락에 나머지를 합쳐 넣는다.
    - 단락 수가 남으면 빈 문자열로 클리어한다.

    Returns: 주입된 텍스트 수
    """
    if not md_texts:
        return 0

    # 텍스트가 있는 단락만 교체 대상
    writable = [p for p in tmpl_paras if _para_text(p).strip()]
    if not writable:
        # 텍스트 없으면 모든 단락을 대상으로
        writable = tmpl_paras

    if not writable:
        return 0

    n = min(len(writable), len(md_texts))
    for i in range(n):
        _set_para_text(writable[i], md_texts[i])

    # MD 텍스트가 더 많으면 마지막 단락에 합침
    if len(md_texts) > len(writable):
        extra = "\n\n".join(md_texts[len(writable):])
        existing = _para_text(writable[-1])
        _set_para_text(writable[-1], existing + "\n\n" + extra)

    # 템플릿 단락이 더 많으면 남는 단락 비우기
    for i in range(n, len(writable)):
        _set_para_text(writable[i], "")

    return len(md_texts)


def _set_para_text(para: ParagraphBlock, text: str) -> None:
    """단락의 첫 인라인 텍스트를 교체한다. 없으면 새로 생성."""
    if para.inlines:
        para.inlines[0] = TextInline(text=text)
        # 나머지 TextInline 제거 (서식 유지를 위해 첫 인라인만 사용)
        para.inlines = [para.inlines[0]]
    else:
        para.inlines = [TextInline(text=text)]


# ---------------------------------------------------------------------------
# 5. 메인 실행
# ---------------------------------------------------------------------------

def run_e2e_matched(case_dir: pathlib.Path, output_path: pathlib.Path) -> dict:
    result: dict = {}

    # 1. 파일 찾기
    hwp_candidates = list(case_dir.glob("attachments/*.hwp"))
    if not hwp_candidates:
        hwp_candidates = list(case_dir.rglob("*.hwp"))
    hwp_path = hwp_candidates[0] if hwp_candidates else None
    if not hwp_path:
        print("[ERROR] HWP 템플릿 없음")
        return {"status": "FAIL", "reason": "HWP 없음"}

    md_path = None
    for name in ("draft_report.md", "draft.md"):
        p = case_dir / name
        if p.exists():
            md_path = p
            break
    if not md_path:
        md_candidates = list(case_dir.rglob("*.md"))
        md_path = md_candidates[0] if md_candidates else None
    if not md_path:
        print("[ERROR] MD 드래프트 없음")
        return {"status": "FAIL", "reason": "MD 없음"}

    # 2. 파싱
    print(f"[1] 템플릿: {hwp_path.name}")
    tmpl = udf.parse(str(hwp_path))
    print(f"    {len(tmpl.blocks)} 블록, verbatim={tmpl.verbatim is not None}")

    print(f"[2] 드래프트: {md_path.name}")
    md_doc = udf.parse(str(md_path))

    # 3. 섹션 추출
    tmpl_sections = extract_template_sections(tmpl.blocks)
    md_sections = extract_md_sections(md_doc)

    print(f"\n[3] 템플릿 섹션 {len(tmpl_sections)}개:")
    for s in tmpl_sections:
        para_count = len(s["paras"])
        text_count = sum(1 for p in s["paras"] if _para_text(p).strip())
        print(f"    \"{s['header_norm']}\" → 단락 {para_count}개 (텍스트 {text_count}개)")

    print(f"\n[4] MD 섹션 {len(md_sections)}개:")
    for s in md_sections:
        print(f"    \"{s['heading_norm']}\" (L{s['level']}) → {len(s['paragraphs'])} 단락")

    # 4. 매칭
    matches = match_sections(tmpl_sections, md_sections)
    print(f"\n[5] 섹션 매칭:")
    total_injected = 0
    matched_count = 0
    unmatched = []
    for ts, ms in matches:
        if ts.get("structured"):
            print(f"    ▶ \"{ts['header_norm']}\" → 구조화된 표, 건너뜀")
            continue
        if ms:
            matched_count += 1
            texts = ms["paragraphs"] if ms["paragraphs"] else ms.get("paragraphs_deep", [])
            injected = inject_section(ts["paras"], texts)
            total_injected += injected
            src = "deep" if not ms["paragraphs"] and texts else "direct"
            print(f"    ✓ \"{ts['header_norm']}\" ← \"{ms['heading_norm']}\" ({injected} 텍스트, {src})")
        else:
            unmatched.append(ts["header_norm"])
            print(f"    ✗ \"{ts['header_norm']}\" → 매칭 없음")

    result["matched"] = matched_count
    result["unmatched"] = len(unmatched)
    result["total_injected"] = total_injected

    # 5. 렌더링
    print(f"\n[6] HWP 렌더링 → {output_path}")
    try:
        udf.render(tmpl, "hwp", output_path=str(output_path))
        fsize = output_path.stat().st_size
        print(f"    성공: {fsize:,} bytes")
        result["render_ok"] = True
        result["output_size"] = fsize
    except Exception as e:
        print(f"    실패: {e}")
        result["render_ok"] = False
        result["render_error"] = str(e)
        return result

    # 6. 재파싱 검증
    print("\n[7] 재파싱 검증")
    rt = udf.parse(str(output_path))
    print(f"    블록: {len(tmpl.blocks)} → {len(rt.blocks)}")

    # 재파싱 결과에서 주입된 텍스트 확인
    rt_sections = extract_template_sections(rt.blocks)
    rt_matches = match_sections(rt_sections, md_sections)

    verified = 0
    verify_fail = 0
    for ts, ms in rt_matches:
        if ms and ms["paragraphs"]:
            first_md = ms["paragraphs"][0][:30]
            rt_texts = [_para_text(p) for p in ts["paras"]]
            if any(first_md in t for t in rt_texts):
                verified += 1
            else:
                verify_fail += 1
                print(f"    [경고] \"{ts['header_norm']}\": 첫 텍스트 미발견 \"{first_md[:40]}...\"")

    result["verified"] = verified
    result["verify_fail"] = verify_fail

    # 7. 요약
    print(f"\n{'='*60}")
    print(f"매칭: {matched_count}/{len(tmpl_sections)} 섹션")
    print(f"주입: {total_injected} 텍스트")
    print(f"검증: {verified}/{verified + verify_fail} 섹션 텍스트 확인")
    if verify_fail == 0 and result["render_ok"]:
        print("결과: PASS")
        result["status"] = "PASS"
    else:
        print(f"결과: PARTIAL ({verify_fail}건 미확인)")
        result["status"] = "PARTIAL"
    print(f"{'='*60}")

    return result


# ---------------------------------------------------------------------------
# 6. HTML 비교 페이지 생성
# ---------------------------------------------------------------------------

def generate_compare_html(
    hwp_path: pathlib.Path,
    filled_path: pathlib.Path,
    output_dir: pathlib.Path,
    case_name: str,
) -> pathlib.Path | None:
    """원본과 채운 HWP를 각각 HTML로 렌더하고 비교 페이지를 생성한다."""
    try:
        orig_html = output_dir / f"{case_name}_원본.html"
        filled_html = output_dir / f"{case_name}_채움.html"

        orig_doc = udf.parse(str(hwp_path))
        orig_result = udf.render(orig_doc, "html")
        orig_html.write_text(orig_result, encoding="utf-8")

        filled_doc = udf.parse(str(filled_path))
        filled_result = udf.render(filled_doc, "html")
        filled_html.write_text(filled_result, encoding="utf-8")

        compare_path = output_dir / f"{case_name}_compare.html"
        compare_path.write_text(f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{case_name} — 섹션 매칭 비교</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f5f5f5; }}
h1 {{ text-align: center; }}
.frames {{ display: flex; height: 900px; }}
.frame-col {{ flex: 1; display: flex; flex-direction: column; border: 1px solid #ddd; }}
.frame-label {{ text-align: center; padding: 8px; background: #333; color: white; font-weight: bold; }}
iframe {{ flex: 1; border: none; }}
</style>
</head>
<body>
<h1>{case_name} — 섹션 매칭 채우기 결과</h1>
<div class="frames">
  <div class="frame-col">
    <div class="frame-label">원본 템플릿 (SMP 인공근육)</div>
    <iframe src="{orig_html.name}"></iframe>
  </div>
  <div class="frame-col">
    <div class="frame-label">드래프트 주입 (Synechococcus 바이오미네랄)</div>
    <iframe src="{filled_html.name}"></iframe>
  </div>
</div>
</body>
</html>""", encoding="utf-8")
        return compare_path
    except Exception as e:
        print(f"    [경고] HTML 비교 생성 실패: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="E2E HWP 양식 섹션 매칭 채우기")
    parser.add_argument(
        "case_dir",
        nargs="?",
        default="tests/fixtures/codex_cases/AFE실험_임운택",
    )
    parser.add_argument("--output", default="/tmp/udf_e2e_matched/filled.hwp")
    parser.add_argument("--compare", action="store_true", help="HTML 비교 페이지 생성")
    args = parser.parse_args()

    case_dir = pathlib.Path(args.case_dir)
    if not case_dir.is_absolute():
        case_dir = pathlib.Path(__file__).resolve().parent.parent / case_dir

    output_path = pathlib.Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = run_e2e_matched(case_dir, output_path)

    if args.compare and result.get("render_ok"):
        hwp_candidates = list(case_dir.glob("attachments/*.hwp"))
        if not hwp_candidates:
            hwp_candidates = list(case_dir.rglob("*.hwp"))
        if hwp_candidates:
            compare = generate_compare_html(
                hwp_candidates[0],
                output_path,
                output_path.parent,
                case_dir.name,
            )
            if compare:
                print(f"\n비교 페이지: {compare}")


if __name__ == "__main__":
    main()
