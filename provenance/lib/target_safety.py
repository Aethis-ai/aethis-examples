"""Safety validation for a cited source URL, mirrored from the engine.

Publishing a citation makes the engine fetch a caller-supplied URL. That is a
server-side request to an attacker-influencable destination, so the publish
path rejects anything that is not a plain, credential-free, globally-routable
HTTPS document. This module applies the same rules locally, so a manifest that
would be rejected at publish time is rejected here first, with the same stable
``reason_code``.

Checks, in order:

* **https only** - any other scheme (http, javascript, data, file, ftp) is
  refused before any network activity;
* **no credentials** in the URL (``user:pass@host``);
* **default port only** - an explicit non-443 port is refused;
* **no IP-literal hosts** - including the integer, hex and octal encodings of
  IPv4 that ``inet_aton`` accepts, and bracketed IPv6;
* **host must survive IDNA encoding** and match a strict ASCII DNS pattern,
  so confusable Unicode never reaches a resolver;
* **every resolved address must be globally routable** - loopback, RFC1918,
  link-local, carrier-grade NAT, multicast, reserved, unspecified and
  IPv4-mapped IPv6 destinations are all refused.

The resolver is injectable so the tests can exercise the private-destination
path without touching the network.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

_IPV4_SHAPE_RE = re.compile(r"^(?:\d+|0x[0-9a-fA-F]+|0[0-7]*)(?:\.(?:\d+|0x[0-9a-fA-F]+|0[0-7]*)){0,3}$")
_DNS_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62})?(\.[a-z0-9]([a-z0-9-]{0,62})?)*$", re.IGNORECASE)

Resolver = Callable[[str], List[str]]


class TargetSafetyError(ValueError):
    """A cited URL failed safety validation. ``reason_code`` is stable and
    matches the code the publish path reports for the same class."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


def _is_ip_literal(host: str) -> bool:
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ipaddress.ip_address(candidate)
        return True
    except ValueError:
        pass
    if _IPV4_SHAPE_RE.match(candidate):
        try:
            socket.inet_aton(candidate)
            return True
        except OSError:
            return False
    return False


def _idna_encode(host: str) -> str:
    try:
        encoded = host.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError) as exc:
        raise TargetSafetyError("unsafe_host", f"Host {host!r} failed IDNA encoding: {exc}")
    if not _DNS_NAME_RE.match(encoded):
        raise TargetSafetyError("unsafe_host", f"Host {host!r} is not a valid DNS name")
    return encoded.lower()


def address_is_public(addr: str) -> bool:
    """True iff ``addr`` is a globally routable unicast address."""
    ip = ipaddress.ip_address(addr)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def validate_target_url(url: str) -> Tuple[str, str]:
    """Static (pre-DNS) validation. Returns ``(normalised_url, ascii_host)``."""
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise TargetSafetyError("invalid_url", f"URL does not parse: {exc}")
    if parts.scheme.lower() != "https":
        raise TargetSafetyError("unsafe_scheme", f"Only https:// sources are accepted (got {parts.scheme!r})")
    if parts.username is not None or parts.password is not None:
        raise TargetSafetyError("credentials_in_url", "URLs must not embed credentials")
    host = parts.hostname or ""
    if not host:
        raise TargetSafetyError("invalid_url", "URL has no host")
    try:
        port = parts.port
    except ValueError as exc:
        raise TargetSafetyError("invalid_url", f"Invalid port: {exc}")
    if port not in (None, 443):
        raise TargetSafetyError("unsafe_port", "Only the default HTTPS port (443) is accepted")
    if _is_ip_literal(host):
        raise TargetSafetyError("ip_literal_host", "IP-literal hosts are not accepted; cite a named authority")
    ascii_host = _idna_encode(host)
    normalised = urlunsplit(("https", ascii_host, parts.path or "/", parts.query, ""))
    return normalised, ascii_host


def _default_resolver(host: str) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise TargetSafetyError("dns_failure", f"Could not resolve {host!r}: {exc}")
    return sorted({info[4][0] for info in infos})


def resolve_and_vet(host: str, resolver: Optional[Resolver] = None) -> str:
    """Resolve ``host`` and require EVERY returned address to be globally
    routable. Returns one vetted address."""
    addrs = (resolver or _default_resolver)(host)
    if not addrs:
        raise TargetSafetyError("dns_failure", f"{host!r} resolved to no addresses")
    for addr in addrs:
        if not address_is_public(addr):
            raise TargetSafetyError(
                "private_destination",
                f"{host!r} resolves to a non-public address ({addr}); refusing to fetch",
            )
    return addrs[0]


# Hosts that serve real users. Compared by exact, lower-cased hostname - never
# by substring. `"api.aethis.ai" in url and "staging" not in url` reads like a
# guard and is not one: `https://api.aethis.ai/?x=staging` and
# `https://API.AETHIS.AI` both slip straight past it.
PRODUCTION_HOSTS = frozenset({"api.aethis.ai", "aethis.ai", "www.aethis.ai"})


def is_production_url(url: str) -> bool:
    """True iff ``url``'s host is a production host, whatever the rest says."""
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        # Unparseable is treated as production: a guard that cannot tell where
        # a request is going must assume the answer it least wants.
        return True
    return host in PRODUCTION_HOSTS
