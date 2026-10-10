"""Shared async HTTP client for 30book.com.

30book is an ASP.NET Blazor Server site with no JSON API. Two kinds of page:
- plain server-rendered HTML (book page, home, landing pages): `html(path)`;
- list pages (search, category, publisher, author, tag, best sellers, ...) whose book cards are drawn after load by a
  Blazor circuit: `render(path, ready)` opens one with `blazor.Circuit` and returns the rendered component trees.
Every tool goes through these two. `_send` caps concurrency, retries once on dropped connections and turns HTTP
failures into `ToolError` messages the model can act on.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .blazor import Circuit, CircuitError
from .dom import Node
from .parse import path_quote

SITE = "https://www.30book.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Accept-Language": "fa,en;q=0.8",
}

MAX_CONCURRENCY = 3
MAX_CIRCUITS = 2

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None
_circuits: asyncio.Semaphore | None = None


class ApiError(ToolError):
    """A failed upstream call."""


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client."""
    global _transport, _client, _limit, _circuits
    _transport, _client, _limit, _circuits = transport, None, None, None


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore, asyncio.Semaphore]:
    global _client, _limit, _circuits
    if _client is None:
        # 30book answers direct connections fine; a proxy is only used when the user opts in with SIBOOK_MCP_PROXY.
        _client = httpx.AsyncClient(
            transport=_transport,
            headers=HEADERS,
            timeout=30,
            follow_redirects=True,
            trust_env=False,
            proxy=os.environ.get("SIBOOK_MCP_PROXY") or None,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
        _circuits = asyncio.Semaphore(MAX_CIRCUITS)
    assert _limit is not None and _circuits is not None
    return _client, _limit, _circuits


async def html(path: str) -> str:
    """GET a server-rendered page (`/book/123`, `/`, `/landing/pod`) and return its HTML."""
    return (await _send(SITE + path_quote(path))).text


async def render(
    path: str, ready: Callable[[list[Node]], bool], *, type_into: tuple[str, str, str] | None = None
) -> list[Node]:
    """Render a list page through a Blazor circuit and return its component trees once `ready(trees)` holds.

    `type_into=(input_class, text, button_class)` types `text` into the page's name box and presses its button
    (the publisher / author index pages filter that way); `ready` is then checked again on the new content.
    """
    client, _, circuits = _get_client()
    base, _, qs = path.partition("?")
    page = await _send(
        SITE + path_quote(base)
    )  # dummy slugs redirect (301) to the canonical URL, which drops the query
    href = str(page.url) + (f"?{qs}" if qs else "")
    for attempt in (1, 2, 3):
        try:
            async with circuits, Circuit(client, SITE, href, page.text) as c:
                trees = await c.wait(ready, timeout=20)
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
    raise AssertionError("unreachable")


def _first(trees: list[Node], cls: str) -> Node | None:
    for t in trees:
        n = t.find(cls=cls)
        if n:
            return n
    return None


async def _send(url: str) -> httpx.Response:
    client, limit, _ = _get_client()
    for attempt in (1, 2):
        try:
            async with limit:
                r = await client.get(url)
        except httpx.TimeoutException as e:
            raise ApiError("30book.com did not answer in time. Try again in a moment.") from e
        except httpx.TransportError as e:
            if attempt == 2:
                raise ApiError(
                    f"Could not reach 30book.com ({type(e).__name__}). Check the internet connection, "
                    "or set SIBOOK_MCP_PROXY."
                ) from e
            continue
        break
    if r.status_code >= 400:
        raise ApiError(_status_message(r.status_code))
    return r


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
