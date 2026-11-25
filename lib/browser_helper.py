#!/usr/bin/env python3
"""Container-safe Playwright (Chromium) helper for Gemini Web Persistent VM.

Features:
- Automatically configures PLAYWRIGHT_BROWSERS_PATH ($HOME/.local/share/ms-playwright)
  and rootless fallback LD_LIBRARY_PATH ($HOME/.local/opt/browser-libs) before spawning Chromium.
- Enforces --no-sandbox and --disable-dev-shm-usage to prevent 64MB /dev/shm tab crashes.
- Isolates browser contexts and download directories per run.
- Can be imported from Python OR executed directly as a CLI to render SPA pages into Markdown/HTML.
"""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import AsyncIterator, Iterator


def configure_browser_env() -> None:
    """Ensure $HOME-persisted Chromium path, proxy CA env vars, and fallback .so paths are active."""
    home = Path(os.environ.get("WB_HOME", str(Path.home())))
    browsers_path = home / ".local" / "share" / "ms-playwright"
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers_path))

    sys_ca = Path("/etc/ssl/certs/ca-certificates.crt")
    if sys_ca.is_file():
        os.environ.setdefault("NODE_EXTRA_CA_CERTS", str(sys_ca))
        os.environ.setdefault("SSL_CERT_FILE", str(sys_ca))
        os.environ.setdefault("REQUESTS_CA_BUNDLE", str(sys_ca))

    libs_root = home / ".local" / "opt" / "browser-libs"
    if libs_root.is_dir():
        candidates: list[str] = []
        for dirpath, dirnames, _ in os.walk(libs_root):
            base = os.path.basename(dirpath)
            if "linux-gnu" in base or base in {"lib", "lib64"}:
                candidates.append(dirpath)
            # Prune deep irrelevant trees
            dirnames[:] = [d for d in dirnames if d not in {"share", "doc", "include"}]
        if candidates:
            existing = os.environ.get("LD_LIBRARY_PATH", "")
            joined = ":".join(candidates)
            os.environ["LD_LIBRARY_PATH"] = f"{joined}:{existing}" if existing else joined


configure_browser_env()

LAUNCH_ARGS: list[str] = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-first-run",
    "--no-zygote",
]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class RenderedPage:
    url: str
    title: str
    html: str
    markdown: str


def html_to_markdown(html: str, url: str | None = None) -> str:
    """Extract clean article/page Markdown using trafilatura with plain-text fallback."""
    try:
        import trafilatura  # type: ignore

        extracted = trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_links=True,
            include_tables=True,
        )
        if extracted:
            return extracted
    except ImportError:
        pass

    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text("\n", strip=True)
    except ImportError:
        return html


@contextmanager
def sync_open_page(
    download_dir: str | Path | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    viewport: dict[str, int] | None = None,
    timeout_ms: int = 45_000,
    ignore_https_errors: bool = True,
    locale: str | None = None,
    timezone_id: str | None = None,
) -> Iterator["Page"]:  # type: ignore[name-defined]
    """Open an isolated headless Chromium page with container-safe & TLS-proxy-safe flags."""
    from playwright.sync_api import sync_playwright  # type: ignore

    dl_path = str(Path(download_dir).expanduser().resolve()) if download_dir else None
    if dl_path:
        Path(dl_path).mkdir(parents=True, exist_ok=True)

    ctx_kwargs: dict[str, object] = {
        "accept_downloads": True,
        "ignore_https_errors": ignore_https_errors,
        "user_agent": user_agent,
        "viewport": viewport or {"width": 1440, "height": 900},
    }
    if locale:
        ctx_kwargs["locale"] = locale
    if timezone_id:
        ctx_kwargs["timezone_id"] = timezone_id

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=LAUNCH_ARGS,
            downloads_path=dl_path,
        )
        context = browser.new_context(**ctx_kwargs)  # type: ignore[arg-type]
        context.set_default_timeout(timeout_ms)
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()


