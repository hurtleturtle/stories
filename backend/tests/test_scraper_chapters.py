"""Chapters are stored as they are scraped: repeat detection, streaming to
disk, and carrying on after an interruption."""

import httpx
import pytest
import respx
from sitehelpers import BASE, mount, page

from story_scraper.chapters import MANIFEST
from story_scraper.config import StoryConfig
from story_scraper.scraper import ChapterNotFoundError, Story


def make_story(work_dir=None, first="c1", **overrides) -> Story:
    settings = {"container": "div.chapter-content", "next_selector": "a#next_chap", **overrides}
    return Story(StoryConfig(url=BASE + first, **settings), work_dir=work_dir)


def stored_files(work_dir) -> list[str]:
    return sorted(p.name for p in work_dir.glob("chapter-*.html"))


# --- repeat detection ------------------------------------------------------------


@respx.mock
def test_a_page_repeating_an_earlier_chapters_text_ends_the_story():
    routes = mount(
        c1=page("<p>The first chapter.</p>", "c2"),
        c2=page("<p>The first chapter.</p>", "c3"),
        c3=page("<p>Never reached.</p>"),
    )

    with make_story() as story:
        chapters = list(story.iter_chapters())
        html = story.download()

    assert [url for _, url in chapters] == [BASE + "c1"]
    assert html.count('class="chp"') == 1
    assert not routes["c3"].called
    assert "same text as chapter 1" in story.stop_reason
    assert BASE + "c2" in story.stop_reason


@respx.mock
def test_a_site_serving_its_last_page_under_endless_new_urls_is_stopped():
    """The common way a scrape never ends: the final page links to 'next', which
    is the same page again under a fresh URL. No URL repeats; the text does."""
    respx.get(BASE + "c1").mock(
        return_value=httpx.Response(200, text=page("<p>One.</p>", "last?n=0"))
    )

    def last_page(request: httpx.Request) -> httpx.Response:
        n = int(request.url.params["n"])
        return httpx.Response(200, text=page("<p>The final page.</p>", f"last?n={n + 1}"))

    last = respx.get(url__regex=r"https://example\.com/novel/last\?n=\d+").mock(
        side_effect=last_page
    )

    with make_story() as story:
        chapters = list(story.iter_chapters())

    assert len(chapters) == 2  # chapter 1 and the final page, once
    assert last.call_count == 2  # the second fetch is what revealed the repeat
    assert "same text as chapter 2" in story.stop_reason


@respx.mock
def test_a_repeat_of_any_earlier_chapter_is_caught_not_just_the_previous_one():
    mount(
        c1=page("<p>Alpha.</p>", "c2"),
        c2=page("<p>Beta.</p>", "c3"),
        c3=page("<p>Alpha.</p>", "c4"),
        c4=page("<p>Never reached.</p>"),
    )

    with make_story() as story:
        chapters = list(story.iter_chapters())

    assert len(chapters) == 2
    assert "same text as chapter 1" in story.stop_reason


@respx.mock
def test_markup_and_whitespace_do_not_hide_a_repeat():
    mount(
        c1=page("<p>Same text here</p>", "c2"),
        c2=page('<div class="wrap">\n  <p id="x">Same   text</p>\n<p>here</p></div>'),
    )

    with make_story() as story:
        assert len(list(story.iter_chapters())) == 1


@respx.mock
def test_scripts_and_ads_do_not_hide_a_repeat():
    """Ad scripts change on every load. They are removed before the text is
    hashed, so they cannot make identical chapters look different."""
    mount(
        c1=page("<p>Story text.</p><script>ad_id = 111</script>", "c2"),
        c2=page('<p>Story text.</p><script>ad_id = 222</script><iframe src="//ads.test"></iframe>'),
    )

    with make_story() as story:
        assert len(list(story.iter_chapters())) == 1


@respx.mock
def test_the_heading_is_not_part_of_what_is_compared():
    mount(
        c1=page("<p>Same body.</p>", "c2", title="Chapter 1: One"),
        c2=page("<p>Same body.</p>", title="Chapter 2: Two"),
    )

    with make_story(detect_title="span.title") as story:
        assert len(list(story.iter_chapters())) == 1


@respx.mock
def test_chapters_with_different_text_are_all_kept():
    mount(
        c1=page("<p>He opened the door.</p>", "c2"),
        c2=page("<p>He closed the door.</p>", "c3"),
        c3=page("<p>He opened the door!</p>"),  # differs only by punctuation
    )

    with make_story() as story:
        assert len(list(story.iter_chapters())) == 3


