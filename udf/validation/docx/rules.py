"""DOCX D-규칙 검증 함수.

D1: 필수 파트 존재 — Word가 파일을 열려면 반드시 있어야 하는 ZIP 엔트리
D2: Content_Types 일관성 — [Content_Types].xml의 Override가 실제 파트와 일치
D3: Relationships 참조 무결성 — .rels에서 참조하는 Target이 ZIP에 존재
D4: XML 네임스페이스 URI + 루트 요소 정확성
D5: 모든 XML 파트 well-formedness
D6: w:body 마지막에 w:sectPr 존재 확인

각 함수는 RuleViolation 리스트를 반환한다. 빈 리스트 = 통과.
"""

from __future__ import annotations

import posixpath
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


_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_EXPECTED_NS: dict[str, tuple[str, str]] = {
    "word/document.xml": (_W_NS, "document"),
    "word/styles.xml": (_W_NS, "styles"),
    "[Content_Types].xml": (_CT_NS, "Types"),
    "_rels/.rels": (_RELS_NS, "Relationships"),
}

_REQUIRED_PARTS = [
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
    "word/styles.xml",
    "word/_rels/document.xml.rels",
]

_REQUIRED_OVERRIDES = {
    "/word/document.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "/word/styles.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
}


def check_d1(path: str) -> list[RuleViolation]:
    """Validate D1: all mandatory ZIP entries exist.

    Word refuses to open a DOCX that lacks any of:
    [Content_Types].xml, _rels/.rels, word/document.xml,
    word/styles.xml, word/_rels/document.xml.rels.

    Parameters
    ----------
    path : str
        Path to the .docx file.

    Returns
    -------
    list[RuleViolation]
        Violations found. Empty list means D1 passes.
    """
    violations: list[RuleViolation] = []
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as e:
        return [RuleViolation("D1", "", f"ZIP 열기 실패: {e}")]

    with zf:
        names = set(zf.namelist())
        for part in _REQUIRED_PARTS:
            if part not in names:
                violations.append(RuleViolation("D1", "", f"필수 파트 누락: {part}"))
    return violations


def check_d2(path: str) -> list[RuleViolation]:
    """Validate D2: [Content_Types].xml overrides match actual ZIP entries.

    Every Override PartName in [Content_Types].xml must correspond to a
    real ZIP entry (strip leading '/'). Conversely, the mandatory overrides
    (/word/document.xml, /word/styles.xml) must be present with correct
    MIME types.

    Parameters
    ----------
    path : str
        Path to the .docx file.

    Returns
    -------
    list[RuleViolation]
        Violations found. Empty list means D2 passes.
    """
    violations: list[RuleViolation] = []
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError):
        return []

    with zf:
        names = set(zf.namelist())
        if "[Content_Types].xml" not in names:
            return []

        ct_xml = zf.read("[Content_Types].xml")
        try:
            root = etree.fromstring(ct_xml)
        except etree.XMLSyntaxError as e:
            return [RuleViolation("D2", "", f"[Content_Types].xml 파싱 실패: {e}")]

        overrides: dict[str, str] = {}
        for elem in root.findall(f"{{{_CT_NS}}}Override"):
            part = elem.get("PartName", "")
            ct = elem.get("ContentType", "")
            overrides[part] = ct
            zip_path = part.lstrip("/")
            if zip_path not in names:
                violations.append(
                    RuleViolation(
                        "D2",
                        "",
                        f"Override가 존재하지 않는 파트 참조: {part}",
                    )
                )

        for required_part, required_ct in _REQUIRED_OVERRIDES.items():
            if required_part not in overrides:
                violations.append(
                    RuleViolation(
                        "D2",
                        "",
                        f"필수 Override 누락: {required_part}",
                    )
                )
            elif overrides[required_part] != required_ct:
                violations.append(
                    RuleViolation(
                        "D2",
                        "",
                        f"잘못된 ContentType: {required_part} → "
                        f"{overrides[required_part]} (expected {required_ct})",
                    )
                )
    return violations


