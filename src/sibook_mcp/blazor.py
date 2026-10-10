"""A read-only Blazor Server client: render a 30book list page the way the browser does, without a browser.

Search, category, publisher, author and tag pages are built after load by a Blazor Server circuit; the plain HTML
has no book cards. The browser opens a SignalR connection (`/_blazor`, MessagePack "blazorpack") and receives binary
render batches that it applies to the DOM. This module does the same over SignalR *long polling* (the server offers
WebSockets, Server-Sent Events and LongPolling; httpx can only do the last) and applies the batches to a `dom.Node` tree.

Flow: GET the page (HTML with component markers and a state blob) -> POST negotiate -> poll loop + POST sends ->
handshake -> StartCircuit -> UpdateRootComponents(markers) -> receive JS.AttachComponent / JS.RenderBatch, ack each
batch with OnRenderCompleted -> stop when the caller's `ready` test passes -> DELETE the connection.
Paging, sorting and filters live in the URL (`?pg=`, `sort=`, ...), so lists need no click events. Only the name
boxes on the publisher / author index pages are driven by events (`Circuit.fire`).
"""

from __future__ import annotations

import asyncio
import json
import re
import struct
import time
from collections.abc import Callable
from typing import Any

import httpx

from .dom import Node, parse_html

# ---------------------------------------------------------------- MessagePack (the subset SignalR uses)


def mp_encode(v: Any) -> bytes:
    if v is None:
        return b"\xc0"
    if v is True:
        return b"\xc3"
    if v is False:
        return b"\xc2"
    if isinstance(v, int):
        if 0 <= v < 128:
            return bytes([v])
        if 0 <= v < 256:
            return b"\xcc" + bytes([v])
        if 0 <= v < 65536:
            return b"\xcd" + struct.pack(">H", v)
        if 0 <= v < 2**32:
            return b"\xce" + struct.pack(">I", v)
        raise ValueError(v)
    if isinstance(v, bytes):
        return b"\xc6" + struct.pack(">I", len(v)) + v
    if isinstance(v, str):
        b = v.encode()
        n = len(b)
        if n < 32:
            return bytes([0xA0 | n]) + b
        if n < 256:
            return b"\xd9" + bytes([n]) + b
        if n < 65536:
            return b"\xda" + struct.pack(">H", n) + b
        return b"\xdb" + struct.pack(">I", n) + b
    if isinstance(v, list | tuple):
        n = len(v)
        head = bytes([0x90 | n]) if n < 16 else b"\xdc" + struct.pack(">H", n)
        return head + b"".join(mp_encode(x) for x in v)
    if isinstance(v, dict):
        if v:
            raise ValueError("only empty maps are needed")
        return b"\x80"
    raise TypeError(type(v))


_FIXED = {
    0xCC: ">B", 0xCD: ">H", 0xCE: ">I", 0xCF: ">Q",
    0xD0: ">b", 0xD1: ">h", 0xD2: ">i", 0xD3: ">q", 0xCA: ">f", 0xCB: ">d",
}  # fmt: skip
_SIZED = {0xC4: ">B", 0xD9: ">B", 0xC5: ">H", 0xDA: ">H", 0xC6: ">I", 0xDB: ">I"}


def mp_decode(b: bytes, i: int = 0) -> tuple[Any, int]:
    t = b[i]
    i += 1
    if t < 0x80:
        return t, i
    if t >= 0xE0:
        return t - 256, i
    if 0x80 <= t <= 0x8F:
        return _mp_map(b, i, t & 0x0F)
    if 0x90 <= t <= 0x9F:
        return _mp_array(b, i, t & 0x0F)
    if 0xA0 <= t <= 0xBF:
        n = t & 0x1F
        return b[i : i + n].decode(), i + n
    if t in _FIXED:
        (v,) = struct.unpack_from(_FIXED[t], b, i)
        return v, i + struct.calcsize(_FIXED[t])
    if t == 0xC0:
        return None, i
    if t in (0xC2, 0xC3):
        return t == 0xC3, i
    if t in _SIZED:
        (n,) = struct.unpack_from(_SIZED[t], b, i)
        i += struct.calcsize(_SIZED[t])
        raw = b[i : i + n]
        return (raw if t in (0xC4, 0xC5, 0xC6) else raw.decode()), i + n
    if t in (0xDC, 0xDD):
        fmt = ">H" if t == 0xDC else ">I"
        (n,) = struct.unpack_from(fmt, b, i)
        return _mp_array(b, i + struct.calcsize(fmt), n)
    if t in (0xDE, 0xDF):
        fmt = ">H" if t == 0xDE else ">I"
        (n,) = struct.unpack_from(fmt, b, i)
        return _mp_map(b, i + struct.calcsize(fmt), n)
    raise ValueError(f"unsupported MessagePack type 0x{t:02x}")


