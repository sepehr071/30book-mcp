"""A tiny DOM: parse HTML with the stdlib, search it by tag / class, and print it back.

30book is a Blazor Server site. Pages that arrive as plain HTML (book page, home, landing pages) are parsed with
`parse_html`; list pages are built by `blazor.py` out of render batches into the same `Node` objects.
Children are `Node` or `str` (text). Logical Blazor containers (components) are `Node("#c")` and print as their children.
"""

from __future__ import annotations

from collections.abc import Iterator
from html import escape
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
RAW = {"script", "style"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str] | None = None):
        self.tag = tag
        self.attrs: dict[str, str] = attrs if attrs is not None else {}
        self.children: list[Node | str] = []
        self.parent: Node | None = None

    def add(self, child: Node | str, index: int | None = None) -> None:
        if isinstance(child, Node):
            child.parent = self
        if index is None or index >= len(self.children):
            self.children.append(child)
        else:
            self.children.insert(max(index, 0), child)

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name) or default

    def iter(self) -> Iterator[Node]:
        """Every descendant element, document order."""
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.iter()

    def find_all(self, tag: str | None = None, cls: str | None = None) -> list[Node]:
        return [n for n in self.iter() if (tag is None or n.tag == tag) and (cls is None or cls in n.classes())]

    def find(self, tag: str | None = None, cls: str | None = None) -> Node | None:
        for n in self.iter():
            if (tag is None or n.tag == tag) and (cls is None or cls in n.classes()):
                return n
        return None

    def text(self) -> str:
        """Visible text with whitespace collapsed."""
        out: list[str] = []
        self._text(out)
        return " ".join("".join(out).split())

    def _text(self, out: list[str]) -> None:
        if self.tag in RAW:
            return
        for c in self.children:
            if isinstance(c, str):
                out.append(c)
            else:
                if c.tag in ("br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr"):
                    out.append(" ")
                c._text(out)


def to_html(node: Node | str) -> str:
    if isinstance(node, str):
        return escape(node, quote=False)
    inner = "".join(to_html(c) for c in node.children)
    if node.tag.startswith("#"):
        return inner
    attrs = "".join(f' {k}="{escape(v, quote=True)}"' for k, v in node.attrs.items() if not k.startswith("@"))
    if node.tag in VOID:
        return f"<{node.tag}{attrs}>"
    return f"<{node.tag}{attrs}>{inner}</{node.tag}>"


class _Builder(HTMLParser):
    def __init__(self, root: Node):
        super().__init__(convert_charrefs=True)
        self.root = root
        self.stack = [root]

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: (v if v is not None else "") for k, v in attrs})
        self.stack[-1].add(n)
        if tag not in VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        n = Node(tag, {k: (v if v is not None else "") for k, v in attrs})
        self.stack[-1].add(n)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data:
            self.stack[-1].add(data)


def parse_html(html: str, root: Node | None = None) -> Node:
    """Parse an HTML document or fragment into a tree. Comments and doctype are dropped."""
    root = root or Node("#root")
    b = _Builder(root)
    b.feed(html)
    b.close()
    return root
