import httpx
import pytest
import respx
from bs4 import BeautifulSoup

from story_scraper.config import StoryConfig
from story_scraper.scraper import ChapterNotFoundError, Story

CHAPTER_1 = """
<html><body>
<div class="chapter-content"><p>Once upon a time.</p></div>
<a id="next_chap" href="/chapter-2">Next</a>
</body></html>
"""

CHAPTER_2 = """
<html><body>
<div class="chapter-content"><p>The end.</p></div>
</body></html>
"""


def make_story(**overrides) -> Story:
    config = StoryConfig(
        url="https://example.com/chapter-1",
        container="div.chapter-content",
        next_selector="a#next_chap",
        **overrides,
    )
    return Story(config)


@respx.mock
def test_iter_chapters_follows_next_link_until_exhausted():
    respx.get("https://example.com/chapter-1").mock(
        return_value=httpx.Response(200, text=CHAPTER_1)
    )
    respx.get("https://example.com/chapter-2").mock(
        return_value=httpx.Response(200, text=CHAPTER_2)
    )

    with make_story() as story:
        chapters = list(story.iter_chapters())
        html = story.download()

    assert [c for c, _ in chapters] == [1, 2]
    assert "Once upon a time" in html
    assert "The end" in html


@respx.mock
def test_iter_chapters_stops_at_num_chapters():
    respx.get("https://example.com/chapter-1").mock(
        return_value=httpx.Response(200, text=CHAPTER_1)
    )

    with make_story(num_chapters=1) as story:
        chapters = list(story.iter_chapters())

    assert len(chapters) == 1


@respx.mock
def test_missing_container_raises():
    respx.get("https://example.com/chapter-1").mock(
        return_value=httpx.Response(200, text="<html><body>nothing here</body></html>")
    )

    with make_story() as story, pytest.raises(ChapterNotFoundError):
        list(story.iter_chapters())


@respx.mock
def test_fetch_retries_then_raises_on_persistent_failure():
    route = respx.get("https://example.com/chapter-1").mock(
        side_effect=httpx.ConnectError("boom")
    )

    with make_story() as story:
        with pytest.raises(httpx.ConnectError):
            story.fetch("https://example.com/chapter-1", retries=2)

    assert route.call_count == 2


@respx.mock
def test_chapter_title_uses_detect_title_selector():
    html = """
    <html><body>
    <span class="title">Chapter 5: A New Beginning</span>
    <div class="chapter-content"><p>Text.</p></div>
    </body></html>
    """
    respx.get("https://example.com/chapter-1").mock(return_value=httpx.Response(200, text=html))

    with make_story(detect_title="span.title") as story:
        html = story.download()

    heading = BeautifulSoup(html, "lxml").select_one("h2.chapter-heading")
    assert heading.text == "Chapter 5 - A New Beginning"


@respx.mock
def test_next_url_resolves_relative_links_against_base_url():
    respx.get("https://example.com/chapter-1").mock(
        return_value=httpx.Response(200, text=CHAPTER_1)
    )
    respx.get("https://example.com/chapter-2").mock(
        return_value=httpx.Response(200, text=CHAPTER_2)
    )

    with make_story() as story:
        chapters = list(story.iter_chapters())

    assert chapters[1][1] == "https://example.com/chapter-2"


@respx.mock
def test_base_url_keeps_non_default_port():
    """Regression test: base_url must include the port, not just the
    hostname, or relative next-links break on any non-default-port host."""
    respx.get("http://example.com:8000/chapter-1").mock(
        return_value=httpx.Response(200, text=CHAPTER_1)
    )
    respx.get("http://example.com:8000/chapter-2").mock(
        return_value=httpx.Response(200, text=CHAPTER_2)
    )

    config = StoryConfig(
        url="http://example.com:8000/chapter-1",
        container="div.chapter-content",
        next_selector="a#next_chap",
    )
    with Story(config) as story:
        chapters = list(story.iter_chapters())

    assert chapters[1][1] == "http://example.com:8000/chapter-2"


