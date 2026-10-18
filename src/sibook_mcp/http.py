"""Shared async HTTP client for 30book.com.

30book is an ASP.NET Blazor Server site with no JSON API. Two kinds of page:
- plain server-rendered HTML (book page, home, landing pages): `html(path)`;
- list pages (search, category, publisher, author, tag, best sellers, ...) whose book cards are drawn after load by a
  Blazor circuit: `render(path, ready)` opens one with `blazor.Circuit` and returns the rendered component trees.
Every tool goes through these two. `_send` caps concurrency, retries transient failures with backoff and turns HTTP
failures into `ToolError` messages the model can act on.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from httpx_curl_cffi import AsyncCurlTransport
from mcp.server.mcpserver.exceptions import ToolError

from .blazor import Circuit, CircuitError
from .dom import Node
from .parse import path_quote

SITE = "https://www.30book.com"

# User-Agent, sec-ch-ua, sec-fetch-* and TLS come from the impersonated Chrome profile (see _get_client).
HEADERS = {"Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8"}
# What the page's own script sends on the Blazor circuit calls (fetch/XHR, not navigation).
XHR_HEADERS = {
    "Accept": "*/*",
    "Origin": SITE,
    "Referer": f"{SITE}/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "priority": "u=1, i",
}

MAX_CONCURRENCY = 2
MAX_CIRCUITS = 2
JITTER = (0.15, 0.6)  # seconds before each uncached call
MAX_RETRIES = 2
MAX_RETRY_WAIT = 10  # cap for Retry-After and backoff, seconds

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None
_circuits: asyncio.Semaphore | None = None
_proxy_index = 0
_retired: set[asyncio.Task] = set()
_browser_lock: asyncio.Lock | None = None
_cleared: tuple[httpx.AsyncClient, float] | None = None
_pages: dict[str, tuple[float, str]] = {}  # /book/<id> HTML for a few minutes: book -> similar -> reviews reuse it
PAGE_TTL = 300
PAGE_CACHE_MAX = 64
MAX_BODY = 3_000_000  # bytes per page; the biggest real pages are well under 1 MB
RETRY_DELAY = 0.5  # base pause before retrying an idempotent GET / circuit
READY_TIMEOUT = 20  # slow circuits still draw a full list; a shorter wait drops results


class _ChromeTransport(AsyncCurlTransport):
    """Pages are navigations (Chrome's default headers); /_blazor calls are XHR, so they drop the navigation-only
    headers (a None value makes curl drop them) and carry the page script's own."""

    def _create_request_params(self, req: httpx.Request) -> dict[str, Any]:
        xhr = req.url.path.startswith("/_blazor")
        if xhr:
            req.headers.update(XHR_HEADERS)
        p = super()._create_request_params(req)
        if xhr:
            p["headers"] = [*p["headers"], (b"upgrade-insecure-requests", None), (b"sec-fetch-user", None)]
        return p


class ApiError(ToolError):
    """A failed upstream call. `status` is the HTTP status, or None for network errors."""

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client."""
    global _transport, _client, _limit, _circuits, _proxy_index, _browser_lock, _cleared
    _transport, _client, _limit, _circuits = transport, None, None, None
    _proxy_index, _browser_lock, _cleared = 0, None, None
    _pages.clear()


def _proxies() -> list[str]:
    """SIBOOK_MCP_PROXY: one proxy URL, or a comma-separated list used one at a time."""
    return [p.strip() for p in os.environ.get("SIBOOK_MCP_PROXY", "").split(",") if p.strip()]


_CHALLENGE = re.compile(r"just a moment|captcha|challenge|arvan|attention required|enable javascript", re.I)


def _is_challenge(r: httpx.Response) -> bool:
    """A bot-check page: 403/429/503 with an HTML body that carries a known challenge marker."""
    return (
        r.status_code in (403, 429, 503)
        and "html" in (r.headers.get("content-type", "") + r.text[:20]).lower()
        and bool(_CHALLENGE.search(r.text[:5000]))
    )


def _next_proxy(client: httpx.AsyncClient) -> None:
    """Sticky pool: move to the next proxy after a block or connect error; the next call rebuilds the client.

    Only the client that failed may rotate: a slower request that failed on an old client must not skip a good proxy.
    The old client is closed late because other requests (and circuits) may still be using it.
    """
    global _client, _limit, _circuits, _proxy_index
    if len(_proxies()) < 2 or client is not _client:
        return
    _client, _limit, _circuits, _proxy_index = None, None, None, _proxy_index + 1
    t = asyncio.create_task(_close_later(client))
    _retired.add(t)
    t.add_done_callback(_retired.discard)


async def _close_later(client: httpx.AsyncClient) -> None:
    await asyncio.sleep(60)  # longer than the 30 s request timeout and a 20 s circuit wait
    await client.aclose()


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore, asyncio.Semaphore]:
    global _client, _limit, _circuits
    if _client is None:
        # 30book answers direct connections fine; a proxy is only used when the user opts in with SIBOOK_MCP_PROXY.
        # curl_cffi presents Chrome's TLS/HTTP2 fingerprint and default headers; cookies and redirects stay with httpx.
        # The proxy goes to the transport (a client-level proxy would be ignored once a transport is given).
        proxies = _proxies()
        _client = httpx.AsyncClient(
            transport=_transport
            or _ChromeTransport(
                impersonate="chrome",
                default_headers=True,
                proxy=proxies[_proxy_index % len(proxies)] if proxies else None,
                max_connections=2 * MAX_CONCURRENCY,
            ),
            headers=HEADERS,
            timeout=30,
            follow_redirects=True,
            trust_env=False,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
        _circuits = asyncio.Semaphore(MAX_CIRCUITS)
    assert _limit is not None and _circuits is not None
    return _client, _limit, _circuits


async def html(path: str) -> str:
    """GET a server-rendered page (`/book/123`, `/`, `/landing/pod`) and return its HTML."""
    hit = _pages.get(path)
    if hit and time.monotonic() - hit[0] < PAGE_TTL:
        return hit[1]
    text = (await _send(SITE + path_quote(path))).text
    if path.startswith("/book/"):
        if len(_pages) >= PAGE_CACHE_MAX:
            _pages.pop(next(iter(_pages)))
        _pages[path] = (time.monotonic(), text)
    return text


async def render(
    path: str, ready: Callable[[list[Node]], bool], *, type_into: tuple[str, str, str] | None = None
) -> list[Node]:
    """Render a list page through a Blazor circuit and return its component trees once `ready(trees)` holds.

    `type_into=(input_class, text, button_class)` types `text` into the page's name box and presses its button
    (the publisher / author index pages filter that way); `ready` is then checked again on the new content.
    """
    base, _, qs = path.partition("?")
    page = await _send(
        SITE + path_quote(base)
    )  # dummy slugs redirect (301) to the canonical URL, which drops the query
    href = str(page.url) + (f"?{qs}" if qs else "")
    for attempt in (1, 2, 3):
        client, _, circuits = _get_client()
        try:
            async with circuits, Circuit(client, SITE, href, page.text) as c:
                trees = await c.wait(ready, timeout=READY_TIMEOUT)
                if type_into:
                    box_class, text, button_class = type_into
                    box = _first(trees, box_class)
                    button = _first(trees, button_class)
                    if box is None or button is None:
                        raise ApiError("30book.com changed its search box; the name filter is not available.")
                    await c.fire(box, "input", text)
                    await c.fire(button, "click")
                    trees = await c.wait(ready, settle=2.5)
                return trees
        except CircuitError as e:
            if attempt == 3:
                raise ApiError(str(e)) from e
            await asyncio.sleep(RETRY_DELAY * random.uniform(1, 1.5))
    raise AssertionError("unreachable")


def _first(trees: list[Node], cls: str) -> Node | None:
    for t in trees:
        n = t.find(cls=cls)
        if n:
            return n
    return None


async def _send(url: str) -> httpx.Response:
    """GET with up to MAX_RETRIES retries on network errors, timeouts, 429 and 5xx (Retry-After honoured); 403 never."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await _get(url)
        except ApiError as e:
            if attempt == MAX_RETRIES or (e.status is not None and e.status < 500 and e.status != 429):
                raise
            wait = e.retry_after if e.retry_after is not None else RETRY_DELAY * 2**attempt * random.uniform(1, 1.5)
            await asyncio.sleep(min(wait, MAX_RETRY_WAIT))
    raise AssertionError("unreachable")


async def _once(client: httpx.AsyncClient, limit: asyncio.Semaphore, url: str) -> httpx.Response:
    try:
        async with limit:
            await asyncio.sleep(random.uniform(*JITTER))
            async with client.stream("GET", url) as resp:
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BODY:
                        # status 200 = the server answered fine, so _send does not retry it
                        raise ApiError("30book.com sent an unexpectedly large page; giving up.", 200)
                # rebuild a plain Response: aiter_bytes already decoded the body, so drop the encoding headers
                skip = {"content-encoding", "content-length", "transfer-encoding"}
                return httpx.Response(
                    resp.status_code,
                    headers=[(k, v) for k, v in resp.headers.items() if k.lower() not in skip],
                    content=bytes(body),
                    request=resp.request,
                )
    except httpx.TimeoutException as e:
        raise ApiError("30book.com did not answer in time. Try again in a moment.") from e
    except httpx.TransportError as e:
        if isinstance(e, httpx.ConnectError | httpx.ProxyError):
            _next_proxy(client)
        raise ApiError(
            f"Could not reach 30book.com ({type(e).__name__}). Check the internet connection, or set SIBOOK_MCP_PROXY."
        ) from e


async def _get(url: str) -> httpx.Response:
    client, limit, _ = _get_client()
    r = await _once(client, limit, url)
    if _is_challenge(r):
        _next_proxy(client)
        client, limit, _ = _get_client()
        await _clear_challenge(client)
        r = await _once(client, limit, url)  # one retry; a second block is final
        if _is_challenge(r):
            _next_proxy(client)
    if r.status_code >= 400:
        raise ApiError(_status_message(r.status_code), r.status_code, _retry_after(r))
    return r


async def _browser_cookies(proxy: str | None) -> list[dict[str, Any]]:
    """Open the home page in headless patchright, wait for the challenge to clear, return the cookies."""
    try:
        from patchright.async_api import async_playwright
    except ImportError as e:
        raise ApiError(
            "30book served a bot-check page. Install the browser extra (`pip install 30book-mcp[browser]`, or "
            "`uvx --with patchright==1.63.0 30book-mcp`) and run `patchright install chromium`.",
            403,
        ) from e
    u = httpx.URL(proxy) if proxy else None
    opts = u and {"server": f"{u.scheme}://{u.host}:{u.port}", "username": u.username, "password": u.password}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, proxy=opts)
        try:
            page = await browser.new_page()
            await page.goto(SITE, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_function(
                "!/just a moment|access denied|attention required|arvancloud/i.test(document.title)", timeout=30_000
            )
            return await browser.contexts[0].cookies()
        finally:
            await browser.close()


async def _clear_challenge(client: httpx.AsyncClient) -> None:
    """Rung 2: let a real browser pass the bot check once and share its cookies with the httpx jar."""
    global _browser_lock, _cleared
    _browser_lock = _browser_lock or asyncio.Lock()
    async with _browser_lock:  # one browser at a time; callers that waited reuse the cookies just fetched
        if _cleared and _cleared[0] is client and time.monotonic() - _cleared[1] < 30:
            return
        proxies = _proxies()
        try:
            cookies = await _browser_cookies(proxies[_proxy_index % len(proxies)] if proxies else None)
        except ApiError:
            raise
        except Exception as e:
            raise ApiError(f"30book bot check was not cleared by the browser ({type(e).__name__}).", 403) from e
        for c in cookies:
            client.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
        _cleared = (client, time.monotonic())


def _retry_after(r: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After on a 429/503, else None (HTTP-date form is ignored)."""
    v = r.headers.get("retry-after", "")
    return float(v) if r.status_code in (429, 503) and v.replace(".", "", 1).isdigit() else None


def _status_message(code: int) -> str:
    if code == 404:
        return "Not found on 30book.com (HTTP 404). Check the book id, slug or code; find ids with sb_search."
    if code == 403:
        return "30book.com blocked the request (HTTP 403). Turn off VPN/proxy or set SIBOOK_MCP_PROXY."
    if code == 429:
        return "30book.com is rate limiting requests (HTTP 429). Wait a minute before retrying."
    if code >= 500:
        return f"30book.com had a server error (HTTP {code}). Check the ids, or try again later."
    return f"30book.com rejected the request (HTTP {code})."


def query(params: dict[str, Any]) -> str:
    """`?a=1&b=x` from the non-empty params (True -> 'True', the site's own spelling); '' when none."""
    items = [(k, "True" if v is True else str(v)) for k, v in params.items() if v not in (None, "", False)]
    return "?" + "&".join(f"{k}={v}" for k, v in items) if items else ""
