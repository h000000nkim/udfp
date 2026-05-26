#!/usr/bin/env python3
"""Demo: AI-driven HWP form filling from Markdown content.

Demonstrates three Seed Patch capabilities:
1. Text replacement — fill form fields with real content
2. CharShape override — change gray placeholder text to black
3. Table like_char toggle — allow large tables to flow across pages

Usage:
    python scripts/demo_form_fill.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import udf
from udf.core.schema import (
    ParagraphBlock,
    TableBlock,
    TextBoxBlock,
    TextInline,
)

TEMPLATE = "tests/fixtures/codex_cases/AFE실험_임운택/attachments/TalkFile_[실험] AFE 실험보고서(양식, 2026).hwp"
MD_DRAFT = "tests/fixtures/codex_cases/AFE실험_임운택/draft_report.md"
OUTPUT = "output/demo_form_filled.hwp"


def _iter_deep(blocks, depth=0):
    for b in blocks:
        yield b, depth
        if isinstance(b, TableBlock):
            for row in b.rows:
                for cell in row.cells:
                    yield from _iter_deep(cell.content, depth + 1)
        elif hasattr(b, "content") and isinstance(getattr(b, "content"), list):
            yield from _iter_deep(b.content, depth + 1)


def _get_text(block):
    if isinstance(block, ParagraphBlock):
        return "".join(i.text for i in block.inlines if isinstance(i, TextInline))
    return ""


def _set_text(block, text, color=None):
    if isinstance(block, ParagraphBlock):
        kwargs = {"text": text}
        if color:
            kwargs["color"] = color
        block.inlines = [TextInline(**kwargs)]


def main():
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)

    print("=" * 60)
    print("UDF Seed Patch Demo: MD → HWP Form Fill")
    print("=" * 60)

    # 1. Parse template and MD
    print("\n[1] Parsing template and MD draft...")
    doc = udf.parse(TEMPLATE)
    md_doc = udf.parse(MD_DRAFT)

    # Extract MD content by section
    md_sections = {}
    current_section = None
    for b, _ in _iter_deep(md_doc.blocks):
        if hasattr(b, "level") and hasattr(b, "text"):
            current_section = b.text.strip()
            md_sections[current_section] = []
        elif isinstance(b, ParagraphBlock) and current_section:
            text = _get_text(b)
            if text.strip():
                md_sections[current_section].append(text)

    print(f"   MD sections: {len(md_sections)}")
    for sec, paras in list(md_sections.items())[:8]:
        print(f"     '{sec[:50]}': {len(paras)} paragraphs")

    # 2. Map MD content to template fields
    print("\n[2] Mapping MD content to template fields...")

    changes = []

    # Field mappings: template block ID → MD section content
    # Research info table (b_0051): rows = [학교, 그룹명, 담당강사, 연구참가자]
    info_map = {
        "b_0023": "온양고등학교",    # 학교
        "b_0027": "바이오건축",       # 그룹명
        "b_0031": "김OO",            # 담당 강사
        "b_0037": "3210/임운택",     # 학번/이름
    }

    # Research period
    period_map = {
        "b_0058": "2026년 5월 1일 ~ 2026년 5월 31일",
    }

    # Keywords
    keyword_map = {
        "b_0067": md_sections.get("연구키워드", [""])[0] if "연구키워드" in md_sections else "",
    }

    # Title (currently has example text)
    title_map = {}
    for sec_name, paras in md_sections.items():
        if "탄산칼슘" in sec_name:
            title_map["b_0012"] = sec_name
            break

    all_field_maps = [info_map, period_map, keyword_map, title_map]

    for field_map in all_field_maps:
        for blk_id, new_text in field_map.items():
            if not new_text:
                continue
            for b, _ in _iter_deep(doc.blocks):
                if isinstance(b, ParagraphBlock) and b.id == blk_id:
                    old_text = _get_text(b)
                    if old_text.strip() != new_text.strip():
                        _set_text(b, new_text, color="#000000")
                        changes.append(f"  {blk_id}: '{old_text[:30]}' → '{new_text[:30]}'")
                    break

    # 3. Fill main content sections into body tables
    # The body tables contain the actual report text
    # Map by section headers found in TextBox labels
    body_section_map = {
        "연구 배경 및 목적": "연구 배경 및 목적",
        "연구 동향 및 주요 결과": "연구 동향 및 주요 결과",
    }

    body_tables = []
    for b, d in _iter_deep(doc.blocks):
        if isinstance(b, TableBlock) and d == 0:
            # Check if this table has content paragraphs
            for row in b.rows:
                for cell in row.cells:
                    for cb in cell.content:
                        if isinstance(cb, ParagraphBlock):
                            text = _get_text(cb)
                            if len(text) > 50:
                                body_tables.append((b, text[:40]))
                                break

    content_sections = ["연구 배경 및 목적", "연구 동향 및 주요 결과"]
    body_table_idx = 0
    for tbl, preview in body_tables:
        if body_table_idx >= len(content_sections):
            break
        sec_name = content_sections[body_table_idx]
        md_paras = md_sections.get(sec_name, [])
        if not md_paras:
            body_table_idx += 1
            continue

        combined_text = "\n".join(md_paras)

        for row in tbl.rows:
            for cell in row.cells:
                content_paras = [
                    cb for cb in cell.content
                    if isinstance(cb, ParagraphBlock) and _get_text(cb).strip()
                ]
                if content_paras:
                    _set_text(content_paras[0], combined_text, color="#000000")
                    for extra in content_paras[1:]:
                        _set_text(extra, "", color="#000000")
                    changes.append(f"  TABLE {tbl.id} ← MD section '{sec_name[:30]}'")
                    break

        body_table_idx += 1

    # 4. Demo: CharShape override (gray → black)
    print("\n[3] Applying CharShape overrides (gray → black)...")
    gray_count = 0
    for b, _ in _iter_deep(doc.blocks):
        if isinstance(b, ParagraphBlock):
            for i in b.inlines:
                if isinstance(i, TextInline) and str(getattr(i, "color", "")) == "#999999":
                    i.color = "#000000"
                    gray_count += 1
    print(f"   Changed {gray_count} gray text spans to black")

    # 5. Demo: Table like_char toggle
    print("\n[4] Toggling like_char on large content tables...")
    toggled_ids: set[str] = set()
    for b, _ in _iter_deep(doc.blocks):
        if isinstance(b, TableBlock) and b.position:
            total_text = 0
            for row in b.rows:
                for cell in row.cells:
                    for cb in cell.content:
                        if isinstance(cb, ParagraphBlock):
                            total_text += len(_get_text(cb))

            if total_text > 200 and b.position.like_char:
                b.position.like_char = False
                toggled_ids.add(b.id)
                changes.append(f"  TABLE {b.id} like_char=True → False (text={total_text} chars)")

    print(f"   Toggled {len(toggled_ids)} tables from like_char=True → False")

    # 6. Render
    print(f"\n[5] Rendering to {OUTPUT}...")
    for c in changes:
        print(c)

    udf.render(doc, "hwp", OUTPUT)
    size = os.path.getsize(OUTPUT)
    print(f"\n   Output: {size:,} bytes ({size/1024/1024:.1f} MB)")

    # 7. Verify
    print("\n[6] Verification...")
    doc2 = udf.parse(OUTPUT)
    print(f"   Blocks: {len(doc2.blocks)}")

    verify_ok = True
    for blk_id, expected in list(info_map.items())[:2]:
        for b, _ in _iter_deep(doc2.blocks):
            if isinstance(b, ParagraphBlock) and b.id == blk_id:
                actual = _get_text(b)
                status = "PASS" if expected in actual else "FAIL"
                if status == "FAIL":
                    verify_ok = False
                print(f"   [{status}] {blk_id}: expected '{expected[:30]}', got '{actual[:30]}'")
                break

    # Verify gray → black
    gray_after = 0
    for b, _ in _iter_deep(doc2.blocks):
        if isinstance(b, ParagraphBlock):
            for i in b.inlines:
                if isinstance(i, TextInline) and str(getattr(i, "color", "")) == "#999999":
                    gray_after += 1
    status = "PASS" if gray_after == 0 else "FAIL"
    if gray_after > 0:
        verify_ok = False
    print(f"   [{status}] Gray text spans remaining: {gray_after}")

    # Verify like_char toggle: no large tables should have like_char=True
    large_with_like_char = 0
    large_total = 0
    for b, _ in _iter_deep(doc2.blocks):
        if isinstance(b, TableBlock) and b.position:
            total_text = 0
            for row in b.rows:
                for cell in row.cells:
                    for cb in cell.content:
                        if isinstance(cb, ParagraphBlock):
                            total_text += len(_get_text(cb))
            if total_text > 200:
                large_total += 1
                if b.position.like_char:
                    large_with_like_char += 1
    status = "PASS" if large_with_like_char == 0 else "FAIL"
    if large_with_like_char > 0:
        verify_ok = False
    print(f"   [{status}] Large tables with like_char=True remaining: {large_with_like_char}/{large_total}")

    print("\n" + "=" * 60)
    print(f"RESULT: {'ALL PASS' if verify_ok else 'SOME FAILURES'}")
    print("=" * 60)

    return 0 if verify_ok else 1


if __name__ == "__main__":
    sys.exit(main())