def _story_url(path: str) -> str:
    return f"https://example.com/novel/{path}"


def _chapter(next_href: str | None, text: str | None = None) -> str:
    """A chapter page. Unless given, its text differs with where it links, so
    the chapters of a test story are not taken for repeats of one another."""
    link = f'<a id="next_chap" href="{next_href}">Next</a>' if next_href is not None else ""
    text = text if text is not None else f"Text before {next_href}."
    return f'<html><body><div class="chapter-content"><p>{text}</p></div>{link}</body></html>'


def _make_story_at(url: str, **overrides) -> Story:
    config = StoryConfig(
        url=url, container="div.chapter-content", next_selector="a#next_chap", **overrides
    )
    return Story(config)


@respx.mock
@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("chapter-2", "https://example.com/novel/chapter-2"),
        ("./chapter-2", "https://example.com/novel/chapter-2"),
        ("../other/chapter-2", "https://example.com/other/chapter-2"),
        ("/chapter-2", "https://example.com/chapter-2"),
        ("//example.com/chapter-2", "https://example.com/chapter-2"),
        ("https://example.com/novel/chapter-2#comments", "https://example.com/novel/chapter-2"),
    ],
)
def test_next_link_forms_are_resolved_against_the_current_page(href, expected):
    respx.get(_story_url("chapter-1")).mock(
        return_value=httpx.Response(200, text=_chapter(href))
    )
    respx.get(expected).mock(return_value=httpx.Response(200, text=_chapter(None)))

    with _make_story_at(_story_url("chapter-1")) as story:
        chapters = list(story.iter_chapters())

    assert [url for _, url in chapters] == [_story_url("chapter-1"), expected]


@respx.mock
def test_next_link_is_resolved_against_the_page_after_redirects():
    respx.get("https://example.com/old/chapter-1").mock(
        return_value=httpx.Response(302, headers={"Location": "https://example.com/new/chapter-1"})
    )
    respx.get("https://example.com/new/chapter-1").mock(
        return_value=httpx.Response(200, text=_chapter("chapter-2"))
    )
    respx.get("https://example.com/new/chapter-2").mock(
        return_value=httpx.Response(200, text=_chapter(None))
    )

    with _make_story_at("https://example.com/old/chapter-1") as story:
        chapters = list(story.iter_chapters())

    assert chapters[1][1] == "https://example.com/new/chapter-2"


@respx.mock
@pytest.mark.parametrize("href", ["#", "", "   ", "javascript:void(0)", "mailto:a@b.c"])
def test_a_disabled_next_link_ends_the_story(href):
    route = respx.get(_story_url("chapter-1")).mock(
        return_value=httpx.Response(200, text=_chapter(href))
    )

    with _make_story_at(_story_url("chapter-1")) as story:
        chapters = list(story.iter_chapters())

    assert len(chapters) == 1
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize("status", [404, 410])
def test_a_dead_next_link_keeps_the_chapters_already_fetched(status):
    respx.get(_story_url("chapter-1")).mock(
        return_value=httpx.Response(200, text=_chapter("chapter-2"))
    )
    respx.get(_story_url("chapter-2")).mock(
        return_value=httpx.Response(200, text=_chapter("chapter-3"))
    )
    respx.get(_story_url("chapter-3")).mock(return_value=httpx.Response(status))

    with _make_story_at(_story_url("chapter-1")) as story:
        html = story.download()

    assert html.count('class="chp"') == 2


@respx.mock
def test_a_next_page_without_chapter_content_keeps_the_chapters_already_fetched():
    respx.get(_story_url("chapter-1")).mock(
        return_value=httpx.Response(200, text=_chapter("index"))
    )
    respx.get(_story_url("index")).mock(
        return_value=httpx.Response(200, text="<html><body>Table of contents</body></html>")
    )

    with _make_story_at(_story_url("chapter-1")) as story:
        html = story.download()

    assert html.count('class="chp"') == 1


