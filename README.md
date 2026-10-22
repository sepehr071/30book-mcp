<!-- mcp-name: io.github.sepehr071/30book-mcp -->

# 30book-mcp: 30book MCP server for AI agents

**Let your AI agent search Iran's 30book bookstore (<span dir="rtl">۳۰بوک</span>).**<br>
An unofficial, read-only MCP server for [30book](https://www.30book.com), an Iranian online bookstore with about 200,000 printed books:
search by title, compare editions and publishers, see list and discounted prices in Toman, stock, ISBN, authors, translators, reviews, best sellers and discounts, all from Claude, Cursor or Copilot.

[![PyPI](https://img.shields.io/pypi/v/30book-mcp?color=2563eb)](https://pypi.org/project/30book-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/30book-mcp)](https://pypi.org/project/30book-mcp/)
[![CI](https://github.com/sepehr071/30book-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sepehr071/30book-mcp/actions/workflows/ci.yml)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-io.github.sepehr071%2F30book--mcp-7c3aed)](https://registry.modelcontextprotocol.io/?q=30book-mcp)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)](https://github.com/sepehr071/30book-mcp/blob/main/LICENSE)
[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_30book--mcp-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=30book&config=%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%2230book-mcp%22%5D%7D)

[For AI agents](#for-ai-agents) · [Why](#why) · [What it can do](#what-it-can-do) · [Quick start](#quick-start) · [Tools](#tools) · [How it works](#how-it-works) · [Good to know](#good-to-know) · [FAQ](#faq) · [Configuration](#configuration) · [فارسی](#فارسی) · [Development](#development) · [Related servers](#related-servers) · [Disclaimer](#disclaimer) · [License](#license)

---

## For AI agents

- **What:** unofficial MCP server for 30book (30book.com), an Iranian online bookstore. Search terms work best in Persian (titles, names); prices in Toman.
- **Install:** `uvx 30book-mcp` or `claude mcp add 30book -- uvx 30book-mcp`. Transport: stdio. Needs [uv](https://docs.astral.sh/uv/getting-started/installation/) (Python 3.10+), or `pip install 30book-mcp`.
- **Auth:** none, no API key or account. Optional `SIBOOK_MCP_PROXY` (HTTP proxy URL, or a comma-separated list, for requests to 30book.com).
- **Access:** read-only. It never logs in and has no cart, checkout, wishlist or review-writing tools, so no confirmation is needed before calling any tool.
- **Tools:** 14, all prefixed `sb_`. Start with `sb_search`, `sb_book`, `sb_bestsellers`, `sb_deals`, `sb_browse`.
  Typical sequence: `sb_search` -> `sb_book` -> `sb_similar` or `sb_reviews`; for one person or publisher, `sb_find_person` / `sb_find_publisher` -> `sb_author` / `sb_publisher`.
- **Units:** prices in Toman (`price` list price, `final_price` to pay, `discount_pct` int). Stock is yes/no, never a count. About 20 books per page (award pages about 22).
- **Use when:** comparing editions, publishers, prices, stock or ratings of printed Iranian and foreign books on 30book.
- **Do not use when:** the user wants to buy or order (no cart or checkout), needs shipping cost (quoted at checkout), wants e-books or audiobooks, or other bookstores.
- **Machine-readable:** [`server.json`](https://github.com/sepehr071/30book-mcp/blob/main/server.json) and the
  [awesome-iran-mcp catalog](https://github.com/sepehr071/awesome-iran-mcp) (`TOOLS.md`, `servers.json`, `llms.txt`).

## Why

30book has no public API and its list pages are drawn by a live Blazor Server session, so a plain scraper sees empty
pages. This server speaks that protocol (SignalR long polling, no browser needed) and parses the book pages, so an
agent can answer "cheapest edition of Little Prince with a hard cover", "everything by this translator under
300,000 Toman" or "what are the best sellers in history" in a few calls.

## What it can do

- **Search** books by title (exact phrase or word by word), with sort, in-stock, publisher, author and translator filters
- **Compare editions and publishers**: the same title from several publishers, list price against the price to pay
- **Book details**: price, discount, stock, authors, translators, publisher, pages, cover, size, ISBN, language, edition (print number), year (Shamsi), weight, categories, rating, tags, description
- **Browse** categories, fiction genres, national literatures, literary award lists and tags
- **Publishers and people**: one publisher's catalogue, everything by an author or translator, name to id lookups
- **Reader opinion**: reviews with stars and the rating summary, similar books
- **Popular and cheap**: site-wide best sellers, newest books, best sellers by biggest discount
- **Read-only by design**: no login, no cart, no orders

Example prompts:

- "Cheapest edition of The Little Prince (شازده کوچولو) with a hard cover on 30book?"
- "List books by this translator under 300,000 Toman and show their ratings."
- "What are the best sellers in history right now, and which has the biggest discount?"
- <span dir="rtl">ارزان&zwnj;ترین چاپ رمان «صد سال تنهایی» در ۳۰بوک کدام است؟</span>
- <span dir="rtl">پرفروش&zwnj;ترین کتاب&zwnj;های روانشناسی را با قیمت و تخفیف نشان بده.</span>
- <span dir="rtl">کتاب&zwnj;های این ناشر را از ارزان به گران مرتب کن.</span>

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). No API key or account.

<details open>
<summary><b>Claude Code</b></summary>

```bash
claude mcp add 30book -- uvx 30book-mcp
```
</details>

<details>
<summary><b>Claude Desktop</b></summary>

Settings → Developer → Edit Config, then add:

```json
{
  "mcpServers": {
    "30book": { "command": "uvx", "args": ["30book-mcp"] }
  }
}
```
</details>

<details>
<summary><b>Cursor</b></summary>

Add the Claude Desktop block above to `~/.cursor/mcp.json` (or `.cursor/mcp.json` in a project).
</details>

<details>
<summary><b>VS Code (Copilot agent mode)</b></summary>

Click **Install in VS Code** above, or add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "30book": { "type": "stdio", "command": "uvx", "args": ["30book-mcp"] }
  }
}
```
</details>

<details>
<summary><b>Codex CLI</b></summary>

```bash
codex mcp add 30book -- uvx 30book-mcp
```

Or in `~/.codex/config.toml`:

```toml
[mcp_servers.30book]
command = "uvx"
args = ["30book-mcp"]
```
</details>

<details>
<summary><b>Gemini CLI</b></summary>

Add to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "30book": { "command": "uvx", "args": ["30book-mcp"] }
  }
}
```
</details>

<details>
<summary><b>Windsurf</b></summary>

Add the Claude Desktop block to `~/.codeium/windsurf/mcp_config.json`.
</details>

<details>
<summary><b>Anything else</b></summary>

It is a standard stdio MCP server: run `uvx 30book-mcp`, or `pip install 30book-mcp` and run `30book-mcp`.
</details>

Behind a proxy, set `SIBOOK_MCP_PROXY=http://host:port` (system proxy variables are ignored on purpose).

## Tools

All 14 tools are read-only and prefixed `sb_`. Prices are Toman. Pass book, publisher and person ids between tools.

<details open>
<summary><b>Find books</b> (8)</summary>

| Tool | What it does |
|---|---|
| `sb_search` | Search by title (exact phrase or word by word) with sort, in-stock, publisher, author and translator filters; 20 per page |
| `sb_browse` | Books of a category (section, subject, topic), fiction genre, national literature, literary award or tag |
| `sb_publisher` | One publisher's catalogue with a short description |
| `sb_author` | Everything by one author or translator |
| `sb_find_publisher` | Publisher name to id |
| `sb_find_person` | Author / translator name to id |
| `sb_categories` | Category sections and their subjects (codes for `sb_browse`) |
| `sb_collections` | Genres, national literatures, award lists and current tags |
</details>

<details open>
<summary><b>One book</b> (3)</summary>

| Tool | What it does |
|---|---|
| `sb_book` | Price, final price, discount %, stock, authors, translators, publisher, pages, cover, size, ISBN, language, edition (print number), year (Shamsi), weight, categories, rating, tags, description |
| `sb_similar` | Similar books, more by the author, more by the translator |
| `sb_reviews` | Reader comments with stars, plus the rating summary |
</details>

<details open>
<summary><b>Popular and cheap</b> (3)</summary>

| Tool | What it does |
|---|---|
| `sb_bestsellers` | Site-wide best sellers |
| `sb_new_releases` | Newest books |
| `sb_deals` | Best sellers, optionally sorted by biggest discount |
</details>

All tools are annotated `readOnlyHint: true` and return compact JSON.

## How it works

```text
  AI agent  (Claude, Cursor, Copilot, ...)
      │
      │  MCP over stdio
      ▼
  30book-mcp  (runs on your machine)
      │
      │  HTTPS (Chrome TLS/HTTP2 fingerprint) + SignalR long polling
      └──────▶  30book.com   book pages, Blazor-drawn list pages
```

- Book pages, the home page and landing pages are plain server-rendered HTML and are parsed directly.
- Search, category, publisher, author, genre and tag pages are built after load by a Blazor Server circuit. The server
  opens one over SignalR long polling, applies the binary render batches to a small DOM and reads the
  cards. Paging, sort and filters are URL query parameters, so no clicks are simulated; only the name boxes on the
  publisher and author index pages use a fired event.
- It runs on your machine and calls 30book directly; there is no hosted server in between.

## Good to know

- **Prices are in Toman.** HTML prices are Toman; the JSON-LD on book pages is Rial (x10) and is only used for sold-out books.
- **`price` is the list price, `final_price` is what you pay**, `discount_pct` is computed. `in_stock: false` means sold out (the price may be the last known one).
- **Stock is yes/no only**, never a count.
- **Speed:** list pages take 2 to 5 seconds (a Blazor session is opened per list), book pages about 1 second. Book pages are cached for 5 minutes, so book -> similar -> reviews is one fetch.
- **Search is name-fragment based.** The site stores some names with Arabic yeh / kaf, so a person or publisher lookup can miss; try a shorter word.
- **Categories:** `bts-N` section pages are landing pages only; lists work for subject and topic codes (see `sb_categories`). Award pages show about 22 books per page and ignore sort.
- **No price-range filter and no result count**; only the last page number is known.
- **Special offers** on the site are mostly stationery, so `sb_deals` uses best sellers or one subject sorted by discount.
- **Not covered:** shipping cost (quoted at checkout after login), e-books, audiobooks, buying.
- **Request rate:** at most 2 requests at once with a short random delay, and timeouts, 429 and 5xx are retried up to twice. Keep your own call rate low; the site's `robots.txt` disallows `*/search` for crawlers.
- **Proxy:** `SIBOOK_MCP_PROXY` (see [Configuration](#configuration)).

## FAQ

<details>
<summary><b>Is there a 30book API or MCP server for AI agents?</b></summary>

30book has no public API. `30book-mcp` is an unofficial MCP server with 14 read-only tools that reads the site's
pages and exposes them to any MCP client, so an agent can search books and compare prices.
</details>

<details>
<summary><b>How do I use 30book with Claude, Cursor or Copilot?</b></summary>

Run `claude mcp add 30book -- uvx 30book-mcp`, or use the matching config in [Quick start](#quick-start) for Claude
Desktop, Cursor, VS Code, Codex CLI, Gemini CLI or Windsurf, then ask in plain language, in Persian or English.
</details>

<details>
<summary><b>Can it buy a book for me?</b></summary>

No, and that is deliberate. It never logs in and never calls cart, checkout, wishlist or review endpoints. The agent
finds the best edition; you order on the site.
</details>

<details>
<summary><b>Why is a search sometimes empty?</b></summary>

The site stores some names with Arabic yeh / kaf. Try a shorter word, or the `extended=true` option of `sb_search`.
</details>

<details>
<summary><b>Do I need an Iranian IP, and is it free?</b></summary>

It is free and needs no key. It calls 30book.com directly; if that host is unreachable from your network, set
`SIBOOK_MCP_PROXY` to an HTTP proxy. System proxy variables are ignored on purpose.
</details>

<details>
<summary><b>What if the site shows a bot-check page?</b></summary>

Requests use a Chrome TLS/HTTP2 fingerprint. If the site still serves a bot-check page, install the optional browser
extra (`pip install "30book-mcp[browser]"`, then `patchright install chromium`) to clear it once.
</details>

<details>
<summary><b>Does it find e-books or audiobooks?</b></summary>

No, 30book sells printed books (and some stationery). For e-books and audiobooks see
[taaghche-mcp](https://github.com/sepehr071/taaghche-mcp) and [fidibo-mcp](https://github.com/sepehr071/fidibo-mcp).
</details>

<details>
<summary><b>Claude Desktop says <code>uvx</code> is not found</b></summary>

Use the full path to `uvx` (`where uvx` on Windows, `which uvx` on macOS/Linux) as `command`.
</details>

<details>
<summary><b>How do I debug what the agent sees?</b></summary>

```bash
npx @modelcontextprotocol/inspector uvx 30book-mcp
```
</details>

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SIBOOK_MCP_PROXY` | unset | Optional HTTP proxy URL for requests to 30book.com, or a comma-separated list used one at a time (the next one after a block or connect error). System proxy settings are ignored |

<a id="فارسی"></a>

## فارسی: سرور MCP کتاب ۳۰بوک

<div dir="rtl">

**30book-mcp** یک سرور MCP غیررسمی و فقط&zwnj;خواندنی برای ۳۰بوک (30book.com)، فروشگاه اینترنتی کتاب در ایران با حدود ۲۰۰ هزار عنوان کتاب چاپی، است. این سرور به دستیار هوش مصنوعی شما (Claude، Cursor، Copilot و ...) اجازه می&zwnj;دهد کتاب جستجو کند، چاپ&zwnj;ها و ناشران را مقایسه کند و قیمت و تخفیف را ببیند.

**چه کارهایی می&zwnj;کند**

- **جستجوی کتاب** با عنوان، و فیلتر ناشر، نویسنده، مترجم و موجودی.
- **مقایسهٔ چاپ&zwnj;ها و ناشران** با قیمت (تومان)، قیمت پس از تخفیف و درصد تخفیف.
- **مشخصات کتاب**: موجودی، شابک، تعداد صفحه، نوع جلد، قطع، نوبت چاپ، سال نشر، نویسنده و مترجم.
- **مرور موضوعات**: دسته&zwnj;بندی&zwnj;ها، ژانرها، ادبیات ملل، جوایز ادبی و برچسب&zwnj;ها.
- **نظرات خوانندگان** با امتیاز، کتاب&zwnj;های مشابه، پرفروش&zwnj;ها، تازه&zwnj;ها و تخفیف&zwnj;ها.

**نکته&zwnj;ها**

- فقط خواندنی است: وارد حساب نمی&zwnj;شود، سبد خرید نمی&zwnj;سازد و سفارش ثبت نمی&zwnj;کند.
- همه قیمت&zwnj;ها به تومان است. موجودی فقط «موجود» یا «ناموجود» است، نه تعداد.
- هزینهٔ ارسال در سایت عمومی نیست و هنگام ثبت سفارش محاسبه می&zwnj;شود.
- کلید API یا حساب کاربری لازم ندارد. جستجو با کلمات فارسی بهتر جواب می&zwnj;دهد.

**نصب** (اول [uv](https://docs.astral.sh/uv/getting-started/installation/) را نصب کنید). در Claude Code:

</div>

```bash
claude mcp add 30book -- uvx 30book-mcp
```

<div dir="rtl">

در Claude Desktop، Cursor و بقیه برنامه&zwnj;ها همان تنظیم بخش [Quick start](#quick-start) را بگذارید.

**نمونه پرسش&zwnj;ها**

- «ارزان&zwnj;ترین چاپ شازده کوچولو با جلد گالینگور کدام است؟»
- «پرفروش&zwnj;ترین کتاب&zwnj;های ۳۰بوک کدام&zwnj;اند و کدام بیشترین تخفیف را دارند؟»
- «کتاب&zwnj;های این مترجم را زیر ۳۰۰ هزار تومان نشان بده.»

**عبارت&zwnj;های جستجو:** خرید کتاب، قیمت کتاب، مقایسه قیمت کتاب، کتاب&zwnj;فروشی اینترنتی، ۳۰بوک، سی&zwnj;بوک، تخفیف کتاب، پرفروش&zwnj;ترین کتاب&zwnj;ها، ناشر، مترجم، شابک، سرور MCP فارسی.

</div>

## Development

```bash
git clone https://github.com/sepehr071/30book-mcp && cd 30book-mcp
uv sync
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest -q            # offline, recorded pages
uv run python -m pytest -m live -q    # real site, one test per tool
```

Tools live in `src/sibook_mcp/catalog.py` and `product.py` (the Python package is `sibook_mcp`, because a module name
cannot start with a digit); each is a typed async function with a docstring that tells the agent when to use it. A test
checks that the tool tables in this README match the server. Issues and PRs are welcome.

Releases: bump the version in `pyproject.toml` and `server.json`, then push a `v*` tag. GitHub Actions tests,
publishes to PyPI and the [MCP Registry](https://registry.modelcontextprotocol.io), and creates the GitHub Release.

## Related servers

- [Taaghche MCP server](https://github.com/sepehr071/taaghche-mcp) for Iranian e-books and audiobooks
- [Fidibo MCP server](https://github.com/sepehr071/fidibo-mcp) for Persian e-books and audiobooks
- [Shopino MCP server](https://github.com/sepehr071/shopino-mcp) for another Iranian online shop
- [Digikala MCP server](https://github.com/sepehr071/digikala-mcp) for Iran's largest online store
- [awesome-iran-mcp](https://github.com/sepehr071/awesome-iran-mcp): catalog of all Iranian-service MCP servers

## Disclaimer

Unofficial and not affiliated with or endorsed by 30book. It reads the site's public pages, which can change without
notice. It is read-only: it never logs in and never changes anything on the site. Please keep request rates reasonable.

## Author

<a href="https://www.linkedin.com/in/sepehr-radmard"><img src="https://raw.githubusercontent.com/sepehr071/awesome-iran-mcp/main/assets/author-banner.png" alt="Sepehr Radmard: open-source MCP servers for the Iranian web. LinkedIn: linkedin.com/in/sepehr-radmard" width="100%"></a>

Built and maintained by **Sepehr Radmard** (سپهر رادمرد). Connect on [LinkedIn](https://www.linkedin.com/in/sepehr-radmard) or follow [@sepehr071 on GitHub](https://github.com/sepehr071) for more MCP servers for Iranian websites, all listed in [awesome-iran-mcp](https://github.com/sepehr071/awesome-iran-mcp). If this saves you time, a star on the repo helps other people find it.

## License

[MIT](https://github.com/sepehr071/30book-mcp/blob/main/LICENSE)

If this saves you clicks, a star helps others find it.
