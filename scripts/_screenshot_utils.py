"""Screenshot comparison utilities shared by capture pipelines."""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image


def load_image(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def pixel_similarity(img_a: Image.Image, img_b: Image.Image) -> float:
    """Return 0.0–1.0 similarity (1.0 = identical) based on mean pixel difference."""
    import numpy as np

    target_size = (max(img_a.width, img_b.width), max(img_a.height, img_b.height))
    a = np.asarray(img_a.resize(target_size, Image.LANCZOS), dtype=np.float32)
    b = np.asarray(img_b.resize(target_size, Image.LANCZOS), dtype=np.float32)
    return 1.0 - float(np.mean(np.abs(a - b)) / 255.0)


def _page_number(filename: str) -> int:
    m = re.search(r"_p(\d+)\.png$", filename)
    return int(m.group(1)) if m else 0


def compare_page_dirs(
    actual_dir: str | Path, gt_dir: str | Path
) -> dict[str, float]:
    actual_dir, gt_dir = Path(actual_dir), Path(gt_dir)
    actual_files = sorted(actual_dir.glob("*_p*.png"), key=lambda p: _page_number(p.name))
    gt_files = {_page_number(p.name): p for p in gt_dir.glob("*_p*.png")}

    results: dict[str, float] = {}
    for af in actual_files:
        pn = _page_number(af.name)
        if pn in gt_files:
            results[f"p{pn}"] = pixel_similarity(load_image(af), load_image(gt_files[pn]))
        else:
            results[f"p{pn}"] = -1.0  # no GT
    return results


def print_comparison_table(doc_results: dict[str, dict[str, float]]) -> None:
    print(f"\n{'Document':<40} {'Page':<8} {'Similarity':>10}")
    print("-" * 60)
    for doc, pages in sorted(doc_results.items()):
        for page, score in sorted(pages.items()):
            label = f"{score:.4f}" if score >= 0 else "no GT"
            print(f"{doc:<40} {page:<8} {label:>10}")
    print()
