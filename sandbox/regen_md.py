#!/usr/bin/env python3
"""Regenerate MD originals + MD→DOCX + MD→HWP conversions."""
from __future__ import annotations

import shutil
from pathlib import Path

import udf

FILES = Path("output/files")

MD_SOURCES = {
    "01_주식기술분석_스캔": Path.home() / "Documents/Claude/Projects/US-STOCK/daily_technical_scan_may_10_2026.md",
    "02_AFE실험_보고서": Path.home() / "Documents/Codex/2026-05-21/https-www-notion-so-36346991dbbd817bad04f8f319a512ec/draft_report_revised.md",
    "03_주식일일분석": Path.home() / "Documents/Claude/Projects/US-STOCK/Daily_Technical_Analysis_2026-05-21.md",
    "04_주식기술스코어": Path.home() / "Documents/Claude/Projects/US-STOCK/daily_technical_score_20260522.md",
    "05_물리학실험_이정민": Path.home() / "Documents/Codex/2026-05-22/https-www-notion-so-36646991dbbd81bcb622d00ad88c7550/outputs/물리학실험_이정민/final_report.md",
    "06_태양전지_보고서": Path.home() / "Documents/Codex/2026-05-21/https-www-notion-so-36546991dbbd819ea3a0e43aa18e10f2/output/동아리_활동_이찬휘_태양전지_보고서.md",
    "07_생명과학2_홍형기": Path.home() / "Documents/Codex/2026-05-22/2-https-www-notion-so-36746991dbbd819b8c38db519a4c224c/outputs/생명과학2_홍형기/final_report.md",
    "08_자율활동_이승현": Path.home() / "Documents/Codex/2026-05-22/36746991dbbd8156be6bc3c48b3938f2-https-www-notion-so-36746991dbbd8156be6bc3c48b3/outputs/자율 활동 _이승현/final.md",
    "09_미적분1_김도현": Path.home() / "Documents/Codex/2026-05-22/1-https-www-notion-so-36546991dbbd81a7bcbff1a64ad33df6/outputs/미적분1_김도현/미적분1_김도현_최종초안.md",
    "10_화학2_류은찬": Path.home() / "Documents/Codex/2026-05-22/2-https-www-notion-so-36046991dbbd81f5b7abf0e30e81d5f5/outputs/화학2_류은찬/final.md",
}


def main() -> None:
    orig_dir = FILES / "originals" / "md"
    docx_dir = FILES / "converted" / "md2docx"
    hwp_dir = FILES / "converted" / "md2hwp"

    for d in [orig_dir, docx_dir, hwp_dir]:
        d.mkdir(parents=True, exist_ok=True)

    for name, src in MD_SOURCES.items():
        if not src.exists():
            print(f"  MISSING: {name} ← {src}")
            continue

        dst_md = orig_dir / f"{name}.md"
        shutil.copy2(str(src), str(dst_md))
        print(f"  COPY: {name}.md")

        dst_docx = docx_dir / f"{name}.docx"
        try:
            udf.convert(str(dst_md), str(dst_docx))
            print(f"  OK: {name}.md → docx ({dst_docx.stat().st_size:,} bytes)")
        except Exception as e:
            print(f"  FAIL docx: {name} — {e}")

        dst_hwp = hwp_dir / f"{name}.hwp"
        try:
            udf.convert(str(dst_md), str(dst_hwp))
            print(f"  OK: {name}.md → hwp ({dst_hwp.stat().st_size:,} bytes)")
        except Exception as e:
            print(f"  FAIL hwp: {name} — {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
