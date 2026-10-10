# 30book-mcp

Unofficial, read-only MCP server for 30book (30book.com), an Iranian online bookstore with about 200,000 printed books.
Intended GitHub `sepehr071/30book-mcp`, PyPI `30book-mcp`, MCP Registry `io.github.sepehr071/30book-mcp` (not published yet,
no git repo yet). Python package `sibook_mcp` (a module name cannot start with a digit). Sibling of `../shopino-mcp`
and `../masterkala-mcp`; same layout and idioms, keep them in step.

API map this server is built on (pages, circuit transport, quirks, test report): `../30book/`.

## Layout

- `src/sibook_mcp/http.py`: the only HTTP code. One shared `httpx.AsyncClient` (`trust_env=False`, proxy only from
  `SIBOOK_MCP_PROXY`), `html(path)` for plain pages, `render(path, ready, type_into=)` for list pages (opens a Blazor
  circuit, up to 3 attempts), `ApiError(ToolError)`, `set_transport()` for tests, `query()` builds `?a=1&b=True`.
- `blazor.py`: the Blazor Server client (MessagePack + SignalR long polling + render-batch DOM). `dom.py`: tiny DOM and
  HTML parser. `parse.py`: cards, book page, reviews to dicts (Toman ints). `registry.py` / `server.py`: tool registry,
  `INSTRUCTIONS`.
- Tools: `catalog.py` (search, browse, publisher, author, best sellers, new releases, deals, find publisher / person),
  `product.py` (book, similar, reviews, categories, collections). 14 tools, all `sb_*`.
- `tests/`: `test_tools.py` (tools on trimmed real pages in `tests/fixtures/`, `http.html` / `http.render` patched),
  `test_blazor.py` (codecs, a synthetic render-batch writer, a scripted fake SignalR server), `test_http.py` (client,
  errors, README tables), `test_live.py` (`@pytest.mark.live`, one test per tool, about 2 minutes).

## Commands

uv needs the local proxy to download packages; the server and tests call 30book directly (env proxies are ignored).

```bash
export HTTPS_PROXY=http://127.0.0.1:10898 HTTP_PROXY=http://127.0.0.1:10898
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest -q            # offline
uv run pytest -m live -q    # real site
uv build
```

Git Bash mangles `/path` arguments: prefix with `MSYS_NO_PATHCONV=1` when passing site paths to scripts or curl.

## Rules for changes

- Read-only only. Never log in, never touch `/login`, `/basket`, `/profile`, the like / want-to-read / recommend buttons,
  the comment form, contact forms or the analytics hosts. The only events ever fired are `input` and `click` on the
  name box of `/publisher` and `/person`.
- Output units: prices in **Toman**. HTML prices are Toman; the JSON-LD on book pages is Rial (x10) and only fills the
  price of sold-out books. `price` = list price, `final_price` = to pay, `discount_pct` computed; `in_stock` false when
  the page shows no price («ناموجود»). Stock is yes/no, never a count.
- New tool: `@tool("Title")` async function, every param `Annotated[..., Field(...)]` with constraints and an example,
  docstring = what it returns + when to use + what to call next, compact dict output. Add a unit test on a real trimmed
  fixture, a live test, a README tool-table row (a test checks the tables) and an `INSTRUCTIONS` mention.
- Deps stay `mcp` + `httpx`. Write ZWNJ as `‌`, never the invisible character. Keep `Field(pattern=...)` small.

## 30book quirks (keep them)

- No JSON API. Book page / home / landing are plain HTML (cards present). Every list page is an empty shell until a
  Blazor circuit draws it, so `http.render` is used; one list costs 2-5 s and about 10 requests. About 1 in 20 circuits
  fails to render: `render` retries. Keep at most 2 circuits at once (`MAX_CIRCUITS`).
- A markup frame counts as ONE logical child (the browser wraps its nodes in a container); components are logical
  containers too. Getting this wrong shows up as a `stepIn` into a text node. Handler attributes are kept as `@click`.
- Query params are the state: `pg` (0-based), `sort` 1-7, `qt=True`, `pub`, `wtr`, `inp`, `stp=True`. Dummy slugs redirect
  (301) to the canonical URL and the redirect drops the query: resolve first, then append (done in `http.render`).
- Category: `bts-N` section pages are landing pages only (no list); lists work for `bta-N-M` / `btf-N-M-K` (1 / 2 / 3
  dummy slug segments). Award pages use a different layout (`loose` ready test, about 22 cards per page, sort ignored).
- `/special-offers` is mostly stationery (`/product/..` links); `sb_deals` uses best sellers or a subject with `sort=7`.
- Person / publisher name boxes match name fragments and miss some people (Arabic yeh / kaf in stored names).
- `sort=4/5` follow the list price. No price-range filter, no result count (only the last page number).
- `robots.txt` disallows `*/search` for crawlers; keep request rates low.

## Release

Bump `version` in `pyproject.toml` and both versions in `server.json`, `uv lock`, commit, `git tag vX.Y.Z && git push --tags`
once a publish workflow is added (copy `.github/workflows` from `../shopino-mcp`). This file is local only.