def _mp_array(b: bytes, i: int, n: int) -> tuple[list[Any], int]:
    out = []
    for _ in range(n):
        v, i = mp_decode(b, i)
        out.append(v)
    return out, i


def _mp_map(b: bytes, i: int, n: int) -> tuple[dict[Any, Any], int]:
    out = {}
    for _ in range(n):
        k, i = mp_decode(b, i)
        v, i = mp_decode(b, i)
        out[k] = v
    return out, i


# ---------------------------------------------------------------- SignalR framing


def frame(msg: list[Any]) -> bytes:
    """One hub message: 7-bit varint length + MessagePack array."""
    body = mp_encode(msg)
    n, head = len(body), bytearray()
    while True:
        part = n & 0x7F
        n >>= 7
        head.append(part | (0x80 if n else 0))
        if not n:
            return bytes(head) + body


def unframe(data: bytes) -> list[Any]:
    out, i = [], 0
    while i < len(data):
        n, shift = 0, 0
        while True:
            c = data[i]
            i += 1
            n |= (c & 0x7F) << shift
            shift += 7
            if c < 0x80:
                break
        out.append(mp_decode(data[i : i + n])[0])
        i += n
    return out


def invocation(target: str, args: list[Any], invocation_id: str | None = None) -> bytes:
    return frame([1, {}, invocation_id, target, args])


HANDSHAKE = b'{"protocol":"blazorpack","version":1}\x1e'

# ---------------------------------------------------------------- render batches

_PREPEND, _REMOVE, _SET_ATTR, _REMOVE_ATTR, _UPDATE_TEXT, _STEP_IN, _STEP_OUT, _UPDATE_MARKUP, _PERM, _PERM_END = range(
    1, 11
)
_ELEMENT, _TEXT, _ATTRIBUTE, _COMPONENT, _REGION, _REF_CAPTURE, _MARKUP, _NAMED_EVENT = 1, 2, 3, 4, 5, 6, 8, 10


class Batch:
    """Binary render batch from the server (layout read off blazor.web.js).

    Trailing 20 bytes: offsets of updated components, reference frames, disposed component ids, disposed event
    handler ids, and the string table. Arrays are `int32 count` + items; a diff is `componentId` + edits
    (16 bytes each: type, siblingIndex, newTreeIndex/moveTo, removedAttributeName string index); a frame is 20 bytes.
    """

    def __init__(self, data: bytes):
        self.d = data
        n = len(data)
        self.upd, self.frames, self.disp, _, self.strings = (self.i32(n - 20 + 4 * k) for k in range(5))

    def i32(self, at: int) -> int:
        return struct.unpack_from("<i", self.d, at)[0]

    def string(self, idx: int) -> str | None:
        if idx == -1:
            return None
        off = self.i32(self.strings + 4 * idx)
        n, shift = 0, 0
        while True:
            c = self.d[off]
            off += 1
            n |= (c & 0x7F) << shift
            shift += 7
            if c < 0x80:
                break
        return self.d[off : off + n].decode("utf-8")

    def updated(self):
        """Yield (component_id, [(type, sibling, tree_index, moveto_or_name_idx)])."""
        for k in range(self.i32(self.upd)):
            at = self.i32(self.upd + 4 + 4 * k)
            cid, cnt = self.i32(at), self.i32(at + 4)
            edits = []
            for j in range(cnt):
                e = at + 8 + 16 * j
                edits.append((self.i32(e), self.i32(e + 4), self.i32(e + 8), self.i32(e + 12)))
            yield cid, edits

    def disposed(self) -> list[int]:
        return [self.i32(self.disp + 4 + 4 * k) for k in range(self.i32(self.disp))]

    def frame_at(self, i: int) -> int:
        return self.frames + 4 + 20 * i

    def ftype(self, i: int) -> int:
        return self.i32(self.frame_at(i))

    def sublen(self, i: int) -> int:
        return self.i32(self.frame_at(i) + 4)

    def fstr(self, i: int, offset: int) -> str | None:
        return self.string(self.i32(self.frame_at(i) + offset))


