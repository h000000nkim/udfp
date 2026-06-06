"""Font metrics utilities for renderers.

Provides CSS line-height correction based on font ascender/descender ratios.
Uses freetype-py when available, falls back to safe defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

_FONT_DIRS: list[str] = []
if os.name == "posix":
    _FONT_DIRS = [
        "/System/Library/Fonts",
        "/Library/Fonts",
        os.path.expanduser("~/Library/Fonts"),
        "/usr/share/fonts",
        "/usr/local/share/fonts",
    ]
elif os.name == "nt":
    _FONT_DIRS = [
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
    ]

_FONT_NAME_TO_FILE: dict[str, str] = {
    "함초롬바탕": "HANBatang",
    "함초롬돋움": "HANDotum",
    "한컴돋움": "HANDotum",
    "한컴바탕": "HANBatang",
    "HY신명조": "HANBatang",
    "HY헤드라인M": "HANDotumB",
    "맑은 고딕": "Malgun Gothic",
    "굴림": "Gulim",
    "바탕": "HANBatang",
    "돋움": "HANDotum",
    "나눔고딕": "NanumGothic",
    "나눔명조": "NanumMyeongjo",
}

_HANCOM_FONT_DIR = "/Applications/Hancom Office HWP.app/Contents/Resources/Hnc/Shared/TTF/Install"

_FALLBACK_FONTS = [
    "AppleSDGothicNeo.ttc",
    "NotoSansCJKkr-Regular.otf",
    "NanumGothic.ttf",
    "malgun.ttf",
]


@dataclass(frozen=True)
class FontInfo:
    path: str
    face_index: int = 0
    units_per_em: int = 1000
    ascender: int = 800
    descender: int = -200
    height: int = 1000


_font_path_cache: dict[str, str | None] = {}


def find_font_path(font_name: str) -> str | None:
    if font_name in _font_path_cache:
        return _font_path_cache[font_name]

    search_names = [font_name]
    mapped = _FONT_NAME_TO_FILE.get(font_name)
    if mapped:
        search_names.append(mapped)

    search_dirs = list(_FONT_DIRS)
    if os.path.isdir(_HANCOM_FONT_DIR):
        search_dirs.insert(0, _HANCOM_FONT_DIR)

    for search in search_names:
        lower = search.lower().replace(" ", "")
        for font_dir in search_dirs:
            if not os.path.isdir(font_dir):
                continue
            for root, _dirs, files in os.walk(font_dir):
                for f in files:
                    if not f.lower().endswith((".ttf", ".otf", ".ttc")):
                        continue
                    fl = f.lower()
                    if "ext" in fl and lower not in ("ext",):
                        continue
                    if lower in fl.replace(" ", ""):
                        path = os.path.join(root, f)
                        _font_path_cache[font_name] = path
                        return path

    for fallback in _FALLBACK_FONTS:
        for font_dir in _FONT_DIRS:
            path = os.path.join(font_dir, fallback)
            if os.path.exists(path):
                _font_path_cache[font_name] = path
                return path
            sub = os.path.join(font_dir, "Supplemental", fallback)
            if os.path.exists(sub):
                _font_path_cache[font_name] = sub
                return sub

    _font_path_cache[font_name] = None
    return None


@lru_cache(maxsize=64)
def _load_face(font_path: str, face_index: int = 0) -> Any:
    import freetype
    face = freetype.Face(font_path, face_index)
    return face


def get_font_info(font_name: str) -> FontInfo:
    path = find_font_path(font_name)
    if not path:
        return FontInfo(path="", units_per_em=1000, ascender=800, descender=-200, height=1000)

    try:
        face = _load_face(path)
        return FontInfo(
            path=path,
            units_per_em=face.units_per_EM,
            ascender=face.ascender,
            descender=face.descender,
            height=face.height,
        )
    except Exception:
        return FontInfo(path=path)


@lru_cache(maxsize=128)
def compute_css_line_height_correction(font_name: str) -> float:
    """CSS line-height correction for HWP→CSS conversion.

    HWP uses bottom-aligned spacing; CSS uses half-leading.
    The correction depends on the font's ascender/descender ratio.
    Falls back to 0.95 for unknown fonts.
    """
    info = get_font_info(font_name)
    if info.units_per_em <= 0:
        return 0.95
    ascent_ratio = info.ascender / info.units_per_em
    descent_ratio = abs(info.descender) / info.units_per_em
    asymmetry = descent_ratio - (1 - ascent_ratio)
    correction = 1 - asymmetry * 0.15
    return max(0.90, min(1.0, correction))
