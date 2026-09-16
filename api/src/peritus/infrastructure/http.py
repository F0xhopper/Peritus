"""Outbound HTTP: one client per configuration, and the guard on user-supplied URLs.

Two jobs, both of which used to be done — differently — at each of twenty-seven
call sites.

**Connection reuse.** Every fetcher built its own ``httpx.AsyncClient`` per call
and closed it again. A discovery round hits the same handful of hosts hundreds
of times, so each of those requests paid for a fresh TCP connection and TLS
handshake because the thing that would have pooled it had just been thrown away.
:func:`shared_client` returns one long-lived client per distinct configuration.

**The SSRF guard.** Every fetch that follows a URL the user or a discovery result
chose passes ``guarded=True``. The guard exists because the worker
sits inside a private network: on Fly it can reach every other machine in the
organisation over 6PN, and on any cloud it can reach the instance metadata
endpoint at ``169.254.169.254``. A scheme check alone — which is all
``AddUrlRequest`` could do — lets an authenticated user point the fetcher at any
of that, and a public hostname that redirects to ``10.0.0.1`` gets there even
without the user naming it.

So the host is resolved before the request goes out and every resolved address
has to be *globally routable*: no loopback, no RFC1918, no link-local, no
carrier-grade NAT, no unique-local IPv6, no reserved range. The check is
installed as an httpx request hook rather than called once, which is what makes
it cover redirects — httpx fires the hook again for each hop.

One residual: between the guard's ``getaddrinfo`` and the connection's own,
a hostile DNS server can change the answer (a rebinding attack). Closing that
needs the resolved address pinned into the connection, which httpx does not
expose. The window is small and the attack is loud; the plain redirect and
literal-address cases this closes are neither.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from peritus.core.exceptions import PeritusError
from peritus.core.logging import get_logger

logger = get_logger(__name__)

# The two identities this process goes out under. RESEARCH is honest about what
# is calling, which is what the scholarly APIs' etiquette asks for and what gets
# a polite-pool rate limit. BROWSER exists because a plain web page served by a
# CDN is frequently refused outright to anything that does not look like a
# browser — and a page nobody can read is a source nobody can cite.
RESEARCH_UA = "Peritus/2.0 (research corpus builder)"
BROWSER_UA = "Mozilla/5.0 (compatible; Peritus/1.0)"

DEFAULT_HEADERS = {"User-Agent": RESEARCH_UA}


class BlockedURLError(PeritusError):
    """A URL resolved to an address the server is not allowed to fetch."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"Refusing to fetch {url}: {reason}")
        self.url = url
        self.reason = reason


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Globally routable, and not a gateway to somewhere that is not.

    ``is_global`` covers loopback, link-local, RFC1918, CGNAT, unique-local and
    the reserved blocks. The two extra cases are IPv6 forms that wrap a v4
    address: ``::ffff:10.0.0.1`` and ``64:ff9b::a00:1`` are both reported global
    by the v6 rules while resolving to a private v4 address at the other end.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped or ip.sixtofour
        if mapped is not None:
            return mapped.is_global
        # NAT64 (RFC 6052) embeds the v4 address in the low 32 bits of 64:ff9b::/96.
        if ip in ipaddress.ip_network("64:ff9b::/96"):
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF).is_global
    return ip.is_global


# Hostnames that never name anything on the public internet. DNS would settle
# most of these anyway, but a split-horizon resolver need not, and refusing them
# by name gives a far better error than "resolved to 127.0.0.1".
_BLOCKED_SUFFIXES = (
    "localhost",
    ".localhost",
    ".local",
    ".internal",
    ".home.arpa",
)


def blocked_url_reason(url: str) -> str | None:
    """Why ``url`` may not be fetched, judged without touching the network.

    Separate from :func:`assert_public_url` so that a request handler can reject
    the obvious cases synchronously — an IP literal, ``localhost``, a non-http
    scheme — and answer 422 instead of accepting the job and failing it in a
    worker minutes later. Returns ``None`` when nothing is obviously wrong,
    which is not the same as safe: only the resolving check can say that.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return f"scheme {parts.scheme!r} is not http(s)"

    host = parts.hostname
    if not host:
        return "no host"

    lowered = host.lower().rstrip(".")
    if lowered.endswith(_BLOCKED_SUFFIXES):
        return f"{host} is not a public hostname"

    literal = _literal_address(host)
    if literal is not None and not _is_public(literal):
        return f"{literal} is not a public address"
    return None


def _literal_address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The address ``host`` *is*, or None if it is a name to be resolved.

    ``ip_address`` only accepts the canonical dotted-quad, so the legacy IPv4
    spellings get a second pass through ``inet_aton``: ``2130706433``,
    ``0177.0.0.1``, ``0x7f.1`` and ``127.1`` all mean 127.0.0.1 to it, and to
    glibc, and to most HTTP clients. They do not all mean that to every
    resolver — macOS's ``getaddrinfo`` reads ``0177.0.0.1`` as the *public*
    177.0.0.1 — and a guard that resolves while the connection parses is a guard
    that can be walked straight past. Reading them here settles it before either
    one runs.
    """
    bare = host.strip("[]")
    try:
        return ipaddress.ip_address(bare)
    except ValueError:
        pass
    try:
        packed = socket.inet_aton(bare)
    except OSError:
        return None
    return ipaddress.IPv4Address(packed)


