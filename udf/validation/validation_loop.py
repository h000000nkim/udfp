"""검증-자동수정 루프.

생성된 HWP의 섹션 스트림에 R-규칙 검증 → 위반 시 fixer 적용 → 재파싱 → 재검증을
최대 max_iterations까지 반복한다. 수렴하면 통과한 문서를 반환한다.
"""

from __future__ import annotations

import base64

from udf.core.schema import UdfDocument
from udf.validation.hwp.fixers import ALL_FIXERS
from udf.validation.hwp.rules import ValidationReport, validate_hwp


def validate_and_fix(
    doc: UdfDocument,
    max_iterations: int = 5,
) -> tuple[UdfDocument, ValidationReport]:
    """Run R-rule validation with auto-fix loop until convergence.

    Repeatedly validates the document against R1-R4 rules, applies
    automatic fixers to the section streams, reparses, and revalidates
    until all rules pass or the iteration limit is reached.

    Parameters
    ----------
    doc : UdfDocument
        HWP parsed document. Must have a verbatim layer with
        ``section_streams`` populated.
    max_iterations : int, default 5
        Maximum number of fix-revalidate iterations.

    Returns
    -------
    tuple[UdfDocument, ValidationReport]
        The (possibly fixed) document and the final validation report.
        If no fixes were needed, the original document is returned.
    """
    from udf.parsers.hwp.parse import parse_hwp as _reparse

    report = validate_hwp(doc)
    if report.is_passing():
        return doc, report

    if doc.verbatim is None or not doc.verbatim.section_streams:
        return doc, report

    for _ in range(max_iterations):
        streams_changed = False

        for section_name, b64 in doc.verbatim.section_streams.items():
            stream = base64.b64decode(b64)
            fixed = stream
            for fixer in ALL_FIXERS:
                fixed = fixer(fixed)
            if fixed != stream:
                doc.verbatim.section_streams[section_name] = base64.b64encode(
                    fixed
                ).decode()
                streams_changed = True

        if not streams_changed:
            break

        # 재파싱: 수정된 section_streams로 Document Model 재구성
        doc = _reparse_from_streams(doc)
        report = validate_hwp(doc)
        if report.is_passing():
            break

    return doc, report


def _reparse_from_streams(doc: UdfDocument) -> UdfDocument:
    """Reparse blocks from modified section_streams in memory."""
    import base64
    from typing import Any

    from udf.pipeline.verbatim import GlobalResources, VerbatimBlock, VerbatimLayer
    from udf.parsers.hwp.body import parse_section
    from udf.parsers.hwp.doc_info import DocInfoResult

    assert doc.verbatim is not None

    gr = doc.verbatim.global_resources
    if not isinstance(gr, GlobalResources):
        gr = GlobalResources.model_construct(**gr.model_dump())
    info = DocInfoResult(global_resources=gr)

    all_blocks: list[Any] = []
    all_verbatim: dict[str, VerbatimBlock] = {}
    all_section_streams: dict[str, str] = {}

    sorted_sections = sorted(
        doc.verbatim.section_streams.items(),
        key=lambda kv: _section_sort_key(kv[0]),
    )

    for section_name, b64 in sorted_sections:
        data = base64.b64decode(b64)
        all_section_streams[section_name] = b64
        blocks, verb_map = parse_section(data, info, section=section_name)
        all_blocks.extend(blocks)
        all_verbatim.update(verb_map)

    verbatim_layer = VerbatimLayer(
        format="hwp",
        blocks=all_verbatim,
        global_resources=doc.verbatim.global_resources,
        section_streams=all_section_streams,
        bindata_streams=getattr(doc.verbatim, 'bindata_streams', {}) or {},
    )

    doc.blocks = all_blocks
    doc.verbatim = verbatim_layer
    return doc


def _section_sort_key(name: str) -> int:
    """Extract numeric sort key from a section name like 'Section0'."""
    stripped = name.replace("Section", "")
    try:
        return int(stripped)
    except ValueError:
        return 0