class Dom:
    """The browser-side state: component id -> logical container node. Applies batches like blazor.web.js."""

    def __init__(self) -> None:
        self.components: dict[int, Node] = {}
        self.roots: dict[int, Node] = {}  # ssrComponentId -> container

    def attach_root(self, component_id: int, ssr_id: int) -> None:
        node = Node("#c")
        self.components[component_id] = node
        self.roots[ssr_id] = node

    def apply(self, data: bytes) -> None:
        b = Batch(data)
        for cid, edits in b.updated():
            if cid not in self.components:
                raise ValueError(f"render batch updates unknown component {cid}")
            self._edits(b, self.components[cid], edits)
        for cid in b.disposed():
            self.components.pop(cid, None)

    def _edits(self, b: Batch, parent: Node, edits: list[tuple[int, int, int, int]]) -> None:
        perm: list[tuple[int, int]] = []
        for typ, sib, tree, extra in edits:
            if typ == _PREPEND:
                self._insert(b, parent, sib, tree)
            elif typ == _REMOVE:
                del parent.children[sib]
            elif typ == _SET_ATTR:
                el = parent.children[sib]
                if isinstance(el, Node):
                    self._attr(b, el, tree)
            elif typ == _REMOVE_ATTR:
                el = parent.children[sib]
                if isinstance(el, Node):
                    el.attrs.pop(b.string(extra) or "", None)
            elif typ == _UPDATE_TEXT:
                parent.children[sib] = b.fstr(tree, 4) or ""
            elif typ == _UPDATE_MARKUP:
                del parent.children[sib]
                self._markup(b, parent, sib, tree)
            elif typ == _STEP_IN:
                node = parent.children[sib]
                if not isinstance(node, Node):
                    raise ValueError("render batch steps into a text node")
                parent = node
            elif typ == _STEP_OUT:
                if parent.parent is None:
                    raise ValueError("render batch steps out of the root")
                parent = parent.parent
            elif typ == _PERM:
                perm.append((sib, extra))
            elif typ == _PERM_END:
                moved = [(parent.children[f], t) for f, t in perm]
                for f, _ in sorted(perm, reverse=True):
                    del parent.children[f]
                for child, t in sorted(moved, key=lambda m: m[1]):
                    parent.add(child, t)
                perm = []
            else:
                raise ValueError(f"unknown edit type {typ}")

    def _insert(self, b: Batch, parent: Node, idx: int, fi: int) -> int:
        t = b.ftype(fi)
        if t == _ELEMENT:
            el = Node(b.fstr(fi, 8) or "div")
            end = fi + b.sublen(fi)
            j = fi + 1
            while j < end and b.ftype(j) == _ATTRIBUTE:
                self._attr(b, el, j)
                j += 1
            parent.add(el, idx)
            self._range(b, el, 0, j, end)
            return 1
        if t == _TEXT:
            parent.add(b.fstr(fi, 4) or "", idx)
            return 1
        if t == _COMPONENT:
            node = Node("#c")
            self.components[b.i32(b.frame_at(fi) + 8)] = node
            parent.add(node, idx)
            return 1
        if t == _REGION:
            return self._range(b, parent, idx, fi + 1, fi + b.sublen(fi))
        if t == _MARKUP:
            return self._markup(b, parent, idx, fi)
        if t in (_REF_CAPTURE, _NAMED_EVENT):
            return 0
        raise ValueError(f"unknown frame type {t}")

    def _range(self, b: Batch, parent: Node, idx: int, start: int, end: int) -> int:
        first, j = idx, start
        while j < end:
            idx += self._insert(b, parent, idx, j)
            j += 1 + (b.sublen(j) - 1 if b.ftype(j) in (_ELEMENT, _COMPONENT, _REGION) else 0)
        return idx - first

    def _markup(self, b: Batch, parent: Node, idx: int, fi: int) -> int:
        """A markup frame is ONE logical child (the browser wraps its nodes in a container), whatever it contains."""
        box = Node("#c")
        parse_html(b.fstr(fi, 4) or "", box)
        parent.add(box, idx)
        return 1

    def _attr(self, b: Batch, el: Node, fi: int) -> None:
        name = b.fstr(fi, 4) or ""
        handler = struct.unpack_from("<Q", b.d, b.frame_at(fi) + 12)[0]
        if handler:  # event handler: kept as "@click" -> id so a caller can fire it; never printed
            el.attrs["@" + name.removeprefix("on")] = str(handler)
            return
        value = b.fstr(fi, 8)
        if value is None:
            el.attrs.pop(name, None)
        else:
            el.attrs[name] = value


