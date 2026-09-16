"""The SSRF guard on outbound fetches.

The worker runs inside a private network — on Fly it can reach every other
machine in the organisation over 6PN, and on any cloud it can reach the instance
metadata endpoint. Any URL the user or a discovery result supplies is therefore
an attempt to make this process issue a request on the attacker's behalf, and
the only safe answer is "every address this resolves to must be public".

Two halves are tested here: the synchronous reason check that the API schema
uses to answer 422 without a DNS lookup, and the resolving check that the httpx
hook applies to the first request and to every redirect after it.
"""

import asyncio
import ipaddress
import socket

import httpx
import pytest

from peritus.api.schemas.sources import AddUrlRequest
from peritus.infrastructure.http import (
    BROWSER_UA,
    RESEARCH_UA,
    BlockedURLError,
    _is_public,
    assert_public_url,
    blocked_url_reason,
    close_shared,
    guarded_client,
    shared_client,
)

# Every shape of "not the public internet" the guard has to recognise, with the
# reason each one is dangerous.
PRIVATE_URLS = [
    ("http://127.0.0.1/", "loopback"),
    ("http://localhost:8000/health", "loopback by name"),
    ("http://10.0.0.5/", "RFC1918"),
    ("http://172.16.4.4/", "RFC1918"),
    ("http://192.168.1.1/", "RFC1918"),
    ("http://169.254.169.254/latest/meta-data/", "cloud metadata"),
    ("http://100.64.0.1/", "carrier-grade NAT"),
    ("http://[::1]/", "IPv6 loopback"),
    ("http://[fd00::1]/", "IPv6 unique-local — Fly's 6PN lives here"),
    ("http://[fe80::1]/", "IPv6 link-local"),
    ("http://[::ffff:10.0.0.1]/", "v4-mapped v6, private underneath"),
    ("http://0.0.0.0/", "unspecified"),
    ("http://api.internal/", "internal hostname"),
    ("http://db.local/", "mDNS hostname"),
]


@pytest.mark.parametrize(("url", "why"), PRIVATE_URLS)
def test_blocked_url_reason_refuses_private_targets(url: str, why: str) -> None:
    assert blocked_url_reason(url) is not None, why


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/paper.pdf",
        "http://arxiv.org/abs/2401.00001",
        "https://8.8.8.8/",
    ],
)
def test_blocked_url_reason_allows_public_targets(url: str) -> None:
    assert blocked_url_reason(url) is None


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "gopher://example.com/", "ftp://example.com/x", "https:///nohost"],
)
def test_blocked_url_reason_refuses_non_http(url: str) -> None:
    assert blocked_url_reason(url) is not None


@pytest.mark.parametrize(
    "spelling",
    ["http://2130706433/", "http://0177.0.0.1/", "http://0x7f.1/", "http://127.1/"],
)
def test_legacy_loopback_spellings_are_refused(spelling: str):
    """Every one of these is 127.0.0.1 to `inet_aton`, to glibc, and to most
    HTTP clients — but not to every resolver. macOS reads `0177.0.0.1` as the
    public 177.0.0.1, so a guard that only resolved would have waved it through
    and then connected to loopback anyway.
    """
    assert blocked_url_reason(spelling) is not None


@pytest.mark.parametrize(("url", "why"), PRIVATE_URLS)
def test_the_upload_schema_rejects_private_targets(url: str, why: str) -> None:
    """The 422 a user gets, rather than an accepted job that fails in a worker."""
    with pytest.raises(ValueError, match=r"cannot be fetched|must start with"):
        AddUrlRequest(url=url)


async def test_assert_public_url_refuses_a_name_that_resolves_privately(monkeypatch):
    """The case a literal check cannot see: a public-looking hostname whose A
    record points inside. This is how an attacker gets past a scheme check
    without ever writing an address down."""

    async def _resolves_to_private(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", _resolves_to_private)

    with pytest.raises(BlockedURLError) as exc:
        await assert_public_url("https://totally-normal.example/")
    assert "10.1.2.3" in str(exc.value)


async def test_assert_public_url_refuses_a_mixed_answer(monkeypatch):
    """One public address and one private one is still a refusal: which one httpx
    would have connected to is not knowable from here."""
    import asyncio

    async def _mixed(host, port, **kw):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.9", port)),
        ]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", _mixed)

    with pytest.raises(BlockedURLError):
        await assert_public_url("https://totally-normal.example/")


