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