# ---------------------------------------------------------------- page markers


def page_markers(html: str) -> tuple[list[dict[str, Any]], str]:
    """Interactive component markers (`<!--Blazor:{...}-->` with type=server) and the persisted-state blob."""
    markers = []
    for m in re.finditer(r"<!--Blazor:(\{.*?\})-->", html):
        d = json.loads(m.group(1))
        if d.get("type") == "server":
            d["uniqueId"] = len(markers)
            markers.append(d)
    s = re.search(r"<!--Blazor-Server-Component-State:(.*?)-->", html)
    return markers, s.group(1) if s else ""


# ---------------------------------------------------------------- the circuit


class CircuitError(Exception):
    """The Blazor connection failed; the message says where."""


def _contains(root: Node, target: Node) -> bool:
    n: Node | None = target
    while n is not None:
        if n is root:
            return True
        n = n.parent
    return False


class Circuit:
    """One Blazor Server circuit for one page URL. Use as `async with Circuit(...) as c: await c.wait(ready)`."""

    def __init__(self, client: httpx.AsyncClient, base: str, page_url: str, html: str):
        self.c, self.base, self.url = client, base, page_url
        self.markers, self.state = page_markers(html)
        self.dom = Dom()
        self.token = ""
        self.interop_id = 1  # DotNetObjectReference of the renderer, announced by the server
        self.batches = 0
        self.last_batch = 0.0
        self.error: Exception | None = None
        self._inbox: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._waiters: dict[str, asyncio.Future[Any]] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._calls = 0

    # -- transport
    async def _poll(self) -> None:
        try:
            while True:
                r = await self.c.get(f"{self.base}/_blazor", params={"id": self.token}, timeout=100)
                if r.status_code == 200 and r.content:
                    await self._inbox.put(r.content)
                elif r.status_code == 204:
                    await asyncio.sleep(0.01)  # a real server holds the poll open; this only matters for fakes
                elif r.status_code != 200:
                    break
        except httpx.HTTPError as e:
            self.error = self.error or CircuitError(f"30book.com connection failed ({type(e).__name__}).")
        finally:
            await self._inbox.put(None)

    async def _send(self, data: bytes) -> None:
        r = await self.c.post(f"{self.base}/_blazor", params={"id": self.token}, content=data, timeout=30)
        if r.status_code >= 400:
            raise CircuitError(f"30book.com refused a circuit message (HTTP {r.status_code}).")

    async def _pump(self) -> None:
        try:
            handshake = True
            while True:
                data = await self._inbox.get()
                if data is None:
                    raise CircuitError("30book.com closed the connection before the page was rendered.")
                if handshake:
                    end = data.index(b"\x1e")
                    if json.loads(data[:end] or b"{}").get("error"):
                        raise CircuitError("30book.com rejected the protocol handshake.")
                    data, handshake = data[end + 1 :], False
                    self._tasks.append(asyncio.create_task(self._guard(self._start())))
                for msg in unframe(data):
                    await self._handle(msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.error = self.error or e
            for fut in self._waiters.values():
                if not fut.done():
                    fut.set_exception(self.error)

    async def _guard(self, coro: Any) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.error = self.error or e

    async def _handle(self, msg: list[Any]) -> None:
        kind = msg[0]
        if kind == 3:  # completion: [3, {}, id, resultKind, result?]
            fut = self._waiters.pop(msg[2], None)
            if fut and not fut.done():
                if msg[3] == 1:
                    fut.set_exception(CircuitError(f"30book.com circuit error: {msg[4]}"))
                else:
                    fut.set_result(msg[4] if len(msg) > 4 else None)
        elif kind == 7:
            self.error = self.error or CircuitError("30book.com closed the circuit.")
        elif kind == 1:
            target, args = msg[3], msg[4]
            if target == "JS.AttachComponent":
                self.dom.attach_root(args[0], int(args[1]))
            elif target == "JS.RenderBatch":
                self.dom.apply(args[1])
                self.batches += 1
                self.last_batch = time.monotonic()
                await self._send(invocation("OnRenderCompleted", [args[0], None]))
            elif target == "JS.BeginInvokeJS":
                if str(args[1]).endswith("attachWebRendererInterop"):
                    ref = re.search(r'"__dotNetObject":(\d+)', args[2] or "")
                    self.interop_id = int(ref.group(1)) if ref else 1
                if args[0]:  # JS interop the server awaits: answer "null"
                    await self._send(invocation("EndInvokeJSFromDotNet", [args[0], True, f"[{args[0]},true,null]"]))

    # -- session
    async def __aenter__(self) -> Circuit:
        try:
            r = await self.c.post(
                f"{self.base}/_blazor/negotiate", params={"negotiateVersion": 1}, content=b"", timeout=30
            )
        except httpx.HTTPError as e:
            raise CircuitError(f"Could not reach 30book.com ({type(e).__name__}).") from e
        if r.status_code != 200:
            raise CircuitError(f"30book.com refused the connection (HTTP {r.status_code}).")
        body = r.json()
        self.token = body.get("connectionToken") or body["connectionId"]
        self._tasks = [asyncio.create_task(self._poll()), asyncio.create_task(self._pump())]
        await self._send(HANDSHAKE)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        for t in self._tasks:
            t.cancel()
        try:
            await self.c.delete(f"{self.base}/_blazor", params={"id": self.token}, timeout=10)
        except httpx.HTTPError:
            pass

    async def _invoke(self, target: str, args: list[Any], inv_id: str) -> Any:
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._waiters[inv_id] = fut
        await self._send(invocation(target, args, inv_id))
        return await fut

    async def _start(self) -> None:
        circuit_id = await self._invoke("StartCircuit", [self.base + "/", self.url, "[]", self.state], "0")
        if not circuit_id:
            raise CircuitError("30book.com did not start a circuit.")
        ops = [{"type": "add", "ssrComponentId": i + 1, "marker": m} for i, m in enumerate(self.markers)]
        payload = json.dumps({"batchId": 1, "operations": ops}, separators=(",", ":"), ensure_ascii=False)
        await self._send(invocation("UpdateRootComponents", [payload, self.state]))

    @property
    def roots(self) -> list[Node]:
        return [self.dom.roots[k] for k in sorted(self.dom.roots)]

    async def wait(self, ready: Callable[[list[Node]], bool], timeout: float = 25, settle: float = 0.5) -> list[Node]:
        """Block until `ready(roots)` holds and no render batch arrived for `settle` seconds."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.error:
                raise self.error
            if self.batches >= 2 and ready(self.roots) and time.monotonic() - self.last_batch >= settle:
                return self.roots
            await asyncio.sleep(0.1)
        raise CircuitError("30book.com did not render the page in time. Try again in a moment.")

    async def fire(self, node: Node, event: str, value: Any = None) -> None:
        """Fire a Blazor event handler on a rendered element (typing: event='input', value='text')."""
        handler = node.attrs.get("@" + event)
        if not handler:
            raise CircuitError(f"element has no {event} handler")
        info: dict[str, Any] = {"eventHandlerId": int(handler), "eventName": event, "eventFieldInfo": None}
        args: dict[str, Any] = {"type": event}
        if value is not None:
            comp = next((cid for cid, n in self.dom.components.items() if _contains(n, node)), 0)
            info["eventFieldInfo"] = {"componentId": comp, "fieldValue": value}
            args = {"value": value}
        self._calls += 1
        payload = json.dumps([info, args], separators=(",", ":"), ensure_ascii=False)
        before = self.batches
        call = [str(self._calls), None, "DispatchEventAsync", self.interop_id, payload]
        await self._send(invocation("BeginInvokeDotNetFromJS", call))
        end = time.monotonic() + 10
        while self.batches == before and time.monotonic() < end:  # the handler re-renders at least once
            await asyncio.sleep(0.05)
