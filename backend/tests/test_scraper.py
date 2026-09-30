import httpx
import pytest
import respx

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

    assert [c for c, _ in chapters] == [1, 2]
    assert "Once upon a time" in story.doc.body.get_text()
    assert "The end" in story.doc.body.get_text()


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
        list(story.iter_chapters())

    heading = story.doc.select_one("h2.chapter-heading")
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


def _chapter(next_href: str | None) -> str:
    link = f'<a id="next_chap" href="{next_href}">Next</a>' if next_href is not None else ""
    return f'<html><body><div class="chapter-content"><p>Text.</p></div>{link}</body></html>'


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