@respx.mock
def test_a_missing_first_page_still_fails():
    respx.get(_story_url("chapter-1")).mock(return_value=httpx.Response(404))

    with _make_story_at(_story_url("chapter-1")) as story:
        with pytest.raises(httpx.HTTPStatusError):
            list(story.iter_chapters())


@respx.mock
def test_a_server_error_mid_story_still_fails():
    """Only "there is no such page" ends a story; an outage must not be
    mistaken for the last chapter and produce a silently truncated book."""
    respx.get(_story_url("chapter-1")).mock(
        return_value=httpx.Response(200, text=_chapter("chapter-2"))
    )
    respx.get(_story_url("chapter-2")).mock(return_value=httpx.Response(503))

    with _make_story_at(_story_url("chapter-1")) as story:
        with pytest.raises(httpx.HTTPStatusError):
            list(story.iter_chapters())


# --- output ----------------------------------------------------------------


def _download(page_html: str, **overrides) -> str:
    respx.get(_story_url("chapter-1")).mock(return_value=httpx.Response(200, text=page_html))
    with _make_story_at(_story_url("chapter-1"), **overrides) as story:
        return story.download()


@respx.mock
def test_inline_markup_is_not_split_by_whitespace():
    html = _download('<div class="chapter-content"><p>un<em>believ</em>able</p></div>')

    assert "un<em>believ</em>able" in html


@respx.mock
def test_the_stylesheet_is_inlined_rather_than_linked_to_a_path_on_the_worker():
    html = _download(_chapter(None))

    assert "<link" not in html
    assert '<style type="text/css">' in html
    assert "font-family" in html  # from the bundled white-style.css


@respx.mock
def test_scripts_are_inlined_too():
    html = _download(_chapter(None), scripts=["scroll_tracker.js"])

    assert "<script>" in html
    assert "src=" not in html
    assert "window.onload" in html


@respx.mock
def test_inlined_css_and_js_are_not_html_escaped(monkeypatch):
    source = "a > b { color: red } /* x && y < z */"
    monkeypatch.setattr("story_scraper.scraper.read_asset", lambda kind, name: source)

    html = _download(_chapter(None), scripts=["scroll_tracker.js"])

    assert html.count(source) == 2  # once as the style, once as the script


@respx.mock
def test_the_document_declares_utf8():
    html = _download(_chapter(None))

    assert '<meta charset="utf-8"/>' in html


@respx.mock
def test_a_chapter_title_split_across_child_elements_is_still_read():
    page = (
        "<html><body><h3 class='t'><span>Chapter 7</span>: The Return</h3>"
        '<div class="chapter-content"><p>x</p></div></body></html>'
    )

    with_title = _download(page, detect_title="h3.t")

    assert "Chapter 7 - The Return" in with_title


@respx.mock
def test_write_saves_utf8(tmp_path):
    respx.get(_story_url("chapter-1")).mock(
        return_value=httpx.Response(
            200, text='<div class="chapter-content"><p>第一章 — café</p></div>'
        )
    )

    with _make_story_at(_story_url("chapter-1")) as story:
        written = story.write(tmp_path)

    assert "第一章 — café" in written.read_bytes().decode("utf-8")


# --- decoding --------------------------------------------------------------


GBK_PAGE = (
    '<html><head><meta charset="gbk"></head><body>'
    '<div class="chapter-content"><p>第一章</p></div></body></html>'
).encode("gbk")


@respx.mock
def test_a_meta_charset_is_honoured_when_the_server_sends_none():
    respx.get(_story_url("chapter-1")).mock(
        return_value=httpx.Response(200, content=GBK_PAGE, headers={"content-type": "text/html"})
    )

    with _make_story_at(_story_url("chapter-1")) as story:
        html = story.download()

    assert "第一章" in html


