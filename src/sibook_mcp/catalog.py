"""List tools: search, browse (category, genre, nation, award, tag), publisher, author, best sellers, new, deals."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import Field

from . import http, parse
from .dom import Node
from .registry import tool

PER_PAGE = 20  # fixed by the site

SORTS = {"views": 1, "bestselling": 2, "favorite": 3, "cheapest": 4, "expensive": 5, "newest": 6, "discount": 7}
Sort = Annotated[
    Literal["views", "bestselling", "favorite", "cheapest", "expensive", "newest", "discount"] | None,
    Field(description="Order; omit for the page default. cheapest / expensive follow list price."),
]
Page = Annotated[int, Field(ge=1, le=500, description="Page from 1.")]
Avail = Annotated[bool, Field(description="Only books that are in stock.")]


def _ready(trees: list[Node]) -> bool:
    return any(
        t.find(cls="product-list-item-search-container") or t.find(cls="product-search-empty-container") for t in trees
    )


def _ready_loose(trees: list[Node]) -> bool:
    return _ready(trees) or any(len(parse.cards(t)) >= 5 for t in trees)


async def listing(path: str, params: dict[str, Any], page: int, *, loose: bool = False) -> dict[str, Any]:
    """Render a list page and return its books. `pg` is 0-based on the site."""
    params = {**params, "pg": page - 1 if page > 1 else None}
    trees = await http.render(path + http.query(params), _ready_loose if loose else _ready)
    items = [c for t in trees for c in parse.cards(t, search_only=not loose)]
    pages = max((parse.pager_last(t) for t in trees), default=1)
    h1 = next((h for t in trees for h in t.find_all("h1")), None)
    desc = next((d for t in trees for d in t.find_all(cls="product-search-top-description-text")), None)
    out: dict[str, Any] = {
        "title": h1.text() if h1 else None,
        "page": page,
        "pages": pages,
        "has_more": page < pages,
        "books": items,
    }
    if desc:
        out["about"] = desc.text()
    if not items:
        out["note"] = "No books matched. Try fewer filters, or extended=true on sb_search."
    return out


def _filters(sort: str | None, available_only: bool, publisher_id: int | None = None, **extra: Any) -> dict[str, Any]:
    return {"sort": SORTS.get(sort or ""), "qt": available_only, "pub": publisher_id, **extra}


@tool("Search books")
async def sb_search(
    query: Annotated[
        str, Field(min_length=1, max_length=100, description="Title words, Persian, e.g. 'شازده کوچولو'.")
    ],
    extended: Annotated[bool, Field(description="Match words, not the exact phrase (more results).")] = False,
    sort: Sort = None,
    available_only: Avail = False,
    publisher_id: Annotated[
        int | None, Field(ge=1, description="Only this publisher (id from sb_find_publisher or a book's publisher.id).")
    ] = None,
    author_id: Annotated[
        int | None, Field(ge=1, description="Only this author (id from sb_find_person or a book's authors[].id).")
    ] = None,
    translator_id: Annotated[int | None, Field(ge=1, description="Only this translator (person id).")] = None,
    page: Page = 1,
) -> dict[str, Any]:
    """Search books by title: price, final_price, discount_pct, in_stock, publisher, id.

    Use first for any book question. Editions of one title are separate books: compare final_price. Next: sb_book(id).
    """
    params = _filters(sort, available_only, publisher_id, wtr=author_id, inp=translator_id, stp=extended)
    return await listing(f"/search/{parse.seg(query)}", params, page)


_CODE = r"^bt[saf]-\d+(-\d+){0,2}$"


@tool("Browse a category, genre, nation, award or tag")
async def sb_browse(
    kind: Annotated[Literal["category", "genre", "nation", "award", "tag"], Field(description="What to open.")],
    key: Annotated[
        str,
        Field(
            min_length=1,
            max_length=100,
            description="category: code like 'bta-1-1' (sb_categories, sb_book); genre / nation / award: id from sb_collections; tag: text, e.g. 'کتاب_های_پرفروش_1404'.",
        ),
    ],
    sort: Sort = None,
    available_only: Avail = False,
    publisher_id: Annotated[int | None, Field(ge=1, description="Only this publisher.")] = None,
    page: Page = 1,
) -> dict[str, Any]:
    """Books of a category (bta-N-M or btf-N-M-K; bts-N sections are landing pages only), genre, nation, award list or tag.

    Use to browse a topic instead of a keyword. Award pages ignore sort / filters and add carousel books (about 22 per page).
    """
    loose = False
    if kind == "category":
        if not re.match(_CODE, key):
            raise ValueError("category key must look like 'bts-1', 'bta-1-1' or 'btf-1-1-1'")
        depth = {"s": 1, "a": 2, "f": 3}[key[2]]
        if depth == 1:
            raise ValueError(
                "a section (bts-N) is only a landing page: pick a subject code from sb_categories(section)"
            )
        path = f"/category/{key}" + "/x" * depth
    elif kind == "genre" and key.isdigit():
        path = f"/genres/{key}/x"
    elif kind == "nation" and key.isdigit():
        path = f"/literature-of-nations/nat-{key}/x"
    elif kind == "award" and key.isdigit():
        path, loose = f"/experts-choice/brw-{key}/x", True
    elif kind == "tag":
        path = f"/tag/{parse.seg(key)}"
    else:
        raise ValueError(f"key for {kind} must be a number" if kind != "tag" else "bad tag")
    return await listing(path, _filters(sort, available_only, publisher_id), page, loose=loose)


@tool("Books of a publisher")
async def sb_publisher(
    publisher_id: Annotated[
        int,
        Field(
            ge=1, description="Publisher id (sb_find_publisher, or publisher.id in sb_book). Example 1 = صدای معاصر."
        ),
    ],
    sort: Sort = None,
    available_only: Avail = False,
    page: Page = 1,
) -> dict[str, Any]:
    """One publisher's books plus a short about text. Try sort='bestselling' or 'cheapest'."""
    return await listing(f"/publisher/bps-1-{publisher_id}/x", _filters(sort, available_only), page)


