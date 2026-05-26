"""udfp — UDF 문서를 AI가 읽고 편집할 수 있는 MCP 서버."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="udfp",
        description="MCP server for reading, editing, and rendering documents via UDF",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if sys.stderr.encoding != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    try:
        from udfp.server import create_server
    except ImportError:
        print(
            "Error: udfp requires the 'mcp' extra.\n"
            "Install with: pip install udfp[mcp]",
            file=sys.stderr,
        )
        sys.exit(1)

    server = create_server()
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="streamable-http", host=args.host, port=args.port)
