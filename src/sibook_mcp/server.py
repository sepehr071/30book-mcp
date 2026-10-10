"""MCP server entry point: registers every read-only 30book tool."""

import logging

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from . import __version__, catalog, product  # noqa: F401  (imports register the tools)
from .registry import TOOLS

INSTRUCTIONS = """\
Unofficial, read-only access to 30book (30book.com), an Iranian online bookstore with about 200,000 printed books
(Persian and foreign-language), plus some stationery. Nothing here can log in, add to a cart, order or review.

Workflow:
1. Find books: sb_search (title words, sort, in-stock, publisher / author / translator filters; page on with page).
   Names to ids: sb_find_publisher, sb_find_person. Topic browsing: sb_categories -> sb_browse (category, genre,
   nation, award, tag; sb_collections lists them). Publishers and authors: sb_publisher, sb_author.
2. One book: sb_book (authors, translators, publisher, pages, cover, size, ISBN, edition, year, price, stock,
   categories). Same title in other editions or publishers: search the title and compare final_price.
   Alternatives and more by the author: sb_similar. Reader opinions: sb_reviews.
3. Popular and cheap: sb_bestsellers, sb_new_releases, sb_deals.

Conventions: all prices are Toman. price = list price, final_price = what the customer pays (30book gives 10-25%
off most books), discount_pct is an int; in_stock=false means sold out (price may be the last known one). Stock
is yes/no only, never a count. Lists have 20 books per page; `pages` is the last page. Persian queries work
best and the site stores names with Arabic yeh / kaf in places, so try a shorter word if a search is empty.
Listing pages take 2-5 seconds (the site draws them with a live Blazor session), book pages about 1 second.
Shipping is not public: it is quoted at checkout (login).
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)

mcp = MCPServer(
    "30book-mcp",
    title="30book",
    instructions=INSTRUCTIONS,
    version=__version__,
    website_url="https://github.com/sepehr071/30book-mcp",
)

for fn, title in TOOLS:
    mcp.add_tool(fn, title=title, annotations=READ_ONLY)


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per request floods client logs
    mcp.run()


if __name__ == "__main__":
    main()