@respx.mock
def test_the_charset_in_the_response_header_is_honoured():
    page = '<div class="chapter-content"><p>café</p></div>'.encode("latin-1")
    respx.get(_story_url("chapter-1")).mock(
        return_value=httpx.Response(
            200, content=page, headers={"content-type": "text/html; charset=iso-8859-1"}
        )
    )

    with _make_story_at(_story_url("chapter-1")) as story:
        html = story.download()

    assert "café" in html


# --- retries ---------------------------------------------------------------


@respx.mock
def test_a_403_is_not_retried(retry_sleeps):
    route = respx.get(_story_url("chapter-1")).mock(return_value=httpx.Response(403))

    with _make_story_at(_story_url("chapter-1")) as story:
        with pytest.raises(httpx.HTTPStatusError):
            story.fetch(_story_url("chapter-1"))

    assert route.call_count == 1
    assert retry_sleeps == []


@respx.mock
def test_a_server_error_is_retried_and_can_recover(retry_sleeps):
    route = respx.get(_story_url("chapter-1")).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, text="ok")]
    )

    with _make_story_at(_story_url("chapter-1")) as story:
        assert story.fetch(_story_url("chapter-1")) == "ok"

    assert route.call_count == 2
    assert retry_sleeps == [2.0]


@respx.mock
def test_the_pause_between_retries_grows_and_none_follows_the_last_attempt(retry_sleeps):
    route = respx.get(_story_url("chapter-1")).mock(return_value=httpx.Response(500))

    with _make_story_at(_story_url("chapter-1")) as story:
        with pytest.raises(httpx.HTTPStatusError):
            story.fetch(_story_url("chapter-1"), retries=4)

    assert route.call_count == 4
    assert retry_sleeps == [2.0, 4.0, 8.0]


@respx.mock
def test_retry_after_is_honoured_and_capped(retry_sleeps):
    respx.get(_story_url("chapter-1")).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(429, headers={"Retry-After": "3600"}),
            httpx.Response(200, text="ok"),
        ]
    )

    with _make_story_at(_story_url("chapter-1")) as story:
        story.fetch(_story_url("chapter-1"))

    assert retry_sleeps == [7.0, 60.0]


@respx.mock
def test_a_retry_after_date_falls_back_to_the_normal_pause(retry_sleeps):
    respx.get(_story_url("chapter-1")).mock(
        side_effect=[
            httpx.Response(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            httpx.Response(200, text="ok"),
        ]
    )

    with _make_story_at(_story_url("chapter-1")) as story:
        story.fetch(_story_url("chapter-1"))

    assert retry_sleeps == [2.0]


@respx.mock
def test_network_errors_are_retried(retry_sleeps):
    route = respx.get(_story_url("chapter-1")).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, text="ok")]
    )

    with _make_story_at(_story_url("chapter-1")) as story:
        assert story.fetch(_story_url("chapter-1")) == "ok"

    assert route.call_count == 2


# --- loops -----------------------------------------------------------------


@respx.mock
def test_a_chapter_linking_to_itself_ends_the_story():
    route = respx.get(_story_url("chapter-1")).mock(
        return_value=httpx.Response(200, text=_chapter("chapter-1"))
    )

    with _make_story_at(_story_url("chapter-1")) as story:
        chapters = list(story.iter_chapters())

    assert len(chapters) == 1
    assert route.call_count == 1


@respx.mock
def test_a_cycle_between_chapters_ends_the_story():
    respx.get(_story_url("chapter-1")).mock(
        return_value=httpx.Response(200, text=_chapter("chapter-2"))
    )
    respx.get(_story_url("chapter-2")).mock(
        return_value=httpx.Response(200, text=_chapter("chapter-1#top"))
    )

    with _make_story_at(_story_url("chapter-1")) as story:
        chapters = list(story.iter_chapters())

    assert [url for _, url in chapters] == [_story_url("chapter-1"), _story_url("chapter-2")]