@respx.mock
def test_a_repeat_is_checked_before_anything_is_numbered_built_or_stored(tmp_path):
    mount(
        c1=page("<p>One.</p>", "c2", title="Chapter 5: Five"),
        c2=page("<p>One.</p>", title="Chapter 6: Six"),
    )
    built: list[int] = []

    class Spy(Story):
        def _build_chapter(self, soup, content):
            built.append(1)
            return super()._build_chapter(soup, content)

    config = StoryConfig(
        url=BASE + "c1",
        container="div.chapter-content",
        next_selector="a#next_chap",
        detect_title="span.title",
    )
    with Spy(config, work_dir=tmp_path) as story:
        list(story.iter_chapters())

        assert len(built) == 1  # never built for the repeated page
        assert story.current_chapter == "5"  # its heading number was not taken
        assert story.chapters_done == 1

    assert stored_files(tmp_path) == ["chapter-000001.html"]
    assert len((tmp_path / MANIFEST).read_text().strip().split("\n")) == 3  # header, ch 1, done


@respx.mock
def test_the_end_of_a_story_is_not_reported_as_a_reason_to_stop():
    mount(c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>"))

    with make_story() as story:
        list(story.iter_chapters())

    assert story.stop_reason is None


@respx.mock
def test_reaching_num_chapters_is_not_reported_as_a_reason_to_stop():
    mount(c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>"))

    with make_story(num_chapters=1) as story:
        assert len(list(story.iter_chapters())) == 1

    assert story.stop_reason is None


@respx.mock
def test_other_ways_the_story_can_end_early_are_explained():
    respx.get(BASE + "a1").mock(return_value=httpx.Response(200, text=page("<p>A.</p>", "gone")))
    respx.get(BASE + "gone").mock(return_value=httpx.Response(404))
    respx.get(BASE + "b1").mock(return_value=httpx.Response(200, text=page("<p>B.</p>", "index")))
    respx.get(BASE + "index").mock(return_value=httpx.Response(200, text="<html>Contents</html>"))
    respx.get(BASE + "c1").mock(return_value=httpx.Response(200, text=page("<p>C.</p>", "c1")))

    with make_story(first="a1") as story:
        list(story.iter_chapters())
    assert "404" in story.stop_reason and "Stopped after 1 chapters" in story.stop_reason

    with make_story(first="b1") as story:
        list(story.iter_chapters())
    assert "No elements matched" in story.stop_reason

    with make_story(first="c1") as story:
        list(story.iter_chapters())
    assert "already fetched" in story.stop_reason


# --- what ends up in the chapters ---------------------------------------------------


@respx.mock
def test_scripts_and_event_handlers_never_reach_the_stored_chapter_or_the_output(tmp_path):
    mount(
        c1=page(
            '<p onclick="steal()">Hello <a href="javascript:steal()">world</a>.</p>'
            "<script>steal()</script><style>p{display:none}</style>"
            '<iframe src="https://ads.test"></iframe><!-- tracker -->'
        )
    )

    with make_story(work_dir=tmp_path) as story:
        html = story.download()

    stored = (tmp_path / "chapter-000001.html").read_text()
    for text in (stored, html):
        assert "steal" not in text
        assert "display:none" not in text
        assert "iframe" not in text
        assert "tracker" not in text
    assert "Hello" in stored and "world" in stored


@respx.mock
def test_a_container_holding_only_blocked_content_counts_as_no_content():
    mount(
        c1=page("<p>One.</p>", "c2"), c2='<div class="chapter-content"><script>x()</script></div>'
    )

    with make_story() as story:
        chapters = list(story.iter_chapters())

    assert len(chapters) == 1
    assert "Nothing usable" in story.stop_reason


@respx.mock
def test_an_empty_container_counts_as_no_content():
    """A page whose text is filled in by JavaScript matches the selector but
    holds nothing; it must not become a blank chapter."""
    mount(c1=page("<p>One.</p>", "c2"), c2=page("  <p> </p>  \n"))

    with make_story() as story:
        chapters = list(story.iter_chapters())

    assert len(chapters) == 1
    assert "Nothing usable" in story.stop_reason


@respx.mock
def test_an_empty_first_page_is_an_error():
    mount(c1=page("<p></p>"))

    with make_story() as story, pytest.raises(ChapterNotFoundError):
        list(story.iter_chapters())


@respx.mock
def test_a_chapter_of_only_images_is_still_a_chapter():
    mount(c1=page('<img src="page1.png"/>', "c2"), c2=page('<p><img src="page2.png"/></p>'))

    with make_story() as story:
        chapters = list(story.iter_chapters())

    assert len(chapters) == 2


@respx.mock
def test_image_only_chapters_are_told_apart_by_their_pictures():
    mount(
        c1=page('<img src="page1.png"/>', "c2"),
        c2=page('<img src="page2.png"/>', "c3"),
        c3=page('<img src="page1.png"/>', "c4"),  # the same picture again: a repeat
        c4=page('<img src="page4.png"/>'),
    )

    with make_story() as story:
        chapters = list(story.iter_chapters())

    assert len(chapters) == 2
    assert "same text as chapter 1" in story.stop_reason


@respx.mock
def test_a_container_that_is_itself_an_image_counts_as_content():
    mount(c1='<img class="page" src="a.png"/><a id="next_chap" href="c2">n</a>')
    mount(c2='<img class="page" src="b.png"/>')

    with make_story(container="img.page") as story:
        assert len(list(story.iter_chapters())) == 2


@respx.mock
def test_the_reason_a_story_ended_survives_asking_again(tmp_path):
    mount(c1=page("<p>One.</p>", "c2"), c2=page("<p>One.</p>"))

    with make_story(work_dir=tmp_path) as story:
        list(story.iter_chapters())
        reason = story.stop_reason
        assert list(story.iter_chapters()) == []  # already finished

    assert reason and story.stop_reason == reason


# --- streaming to disk -----------------------------------------------------------------


@respx.mock
def test_each_chapter_is_on_disk_before_the_next_page_is_fetched(tmp_path):
    routes = mount(
        c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>", "c3"), c3=page("<p>Three.</p>")
    )
    following = {1: "c2", 2: "c3"}

    with make_story(work_dir=tmp_path) as story:
        for count, _url in story.iter_chapters():
            assert (tmp_path / f"chapter-{count:06d}.html").is_file()
            if count in following:
                assert not routes[following[count]].called

    assert stored_files(tmp_path) == [f"chapter-00000{n}.html" for n in (1, 2, 3)]


@respx.mock
def test_progress_is_reported_for_each_new_chapter():
    mount(c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>"))
    reported: list[tuple[int, str]] = []
    config = StoryConfig(
        url=BASE + "c1", container="div.chapter-content", next_selector="a#next_chap"
    )

    with Story(config, progress=lambda n, url: reported.append((n, url))) as story:
        story.scrape()

    assert reported == [(1, BASE + "c1"), (2, BASE + "c2")]


@respx.mock
def test_write_produces_the_whole_document_and_leaves_nothing_else(tmp_path):
    mount(c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>"))
    out = tmp_path / "out"

    with make_story(work_dir=tmp_path / "work") as story:
        written = story.write(out)

    assert [p.name for p in out.iterdir()] == [written.name]
    html = written.read_text(encoding="utf-8")
    assert html.count('class="chp"') == 2
    assert html.index("One.") < html.index("Two.")
    assert html.rstrip().endswith("</html>")


@respx.mock
def test_write_leaves_no_file_when_the_scrape_fails(tmp_path):
    mount(c1=page("<p>One.</p>", "c2"))
    respx.get(BASE + "c2").mock(return_value=httpx.Response(500))
    out = tmp_path / "out"

    with make_story(work_dir=tmp_path / "work") as story:
        with pytest.raises(httpx.HTTPStatusError):
            story.write(out)

    assert list(out.iterdir()) == []


@respx.mock
def test_a_story_without_a_work_dir_cleans_up_after_itself():
    mount(c1=page("<p>One.</p>"))

    with make_story() as story:
        story.download()
        scratch = story.store.directory
        assert scratch.is_dir()

    assert not scratch.exists()


@respx.mock
def test_a_work_dir_that_was_passed_in_is_left_for_the_caller(tmp_path):
    mount(c1=page("<p>One.</p>"))

    with make_story(work_dir=tmp_path) as story:
        story.download()

    assert stored_files(tmp_path) == ["chapter-000001.html"]


# --- resuming -----------------------------------------------------------------------------


@respx.mock
def test_a_scrape_that_failed_partway_carries_on_after_the_last_stored_chapter(tmp_path):
    c1 = respx.get(BASE + "c1").mock(
        return_value=httpx.Response(200, text=page("<p>One.</p>", "c2"))
    )
    c2 = respx.get(BASE + "c2").mock(
        return_value=httpx.Response(200, text=page("<p>Two.</p>", "c3"))
    )
    c3 = respx.get(BASE + "c3").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(503),  # the first attempt gives up here...
            httpx.Response(200, text=page("<p>Three.</p>")),  # ...the second gets through
        ]
    )

    with make_story(work_dir=tmp_path) as first:
        with pytest.raises(httpx.HTTPStatusError):
            first.scrape()
    assert stored_files(tmp_path) == ["chapter-000001.html", "chapter-000002.html"]

    reported: list[int] = []
    config = StoryConfig(
        url=BASE + "c1", container="div.chapter-content", next_selector="a#next_chap"
    )
    with Story(config, work_dir=tmp_path, progress=lambda n, url: reported.append(n)) as second:
        assert second.chapters_done == 2
        html = second.download()

    assert reported == [3]  # only the new chapter was fetched and reported
    assert (c1.call_count, c2.call_count, c3.call_count) == (1, 1, 4)  # 1 and 2 never refetched
    assert [t in html for t in ("One.", "Two.", "Three.")] == [True, True, True]
    assert html.index("One.") < html.index("Two.") < html.index("Three.")
    assert "Chapter 3" in html
    assert second.stop_reason is None


@respx.mock
def test_a_resumed_scrape_produces_the_same_document_as_an_uninterrupted_one(tmp_path):
    mount(c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>", "c3"), c3=page("<p>Three.</p>"))
    with make_story(work_dir=tmp_path / "whole") as story:
        whole = story.download()

    # Interrupt after two chapters by stopping the iteration.
    with make_story(work_dir=tmp_path / "split") as story:
        for count, _ in story.iter_chapters():
            if count == 2:
                break
    with make_story(work_dir=tmp_path / "split") as story:
        assert story.chapters_done == 2
        resumed = story.download()

    assert resumed == whole


@respx.mock
def test_chapter_numbering_carries_on_from_the_stored_headings(tmp_path):
    mount(
        c1=page("<p>One.</p>", "c2", title="Chapter 10: Ten"),
        c2=page("<p>Two.</p>", "c3", title="Chapter 11: Eleven"),
        c3=page("<p>Three.</p>"),  # untitled: numbered from where the story got to
    )
    with make_story(work_dir=tmp_path, detect_title="span.title") as story:
        for count, _ in story.iter_chapters():
            if count == 2:
                break

    with make_story(work_dir=tmp_path, detect_title="span.title") as story:
        html = story.download()

    assert "Chapter 12" in html
    assert "Chapter 3" not in html


@respx.mock
def test_a_finished_scrape_is_not_fetched_again(tmp_path):
    routes = mount(c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>"))
    with make_story(work_dir=tmp_path) as story:
        first = story.download()
    calls = {name: route.call_count for name, route in routes.items()}

    with make_story(work_dir=tmp_path) as story:
        assert list(story.iter_chapters()) == []
        second = story.download()

    assert second == first
    assert {name: route.call_count for name, route in routes.items()} == calls


@respx.mock
def test_a_scrape_stopped_by_num_chapters_is_finished_too(tmp_path):
    routes = mount(c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>"))
    with make_story(work_dir=tmp_path, num_chapters=1) as story:
        story.download()

    with make_story(work_dir=tmp_path, num_chapters=1) as story:
        assert list(story.iter_chapters()) == []

    assert routes["c1"].call_count == 1 and not routes["c2"].called


@respx.mock
def test_a_story_that_ended_on_a_repeat_stays_ended(tmp_path):
    routes = mount(
        c1=page("<p>One.</p>", "c2"), c2=page("<p>One.</p>", "c3"), c3=page("<p>Never.</p>")
    )
    with make_story(work_dir=tmp_path) as story:
        story.download()

    with make_story(work_dir=tmp_path) as story:
        assert list(story.iter_chapters()) == []

    assert routes["c2"].call_count == 1 and not routes["c3"].called


@respx.mock
def test_stored_chapters_of_a_different_story_are_not_reused(tmp_path):
    routes = mount(c1=page("<p>One.</p>"))
    with make_story(work_dir=tmp_path) as story:
        story.download()

    other = StoryConfig(url=BASE + "c1", container="div.chapter-content", next_selector="a.other")
    with Story(other, work_dir=tmp_path) as story:
        assert story.chapters_done == 0  # read differently, so scraped afresh
        story.download()

    assert routes["c1"].call_count == 2


@respx.mock
def test_a_torn_manifest_from_a_crash_is_recovered_from(tmp_path):
    routes = mount(
        c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>", "c3"), c3=page("<p>Three.</p>")
    )
    with make_story(work_dir=tmp_path) as story:
        for count, _ in story.iter_chapters():
            if count == 2:
                break
    with (tmp_path / MANIFEST).open("a") as manifest:
        manifest.write('{"n": 3, "url": "https://exa')  # killed mid-write

    with make_story(work_dir=tmp_path) as story:
        html = story.download()

    assert html.count('class="chp"') == 3
    assert (routes["c1"].call_count, routes["c2"].call_count) == (1, 1)
