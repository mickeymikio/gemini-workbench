#!/usr/bin/env python3
"""Lightweight zero-dependency HTTP server to expose the flight deals dashboard over LAN.

Usage (Windows / macOS / Linux):
  python tasks/flight_deals/serve_dashboard.py --dir <flight-deals-dashboard-dir> --port 8787
"""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import sys


def _detect_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return str(s.getsockname()[0])
    except Exception:
        return "127.0.0.1"


class QuietUTF8Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
    }

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(description="Serve flight-deals-dashboard over LAN.")
    parser.add_argument("--dir", required=True, help="Directory containing index.html")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8787, help="TCP port (default: 8787)")
    args = parser.parse_args()

    serve_dir = Path(args.dir).expanduser().resolve()
    serve_dir.mkdir(parents=True, exist_ok=True)
    handler = partial(QuietUTF8Handler, directory=str(serve_dir))
    lan_ip = _detect_lan_ip()

    with ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        print(f"[serve_dashboard] Serving {serve_dir} at http://{lan_ip}:{args.port}/", flush=True)
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