async def test_assert_public_url_accepts_a_public_answer(monkeypatch):
    async def _public(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", _public)

    await assert_public_url("https://example.com/paper")


async def test_a_public_host_cannot_redirect_into_the_private_network(monkeypatch):
    """The reason the guard is a request hook and not a single up-front call.

    httpx runs the hook again for each hop, so the redirect target is checked
    on its own terms — this is the attack a pre-flight check alone misses.
    """
    hops: list[str] = []

    async def _public(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", _public)

    def _handler(request: httpx.Request) -> httpx.Response:
        hops.append(str(request.url))
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})
        return httpx.Response(200, text="metadata")

    transport = httpx.MockTransport(_handler)
    async with guarded_client(transport=transport) as client:
        with pytest.raises(BlockedURLError) as exc:
            await client.get("https://example.com/start")

    # The first hop went out; the redirect target never did.
    assert hops == ["https://example.com/start"]
    assert "169.254.169.254" in str(exc.value)


def test_nat64_wrapped_private_addresses_are_not_public():
    """64:ff9b::a00:1 is 10.0.0.1 behind a NAT64 gateway, and IPv6's own rules
    report it global."""
    assert not _is_public(ipaddress.ip_address("64:ff9b::a00:1"))
    assert _is_public(ipaddress.ip_address("64:ff9b::5db8:d822"))


# ── the shared client registry ──


@pytest.fixture(autouse=True)
async def _no_leaked_clients():
    """Every test here starts and ends with an empty registry.

    The clients are process-wide by design, so a test that creates one would
    otherwise hand it to the next test — and to the rest of the suite.
    """
    await close_shared()
    yield
    await close_shared()


def test_the_same_configuration_returns_the_same_client():
    """The whole point: a discovery round hits the same host hundreds of times,
    and a client per call threw away the connection pool that would have made
    that cheap."""
    a = shared_client(timeout=30, headers={"User-Agent": RESEARCH_UA})
    b = shared_client(timeout=30, headers={"User-Agent": RESEARCH_UA})
    assert a is b


def test_different_configurations_get_different_clients():
    assert shared_client(timeout=30) is not shared_client(timeout=10)
    assert shared_client(headers={"X": "1"}) is not shared_client(headers={"X": "2"})
    assert shared_client(follow_redirects=True) is not shared_client(follow_redirects=False)
    # The guard is part of the identity: a client that checks addresses must
    # never be handed to a caller that asked for one that does not, or vice versa.
    assert shared_client(guarded=True) is not shared_client(guarded=False)


def test_header_order_does_not_split_the_cache():
    a = shared_client(headers={"A": "1", "B": "2"})
    b = shared_client(headers={"B": "2", "A": "1"})
    assert a is b


def test_a_shared_client_carries_the_default_user_agent():
    client = shared_client()
    assert client.headers["user-agent"] == RESEARCH_UA


def test_an_explicit_header_overrides_the_default():
    client = shared_client(headers={"User-Agent": BROWSER_UA})
    assert client.headers["user-agent"] == BROWSER_UA


async def test_a_closed_client_is_replaced_rather_than_handed_back():
    """`close_shared` runs at shutdown, but a client can also be closed by a
    transport failure. Returning a closed one would fail every later request."""
    first = shared_client(timeout=5)
    await first.aclose()
    second = shared_client(timeout=5)
    assert second is not first
    assert not second.is_closed


async def test_close_shared_is_idempotent():
    shared_client(timeout=5)
    await close_shared()
    await close_shared()


async def test_only_a_guarded_client_checks_addresses(monkeypatch):
    """Two clients, one guard. An unguarded client talks to known API hosts and
    must not pay a resolution per request."""
    seen: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200)

    unguarded = shared_client(guarded=False)
    monkeypatch.setattr(unguarded, "_transport", httpx.MockTransport(_handler))
    await unguarded.get("http://127.0.0.1/would-be-blocked-if-guarded")
    assert seen == ["http://127.0.0.1/would-be-blocked-if-guarded"]

    async with guarded_client(transport=httpx.MockTransport(_handler)) as guarded:
        with pytest.raises(BlockedURLError):
            await guarded.get("http://127.0.0.1/blocked")
    assert len(seen) == 1
