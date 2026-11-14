"""Command line entry point.

  python -m bia_service serve                  # MCP over stdio (Claude Desktop / Claude Code on your PC)
  python -m bia_service serve --http           # MCP + REST over HTTP (for hosting; needs SERVICE_TOKEN)
  python -m bia_service snapshot               # save today's numbers for the trend (run daily)
  python -m bia_service report                 # quick ETA health + action counts in the terminal
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .client import BiaError
from .server import Service, build_http_app, build_mcp


def _print(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


async def _report(service: Service) -> None:
    health = await service.eta_health()
    actions = await service.action_list()
    _print({"eta_health": health, "action_counts": actions["counts"]})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bia_service", description="BIA ticket MCP server and metrics service")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the MCP server")
    serve.add_argument("--http", action="store_true", help="serve over HTTP instead of stdio")
    serve.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8000, help="HTTP port (default 8000)")

    sub.add_parser("snapshot", help="save today's numbers for the trend")
    sub.add_parser("report", help="print ETA health and action counts")

    args = parser.parse_args(argv)
    service = Service()

    try:
        if args.command == "serve" and not args.http:
            build_mcp(service).run("stdio")                 # stdout is the MCP channel: no prints here
        elif args.command == "serve":
            import uvicorn
            uvicorn.run(build_http_app(service, host=args.host), host=args.host, port=args.port)
        elif args.command == "snapshot":
            _print(asyncio.run(service.take_snapshot()))
        elif args.command == "report":
            asyncio.run(_report(service))
    except (BiaError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
