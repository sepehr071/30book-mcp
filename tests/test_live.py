"""One live test per tool against the real site (about 1 minute; list tools open a Blazor circuit each)."""

import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.live]

BOOK = 167515  # دو قرن سکوت, صدای معاصر, in stock at mapping time


async def call(client, name, args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


def check_books(books, min_n=1):
    assert len(books) >= min_n
    for b in books:
        assert b["id"] and b["title"] and b["url"].endswith(f"/book/{b['id']}")
        if b["in_stock"]:
            assert 0 < b["final_price"] <= b["price"], b
            assert 0 <= b["discount_pct"] <= 90


async def test_sb_search(client):
    out = await call(client, "sb_search", {"query": "شازده کوچولو", "sort": "cheapest"})
    check_books(out["books"], 10)
    assert out["pages"] >= 2 and any("شازده" in b["title"] for b in out["books"])
    prices = [b["price"] for b in out["books"] if b["in_stock"]]
    assert prices == sorted(prices)  # 'cheapest' follows the list price
    page2 = await call(client, "sb_search", {"query": "شازده کوچولو", "sort": "cheapest", "page": 2})
    assert {b["id"] for b in page2["books"]}.isdisjoint({b["id"] for b in out["books"]})


async def test_sb_search_filters(client):
    out = await call(client, "sb_search", {"query": "سکوت", "publisher_id": 1, "available_only": True})
    check_books(out["books"])
    assert {b["publisher"] for b in out["books"]} == {"صدای معاصر"} and all(b["in_stock"] for b in out["books"])


async def test_sb_browse(client):
    out = await call(client, "sb_browse", {"kind": "category", "key": "bta-1-1", "sort": "discount"})
    check_books(out["books"], 10)
    assert out["title"] and out["pages"] > 10
    genre = await call(client, "sb_browse", {"kind": "genre", "key": "2"})
    check_books(genre["books"], 10)


async def test_sb_publisher(client):
    out = await call(client, "sb_publisher", {"publisher_id": 1})
    check_books(out["books"], 10)
    assert out["title"] == "نشر صدای معاصر" and out["about"]


async def test_sb_author(client):
    out = await call(client, "sb_author", {"person_id": 6073})
    check_books(out["books"])
    assert "قیم" in out["title"] and BOOK in {b["id"] for b in out["books"]}


async def test_sb_bestsellers_new_deals(client):
    for tool in ("sb_bestsellers", "sb_new_releases"):
        check_books((await call(client, tool, {}))["books"], 10)
    deals = await call(client, "sb_deals", {})
    check_books(deals["books"], 10)
    assert deals["books"][0]["discount_pct"] >= deals["books"][-1]["discount_pct"]


async def test_sb_find_publisher(client):
    out = await call(client, "sb_find_publisher", {"name": "قطره"})
    assert {"id": 1050, "name": "نشر قطره"} in out["matches"]


async def test_sb_find_person(client):
    out = await call(client, "sb_find_person", {"name": "آلبر"})
    assert out["matches"] and all("id" in m for m in out["matches"])


async def test_sb_book(client):
    b = await call(client, "sb_book", {"book_id": BOOK})
    assert b["title"] == "دو قرن سکوت" and b["isbn"] == "9786229255872" and b["pages"] == 300
    assert b["publisher"]["id"] == 1 and b["authors"][0]["id"] == 6073
    assert b["categories"][0]["code"] == "bts-1" and b["year_shamsi"] == 1403
    assert b["price"] > 0 and (b["final_price"] or 0) <= b["price"]


async def test_sb_similar_and_reviews(client):
    sim = await call(client, "sb_similar", {"book_id": BOOK})
    check_books(sim["similar"], 5)
    check_books(sim["same_author"], 1)
    rev = await call(client, "sb_reviews", {"book_id": BOOK})
    assert rev["review_count"] >= 1 and rev["reviews"] and 1 <= rev["reviews"][0]["stars"] <= 5


async def test_sb_categories_and_collections(client):
    sections = (await call(client, "sb_categories", {}))["sections"]
    assert "bts-1" in {s["code"] for s in sections}
    subjects = (await call(client, "sb_categories", {"section": "bts-1"}))["subjects"]
    assert "bta-1-1" in {s["code"] for s in subjects}
    c = await call(client, "sb_collections", {})
    assert c["genres"] and c["nations"] and c["awards"]