@asynccontextmanager
async def async_open_page(
    download_dir: str | Path | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    viewport: dict[str, int] | None = None,
    timeout_ms: int = 45_000,
    ignore_https_errors: bool = True,
    locale: str | None = None,
    timezone_id: str | None = None,
) -> AsyncIterator["AsyncPage"]:  # type: ignore[name-defined]
    """Async counterpart of sync_open_page."""
    from playwright.async_api import async_playwright  # type: ignore

    dl_path = str(Path(download_dir).expanduser().resolve()) if download_dir else None
    if dl_path:
        Path(dl_path).mkdir(parents=True, exist_ok=True)

    ctx_kwargs: dict[str, object] = {
        "accept_downloads": True,
        "ignore_https_errors": ignore_https_errors,
        "user_agent": user_agent,
        "viewport": viewport or {"width": 1440, "height": 900},
    }
    if locale:
        ctx_kwargs["locale"] = locale
    if timezone_id:
        ctx_kwargs["timezone_id"] = timezone_id

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=LAUNCH_ARGS,
            downloads_path=dl_path,
        )
        context = await browser.new_context(**ctx_kwargs)  # type: ignore[arg-type]
        context.set_default_timeout(timeout_ms)
        page = await context.new_page()
        try:
            yield page
        finally:
            await context.close()
            await browser.close()


@asynccontextmanager
async def async_open_browser(
    download_dir: str | Path | None = None,
) -> AsyncIterator["AsyncBrowser"]:  # type: ignore[name-defined]
    """Launch a single shared headless Chromium instance for creating multiple isolated contexts."""
    from playwright.async_api import async_playwright  # type: ignore

    dl_path = str(Path(download_dir).expanduser().resolve()) if download_dir else None
    if dl_path:
        Path(dl_path).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=LAUNCH_ARGS,
            downloads_path=dl_path,
        )
        try:
            yield browser
        finally:
            await browser.close()


def fetch_rendered(
    url: str,
    wait_until: str = "networkidle",
    wait_selector: str | None = None,
    screenshot_path: str | Path | None = None,
    timeout_ms: int = 45_000,
) -> RenderedPage:
    """Render a URL in headless Chromium and return HTML + extracted Markdown."""
    with sync_open_page(timeout_ms=timeout_ms) as page:
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        except Exception:
            # Fallback for sites with perpetual analytics/websocket connections
            if wait_until == "networkidle":
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2000)
            else:
                raise

        if wait_selector:
            page.wait_for_selector(wait_selector, timeout=timeout_ms)

        if screenshot_path:
            out_img = Path(screenshot_path).expanduser().resolve()
            out_img.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out_img), full_page=True)

        final_url = page.url
        title = page.title()
        html = page.content()
        md = html_to_markdown(html, url=final_url)
        return RenderedPage(url=final_url, title=title, html=html, markdown=md)


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Render a web page via container-safe Playwright Chromium."
    )
    parser.add_argument("url", help="Target URL to render")
    parser.add_argument(
        "--markdown",
        action="store_true",
        default=True,
        help="Output extracted Markdown (default)",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Output raw rendered DOM HTML instead of Markdown",
    )
    parser.add_argument(
        "--wait-selector",
        default=None,
        help="Optional CSS selector to wait for before capturing",
    )
    parser.add_argument(
        "--screenshot",
        default=None,
        help="Optional file path to save a full-page PNG screenshot",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=45_000,
        help="Navigation timeout in milliseconds (default: 45000)",
    )
    args = parser.parse_args()

    result = fetch_rendered(
        args.url,
        wait_selector=args.wait_selector,
        screenshot_path=args.screenshot,
        timeout_ms=args.timeout_ms,
    )
    if args.html:
        sys.stdout.write(result.html)
    else:
        header = f"# {result.title}\n\nSource: {result.url}\n\n---\n\n"
        sys.stdout.write(header + result.markdown + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
