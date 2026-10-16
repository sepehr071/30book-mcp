import json
import re
from pathlib import Path

import httpx
import pytest
from conftest import fixture_text

from sibook_mcp import http, parse

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


def test_seg_keeps_free_text_in_one_path_segment():
    assert parse.seg("../login?x=1") == "..%2Flogin%3Fx%3D1"
    assert parse.seg("a/b&c=d%e") == "a%2Fb%26c%3Dd%25e" and parse.seg("شازده کوچولو") == "شازده کوچولو"
    with pytest.raises(ValueError):
        parse.seg("..")


async def test_book_pages_are_cached_but_other_pages_are_not():
    n = []

    def handler(request):
        n.append(request.url.path)
        return httpx.Response(200, text="<p>ok</p>")

    _serve(handler)
    await http.html("/book/7")
    await http.html("/book/7")
    await http.html("/")
    await http.html("/")
    assert n == ["/book/7", "/", "/"]


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


async def test_raw_client_gets_one_text_block_and_no_schemas():
    from mcp import Client

    from sibook_mcp.server import mcp

    _serve(lambda request: httpx.Response(200, text="<html></html>"))
    async with Client(mcp) as c:
        tools = (await c.list_tools()).tools
        assert all(t.output_schema is None for t in tools)
        assert all("title" not in p for t in tools for p in t.input_schema["properties"].values())
        result = await c.call_tool("sb_book", {"book_id": 5})
        assert len(result.content) == 1 and result.content[0].type == "text"
        assert result.structured_content is None


def test_circuit_ready_wait_is_not_shortened():
    assert http.READY_TIMEOUT >= 20  # a shorter wait loses results on slow circuits


async def test_oversized_page_is_refused(monkeypatch):
    monkeypatch.setattr(http, "MAX_BODY", 100)
    _serve(lambda request: httpx.Response(200, text="x" * 1000))
    with pytest.raises(http.ApiError, match="large"):
        await http.html("/")


async def test_reviews_text_is_clipped(client, site):
    from sibook_mcp import product

    site.pages["/book/167515"] = fixture_text("book_167515.html")
    out = await client.call_tool("sb_reviews", {"book_id": 167515})
    assert not out.is_error
    assert all(len(r["text"] or "") <= product.REVIEW_CHARS + 1 for r in json.loads(out.content[0].text)["reviews"])
