<!-- mcp-name: io.github.sepehr071/30book-mcp -->

# 30book-mcp

**Let your AI agent search Iran's 30book bookstore.** Unofficial, read-only MCP server for [30book](https://www.30book.com)
(about 200,000 printed books, Persian and foreign): search by title, compare editions and publishers, see list and
discounted price in Toman, stock, pages, cover type, ISBN, print run, authors, translators, reviews, best sellers and
discounts. No account, no API key, no login, no cart.

[Quick start](#quick-start) · [Tools](#tools) · [How it works](#how-it-works) · [FAQ](#faq) · [فارسی](#فارسی)

## Why

30book has no public API and its list pages are drawn by a live Blazor Server session, so a plain scraper sees empty
pages. This server speaks that protocol (SignalR long polling, no browser needed) and parses the book pages, so an
agent can answer "cheapest edition of Little Prince with a hard cover", "everything by this translator under
300,000 Toman" or "what are the best sellers in history" in a few calls.

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
claude mcp add 30book -- uvx 30book-mcp
```

Other clients (Claude Desktop, Cursor, VS Code): run the command `uvx` with argument `30book-mcp`.
Behind a proxy, set `SIBOOK_MCP_PROXY=http://host:port` (system proxy variables are ignored on purpose).

## Tools

All tools are read-only and prefixed `sb_`. Prices are Toman.

### Find books

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

### One book

| Tool | What it does |
|---|---|
| `sb_book` | Price, final price, discount %, stock, authors, translators, publisher, pages, cover, size, ISBN, print run, year, categories, rating, description |
| `sb_similar` | Similar books, more by the author, more by the translator |
| `sb_reviews` | Reader comments with stars, plus the rating summary |

### Popular and cheap

| Tool | What it does |
|---|---|
| `sb_bestsellers` | Site-wide best sellers |
| `sb_new_releases` | Newest books |
| `sb_deals` | The discounted-books page, biggest discount first on request |

## How it works

- Book pages, the home page and landing pages are plain server-rendered HTML and are parsed directly.
- Search, category, publisher, author, genre and tag pages are built after load by a Blazor Server circuit. The server
  opens one over SignalR long polling, applies the binary render batches to a small DOM (`blazor.py`) and reads the
  cards. Paging, sort and filters are URL query parameters (`pg`, `sort`, `qt`, `pub`, `wtr`, `inp`, `stp`), so no
  clicks are simulated; only the name boxes on the publisher and author index pages use a fired event.
- HTML prices are Toman; the JSON-LD on book pages is Rial (x10) and is only used for sold-out books.
- List pages take 2 to 5 seconds, book pages about 1 second. Stock is yes/no only.

## Development

```bash
export HTTPS_PROXY=http://127.0.0.1:10898 HTTP_PROXY=http://127.0.0.1:10898   # uv downloads only
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest -q            # offline, recorded pages
uv run pytest -m live -q    # real site, one test per tool
```

API map and test report: `../30book/`.

## FAQ

**Does it buy anything?** No. It never logs in and never calls cart, checkout, wishlist or review endpoints.

**Why is a search sometimes empty?** The site stores some names with Arabic yeh / kaf; try a shorter word or `extended=true`.

**Is it affiliated with 30book?** No. Unofficial; keep the request rate low.

## فارسی

سرور MCP غیررسمی و فقط‌خواندنی برای فروشگاه کتاب ۳۰بوک: جستجوی کتاب، مقایسهٔ چاپ‌ها و ناشران، قیمت (تومان) و
تخفیف، موجودی، مشخصات کتاب، نویسنده و مترجم، نظرات، پرفروش‌ها و تخفیف‌ها. نیازی به حساب یا کلید ندارد.

نصب: `claude mcp add 30book -- uvx 30book-mcp`
