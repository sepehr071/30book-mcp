import pytest
from conftest import fixture_text

pytestmark = pytest.mark.anyio


async def call(client, name, args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


# ---------------------------------------------------------------- book pages


async def test_sb_book_discounted(client, site):
    site.pages["/book/167515"] = fixture_text("book_167515.html")
    b = await call(client, "sb_book", {"book_id": 167515, "max_chars": 100})
    assert b["title"] == "دو قرن سکوت"
    assert (b["price"], b["final_price"], b["discount_pct"], b["in_stock"]) == (700000, 525000, 25, True)
    assert b["authors"] == [{"id": 6073, "name": "عبدالنبی قیم"}]
    assert b["translators"] == [] and b["publisher"] == {"id": 1, "name": "صدای معاصر"}
    assert (b["isbn"], b["pages"], b["cover"], b["size"], b["edition"], b["year_shamsi"], b["weight_g"]) == (
        "9786229255872", 300, "گالینگور", "وزیری", 1, 1403, 600,
    )  # fmt: skip
    assert [c["code"] for c in b["categories"]] == ["bts-1", "bta-1-1", "btf-1-1-1"]
    assert (b["rating"], b["rating_count"], b["review_count"]) == (2.0, 5, 5)
    assert len(b["description"]) <= 101 and b["image"].endswith("/Media/Book/167515.jpg")


async def test_sb_book_translated_and_sold_out(client, site):
    site.pages["/book/6426"] = fixture_text("book_6426_translated.html")
    site.pages["/book/103736"] = fixture_text("book_103736_soldout.html")
    t = await call(client, "sb_book", {"book_id": 6426})
    assert t["authors"][0]["name"] == "تونی گراس" and t["translators"] == [{"id": 4177, "name": "میترا لبافی"}]
    assert t["publisher"]["id"] == 511 and t["edition"] == 22
    s = await call(client, "sb_book", {"book_id": 103736})
    # sold out: no price on the page; the JSON-LD offer (Rial 217500) gives 21,750 Toman
    assert s["in_stock"] is False and s["final_price"] == 21750 and s["discount_pct"] == 0


async def test_sb_similar(client, site):
    site.pages["/book/167515"] = fixture_text("book_167515.html")
    out = await call(client, "sb_similar", {"book_id": 167515})
    assert set(out) == {"similar", "same_author"}
    first = out["similar"][0]
    assert first["id"] and first["final_price"] and first["url"].startswith("https://www.30book.com/book/")


async def test_sb_reviews(client, site):
    site.pages["/book/167515"] = fixture_text("book_167515.html")
    out = await call(client, "sb_reviews", {"book_id": 167515})
    assert out["review_count"] == 5 and out["reviews"][0]["stars"] == 5
    assert out["reviews"][0]["author"] == "جواد عیدان" and out["reviews"][0]["date"] == "30 مرداد 1404"


async def test_book_not_found(client, site):
    result = await client.call_tool("sb_book", {"book_id": 9999999})
    assert result.is_error and "404" in result.content[0].text


async def test_sb_categories_and_collections(client, site):
    site.pages["/"] = fixture_text("home_links.html")
    sections = (await call(client, "sb_categories", {}))["sections"]
    assert sections == [{"code": "bts-1", "name": "کتاب عمومی"}, {"code": "bts-4", "name": "کتاب کودک و نوجوان"}]
    c = await call(client, "sb_collections", {})
    assert c["genres"] == [{"id": 2, "name": "داستان فانتزی"}]
    assert c["nations"][0]["id"] == 4 and c["awards"][0]["id"] == 1
    assert c["tags"][0]["tag"] == "پرفروش_های_شهریور_1405"


# ---------------------------------------------------------------- lists


async def test_sb_search_builds_the_url_and_parses_cards(client, site):
    site.lists["/search/"] = fixture_text("list_search.html")
    out = await call(
        client,
        "sb_search",
        {
            "query": "شازده کوچولو",
            "sort": "cheapest",
            "available_only": True,
            "publisher_id": 5,
            "page": 2,
            "extended": True,
        },
    )
    assert site.last() == "/search/شازده کوچولو?sort=4&qt=True&pub=5&stp=True&pg=1"
    assert out["page"] == 2 and out["pages"] >= 2 and out["has_more"] is True
    book = out["books"][0]
    assert book["title"].startswith("شازده کوچولو") and book["publisher"] == "نگاه"
    assert (book["price"], book["final_price"], book["discount_pct"]) == (500000, 425000, 15)


async def test_sb_search_empty(client, site):
    site.lists["/search/"] = fixture_text("list_empty.html")
    out = await call(client, "sb_search", {"query": "qqqzzz"})
    assert out["books"] == [] and "No books matched" in out["note"] and site.last() == "/search/qqqzzz"


async def test_sb_publisher_and_author_paths(client, site):
    site.lists["/publisher/"] = fixture_text("list_publisher.html")
    site.lists["/person/"] = fixture_text("list_publisher.html")
    out = await call(client, "sb_publisher", {"publisher_id": 1, "sort": "discount"})
    assert site.last() == "/publisher/bps-1-1/x?sort=7"
    assert out["title"] == "نشر صدای معاصر" and out["about"].startswith("صدای معاصر") and out["pages"] > 1
    await call(client, "sb_author", {"person_id": 6073, "available_only": True})
    assert site.last() == "/person/bws-6073/x?qt=True"


@pytest.mark.parametrize(
    ("args", "path"),
    [
        ({"kind": "category", "key": "bta-1-1"}, "/category/bta-1-1/x/x"),
        ({"kind": "category", "key": "btf-1-1-1", "publisher_id": 1}, "/category/btf-1-1-1/x/x/x?pub=1"),
        ({"kind": "genre", "key": "2"}, "/genres/2/x"),
        ({"kind": "nation", "key": "4", "sort": "newest"}, "/literature-of-nations/nat-4/x?sort=6"),
        ({"kind": "award", "key": "1"}, "/experts-choice/brw-1/x"),
        ({"kind": "tag", "key": "پرفروش_های_شهریور_1405"}, "/tag/پرفروش_های_شهریور_1405"),
    ],
)
async def test_sb_browse_paths(client, site, args, path):
    site.lists["/"] = fixture_text("list_publisher.html")
    await call(client, "sb_browse", args)
    assert site.last() == path


async def test_sb_deals_sorts_by_discount(client, site):
    site.lists["/"] = fixture_text("list_publisher.html")
    await call(client, "sb_deals", {})
    assert site.last() == "/best-sellers?sort=7&qt=True"
    await call(client, "sb_deals", {"subject": "bta-1-1", "available_only": False})
    assert site.last() == "/category/bta-1-1/x/x?sort=7"


async def test_sb_browse_bad_key(client, site):
    for key in ("nope", "bts-1"):
        result = await client.call_tool("sb_browse", {"kind": "category", "key": key})
        assert result.is_error


@pytest.mark.parametrize(
    ("tool", "path"),
    [("sb_bestsellers", "/best-sellers"), ("sb_new_releases", "/new-releases")],
)
async def test_sb_fixed_lists(client, site, tool, path):
    site.lists["/"] = fixture_text("list_publisher.html")
    out = await call(client, tool, {"page": 3})
    assert site.last() == f"{path}?pg=2" and out["page"] == 3


async def test_sb_find_publisher_skips_the_featured_slider(client, site):
    site.lists["/publisher"] = fixture_text("find_publisher.html")
    out = await call(client, "sb_find_publisher", {"name": "قطره"})
    assert out["matches"] == [{"id": 1050, "name": "نشر قطره"}]
    assert site.typed == [("product-search-search-input", "قطره", "product-search-search-btn")]
