"""SSRF guard for operator-supplied outbound URLs (Python side).

Mirrors the Rust muscle's ``common::validate_outbound_url`` / ``is_blocked_ip``
(backend-rust/src/handlers/common.rs) so a URL rejected there is rejected here
too. Used by the outbound webhook subscription CRUD (validate at CREATE) and by
the fan-out worker (validate again at SEND) — a hostname can re-resolve to a
private IP between create and delivery (DNS rebinding), so both gates matter.

We block: loopback, RFC-1918 private, link-local (incl. 169.254.169.254 IMDS),
carrier-grade NAT (100.64.0.0/10), broadcast/unspecified, IPv6 ULA/link-local,
and any hostname that resolves to one of those. Only http/https schemes pass.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """Raised when a URL is not a safe public http(s) destination."""


# Hostnames that are blocked by name regardless of DNS resolution — a defense-in-
# depth layer so a resolver that hands back a public address for "localhost" (or
# the cloud-metadata alias) can't defeat the IP checks.
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata",
    }
)


def _hostname_is_blocked(host: str) -> bool:
    h = host.lower().rstrip(".")
    if h in _BLOCKED_HOSTNAMES:
        return True
    # *.localhost is reserved (RFC 6761) and always resolves to loopback.
    return h.endswith(".localhost")


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if this IP is loopback/private/link-local/reserved (SSRF risk)."""
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_reserved:
        return True
    if ip.is_private:
        # ipaddress marks RFC-1918, ULA fc00::/7, etc. as private.
        return True
    if ip.is_multicast:
        return True
    if isinstance(ip, ipaddress.IPv4Address):
        octets = ip.packed
        # 100.64.0.0/10 carrier-grade NAT (shared address space).
        if octets[0] == 100 and 64 <= octets[1] <= 127:
            return True
        # 0.0.0.0/8 "this network".
        if octets[0] == 0:
            return True
        if ip.is_reserved:  # e.g. 240.0.0.0/4
            return True
    else:
        # IPv4-mapped IPv6 — re-check the embedded v4.
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None and _ip_is_blocked(mapped):
            return True
    return False


def validate_outbound_url(url: str, *, resolve: bool = True) -> str:
    """Return the URL unchanged if it is a safe public http(s) destination.

    Raises ``UnsafeURLError`` on: bad/relative URL, non-http(s) scheme, missing
    host, an IP-literal host that is private/loopback/etc., or (when ``resolve``)
    a hostname that resolves to ANY blocked IP.

    ``resolve=False`` skips DNS (used in unit tests / when only the literal shape
    matters); the worker calls with ``resolve=True`` at send time.
    """
    if not url or not isinstance(url, str):
        raise UnsafeURLError("empty URL")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"scheme {parsed.scheme!r} not allowed (http/https only)")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host")

    # Block well-known private/metadata hostnames by name (defense in depth) —
    # applies even when resolve=False and even if a resolver misbehaves.
    if _hostname_is_blocked(host):
        raise UnsafeURLError(f"hostname {host!r} is not a permitted destination")

    # IP literal → classify directly.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if _ip_is_blocked(ip):
            raise UnsafeURLError("URL resolves to a private/loopback/reserved address")
        return url

    if not resolve:
        return url

    # Hostname → reject if ANY resolved address is blocked.
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as e:
        raise UnsafeURLError(f"DNS resolution failed for {host!r}") from e
    saw_any = False
    for info in infos:
        addr = info[4][0]
        saw_any = True
        try:
            if _ip_is_blocked(ipaddress.ip_address(addr)):
                raise UnsafeURLError("URL resolves to a private/loopback/reserved address")
        except ValueError:
            continue
    if not saw_any:
        raise UnsafeURLError(f"DNS resolution failed for {host!r}")
    return url
