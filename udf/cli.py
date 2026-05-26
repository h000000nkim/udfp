"""UDF CLI — command-line interface for the Universal Document Format library.

Subcommands
-----------
convert    Convert a document to another format.
patch      Apply Markdown edits back to an HWP file (Seed Patch).
validate   Check HWP structural integrity via R-rules (R-규칙).
diff       Semantic comparison of two documents.
info       List supported formats and their capabilities.
inspect    Print a structural summary of a document.

Entry point is registered as ``udf`` in pyproject.toml console_scripts.
"""

from __future__ import annotations

import argparse
import sys


def _cmd_convert(args: argparse.Namespace) -> int:
    """Convert a document to another format."""
    import udf

    try:
        doc = udf.parse(args.input)
    except Exception as e:
        print(f"파싱 실패: {e}", file=sys.stderr)
        return 1

    if getattr(args, "format", None):
        out_fmt = args.format
    elif args.output:
        from pathlib import Path
        from udf.formats import get_registry
        ext = Path(args.output).suffix.lower()
        out_fmt = get_registry().detect_by_ext(ext)
        if out_fmt is None:
            print(f"출력 포맷을 감지할 수 없음: {args.output}", file=sys.stderr)
            return 1
    else:
        out_fmt = "md"

    try:
        from udf.formats import get_registry
        spec = get_registry().get(out_fmt)
        if spec is None:
            print(f"지원하지 않는 포맷: {out_fmt}", file=sys.stderr)
            return 1

        kwargs = {}
        if hasattr(args, "embed_ids") and args.embed_ids:
            kwargs["embed_ids"] = True

        result = udf.render(doc, out_fmt, output_path=args.output, **kwargs)
    except ValueError as e:
        print(f"렌더링 실패: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"렌더링 실패: {e}", file=sys.stderr)
        return 1

    if result is not None:
        if args.output:
            try:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(result)
            except OSError as e:
                print(f"파일 쓰기 실패: {e}", file=sys.stderr)
                return 1
        else:
            print(result)
    else:
        if args.output:
            print(f"출력: {args.output}")
    return 0


def _cmd_patch(args: argparse.Namespace) -> int:
    """Apply Markdown edits back to an HWP file via Seed Patch."""
    from udf.renderers.hwp import patch_hwp_from_md

    try:
        with open(args.md, encoding="utf-8") as f:
            md_content = f.read()
    except OSError as e:
        print(f"MD 파일 읽기 실패: {e}", file=sys.stderr)
        return 1

    try:
        report = patch_hwp_from_md(args.input, md_content, args.output)
    except Exception as e:
        print(f"패치 실패: {e}", file=sys.stderr)
        return 1

    if not report.is_roundtrip_safe:
        unintended = [
            b for b in report.lossy_blocks if b.loss_type.value == "unintended"
        ]
        print(f"경고: 비의도 손실 {len(unintended)}건", file=sys.stderr)
        for b in unintended:
            print(f"  [{b.block_id}] {b.description}", file=sys.stderr)

    print(f"출력: {args.output} (손실 블록: {len(report.lossy_blocks)})")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate HWP structural integrity via R-rules."""
    from udf.parsers.hwp.parse import parse_hwp
    from udf.validation.hwp.rules import validate_hwp

    try:
        doc = parse_hwp(args.input)
    except Exception as e:
        print(f"파싱 실패: {e}", file=sys.stderr)
        return 1

    report = validate_hwp(doc)
    if report.is_passing():
        print(f"통과: {args.input}")
        return 0
    else:
        print(f"실패: {args.input}", file=sys.stderr)
        for v in report.all_violations:
            print(f"  [{v.rule_id}] {v.block_id}: {v.message}", file=sys.stderr)
        return 1


def _cmd_diff(args: argparse.Namespace) -> int:
    """Perform a semantic diff between two documents."""
    import udf

    try:
        orig = udf.parse(args.a)
        result = udf.parse(args.b)
    except Exception as e:
        print(f"파싱 실패: {e}", file=sys.stderr)
        return 1

    report = udf.diff(orig, result)
    if report.is_roundtrip_safe and not report.lossy_blocks:
        print("동일: 시맨틱 차이 없음")
        return 0
    else:
        print(f"차이 {len(report.lossy_blocks)}건:")
        for b in report.lossy_blocks:
            print(f"  [{b.loss_type.value}] {b.block_id}: {b.description}")
        return 0 if report.is_roundtrip_safe else 1


def _cmd_info(args: argparse.Namespace) -> int:
    """Print supported format information."""
    from udf.formats import get_registry

    registry = get_registry()
    formats = registry.list()

    print("UDF — Universal Document Format")
    print()
    print(f"  지원 포맷: {len(formats)}개")
    print()
    print(f"  {'포맷':<8} {'확장자':<16} {'파서':^6} {'렌더러':^6} {'라운드트립':^10}")
    print(f"  {'─'*8} {'─'*16} {'─'*6} {'─'*6} {'─'*10}")
    for spec in formats:
        exts = ", ".join(spec.extensions)
        parse_mark = "O" if spec.parser else "-"
        render_mark = "O" if spec.renderer else "-"
        rt_mark = "O" if spec.roundtrip else "-"
        print(f"  {spec.name:<8} {exts:<16} {parse_mark:^6} {render_mark:^6} {rt_mark:^10}")

    if args.format:
        fmt = args.format.lower().strip()
        spec = registry.get(fmt)
        if spec is None:
            print(f"\n  알 수 없는 포맷: {fmt}")
            return 1
        print(f"\n  [{spec.name}] 상세:")
        print(f"    MIME: {', '.join(spec.mime_types) if spec.mime_types else '(없음)'}")
        print(f"    바이너리: {'예' if spec.is_binary else '아니오'}")
        if spec.parser:
            print(f"    파서: {spec.parser}")
        if spec.renderer:
            print(f"    렌더러: {spec.renderer}")

    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    """Print a structural summary of a document."""
    import udf

    try:
        doc = udf.parse(args.input)
    except Exception as e:
        print(f"파싱 실패: {e}", file=sys.stderr)
        return 1

    print(f"파일: {args.input}")
    print(f"포맷: {doc.source_format}")
    if doc.metadata:
        if doc.metadata.title:
            print(f"제목: {doc.metadata.title}")
        if doc.metadata.author:
            print(f"작성자: {doc.metadata.author}")
    print(f"블록: {len(doc.blocks)}개")

    from collections import Counter
    type_counts = Counter(b.type for b in doc.blocks)
    for btype, count in type_counts.most_common():
        print(f"  {btype}: {count}")

    if doc.loss_report:
        lr = doc.loss_report
        print(f"손실: {lr.total_blocks}블록 중 {len(lr.lossy_blocks)}건 손실")
        if lr.dropped_features:
            print(f"미지원 기능: {len(lr.dropped_features)}건")

    if args.json:
        print()
        print(doc.to_json())

    return 0


def main() -> None:
    """CLI entry point — parse args, dispatch to the appropriate subcommand."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        prog="udf",
        description="Universal Document Format Protocol CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # convert
    p_convert = sub.add_parser("convert", help="문서를 다른 포맷으로 변환")
    p_convert.add_argument("input", help="입력 파일")
    p_convert.add_argument("-o", "--output", help="출력 파일 (기본: stdout)")
    p_convert.add_argument("-f", "--format", help="출력 포맷 (기본: 확장자 감지 또는 md)")
    p_convert.add_argument(
        "--embed-ids", action="store_true", help="블록 ID 주석 삽입"
    )

    # patch
    p_patch = sub.add_parser("patch", help="MD 편집 내용을 HWP에 패치")
    p_patch.add_argument("input", help="원본 HWP 파일")
    p_patch.add_argument("--md", required=True, help="편집된 MD 파일")
    p_patch.add_argument("-o", "--output", required=True, help="출력 HWP 파일")

    # validate
    p_validate = sub.add_parser("validate", help="HWP 구조 정합성 검증 (R-규칙)")
    p_validate.add_argument("input", help="검증할 HWP 파일")

    # diff
    p_diff = sub.add_parser("diff", help="두 문서 시맨틱 비교")
    p_diff.add_argument("a", help="첫 번째 파일")
    p_diff.add_argument("b", help="두 번째 파일")
    p_diff.add_argument(
        "--semantic", action="store_true", help="(기본값, 항상 시맨틱 비교)"
    )

    # info
    p_info = sub.add_parser("info", help="지원 포맷 정보 출력")
    p_info.add_argument("format", nargs="?", help="특정 포맷 상세 (예: hwp)")

    # inspect
    p_inspect = sub.add_parser("inspect", help="문서 구조 요약")
    p_inspect.add_argument("input", help="분석할 파일")
    p_inspect.add_argument("--json", action="store_true", help="UDF JSON 출력")

    args = parser.parse_args()

    handlers = {
        "convert": _cmd_convert,
        "patch": _cmd_patch,
        "validate": _cmd_validate,
        "diff": _cmd_diff,
        "info": _cmd_info,
        "inspect": _cmd_inspect,
    }
    rc = handlers[args.command](args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
