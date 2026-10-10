import json
import struct

import httpx
import pytest

from sibook_mcp.blazor import (
    HANDSHAKE,
    Circuit,
    CircuitError,
    Dom,
    frame,
    invocation,
    mp_decode,
    mp_encode,
    page_markers,
    unframe,
)
from sibook_mcp.dom import to_html

pytestmark = pytest.mark.anyio

# edit types / frame types, as in blazor.web.js
PREPEND, REMOVE, SET_ATTR, UPDATE_TEXT, STEP_IN, STEP_OUT = 1, 2, 3, 5, 6, 7
EL, TEXT, ATTR, COMP, REGION, MARKUP = 1, 2, 3, 4, 5, 8


def batch(updates, frames, disposed=()):
    """Write a render batch in the server's binary layout. frames: ('el', sublen, name) | ('text', s) |
    ('attr', name, value|None, handler) | ('comp', sublen, id) | ('region', sublen) | ('markup', s)."""
    strings: list[str] = []

    def sidx(s):
        if s is None:
            return -1
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    buf = bytearray()
    offs = []
    for cid, edits in updates:
        offs.append(len(buf))
        buf += struct.pack("<ii", cid, len(edits))
        for e in edits:
            t, sib, tree, name = (list(e) + [0, 0])[:4]
            buf += struct.pack("<iiii", t, sib, tree, sidx(name) if isinstance(name, str) else -1)
    upd = len(buf)
    buf += struct.pack("<i", len(offs)) + b"".join(struct.pack("<i", o) for o in offs)
    fr = len(buf)
    buf += struct.pack("<i", len(frames))
    for f in frames:
        kind = f[0]
        if kind == "el":
            buf += struct.pack("<iiii", EL, f[1], sidx(f[2]), 0) + b"\0" * 4
        elif kind == "text":
            buf += struct.pack("<ii", TEXT, sidx(f[1])) + b"\0" * 12
        elif kind == "attr":
            buf += struct.pack("<iiiQ", ATTR, sidx(f[1]), sidx(f[2]), f[3] if len(f) > 3 else 0)
        elif kind == "comp":
            buf += struct.pack("<iiii", COMP, f[1], f[2], 0) + b"\0" * 4
        elif kind == "region":
            buf += struct.pack("<ii", REGION, f[1]) + b"\0" * 12
        elif kind == "markup":
            buf += struct.pack("<ii", MARKUP, sidx(f[1])) + b"\0" * 12
    dsp = len(buf)
    buf += struct.pack("<i", len(disposed)) + b"".join(struct.pack("<i", d) for d in disposed)
    ev = len(buf)
    buf += struct.pack("<i", 0)
    data = bytearray()
    table_pos = []
    base = len(buf) + 0
    chunks = []
    for s in strings:
        raw = s.encode()
        n, head = len(raw), bytearray()
        while True:
            part = n & 0x7F
            n >>= 7
            head.append(part | (0x80 if n else 0))
            if not n:
                break
        chunks.append(bytes(head) + raw)
    pos = base
    for c in chunks:
        table_pos.append(pos)
        pos += len(c)
        data += c
    buf += data
    st = len(buf)
    buf += b"".join(struct.pack("<i", p) for p in table_pos)
    buf += struct.pack("<iiiii", upd, fr, dsp, ev, st)
    return bytes(buf)


# ---------------------------------------------------------------- codecs


def test_messagepack_roundtrip():
    for v in [
        None,
        True,
        False,
        0,
        127,
        128,
        255,
        65535,
        70000,
        "",
        "a" * 40,
        "ب" * 200,
        "x" * 70000,
        [1, ["a", None]],
        [],
    ]:
        assert mp_decode(mp_encode(v))[0] == v
    assert mp_decode(b"\xc5\x00\x03abc")[0] == b"abc"  # bin16 (render batches)


def test_signalr_framing_roundtrip():
    msgs = [[1, {}, None, "JS.AttachComponent", [0, "1"]], [3, {}, "0", 3, "circuit-id"]]
    data = b"".join(frame(m) for m in msgs) + invocation("OnRenderCompleted", [7, None])
    assert unframe(data) == [*msgs, [1, {}, None, "OnRenderCompleted", [7, None]]]
    assert len(frame([1, {}, None, "x" * 200, []])) > 128  # two-byte length prefix


def test_page_markers_keeps_interactive_components_only():
    html = (
        '<!--Blazor:{"type":"server","prerenderId":"a","key":{"locationHash":"h:1","formattedComponentKey":""},'
        '"sequence":0,"descriptor":"D0"}--><p>x</p><!--Blazor:{"prerenderId":"a"}-->'
        '<!--Blazor:{"type":"server","key":{"locationHash":"h:2","formattedComponentKey":""},"sequence":1,"descriptor":"D1"}-->'
        "<!--Blazor-Server-Component-State:STATE=-->"
    )
    markers, state = page_markers(html)
    assert [m["descriptor"] for m in markers] == ["D0", "D1"] and [m["uniqueId"] for m in markers] == [0, 1]
    assert state == "STATE="


# ---------------------------------------------------------------- render batches


