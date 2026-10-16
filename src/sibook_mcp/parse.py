"""Turn 30book HTML (page or rendered Blazor tree) into plain dicts. All prices come out in Toman as ints."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, unquote

from .dom import Node

SITE = "https://www.30book.com"
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def num(text: str | None) -> int | None:
    """'1٬762٬500 تومان' / '۱۲۰' -> int; None when there is no digit."""
    digits = re.sub(r"\D", "", (text or "").translate(_DIGITS))
    return int(digits) if digits else None


def fix_yeh(text: str) -> str:
    """The site's image alt text uses Arabic yeh/kaf; titles use Persian ones. Normalise for display."""
    return text.replace("ي", "ی").replace("ك", "ک")


def _txt(n: Node | None) -> str | None:
    t = n.text() if n else ""
    return t or None


def _img(n: Node) -> str | None:
    img = n.find("img")
    src = img.get("data-src") or img.get("src") if img else ""
    return SITE + src if src.startswith("/") else (src or None)


def discount_pct(price: int | None, final: int | None) -> int:
    if not price or not final or final >= price:
        return 0
    return round(100 * (price - final) / price)


def book_href(href: str) -> tuple[int, str] | None:
    m = re.match(r"^/book/(\d+)(?:/(.*))?$", unquote(href))
    return (int(m.group(1)), m.group(2) or "") if m else None


def card(n: Node) -> dict[str, Any] | None:
    """One book card (`.product-list-item-container`): list, search and carousel cards share this markup."""
    a = n.find("a")
    ref = book_href(a.get("href")) if a else None
    if not ref:
        return None
    final = num(_txt(n.find(cls="product-list-item-price-final")))
    list_price = num(_txt(n.find(cls="product-list-item-price")))
    if final is None:  # no discount: the single price is shown as the final one, or nothing when unavailable
        list_price = None
    price = list_price or final
    return {
        "id": ref[0],
        "title": _txt(n.find(cls="product-list-item-name")),
        "publisher": _txt(n.find(cls="product-list-item-producer")),
        "price": price,
        "final_price": final,
        "discount_pct": discount_pct(price, final),
        "in_stock": final is not None,
        "image": _img(n),
        "url": f"{SITE}/book/{ref[0]}",
    }


def cards(root: Node, search_only: bool = False) -> list[dict[str, Any]]:
    """Book cards in document order, deduped by id."""
    if search_only:
        boxes = [
            c.find(cls="product-list-item-container") for c in root.find_all(cls="product-list-item-search-container")
        ]
    else:
        boxes = root.find_all(cls="product-list-item-container")
    out: dict[int, dict[str, Any]] = {}
    for b in boxes:
        c = card(b) if b else None
        if c and c["id"] not in out:
            out[c["id"]] = c
    return list(out.values())


def pager_last(root: Node) -> int:
    """Highest page number shown in the pager (1 when there is no pager)."""
    pages = [int(b.text()) for b in root.find_all("button", "pager-btn") if b.text().isdigit()]
    return max(pages, default=1)


def link_ref(href: str, kind: str) -> dict[str, Any] | None:
    """`/publisher/bps-1-1/نشر-x` -> {code, id, slug}; kind is publisher | person | category."""
    m = re.match(rf"^/{kind}/([a-z]+-[\d-]+)(?:/(.*))?$", unquote(href))
    if not m:
        return None
    return {"code": m.group(1), "slug": m.group(2) or "", "id": int(m.group(1).split("-")[-1])}


def path_quote(path: str) -> str:
    return quote(path, safe="/?=&%,:_-.~")


def seg(s: str) -> str:
    """Make free text safe as ONE path segment: no '/', '?', '&', '=', '#', '%' or '\\' and no '.' / '..'."""
    if not s.strip("."):
        raise ValueError("value must contain more than dots")
    return re.sub(r"[/?#&=%\\]", lambda m: quote(m.group(), safe=""), s)


# ---------------------------------------------------------------- book page


def _links(n: Node | None, kind: str) -> list[dict[str, Any]]:
    out = []
    for a in n.find_all("a") if n else []:
        ref = link_ref(a.get("href"), kind)
        if ref:
            out.append({"id": ref["id"], "name": a.text()})
    return out


def _row(root: Node, label: str) -> Node | None:
    """The value cell of a `.product-table-row` whose label matches (details tab)."""
    for r in root.find_all(cls="product-table-row"):
        cols = r.find_all("div")
        texts = [c.text() for c in cols]
        if any(t == label for t in texts[:4]):
            return next((c for c in r.find_all("div") if c.get("class") == "col"), None)
    return None


def _labelled(root: Node, label: str, kind: str) -> list[dict[str, Any]]:
    """Authors / translators in the title block: a `.product-main-label` followed by person links."""
    out: list[dict[str, Any]] = []
    for lab in root.find_all(cls="product-main-label"):
        if lab.text().rstrip(":").strip() == label:
            out += _links(lab.parent.parent if lab.parent else None, kind)
    seen, uniq = set(), []
    for x in out:
        if x["id"] not in seen:
            seen.add(x["id"])
            uniq.append(x)
    return uniq


