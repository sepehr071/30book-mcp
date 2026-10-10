from pathlib import Path

import pytest
from mcp import Client

from sibook_mcp import http
from sibook_mcp.dom import parse_html
from sibook_mcp.server import mcp

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    """A recorded (trimmed) page, as text."""
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh_http_client():
    """The shared httpx client is bound to one event loop; each test gets a new loop."""
    http.set_transport(None)
    yield
    http.set_transport(None)


class Site:
    """A fake 30book. `pages[path]` = HTML for http.html; `lists[path_prefix]` = rendered list HTML for http.render."""

    def __init__(self) -> None:
        self.pages: dict[str, str] = {}
        self.lists: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []
        self.typed: list[tuple[str, str, str]] = []

    def last(self) -> str:
        return self.calls[-1][1]


@pytest.fixture
def site(monkeypatch):
    s = Site()

    async def fake_html(path: str) -> str:
        s.calls.append(("html", path))
        if path not in s.pages:
            raise http.ApiError("Not found on 30book.com (HTTP 404).")
        return s.pages[path]

    async def fake_render(path, ready, *, type_into=None):
        s.calls.append(("render", path))
        if type_into:
            s.typed.append(type_into)
        key = next((k for k in s.lists if path.startswith(k)), None)
        if key is None:
            raise http.ApiError("Not found on 30book.com (HTTP 404).")
        trees = [parse_html(s.lists[key])]
        assert ready(trees), "the fixture does not satisfy the tool's ready test"
        return trees

    monkeypatch.setattr(http, "html", fake_html)
    monkeypatch.setattr(http, "render", fake_render)
    return s


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        yield c