def test_batch_builds_and_updates_a_tree():
    dom = Dom()
    dom.attach_root(0, 1)
    frames = [
        ("el", 8, "div"),  # 0
        ("attr", "class", "a"),  # 1
        ("attr", "onclick", None, 99),  # 2 event handler: kept aside, not printed
        ("el", 2, "span"),  # 3
        ("text", "hi"),  # 4
        ("comp", 1, 5),  # 5
        ("markup", "<b>m</b> t"),  # 6
        ("text", "end"),  # 7
    ]
    dom.apply(batch([(0, [(PREPEND, 0, 0)])], frames))
    assert to_html(dom.roots[1]) == '<div class="a"><span>hi</span><b>m</b> tend</div>'
    div = dom.roots[1].children[0]
    assert len(div.children) == 4 and div.attrs["@click"] == "99"  # span, component, markup box, text
    dom.apply(batch([(5, [(PREPEND, 0, 0)])], [("text", "child")]))
    assert to_html(dom.roots[1]) == '<div class="a"><span>hi</span>child<b>m</b> tend</div>'


def test_batch_edits_step_in_update_text_set_attr_remove_permute():
    dom = Dom()
    dom.attach_root(0, 1)
    f = [("region", 7)] + [
        ("el", 2, "li"),
        ("text", "one"),
        ("el", 2, "li"),
        ("text", "two"),
        ("el", 2, "li"),
        ("text", "three"),
    ]
    dom.apply(batch([(0, [(PREPEND, 0, 0)])], f))
    assert to_html(dom.roots[1]) == "<li>one</li><li>two</li><li>three</li>"
    upd_frames = [("text", "TWO"), ("attr", "id", "x")]
    edits = [(STEP_IN, 1), (UPDATE_TEXT, 0, 0), (STEP_OUT, 0), (SET_ATTR, 2, 1), (REMOVE, 0)]
    dom.apply(batch([(0, edits)], upd_frames))
    assert to_html(dom.roots[1]) == '<li>TWO</li><li id="x">three</li>'


def test_event_handlers_are_kept_but_not_printed():
    dom = Dom()
    dom.attach_root(0, 1)
    f = [("el", 3, "button"), ("attr", "onclick", None, 1105), ("text", "go")]
    dom.apply(batch([(0, [(PREPEND, 0, 0)])], f))
    btn = dom.roots[1].children[0]
    assert btn.attrs == {"@click": "1105"} and to_html(btn) == "<button>go</button>"


def test_unknown_component_is_an_error():
    with pytest.raises(ValueError, match="unknown component"):
        Dom().apply(batch([(3, [(PREPEND, 0, 0)])], [("text", "x")]))


# ---------------------------------------------------------------- a whole circuit against a scripted server


class FakeServer:
    """Speaks just enough SignalR long polling: handshake, StartCircuit -> completion + render batches."""

    def __init__(self, page_batches):
        self.out: list[bytes] = [HANDSHAKE.replace(b'{"protocol":"blazorpack","version":1}', b"{}")]
        self.sent: list[list] = []
        self.batches = page_batches
        self.deleted = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/_blazor/negotiate":
            return httpx.Response(200, json={"connectionToken": "tok", "connectionId": "id", "availableTransports": []})
        if request.method == "GET":
            if self.out:
                return httpx.Response(200, content=self.out.pop(0))
            return httpx.Response(204)
        if request.method == "DELETE":
            self.deleted = True
            return httpx.Response(202)
        body = request.content
        if body.endswith(b"\x1e"):  # handshake
            return httpx.Response(200)
        for msg in unframe(body):
            self.sent.append(msg)
            if msg[3] == "StartCircuit":
                self.out.append(frame([3, {}, "0", 3, "circuit-1"]))
                self.out.append(invocation("JS.AttachComponent", [0, "1"]))
                for i, b in enumerate(self.batches, 1):
                    self.out.append(invocation("JS.RenderBatch", [i, b]))
        return httpx.Response(200)


async def test_circuit_end_to_end():
    first = batch([(0, [(PREPEND, 0, 0)])], [("el", 2, "p"), ("text", "loading")])
    second = batch([(0, [(STEP_IN, 0), (UPDATE_TEXT, 0, 0)])], [("text", "done")])
    server = FakeServer([first, second])
    html = (
        '<!--Blazor:{"type":"server","key":{},"sequence":0,"descriptor":"D"}--><!--Blazor-Server-Component-State:S-->'
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(server.handler)) as client:
        async with Circuit(client, "https://x.test", "https://x.test/search/a?pg=1", html) as c:
            trees = await c.wait(lambda rs: "done" in to_html(rs[0]), timeout=5, settle=0.1)
    assert to_html(trees[0]) == "<p>done</p>"
    start = next(m for m in server.sent if m[3] == "StartCircuit")
    assert start[4][:3] == ["https://x.test/", "https://x.test/search/a?pg=1", "[]"] and start[4][3] == "S"
    update = next(m for m in server.sent if m[3] == "UpdateRootComponents")
    ops = json.loads(update[4][0])["operations"]
    assert ops[0]["type"] == "add" and ops[0]["ssrComponentId"] == 1 and ops[0]["marker"]["uniqueId"] == 0
    acks = [m[4][0] for m in server.sent if m[3] == "OnRenderCompleted"]
    assert acks == [1, 2] and server.deleted


async def test_circuit_times_out_with_a_clear_error():
    server = FakeServer([])
    async with httpx.AsyncClient(transport=httpx.MockTransport(server.handler)) as client:
        async with Circuit(client, "https://x.test", "https://x.test/", "") as c:
            with pytest.raises(CircuitError, match="did not render"):
                await c.wait(lambda rs: True, timeout=0.5)


async def test_circuit_surfaces_a_negotiate_failure():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
        with pytest.raises(CircuitError, match="HTTP 503"):
            async with Circuit(client, "https://x.test", "https://x.test/", ""):
                pass
