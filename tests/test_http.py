import re
from pathlib import Path

import httpx
import pytest

from sibook_mcp import http

pytestmark = pytest.mark.anyio


async def test_all_tools_are_read_only(client):
    tools = (await client.list_tools()).tools
    assert len(tools) == 14
    for t in tools:
        assert t.name.startswith("sb_"), t.name
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False, t.name
        assert t.description and t.title, t.name


async def test_readme_tool_tables_match_the_server(client):
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    listed = re.findall(r"^\| `(sb_\w+)` \|", readme, re.M)
    assert sorted(listed) == sorted(t.name for t in (await client.list_tools()).tools)


def test_query_builder():
    assert http.query({"sort": 4, "qt": True, "pub": None, "stp": False, "pg": 0}) == "?sort=4&qt=True"
    assert http.query({}) == ""


def _serve(handler):
    http.set_transport(httpx.MockTransport(handler))


async def test_html_get_quotes_persian_paths_and_follows_redirects():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/book/1":
            return httpx.Response(301, headers={"location": "/book/1/slug"})
        return httpx.Response(200, text="<p>ok</p>")

    _serve(handler)
    assert await http.html("/book/1") == "<p>ok</p>"
    assert seen == ["https://www.30book.com/book/1", "https://www.30book.com/book/1/slug"]
    await http.html("/search/شازده")
    assert seen[-1] == "https://www.30book.com/search/%D8%B4%D8%A7%D8%B2%D8%AF%D9%87"


@pytest.mark.parametrize(
    ("status", "text"),
    [(404, "HTTP 404"), (403, "blocked"), (429, "rate limiting"), (500, "server error (HTTP 500)")],
)
async def test_http_errors_are_actionable(client, status, text):
    _serve(lambda r: httpx.Response(status))
    result = await client.call_tool("sb_book", {"book_id": 5})
    assert result.is_error and text in result.content[0].text


async def test_dropped_connection_is_retried_once(client):
    attempts = []

    def flaky(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.RemoteProtocolError("Server disconnected", request=request)
        return httpx.Response(200, text="<html></html>")

    _serve(flaky)
    result = await client.call_tool("sb_book", {"book_id": 5})
    assert not result.is_error and len(attempts) == 2


async def test_network_error_after_retry(client):
    def down(request):
        raise httpx.ConnectError("boom", request=request)

    _serve(down)
    result = await client.call_tool("sb_book", {"book_id": 5})
    assert result.is_error and "Could not reach 30book.com (ConnectError)" in result.content[0].text


async def test_timeout_is_not_retried(client):
    calls = []

    def slow(request):
        calls.append(1)
        raise httpx.ReadTimeout("t", request=request)

    _serve(slow)
    result = await client.call_tool("sb_book", {"book_id": 5})
    assert result.is_error and "did not answer in time" in result.content[0].text and len(calls) == 1


async def test_browser_user_agent_and_no_env_proxy(client, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")  # must be ignored (trust_env=False)
    seen = []

    def handler(request):
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, text="<html></html>")

    _serve(handler)
    result = await client.call_tool("sb_book", {"book_id": 5})
    assert not result.is_error and "Chrome" in seen[0]
