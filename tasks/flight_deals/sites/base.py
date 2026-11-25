"""Base adapter utilities, challenge/block detection (strictly non-bypassing), and cookie dismissal."""

from __future__ import annotations

import re

from ..models import FailureCategory

_BOT_TITLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ボットとは", re.IGNORECASE),
    re.compile(r"what is a bot", re.IGNORECASE),
    re.compile(r"access to this page has been denied", re.IGNORECASE),
    re.compile(r"just a moment", re.IGNORECASE),
    re.compile(r"attention required", re.IGNORECASE),
    re.compile(r"security check", re.IGNORECASE),
    re.compile(r"pardon our interruption", re.IGNORECASE),
)

_BOT_URL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/sttc/px/", re.IGNORECASE),
    re.compile(r"google\.[^/]+/sorry", re.IGNORECASE),
    re.compile(r"__cf_chl", re.IGNORECASE),
)

_BOT_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"長押ししてあなたが.*人間であることを確認", re.DOTALL),
        "ボット検知（PerimeterX 長押し認証画面）によりブロック",
    ),
    (
        re.compile(r"press\s*&\s*hold.*confirm you are", re.IGNORECASE | re.DOTALL),
        "ボット検知（PerimeterX Press & Hold）によりブロック",
    ),
    (
        re.compile(r"are you a person or a robot", re.IGNORECASE),
        "ボット検知（人間確認チャレンジ画面）によりブロック",
    ),
    (
        re.compile(r"あなたを[“\"「]?ボット[”\"」]?だと認識", re.IGNORECASE),
        "サイト側ボット判定（「ボットとは？」制限画面）によりブロック",
    ),
    (
        re.compile(r"think you are a bot|detected unusual traffic", re.IGNORECASE),
        "サイト側ボット判定／トラフィック制限によりブロック",
    ),
    (
        re.compile(r"verify you are human|cloudflare", re.IGNORECASE),
        "WAF／人間確認チャレンジによりブロック",
    ),
)

_LOGIN_WALL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ログインして続行|サインインして検索結果を表示|sign in to continue", re.IGNORECASE),
    re.compile(r"회원가입 후|로그인 후 이용", re.IGNORECASE),
)


def detect_access_barrier(
    final_url: str,
    title: str,
    body_text: str,
    http_status: int | None = None,
) -> tuple[FailureCategory, str] | None:
    """Inspect rendered page metadata and return `(category, reason_ja)` if blocked.

    Never interacts with or attempts to solve challenges; callers must immediately abort on match.
    """
    if http_status in (401, 403, 429):
        if http_status == 429:
            return ("http_error", "HTTP 429 レート制限により検索結果画面を取得できず")
        return ("bot_block", f"HTTP {http_status} アクセス拒否により検索結果画面を取得できず")

    if http_status is not None and http_status >= 500:
        return ("http_error", f"サイト側サーバーエラー（HTTP {http_status}）")

    for pat in _BOT_URL_PATTERNS:
        if pat.search(final_url):
            return ("bot_block", "ボット検知リダイレクト（チャレンジ画面）によりブロック")

    for pat in _BOT_TITLE_PATTERNS:
        if pat.search(title):
            return ("bot_block", f"ボット検知画面（タイトル: {title.strip()[:40]}）によりブロック")

    # Only scan short/medium pages or explicit interstitials so normal footer text doesn't false-fire
    head_text = body_text[:3000]
    for pat, reason in _BOT_TEXT_PATTERNS:
        if len(body_text) < 5000 and pat.search(head_text):
            return ("bot_block", reason)

    for pat in _LOGIN_WALL_PATTERNS:
        if len(body_text) < 4000 and pat.search(head_text):
            return ("login_required", "閲覧にログイン／会員登録が必要な画面のため規約に従いスキップ")

    return None


async def dismiss_google_cookie_consent_if_present(page: object) -> None:
    """Click standard regional GDPR cookie consent button if redirected to consent.google.com."""
    url = getattr(page, "url", "")
    if "consent.google." not in url:
        return
    for label in ("すべて拒否", "Reject all", "すべて同意", "Accept all"):
        try:
            btn = page.get_by_role("button", name=label)  # type: ignore[attr-defined]
            if await btn.count() > 0:
                await btn.first.click(timeout=3000)
                await page.wait_for_load_state("domcontentloaded", timeout=10000)  # type: ignore[attr-defined]
                return
        except Exception:
            continue