def _ld_price(root: Node) -> int | None:
    for sc in root.find_all("script"):
        if "ld+json" in sc.get("type"):
            m = re.search(
                r'"@type"\s*:\s*"Book".*?"price"\s*:\s*"(\d+)"',
                "".join(c for c in sc.children if isinstance(c, str)),
                re.S,
            )
            if m:
                return int(m.group(1))
    return None


def book(root: Node, book_id: int) -> dict[str, Any]:
    """The book page (plain server-rendered HTML). HTML prices are Toman; the JSON-LD copy is Rial."""
    title = root.find("h1", "product-title")
    final = num(_txt(root.find(cls="product-final-price")))
    listed = num(_txt(root.find(cls="product-price")))
    in_stock = final is not None
    if final is None:  # sold out: the page shows no price, the JSON-LD offer keeps the last one (Rial)
        rial = _ld_price(root)
        final = rial // 10 if rial else None
    price = listed or final
    cells = {}
    for r in root.find_all(cls="product-table-row"):
        divs = [d for d in r.find_all("div") if d.get("class").startswith("col")]
        if len(divs) >= 2:
            cells[divs[0].text()] = divs[1]

    def cell(label: str) -> str | None:
        return _txt(cells.get(label))

    rate = root.find(cls="product-rate-container")
    rtxt = rate.text() if rate else ""
    m = re.match(r"([\d٫.]+)\s*\((\d+)\)\s*(\d+)\s*نظر", rtxt.translate(_DIGITS))
    stats = [d.text() for d in root.find_all(cls="product-stat-inner-container")[:1]]
    crumbs = []
    for a in root.find_all("a"):
        ref = link_ref(a.get("href"), "category")
        if ref and a.parent and "product-breadcrumb" in (a.parent.parent.classes() if a.parent.parent else set()):
            crumbs.append({"code": ref["code"], "name": a.text()})
    desc = root.find(cls="product-info-container")
    review = root.find(cls="product-site-content-container")
    pages = cell("تعداد صفحه")
    return {
        "id": book_id,
        "title": fix_yeh(title.text()) if title else None,
        "authors": _labelled(root, "نویسنده", "person"),
        "translators": _labelled(root, "مترجم", "person"),
        "publisher": next(iter(_labelled(root, "نشر", "publisher")), None),
        "price": price,
        "final_price": final,
        "discount_pct": discount_pct(price, final),
        "in_stock": in_stock,
        "isbn": cell("شابک"),
        "pages": num(pages),
        "cover": cell("جلد کتاب"),
        "size": cell("قطع کتاب"),
        "language": cell("زبان کتاب"),
        "edition": num(cell("نوبت چاپ")),
        "year_shamsi": num(cell("سال انتشار")),
        "weight_g": num(cell("وزن")),
        "categories": crumbs,
        "rating": float(m.group(1).replace("٫", ".")) if m else None,
        "rating_count": int(m.group(2)) if m else 0,
        "review_count": int(m.group(3)) if m else 0,
        "tags": [a.text() for a in root.find_all("a") if unquote(a.get("href")).startswith("/tag/")][:10],
        "description": _txt(desc),
        "review_text": _txt(review),
        "stats": stats[0] if stats else None,
        "image": _img(root.find(cls="product-img-container") or root),
        "url": f"{SITE}/book/{book_id}",
    }


def book_lists(root: Node) -> dict[str, list[dict[str, Any]]]:
    """Carousels on a book page keyed by their heading ('شاید بپسندید' = similar, 'از این نویسنده' = same author)."""
    out: dict[str, list[dict[str, Any]]] = {}
    heading = ""
    for n in root.iter():
        if n.tag == "h2" and "product-list-tab-title" in n.classes():
            heading = n.text()
        elif "swiper" in n.classes() and n.get("id").endswith("-swiper"):
            out[heading or "list"] = cards(n)
    return out


def reviews(root: Node) -> list[dict[str, Any]]:
    out = []
    for r in root.find_all(cls="product-comment-list-item-container"):
        stars = len([i for i in r.find_all("i") if "ri-star-s-fill" in i.classes() and "yellow" in i.classes()])
        likes = [d.text() for d in r.find_all(cls="product-question-answer-like")]
        out.append(
            {
                "author": _txt(r.find(cls="product-comment-list-item-title")),
                "date": _txt(r.find(cls="product-comment-list-item-date")),
                "stars": stars,
                "text": _txt(r.find(cls="product-comment-list-item-text")),
                "likes": num(likes[0]) if likes else 0,
                "dislikes": num(likes[1]) if len(likes) > 1 else 0,
            }
        )
    return out
