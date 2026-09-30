"""The scraper must not be usable to reach internal services."""

import httpx
import pytest
import respx

from story_scraper import urlsafety
from story_scraper.config import StoryConfig
from story_scraper.scraper import Story
from story_scraper.urlsafety import UnsafeURLError, assert_public_url

# Captured at import, before the autouse stub replaces it on the module.
real_resolve_host = urlsafety.resolve_host


def stub_hosts(monkeypatch, table: dict[str, list[str]]) -> None:
    def lookup(host, port):
        return table.get(host, ["93.184.216.34"])

    monkeypatch.setattr("story_scraper.urlsafety.resolve_host", lookup)


def test_a_public_url_is_accepted():
    assert_public_url("https://example.com/chapter-1")
    assert_public_url("http://93.184.216.34:8080/chapter-1")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:6379/",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[fd00::1]/",
        "http://[::ffff:10.0.0.1]/",
        "http://[::ffff:127.0.0.1]/",
    ],
)
def test_private_and_internal_addresses_are_rejected(url):
    with pytest.raises(UnsafeURLError, match="non-public"):
        assert_public_url(url)


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.com/", "gopher://x.example/", "example.com/1", ""],
)
def test_only_http_and_https_are_allowed(url):
    with pytest.raises(UnsafeURLError):
        assert_public_url(url)


def test_a_url_without_a_host_is_rejected():
    with pytest.raises(UnsafeURLError, match="no host"):
        assert_public_url("http:///chapter-1")


def test_a_malformed_port_is_rejected():
    with pytest.raises(UnsafeURLError):
        assert_public_url("http://example.com:notaport/")


def test_a_hostname_that_resolves_to_a_private_address_is_rejected(monkeypatch):
    """The realistic case: a Docker service name such as `redis` or `db`."""
    stub_hosts(monkeypatch, {"redis": ["172.18.0.3"]})

    with pytest.raises(UnsafeURLError, match="non-public"):
        assert_public_url("http://redis:6379/")


def test_every_resolved_address_must_be_public(monkeypatch):
    stub_hosts(monkeypatch, {"mixed.example": ["93.184.216.34", "10.0.0.9"]})

    with pytest.raises(UnsafeURLError):
        assert_public_url("https://mixed.example/")


def test_an_unresolvable_host_is_rejected(monkeypatch):
    def no_such_host(host, port, **kwargs):
        raise urlsafety.socket.gaierror("Name or service not known")

    monkeypatch.setattr(urlsafety.socket, "getaddrinfo", no_such_host)

    with pytest.raises(UnsafeURLError, match="Could not resolve"):
        real_resolve_host("nope.invalid", None)


def _story(url: str, **kwargs) -> Story:
    return Story(StoryConfig(url=url), **kwargs)


@respx.mock
def test_the_scraper_will_not_fetch_an_internal_host(monkeypatch):
    stub_hosts(monkeypatch, {"internal.example": ["10.0.0.9"]})
    route = respx.get("http://internal.example/chapter-1").mock(
        return_value=httpx.Response(200, text="secret")
    )

    with _story("http://internal.example/chapter-1") as story:
        with pytest.raises(UnsafeURLError):
            list(story.iter_chapters())

    assert not route.called


@respx.mock
def test_a_redirect_to_an_internal_host_is_refused(monkeypatch):
    stub_hosts(monkeypatch, {"internal.example": ["10.0.0.9"]})
    respx.get("https://example.com/chapter-1").mock(
        return_value=httpx.Response(302, headers={"Location": "http://internal.example/admin"})
    )
    internal = respx.get("http://internal.example/admin").mock(
        return_value=httpx.Response(200, text="secret")
    )

    with _story("https://example.com/chapter-1") as story:
        with pytest.raises(UnsafeURLError):
            list(story.iter_chapters())

    assert not internal.called


@respx.mock
def test_a_next_link_to_an_internal_host_is_refused(monkeypatch):
    stub_hosts(monkeypatch, {"internal.example": ["10.0.0.9"]})
    respx.get("https://example.com/chapter-1").mock(
        return_value=httpx.Response(
            200,
            text='<div class="chapter-content"><p>x</p></div>'
            '<a id="next_chap" href="http://internal.example/admin">next</a>',
        )
    )
    internal = respx.get("http://internal.example/admin").mock(
        return_value=httpx.Response(200, text="secret")
    )

    with _story("https://example.com/chapter-1") as story:
        with pytest.raises(UnsafeURLError):
            list(story.iter_chapters())

    assert not internal.called


@respx.mock
def test_private_hosts_can_be_allowed_for_local_use(monkeypatch):
    stub_hosts(monkeypatch, {"internal.example": ["10.0.0.9"]})
    respx.get("http://internal.example/chapter-1").mock(
        return_value=httpx.Response(200, text='<div class="chapter-content"><p>x</p></div>')
    )

    with _story("http://internal.example/chapter-1", allow_private_hosts=True) as story:
        assert len(list(story.iter_chapters())) == 1