def check_d3(path: str) -> list[RuleViolation]:
    """Validate D3: relationship targets exist in the ZIP.

    For each .rels file, every Relationship with TargetMode != 'External'
    must point to a ZIP entry that actually exists.

    Parameters
    ----------
    path : str
        Path to the .docx file.

    Returns
    -------
    list[RuleViolation]
        Violations found. Empty list means D3 passes.
    """
    violations: list[RuleViolation] = []
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError):
        return []

    with zf:
        names = set(zf.namelist())
        rels_files = [n for n in names if n.endswith(".rels")]

        for rels_path in rels_files:
            rels_xml = zf.read(rels_path)
            try:
                root = etree.fromstring(rels_xml)
            except etree.XMLSyntaxError:
                violations.append(
                    RuleViolation("D3", "", f".rels 파싱 실패: {rels_path}")
                )
                continue

            rels_dir = (
                rels_path.rsplit("/", 1)[0].replace("_rels", "")
                if "/" in rels_path
                else ""
            )
            rels_dir = rels_dir.rstrip("/")

            for rel in root.findall(f"{{{_RELS_NS}}}Relationship"):
                target_mode = rel.get("TargetMode", "")
                if target_mode == "External":
                    continue
                target = rel.get("Target", "")
                if not target:
                    continue

                if target.startswith("/"):
                    resolved = target.lstrip("/")
                elif rels_dir:
                    resolved = posixpath.normpath(f"{rels_dir}/{target}")
                else:
                    resolved = posixpath.normpath(target)

                if resolved not in names:
                    violations.append(
                        RuleViolation(
                            "D3",
                            "",
                            f"Relationship target 누락: {rels_path} → {target} "
                            f"(resolved: {resolved})",
                        )
                    )
    return violations


def check_d4(path: str) -> list[RuleViolation]:
    """D-4: XML namespace URI and root element correctness."""
    violations: list[RuleViolation] = []
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError):
        return []

    with zf:
        names = set(zf.namelist())
        for part, (expected_ns, expected_tag) in _EXPECTED_NS.items():
            if part not in names:
                continue
            try:
                tree = etree.parse(zf.open(part))
            except etree.XMLSyntaxError:
                continue
            root = tree.getroot()
            actual_ns = etree.QName(root).namespace or ""
            actual_tag = etree.QName(root).localname
            if actual_ns != expected_ns:
                violations.append(
                    RuleViolation(
                        "D4", "", f"{part}: ns={actual_ns}, expected={expected_ns}"
                    )
                )
            if actual_tag != expected_tag:
                violations.append(
                    RuleViolation(
                        "D4",
                        "",
                        f"{part}: root=<{actual_tag}>, expected=<{expected_tag}>",
                    )
                )
    return violations


def check_d5(path: str) -> list[RuleViolation]:
    """D-5: all XML parts must be well-formed XML 1.0."""
    violations: list[RuleViolation] = []
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError):
        return []

    with zf:
        for name in zf.namelist():
            if not name.endswith(".xml") and not name.endswith(".rels"):
                continue
            try:
                etree.parse(zf.open(name))
            except etree.XMLSyntaxError as e:
                violations.append(RuleViolation("D5", "", f"{name}: {e}"))
    return violations


def check_d6(path: str) -> list[RuleViolation]:
    """D-6: w:body must end with w:sectPr."""
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError):
        return []

    with zf:
        if "word/document.xml" not in set(zf.namelist()):
            return []
        try:
            tree = etree.parse(zf.open("word/document.xml"))
        except etree.XMLSyntaxError:
            return []
        body = tree.find(f"{{{_W_NS}}}body")
        if body is None:
            return [RuleViolation("D6", "", "w:body 요소 없음")]
        children = list(body)
        if not children or etree.QName(children[-1]).localname != "sectPr":
            return [RuleViolation("D6", "", "w:body 마지막에 w:sectPr 없음", "warning")]
    return []


@dataclass
class DocxValidationReport:
    """Aggregated result of D1-D6 validation checks."""

    d1: list[RuleViolation] = field(default_factory=list)
    d2: list[RuleViolation] = field(default_factory=list)
    d3: list[RuleViolation] = field(default_factory=list)
    d4: list[RuleViolation] = field(default_factory=list)
    d5: list[RuleViolation] = field(default_factory=list)
    d6: list[RuleViolation] = field(default_factory=list)

    @property
    def all_violations(self) -> list[RuleViolation]:
        return self.d1 + self.d2 + self.d3 + self.d4 + self.d5 + self.d6

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.all_violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.all_violations if v.severity == "warning")

    def is_passing(self) -> bool:
        return self.error_count == 0 and self.warning_count == 0


def validate_docx(path: str) -> DocxValidationReport:
    """Run all DOCX D-rules (D1-D6) and return a consolidated report.

    Parameters
    ----------
    path : str
        Path to the .docx file to validate.

    Returns
    -------
    DocxValidationReport
        Report containing violations for each rule.
    """
    return DocxValidationReport(
        d1=check_d1(path),
        d2=check_d2(path),
        d3=check_d3(path),
        d4=check_d4(path),
        d5=check_d5(path),
        d6=check_d6(path),
    )
