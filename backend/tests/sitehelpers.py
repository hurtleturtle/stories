"""A tiny fake serial for the tests that scrape one (with respx active)."""

import httpx
import respx

BASE = "https://example.com/novel/"


def page(inner: str, next_href: str | None = None, title: str | None = None) -> str:
    """A chapter page: `inner` is the HTML inside the chapter container."""
    link = f'<a id="next_chap" href="{next_href}">Next</a>' if next_href is not None else ""
    heading = f'<span class="title">{title}</span>' if title else ""
    return f'<html><body>{heading}<div class="chapter-content">{inner}</div>{link}</body></html>'


def mount(**pages: str) -> dict[str, respx.Route]:
    """Serve BASE/<name> for each keyword; returns the routes, by name."""
    return {
        name: respx.get(BASE + name).mock(return_value=httpx.Response(200, text=html))
        for name, html in pages.items()
    }
