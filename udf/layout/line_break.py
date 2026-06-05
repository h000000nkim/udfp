"""Line-breaking engine for Korean/CJK and Western text.

Accumulates glyph widths using font_metrics, splits at word boundaries
or between CJK characters when the line exceeds the container width.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from udf.layout import LayoutLine
from udf.layout.font_metrics import measure_glyph


@dataclass
class InlineRun:
    """A segment of text with uniform style."""
    text: str
    font_name: str = "맑은 고딕"
    font_size: float = 10.0
    letter_spacing: float = 0.0
    bold: bool = False
    italic: bool = False
    inline_ref: Any = None


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        (0x2E80 <= cp <= 0x9FFF)
        or (0xAC00 <= cp <= 0xD7AF)
        or (0xF900 <= cp <= 0xFAFF)
        or (0xFE30 <= cp <= 0xFE4F)
        or (0x20000 <= cp <= 0x2FA1F)
        or (0x3000 <= cp <= 0x303F)
        or (0x3040 <= cp <= 0x30FF)
        or (0x31F0 <= cp <= 0x31FF)
        or (0xFF00 <= cp <= 0xFFEF)
    )


_NO_BREAK_BEFORE = set("!%),.:;?]}¢°·'\"†‡›℃∶、。〉》」』】〕〗〙〛！＂％＇），．：；？！］｝～")
_NO_BREAK_AFTER = set("$([{£¥·'\"‹〈《「『【〔〖〘〚＄（．［｛￡￥")


def _can_break_before(ch: str) -> bool:
    if ch in _NO_BREAK_BEFORE:
        return False
    return True


def _can_break_after(ch: str) -> bool:
    if ch in _NO_BREAK_AFTER:
        return False
    return True


def break_into_lines(
    runs: list[InlineRun],
    container_width: float,
    line_height_ratio: float = 1.6,
    indent_first: float = 0.0,
) -> list[LayoutLine]:
    if not runs:
        return [LayoutLine(text="", width=0, height=10.0 * line_height_ratio, baseline=10.0)]

    chars: list[tuple[str, float, float, str, InlineRun]] = []
    for run in runs:
        ls = run.letter_spacing
        for ch in run.text:
            w = measure_glyph(run.font_name, run.font_size, ch) + ls
            chars.append((ch, w, run.font_size, run.font_name, run))

    if not chars:
        fs = runs[0].font_size if runs else 10.0
        return [LayoutLine(text="", width=0, height=fs * line_height_ratio, baseline=fs)]

    lines: list[LayoutLine] = []
    line_start = 0
    cursor_x = indent_first
    last_break_pos = -1
    last_break_cursor = 0.0

    i = 0
    while i < len(chars):
        ch, w, fs, fn, run = chars[i]

        if ch == '\n':
            text = "".join(c[0] for c in chars[line_start:i])
            max_fs = max((c[2] for c in chars[line_start:i]), default=fs)
            lh = max_fs * line_height_ratio
            lines.append(LayoutLine(
                text=text, width=cursor_x, height=lh, baseline=max_fs,
                x_offset=indent_first if line_start == 0 and lines == [] else 0.0,
            ))
            line_start = i + 1
            cursor_x = 0.0
            last_break_pos = -1
            i += 1
            continue

        if cursor_x + w > container_width and line_start < i:
            if last_break_pos > line_start:
                break_at = last_break_pos
                break_cursor = last_break_cursor
            else:
                break_at = i
                break_cursor = cursor_x

            text = "".join(c[0] for c in chars[line_start:break_at])
            max_fs = max((c[2] for c in chars[line_start:break_at]), default=fs)
            lh = max_fs * line_height_ratio
            lines.append(LayoutLine(
                text=text, width=break_cursor, height=lh, baseline=max_fs,
                x_offset=indent_first if not lines else 0.0,
            ))
            line_start = break_at
            while line_start < len(chars) and chars[line_start][0] == ' ':
                line_start += 1
            cursor_x = sum(c[1] for c in chars[line_start:i+1]) if line_start <= i else w
            last_break_pos = -1
            last_break_cursor = 0.0
            i = max(line_start, i)
            if i < len(chars):
                cursor_x = 0.0
                for j in range(line_start, i + 1):
                    cursor_x += chars[j][1]
            continue

        if ch == ' ':
            last_break_pos = i + 1
            last_break_cursor = cursor_x + w
        elif _is_cjk(ch):
            if i + 1 < len(chars) and _can_break_before(chars[i+1][0]):
                last_break_pos = i + 1
                last_break_cursor = cursor_x + w
            if i > line_start and _can_break_after(chars[i-1][0]):
                last_break_pos = i
                last_break_cursor = cursor_x

        cursor_x += w
        i += 1

    if line_start < len(chars):
        text = "".join(c[0] for c in chars[line_start:])
        max_fs = max((c[2] for c in chars[line_start:]), default=10.0)
        lh = max_fs * line_height_ratio
        lines.append(LayoutLine(
            text=text, width=cursor_x, height=lh, baseline=max_fs,
            x_offset=indent_first if not lines else 0.0,
        ))

    if not lines:
        fs = runs[0].font_size if runs else 10.0
        lines.append(LayoutLine(text="", width=0, height=fs * line_height_ratio, baseline=fs))

    return lines


def inlines_to_runs(inlines: list, default_font: str = "맑은 고딕",
                    default_size: float = 10.0) -> list[InlineRun]:
    runs: list[InlineRun] = []
    for il in inlines:
        if hasattr(il, "text") and il.text:
            fn = getattr(il, "font_name", None) or default_font
            fs = getattr(il, "font_size", None) or default_size
            ls = (getattr(il, "letter_spacing", None) or 0) / 100.0 * fs if getattr(il, "letter_spacing", None) else 0.0
            runs.append(InlineRun(
                text=il.text,
                font_name=fn,
                font_size=fs,
                letter_spacing=ls,
                bold=getattr(il, "bold", False) or False,
                italic=getattr(il, "italic", False) or False,
                inline_ref=il,
            ))
        elif hasattr(il, "src"):
            w = getattr(il, "width", None) or default_size * 2
            h = getattr(il, "height", None) or default_size * 2
            runs.append(InlineRun(
                text="￼",
                font_name=default_font,
                font_size=h,
                inline_ref=il,
            ))
    return runs
