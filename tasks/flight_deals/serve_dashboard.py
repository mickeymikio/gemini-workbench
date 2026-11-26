#!/usr/bin/env python3
"""Zero-dependency HTTP server for the flight deals dashboard (Windows / macOS / Linux).

Features:
- Never relies on `SimpleHTTPRequestHandler` path translation quirks on Windows.
- Auto-discovers the active dashboard directory (`--dir`, `%LOCALAPPDATA%\\gemini-workbench-local\\dashboard`,
  `C:\\Users\\*\\AppData\\Local\\gemini-workbench-local\\dashboard`, or `<repo>/local_data/dashboard`)
  so Windows command-line quoting or Administrator vs. User profile differences never cause HTTP 404.
- Rebuilds `index.html` on the fly from `snapshots/*.json` if missing, and serves `/healthz` JSON.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tasks.flight_deals.dashboard import build_dashboard_html, load_snapshots  # noqa: E402


def _clean_path_arg(raw: str | None) -> Path | None:
    if not raw:
        return None
    cleaned = raw.strip().strip('"').strip("'").rstrip("\\/")
    if not cleaned:
        return None
    try:
        return Path(cleaned).expanduser().resolve()
    except Exception:
        return None


def discover_dashboard_dir(explicit_dir: str | None = None) -> Path:
    """Find the best dashboard directory containing `index.html` or `snapshots/*.json`."""
    candidates: list[Path] = []
    exp = _clean_path_arg(explicit_dir)
    if exp is not None:
        candidates.append(exp)

    wb_home_env = _clean_path_arg(os.environ.get("WB_HOME"))
    if wb_home_env is not None:
        candidates.append(wb_home_env / "dashboard")

    local_appdata = _clean_path_arg(os.environ.get("LOCALAPPDATA"))
    if local_appdata is not None:
        candidates.append(local_appdata / "gemini-workbench-local" / "dashboard")

    candidates.append(Path.home() / "AppData" / "Local" / "gemini-workbench-local" / "dashboard")
    candidates.append(Path.home() / ".local" / "share" / "gemini-workbench-local" / "dashboard")
    candidates.append(REPO_ROOT / "local_data" / "dashboard")

    users_root = Path("C:/Users")
    if users_root.is_dir():
        for u_dir in sorted(users_root.iterdir()):
            cand = u_dir / "AppData" / "Local" / "gemini-workbench-local" / "dashboard"
            if cand.is_dir() and cand not in candidates:
                candidates.append(cand)

    # Prefer the candidate with the newest snapshot or index.html
    best_with_data: tuple[float, Path] | None = None
    for c in candidates:
        try:
            if not c.is_dir():
                continue
            snaps = list((c / "snapshots").glob("*.json")) if (c / "snapshots").is_dir() else []
            idx_file = c / "index.html"
            mtimes = [f.stat().st_mtime for f in snaps if f.is_file()]
            if idx_file.is_file():
                mtimes.append(idx_file.stat().st_mtime)
            if mtimes:
                newest = max(mtimes)
                if best_with_data is None or newest > best_with_data[0]:
                    best_with_data = (newest, c)
        except Exception:
            continue

    if best_with_data is not None:
        return best_with_data[1]

    fallback = exp or (
        (local_appdata / "gemini-workbench-local" / "dashboard")
        if local_appdata
        else (REPO_ROOT / "local_data" / "dashboard")
    )
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _detect_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return str(s.getsockname()[0])
    except Exception:
        return "127.0.0.1"


def make_dashboard_handler(explicit_dir: str | None = None) -> type[BaseHTTPRequestHandler]:
    class DashboardRequestHandler(BaseHTTPRequestHandler):
        def _send_bytes(self, status: int, content_type: str, data: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_GET(self) -> None:  # noqa: N802
            req_path = unquote(urlsplit(self.path).path)
            dash_dir = discover_dashboard_dir(explicit_dir)
            snaps_dir = dash_dir / "snapshots"

            if req_path == "/healthz":
                snaps = load_snapshots(snaps_dir)
                payload = {
                    "status": "ok",
                    "dashboard_dir": str(dash_dir),
                    "has_index_html": (dash_dir / "index.html").is_file(),
                    "snapshot_count": len(snaps),
                }
                self._send_bytes(
                    HTTPStatus.OK,
                    "application/json; charset=utf-8",
                    json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                )
                return

            if req_path in ("/", "/index.html", "/dashboard", "/dashboard/"):
                idx_path = dash_dir / "index.html"
                snaps = load_snapshots(snaps_dir)
                if idx_path.is_file() and snaps:
                    # Rebuild if any snapshot is newer than index.html
                    latest_snap_mtime = max(
                        (f.stat().st_mtime for f in snaps_dir.glob("*.json")),
                        default=0.0,
                    )
                    if latest_snap_mtime > idx_path.stat().st_mtime:
                        html_bytes = build_dashboard_html(snaps, mode="standalone").encode("utf-8")
                        idx_path.write_bytes(html_bytes)
                    else:
                        html_bytes = idx_path.read_bytes()
                elif idx_path.is_file():
                    html_bytes = idx_path.read_bytes()
                else:
                    html_str = build_dashboard_html(snaps, mode="standalone")
                    html_bytes = html_str.encode("utf-8")
                    try:
                        idx_path.write_bytes(html_bytes)
                    except Exception:
                        pass
                self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", html_bytes)
                return

            if req_path in ("/latest.md", "/reports/latest.md"):
                rep = dash_dir / "reports" / "latest.md"
                if rep.is_file():
                    self._send_bytes(
                        HTTPStatus.OK,
                        "text/markdown; charset=utf-8",
                        rep.read_bytes(),
                    )
                    return

            self._send_bytes(
                HTTPStatus.NOT_FOUND,
                "text/plain; charset=utf-8",
                f"404 Not Found: {req_path} (root dashboard is at /)\n".encode("utf-8"),
            )

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    return DashboardRequestHandler


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(description="Serve flight-deals-dashboard over LAN/Tailscale.")
    parser.add_argument("--dir", default=None, help="Optional dashboard directory (auto-discovered if omitted)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8787, help="TCP port (default: 8787)")
    args = parser.parse_args()

    resolved = discover_dashboard_dir(args.dir)
    handler_cls = make_dashboard_handler(args.dir)
    lan_ip = _detect_lan_ip()

    with ThreadingHTTPServer((args.host, args.port), handler_cls) as httpd:
        print(f"[serve_dashboard] Serving {resolved} at http://{lan_ip}:{args.port}/", flush=True)
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
