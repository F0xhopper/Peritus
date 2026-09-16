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
    BlockedURLError,
    _is_public,
    assert_public_url,
    blocked_url_reason,
    guarded_client,
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
