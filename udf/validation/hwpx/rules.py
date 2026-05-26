"""HWPX HX-규칙 검증 함수.

HX1: mimetype 엔트리가 ZIP 첫 번째 + 비압축(STORED) + 정확한 내용
HX2: 필수 파트 존재 — 한글이 파일을 열려면 반드시 있어야 하는 ZIP 엔트리
HX3: manifest(content.hpf) ↔ 실제 ZIP 엔트리 일관성
HX4: header.xml 필수 구조 — fontfaces, charPr, paraPr, style 최소 1개씩

각 함수는 RuleViolation 리스트를 반환한다. 빈 리스트 = 통과.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from typing import Literal

from lxml import etree


@dataclass
class RuleViolation:
    rule_id: str
    block_id: str
    message: str
    severity: Literal["error", "warning"] = "error"


_MIMETYPE_CONTENT = b"application/hwp+zip"

_REQUIRED_PARTS = [
    "mimetype",
    "version.xml",
    "META-INF/container.xml",
    "Contents/content.hpf",
    "Contents/header.xml",
]

_OPF_NS = "http://www.idpf.org/2007/opf/"
_HH_NS = "http://www.hancom.co.kr/hwpml/2011/head"

_REQUIRED_FONTFACE_LANGS = {"hangul", "latin", "hanja", "japanese", "other", "symbol", "user"}


def check_hx1(path: str) -> list[RuleViolation]:
    """Validate HX1: mimetype entry is first, uncompressed, and correct.

    한글 is very strict about the mimetype entry: it must be the first
    entry in the ZIP, use ZIP_STORED (no compression), and contain
    exactly 'application/hwp+zip'.

    Parameters
    ----------
    path : str
        Path to the .hwpx file.

    Returns
    -------
    list[RuleViolation]
        Violations found. Empty list means HX1 passes.
    """
    violations: list[RuleViolation] = []
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as e:
        return [RuleViolation("HX1", "", f"ZIP 열기 실패: {e}")]

    with zf:
        infolist = zf.infolist()
        if not infolist:
            return [RuleViolation("HX1", "", "ZIP이 비어 있음")]

        first = infolist[0]
        if first.filename != "mimetype":
            violations.append(
                RuleViolation(
                    "HX1", "",
                    f"첫 번째 엔트리가 mimetype이 아님: {first.filename}",
                )
            )

        mi = None
        for info in infolist:
            if info.filename == "mimetype":
                mi = info
                break

        if mi is None:
            violations.append(RuleViolation("HX1", "", "mimetype 엔트리 없음"))
            return violations

        if mi.compress_type != zipfile.ZIP_STORED:
            violations.append(
                RuleViolation(
                    "HX1", "",
                    f"mimetype이 비압축(STORED)이 아님: compress_type={mi.compress_type}",
                )
            )

        content = zf.read("mimetype")
        if content != _MIMETYPE_CONTENT:
            violations.append(
                RuleViolation(
                    "HX1", "",
                    f"mimetype 내용 불일치: {content!r} (expected {_MIMETYPE_CONTENT!r})",
                )
            )

    return violations


def check_hx2(path: str) -> list[RuleViolation]:
    """Validate HX2: all mandatory ZIP entries exist.

    한글 requires: mimetype, version.xml, META-INF/container.xml,
    Contents/content.hpf, Contents/header.xml, and at least one
    Contents/section*.xml.

    Parameters
    ----------
    path : str
        Path to the .hwpx file.

    Returns
    -------
    list[RuleViolation]
        Violations found. Empty list means HX2 passes.
    """
    violations: list[RuleViolation] = []
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError):
        return []

    with zf:
        names = set(zf.namelist())
        for part in _REQUIRED_PARTS:
            if part not in names:
                violations.append(
                    RuleViolation("HX2", "", f"필수 파트 누락: {part}")
                )

        has_section = any(
            n.startswith("Contents/section") and n.endswith(".xml")
            for n in names
        )
        if not has_section:
            violations.append(
                RuleViolation("HX2", "", "Contents/section*.xml 없음 (최소 1개 필요)")
            )

    return violations


def check_hx3(path: str) -> list[RuleViolation]:
    """Validate HX3: content.hpf manifest matches actual ZIP entries.

    Every item in the OPF manifest must have a corresponding ZIP entry,
    and every Contents/section*.xml in the ZIP must appear in the manifest.

    Parameters
    ----------
    path : str
        Path to the .hwpx file.

    Returns
    -------
    list[RuleViolation]
        Violations found. Empty list means HX3 passes.
    """
    violations: list[RuleViolation] = []
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError):
        return []

    with zf:
        names = set(zf.namelist())
        if "Contents/content.hpf" not in names:
            return []

        hpf_xml = zf.read("Contents/content.hpf")
        try:
            root = etree.fromstring(hpf_xml)
        except etree.XMLSyntaxError as e:
            return [RuleViolation("HX3", "", f"content.hpf 파싱 실패: {e}")]

        manifest_hrefs: set[str] = set()
        for item in root.iter(f"{{{_OPF_NS}}}item"):
            href = item.get("href", "")
            if href:
                manifest_hrefs.add(href)
                if href not in names:
                    violations.append(
                        RuleViolation(
                            "HX3", "",
                            f"manifest 항목이 ZIP에 없음: {href}",
                        )
                    )

        for name in names:
            if name.startswith("Contents/section") and name.endswith(".xml"):
                if name not in manifest_hrefs:
                    violations.append(
                        RuleViolation(
                            "HX3", "",
                            f"section 파일이 manifest에 없음: {name}",
                            severity="warning",
                        )
                    )

    return violations


def check_hx4(path: str) -> list[RuleViolation]:
    """Validate HX4: header.xml contains required structural elements.

    한글 requires header.xml to have at least: fontfaces (with all 7
    language slots), one charPr, one paraPr, and one style entry.

    Parameters
    ----------
    path : str
        Path to the .hwpx file.

    Returns
    -------
    list[RuleViolation]
        Violations found. Empty list means HX4 passes.
    """
    violations: list[RuleViolation] = []
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError):
        return []

    with zf:
        names = set(zf.namelist())
        if "Contents/header.xml" not in names:
            return []

        header_xml = zf.read("Contents/header.xml")
        try:
            root = etree.fromstring(header_xml)
        except etree.XMLSyntaxError as e:
            return [RuleViolation("HX4", "", f"header.xml 파싱 실패: {e}")]

        fontfaces = root.iter(f"{{{_HH_NS}}}fontface")
        found_langs: set[str] = set()
        for ff in fontfaces:
            lang = ff.get("lang", "")
            if lang:
                found_langs.add(lang)

        missing_langs = _REQUIRED_FONTFACE_LANGS - found_langs
        if missing_langs:
            violations.append(
                RuleViolation(
                    "HX4", "",
                    f"fontface 언어 슬롯 누락: {sorted(missing_langs)}",
                )
            )

        char_prs = list(root.iter(f"{{{_HH_NS}}}charPr"))
        if not char_prs:
            violations.append(
                RuleViolation("HX4", "", "charPr 정의 없음 (최소 id=0 필요)")
            )

        para_prs = list(root.iter(f"{{{_HH_NS}}}paraPr"))
        if not para_prs:
            violations.append(
                RuleViolation("HX4", "", "paraPr 정의 없음 (최소 id=0 필요)")
            )

        styles = list(root.iter(f"{{{_HH_NS}}}style"))
        if not styles:
            violations.append(
                RuleViolation("HX4", "", "style 정의 없음 (최소 바탕글 스타일 필요)")
            )

    return violations


@dataclass
class HwpxValidationReport:
    """Aggregated result of HX1-HX4 validation checks."""

    hx1: list[RuleViolation] = field(default_factory=list)
    hx2: list[RuleViolation] = field(default_factory=list)
    hx3: list[RuleViolation] = field(default_factory=list)
    hx4: list[RuleViolation] = field(default_factory=list)

    @property
    def all_violations(self) -> list[RuleViolation]:
        return self.hx1 + self.hx2 + self.hx3 + self.hx4

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.all_violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.all_violations if v.severity == "warning")

    def is_passing(self) -> bool:
        return self.error_count == 0 and self.warning_count == 0


def validate_hwpx(path: str) -> HwpxValidationReport:
    """Run all HWPX HX-rules (HX1-HX4) and return a consolidated report.

    Parameters
    ----------
    path : str
        Path to the .hwpx file to validate.

    Returns
    -------
    HwpxValidationReport
        Report containing violations for each rule.
    """
    return HwpxValidationReport(
        hx1=check_hx1(path),
        hx2=check_hx2(path),
        hx3=check_hx3(path),
        hx4=check_hx4(path),
    )