@tool("Books of an author or translator")
async def sb_author(
    person_id: Annotated[
        int,
        Field(
            ge=1, description="Person id (sb_find_person, or authors[].id / translators[].id in sb_book). Example 6073."
        ),
    ],
    sort: Sort = None,
    available_only: Avail = False,
    page: Page = 1,
) -> dict[str, Any]:
    """Books by one author or translator (default newest first)."""
    return await listing(f"/person/bws-{person_id}/x", _filters(sort, available_only), page)


@tool("Best sellers")
async def sb_bestsellers(
    available_only: Avail = False,
    page: Page = 1,
) -> dict[str, Any]:
    """Site-wide best sellers (10 pages)."""
    return await listing("/best-sellers", _filters(None, available_only), page)


@tool("New releases")
async def sb_new_releases(
    available_only: Avail = False,
    page: Page = 1,
) -> dict[str, Any]:
    """Newest books (10 pages)."""
    return await listing("/new-releases", _filters(None, available_only), page)


@tool("Discounted books")
async def sb_deals(
    subject: Annotated[
        str | None,
        Field(
            pattern=r"^bta-\d+-\d+$",
            description="Subject code such as 'bta-1-1'; omit for all best sellers.",
        ),
    ] = None,
    available_only: Avail = True,
    page: Page = 1,
) -> dict[str, Any]:
    """Best sellers (or one subject) by biggest discount. Some publishers inflate list prices: compare final_price."""
    path = f"/category/{subject}/x/x" if subject else "/best-sellers"
    return await listing(path, _filters("discount", available_only), page)


async def _find(path: str, kind: str, name: str) -> dict[str, Any]:
    def ready(trees: list[Node]) -> bool:
        return any(t.find(cls="product-search-search-input") for t in trees) and any(
            a.get("href").startswith(f"/{kind}/") for t in trees for a in t.find_all("a")
        )

    trees = await http.render(path, ready, type_into=("product-search-search-input", name, "product-search-search-btn"))
    found: list[dict[str, Any]] = []
    for t in trees:
        for a in t.find_all("a"):
            ref = parse.link_ref(a.get("href"), kind)
            if ref and not any("swiper" in p.classes() for p in _ancestors(a)):  # skip the featured-this-week slider
                found.append({"id": ref["id"], "name": a.text()})
    seen: set[int] = set()
    uniq = [x for x in found if not (x["id"] in seen or seen.add(x["id"]))]
    return {
        "matches": uniq,
        "note": None
        if uniq
        else "No match. The box matches name fragments in Persian; try a shorter word (first name or surname).",
    }


def _ancestors(n: Node):
    p = n.parent
    while p is not None:
        yield p
        p = p.parent


@tool("Find a publisher by name")
async def sb_find_publisher(
    name: Annotated[
        str, Field(min_length=2, max_length=60, description="Part of the publisher name, Persian, e.g. 'قطره' or 'نی'.")
    ],
) -> dict[str, Any]:
    """Look up publisher ids by name. Pass the id to sb_search(publisher_id=...) or sb_publisher."""
    return await _find("/publisher", "publisher", name)


@tool("Find an author or translator by name")
async def sb_find_person(
    name: Annotated[
        str, Field(min_length=2, max_length=60, description="Part of a person's name, Persian, e.g. 'آلبر' or 'کامو'.")
    ],
) -> dict[str, Any]:
    """Look up author / translator ids by name. Pass the id to sb_author or sb_search(author_id=...). The box matches
    name fragments and can miss some people: if nothing matches, search a book and read its authors[].id.
    """
    return await _find("/person", "person", name)
