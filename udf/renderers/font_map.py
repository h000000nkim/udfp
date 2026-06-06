"""Font fallback mapping for HTML rendering.

Maps proprietary document fonts to OFL-licensed alternatives with
letter-spacing compensation to match character advance widths.

Compensation formula:
    letter_spacing = (source_width - fallback_width) / source_width (em)

Source metrics measured with fontTools on actual .ttf files.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FontMapping:
    fallback: str
    letter_spacing_em: float
    category: str  # "gothic" | "serif" | "mono" | "western"
    google_font: str | None = None


# ---------------------------------------------------------------------------
# Width reference (normalized advance width of '가' / UPM)
#
# Proprietary:
#   맑은 고딕, 굴림, 바탕, 돋움, 궁서, HY계열  = 1.000
#   함초롬바탕, 함초롬돋움                         = 0.970
#   한컴산뜻돋움                                  = 0.932
#
# OFL:
#   Noto Sans KR    = 0.920
#   Noto Serif KR   = 0.966
#   NanumGothic     = 0.940
#   NanumMyeongjo   = 0.950
#   NanumGothicCoding = 1.000 (monospace)
# ---------------------------------------------------------------------------

_GOTHIC_1000 = FontMapping(
    fallback="Nanum Gothic",
    letter_spacing_em=0.06,
    category="gothic",
    google_font="Nanum+Gothic:wght@400;700",
)

_SERIF_1000 = FontMapping(
    fallback="Noto Serif KR",
    letter_spacing_em=0.034,
    category="serif",
    google_font="Noto+Serif+KR:wght@400;700",
)

_HAMCHOREOM_SERIF = FontMapping(
    fallback="Noto Serif KR",
    letter_spacing_em=0.004,
    category="serif",
    google_font="Noto+Serif+KR:wght@400;700",
)

_HAMCHOREOM_GOTHIC = FontMapping(
    fallback="Nanum Gothic",
    letter_spacing_em=0.031,
    category="gothic",
    google_font="Nanum+Gothic:wght@400;700",
)

_SANTTEUTDOTUM = FontMapping(
    fallback="Noto Sans KR",
    letter_spacing_em=0.013,
    category="gothic",
    google_font="Noto+Sans+KR:wght@400;700",
)

_MONO = FontMapping(
    fallback="Nanum Gothic Coding",
    letter_spacing_em=0.0,
    category="mono",
    google_font="Nanum+Gothic+Coding",
)

_WESTERN = FontMapping(
    fallback="",
    letter_spacing_em=0.0,
    category="western",
)

_NANUM_GOTHIC = FontMapping(
    fallback="Nanum Gothic",
    letter_spacing_em=0.0,
    category="gothic",
    google_font="Nanum+Gothic:wght@400;700",
)

_NANUM_MYEONGJO = FontMapping(
    fallback="Nanum Myeongjo",
    letter_spacing_em=0.0,
    category="serif",
    google_font="Nanum+Myeongjo:wght@400;700",
)

# font name (lowercase) → FontMapping
FONT_MAP: dict[str, FontMapping] = {
    # --- Gothic, width 1.000 ---
    "맑은 고딕": _GOTHIC_1000,
    "malgun gothic": _GOTHIC_1000,
    "굴림": _GOTHIC_1000,
    "gulim": _GOTHIC_1000,
    "돋움": _GOTHIC_1000,
    "dotum": _GOTHIC_1000,
    "hy견고딕": _GOTHIC_1000,
    "hy견명조": _SERIF_1000,
    "hy신명조": _SERIF_1000,
    "hysinmyeongjo": _SERIF_1000,
    "hy헤드라인m": _GOTHIC_1000,
    "hyheadline m": _GOTHIC_1000,
    "휴먼고딕": _GOTHIC_1000,
    "한컴돋움": _GOTHIC_1000,
    "-윤고딕120": _GOTHIC_1000,
    "한컴 윤고딕 230": _GOTHIC_1000,
    "한컴 말랑말랑 regular": _GOTHIC_1000,
    "apple sd gothic neo": _GOTHIC_1000,
    "apple sd 산돌고딕 neo": _GOTHIC_1000,
    # --- Serif, width 1.000 ---
    "바탕": _SERIF_1000,
    "batang": _SERIF_1000,
    "한컴바탕": _SERIF_1000,
    "궁서": _SERIF_1000,
    "gungsuh": _SERIF_1000,
    "신명조": _SERIF_1000,
    "myungjo": _SERIF_1000,
    "휴먼명조": _SERIF_1000,
    # --- 함초롬 series, width 0.970 ---
    "함초롬바탕": _HAMCHOREOM_SERIF,
    "hcr batang": _HAMCHOREOM_SERIF,
    "함초롬돋움": _HAMCHOREOM_GOTHIC,
    "hcr dotum": _HAMCHOREOM_GOTHIC,
    # --- 한컴산뜻돋움, width 0.932 ---
    "한컴산뜻돋움": _SANTTEUTDOTUM,
    "hansantteutdotum": _SANTTEUTDOTUM,
    # --- 나눔 (already OFL, no compensation) ---
    "나눔고딕": _NANUM_GOTHIC,
    "nanum gothic": _NANUM_GOTHIC,
    "nanumgothic": _NANUM_GOTHIC,
    "나눔명조": _NANUM_MYEONGJO,
    "nanum myeongjo": _NANUM_MYEONGJO,
    "nanummyeongjo": _NANUM_MYEONGJO,
    "나눔고딕코딩": _MONO,
    "nanum gothic coding": _MONO,
    # --- Mono ---
    "고정폭": _MONO,
    "courier": _MONO,
    "courier new": _MONO,
    "consolas": _MONO,
    "d2coding": _MONO,
    # --- Western (pass-through, no fallback) ---
    "arial": _WESTERN,
    "arial unicode ms": _WESTERN,
    "times new roman": _WESTERN,
    "segoe ui": _WESTERN,
    "calibri": _WESTERN,
    "cambria": _WESTERN,
}


def lookup(font_name: str) -> FontMapping:
    """Look up fallback mapping for a font name. Case-insensitive."""
    key = font_name.strip().lower()
    if key in FONT_MAP:
        return FONT_MAP[key]
    for prefix in ("hy", "한컴", "휴먼"):
        if key.startswith(prefix):
            return _GOTHIC_1000
    return _GOTHIC_1000


def collect_google_fonts(font_names: set[str]) -> list[str]:
    """Collect unique Google Font specs needed for a set of document fonts."""
    specs: set[str] = set()
    for name in font_names:
        m = lookup(name)
        if m.google_font:
            specs.add(m.google_font)
    return sorted(specs)