async def assert_public_url(url: str) -> None:
    """Raise :class:`BlockedURLError` unless every address ``url`` resolves to
    is globally routable.

    Called for the original request and again for each redirect target. A host
    that resolves to a mix of public and private addresses is refused outright:
    which one httpx would have connected to is not knowable here.
    """
    reason = blocked_url_reason(url)
    if reason is not None:
        raise BlockedURLError(url, reason)

    parts = urlsplit(url)
    # blocked_url_reason has already established that there is a host.
    host = parts.hostname or ""
    if _literal_address(host) is not None:
        return

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise BlockedURLError(url, f"could not resolve {host!r}: {exc}") from exc

    if not infos:
        raise BlockedURLError(url, f"{host!r} resolved to nothing")

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:  # pragma: no cover — getaddrinfo returns literals
            raise BlockedURLError(url, f"unreadable address {address!r}") from None
        if not _is_public(ip):
            raise BlockedURLError(url, f"{host} resolves to {ip}, which is not public")


async def _guard_hook(request: httpx.Request) -> None:
    """httpx request hook: runs for the first request and for every redirect."""
    await assert_public_url(str(request.url))


# ── shared clients ───────────────────────────────────────────────────────────
#
# Every fetcher used to build its own `httpx.AsyncClient` per call — 27 such
# constructions. A discovery round hits the same handful of hosts (OpenAlex,
# arXiv, Europe PMC, Semantic Scholar) hundreds of times, and each of those
# requests was paying for a fresh TCP connection and TLS handshake because the
# client that would have pooled it had just been closed. The per-site timeout,
# header and redirect settings had diverged too.
#
# One client per distinct configuration, held for the life of the process.
# `httpx.AsyncClient` is safe to use from many tasks at once and pools
# connections across them, which is the point.

_clients: dict[tuple[object, ...], httpx.AsyncClient] = {}


def shared_client(
    *,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
    guarded: bool = False,
) -> httpx.AsyncClient:
    """A process-wide client for this configuration.

    **Do not close it and do not use it as a context manager** — it is shared,
    and `async with` would close it for every other caller. `close_shared()`
    releases them all at shutdown.

    Set ``guarded`` for any URL that came from outside the process: an upload, a
    search result, an open-access location a metadata API handed over. For a
    call to a known API endpoint (OpenAlex, Mistral, Europe PMC) leave it off —
    the host is ours to trust and the guard costs a resolution per request.
    """
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    key = (timeout, follow_redirects, guarded, tuple(sorted(merged.items())))

    client = _clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=timeout,
            headers=merged,
            follow_redirects=follow_redirects,
            event_hooks={"request": [_guard_hook]} if guarded else {},
        )
        _clients[key] = client
    return client


def guarded_client(
    *,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
    **kwargs: object,
) -> httpx.AsyncClient:
    """A one-off client that refuses to reach anything non-public.

    Prefer :func:`shared_client` with ``guarded=True``. This exists for the
    cases that need their own transport — a test's `MockTransport`, above all —
    and unlike the shared ones it *is* meant to be closed by its caller.
    """
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    return httpx.AsyncClient(
        timeout=timeout,
        headers=merged,
        follow_redirects=follow_redirects,
        event_hooks={"request": [_guard_hook]},
        **kwargs,  # type: ignore[arg-type]
    )


async def close_shared() -> None:
    """Release every shared client. Called from the API's lifespan and the
    worker's shutdown; idempotent, and safe with none open."""
    clients = list(_clients.values())
    _clients.clear()
    for client in clients:
        if not client.is_closed:
            with contextlib.suppress(Exception):
                await client.aclose()
