"""Book detail, related lists, reviews, and the category / collection indexes."""

from __future__ import annotations

import re
from typing import Annotated, Any
from urllib.parse import unquote

from pydantic import Field

from . import http, parse
from .dom import Node, parse_html
from .registry import tool

BookId = Annotated[
    int,
    Field(ge=1, le=9_999_999, description="Book id from sb_search / listings (the number in /book/<id>), e.g. 167515."),
]


def _clip(text: str | None, n: int) -> str | None:
    if not text or len(text) <= n:
        return text
    return text[:n].rstrip() + "…"


async def _page(book_id: int) -> Node:
    return parse_html(await http.html(f"/book/{book_id}"))


@tool("Book details")
async def sb_book(
    book_id: BookId,
    max_chars: Annotated[
        int, Field(ge=0, le=20000, description="Cut the description after this many characters (0 = no cut).")
    ] = 1500,
) -> dict[str, Any]:
    """Full details of one book: title, authors, translators, publisher, price (list) and final_price in Toman,
    discount_pct, in_stock, ISBN, pages, cover type (جلد), size (قطع), language, edition (نوبت چاپ), year (Shamsi),
    weight, category chain (codes for sb_browse), rating, tags, description.

    Use after sb_search to compare editions (same title, different publisher / print run / cover) and to get
    author / publisher ids. A sold-out book (in_stock=false) shows its last price. Next: sb_similar, sb_reviews.
    """
    b = parse.book(await _page(book_id), book_id)
    if max_chars:
        b["description"] = _clip(b["description"], max_chars)
        b["review_text"] = _clip(b["review_text"], max_chars)
    return b


@tool("Similar books and more by the author")
async def sb_similar(book_id: BookId) -> dict[str, Any]:
    """The lists on a book's page: similar books from the same topic, more by the same author and, for translations,
    more by the same translator. Each list has up to 20 books with prices in Toman.

    Use for alternatives and 'what else by this author'; for other editions of the same title use sb_search.
    """
    lists = parse.book_lists(await _page(book_id))
    names = {"شاید بپسندید": "similar", "از این نویسنده": "same_author", "از این مترجم": "same_translator"}
    return {names.get(k, k): v for k, v in lists.items()}


@tool("Reader reviews of a book")
async def sb_reviews(book_id: BookId) -> dict[str, Any]:
    """Reader comments on a book (name, Shamsi date, 1-5 stars, text, likes) plus the rating summary. Only the
    first comments the page shows are available. Use to judge quality before buying.
    """
    root = await _page(book_id)
    b = parse.book(root, book_id)
    return {
        "title": b["title"],
        "rating": b["rating"],
        "rating_count": b["rating_count"],
        "review_count": b["review_count"],
        "reviews": parse.reviews(root),
    }


@tool("Category sections and subjects")
async def sb_categories(
    section: Annotated[
        str | None, Field(pattern=r"^bts-\d+$", description="Section code such as 'bts-1'. Omit to list the sections.")
    ] = None,
) -> dict[str, Any]:
    """The top of the category tree: sections (کتاب عمومی, کتاب کودک و نوجوان, ...) and, for one section, its
    subjects (تاریخ, ادبیات, ...). Codes go to sb_browse(kind='category'). Finer topics (btf-...) appear in the
    categories of sb_book.
    """
    if section is None:
        root = parse_html(await http.html("/"))
        refs: dict[str, str] = {}
        for a in root.find_all("a"):
            r = parse.link_ref(a.get("href"), "category")
            if r and r["code"].startswith("bts-") and a.text():
                refs.setdefault(r["code"], a.text())
        return {"sections": [{"code": c, "name": n} for c, n in refs.items()]}

    def ready(trees: list[Node]) -> bool:
        return any(a.get("href").startswith("/category/bta-") for t in trees for a in t.find_all("a"))

    trees = await http.render(f"/category/{section}/x", ready)
    subjects: dict[str, str] = {}
    for t in trees:
        for a in t.find_all("a"):
            r = parse.link_ref(a.get("href"), "category")
            if r and r["code"].startswith("bta-") and a.text() and r["code"] not in subjects:
                subjects[r["code"]] = a.text()
    return {"section": section, "subjects": [{"code": c, "name": n} for c, n in subjects.items()]}


@tool("Genres, nations, awards and tags")
async def sb_collections() -> dict[str, Any]:
    """Curated collections linked from the home page: fiction genres, national literatures, literary award lists and
    the current best-seller tags. Ids and tags go to sb_browse(kind='genre' | 'nation' | 'award' | 'tag').
    """
    root = parse_html(await http.html("/"))
    out: dict[str, list[dict[str, Any]]] = {"genres": [], "nations": [], "awards": [], "tags": []}
    seen: set[str] = set()
    for a in root.find_all("a"):
        href = unquote(a.get("href"))
        if href in seen:
            continue
        seen.add(href)
        if m := re.match(r"^/genres/(\d+)/", href):
            out["genres"].append({"id": int(m.group(1)), "name": a.text()})
        elif m := re.match(r"^/literature-of-nations/nat-(\d+)/", href):
            out["nations"].append({"id": int(m.group(1)), "name": a.text()})
        elif m := re.match(r"^/experts-choice/brw-(\d+)/", href):
            out["awards"].append({"id": int(m.group(1)), "name": a.text()})
        elif href.startswith("/tag/"):
            out["tags"].append({"tag": href[5:], "name": a.text() or href[5:]})
    return out
