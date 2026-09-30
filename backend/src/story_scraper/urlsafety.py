"""Guards against scraping internal services.

Job URLs are user-supplied and the worker follows redirects and "next" links,
so without a check a user could point it at the Redis/Postgres containers, a
cloud metadata endpoint, or anything else on the private network.

This resolves the hostname and requires every address to be publicly
routable. It cannot stop a DNS-rebinding host that answers differently the
second time it is asked; closing that would need connecting to the checked
address directly.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = ("http", "https")


class UnsafeURLError(ValueError):
    """The URL is not one the scraper is willing to fetch."""


def resolve_host(host: str, port: int | None) -> list[str]:
    """Every address `host` resolves to. Split out so tests can stub DNS."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host {host!r}") from exc
    return [str(info[4][0]) for info in infos]


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    # ::ffff:10.0.0.1 is the private 10.0.0.1, whatever the IPv6 flags say.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global


def assert_public_url(url: str) -> None:
    """Raise UnsafeURLError unless `url` is an http(s) URL whose host only
    resolves to public addresses."""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeURLError(f"Invalid URL: {exc}") from exc

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError("Only http and https URLs can be scraped")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no host")

    for address in resolve_host(parsed.hostname, port):
        if not _is_public(address):
            raise UnsafeURLError(
                f"{parsed.hostname!r} resolves to a non-public address and cannot be scraped"
            )
