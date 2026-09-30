"""Ceilings on one scrape: chapters, time and page size."""

import gzip

import httpx
import pytest
import respx
from sitehelpers import BASE, mount, page

from story_scraper import scraper as scraper_module
from story_scraper.config import StoryConfig, settings
from story_scraper.scraper import PageTooLargeError, Story


def make_story(work_dir=None, first="c1", **limits) -> Story:
    config = StoryConfig(
        url=BASE + first, container="div.chapter-content", next_selector="a#next_chap"
    )
    return Story(config, work_dir=work_dir, **limits)


def chain(length: int) -> dict[str, respx.Route]:
    """c1 -> c2 -> ... -> c<length>, every chapter different."""
    pages = {
        f"c{n}": page(f"<p>Chapter text {n}.</p>", f"c{n + 1}" if n < length else None)
        for n in range(1, length + 1)
    }
    return mount(**pages)


# --- chapter limit ---------------------------------------------------------------


@respx.mock
def test_a_scrape_stops_at_the_chapter_limit_and_says_so(tmp_path):
    routes = chain(5)

    with make_story(work_dir=tmp_path, max_chapters=3) as story:
        chapters = list(story.iter_chapters())

    assert len(chapters) == 3
    assert not routes["c4"].called
    assert "limit of 3 chapters" in story.stop_reason and "MAX_CHAPTERS" in story.stop_reason
    assert not story.store.done  # cut short, not finished


@respx.mock
def test_raising_the_limit_and_retrying_carries_on_from_where_it_stopped(tmp_path):
    routes = chain(5)
    with make_story(work_dir=tmp_path, max_chapters=3) as story:
        story.download()

    with make_story(work_dir=tmp_path, max_chapters=100) as story:
        assert story.chapters_done == 3
        html = story.download()

    assert html.count('class="chp"') == 5
    assert [route.call_count for route in routes.values()] == [1, 1, 1, 1, 1]
    assert story.store.done and story.stop_reason is None


@respx.mock
def test_a_story_that_ends_exactly_at_the_limit_is_not_reported_as_cut_short(tmp_path):
    chain(3)

    with make_story(work_dir=tmp_path, max_chapters=3) as story:
        assert len(list(story.iter_chapters())) == 3

    assert story.stop_reason is None
    assert story.store.done


@respx.mock
def test_a_limit_of_zero_means_no_limit():
    chain(6)

    with make_story(max_chapters=0) as story:
        assert len(list(story.iter_chapters())) == 6


@respx.mock
def test_a_site_that_never_ends_is_bounded():
    """Every page is new, so neither the URL check nor the repeat check can
    stop it - only the limit does."""
    respx.get(url__regex=r"https://example\.com/novel/n\d+").mock(
        side_effect=lambda request: httpx.Response(
            200,
            text=page(
                f"<p>Unique text of {request.url.path}.</p>",
                f"n{int(request.url.path.rsplit('/n', 1)[1]) + 1}",
            ),
        )
    )

    with make_story(first="n0", max_chapters=25) as story:
        assert len(list(story.iter_chapters())) == 25

    assert "limit of 25 chapters" in story.stop_reason


@respx.mock
def test_num_chapters_below_the_limit_still_wins():
    chain(6)
    config = StoryConfig(
        url=BASE + "c1",
        container="div.chapter-content",
        next_selector="a#next_chap",
        num_chapters=2,
    )

    with Story(config, max_chapters=100) as story:
        assert len(list(story.iter_chapters())) == 2

    assert story.stop_reason is None


# --- time limit ---------------------------------------------------------------------


class FakeClock:
    """Advances by `step` seconds every time it is read."""

    def __init__(self, step: float) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


@respx.mock
def test_a_scrape_stops_when_it_has_run_too_long(monkeypatch, tmp_path):
    routes = chain(10)
    monkeypatch.setattr(scraper_module, "_monotonic", FakeClock(step=100))

    with make_story(work_dir=tmp_path, max_scrape_seconds=350) as story:
        chapters = list(story.iter_chapters())

    assert 0 < len(chapters) < 10
    assert "over 350 seconds" in story.stop_reason and "MAX_SCRAPE_SECONDS" in story.stop_reason
    assert not story.store.done
    assert not routes["c10"].called


@respx.mock
def test_each_attempt_gets_a_fresh_time_allowance(monkeypatch, tmp_path):
    chain(4)
    monkeypatch.setattr(scraper_module, "_monotonic", FakeClock(step=100))
    with make_story(work_dir=tmp_path, max_scrape_seconds=250) as story:
        list(story.iter_chapters())
    stopped_at = story.chapters_done
    assert stopped_at < 4

    monkeypatch.setattr(scraper_module, "_monotonic", FakeClock(step=1))
    with make_story(work_dir=tmp_path, max_scrape_seconds=250) as story:
        story.download()

    assert story.chapters_done == 4 and story.store.done


@respx.mock
def test_a_time_limit_of_zero_means_no_limit(monkeypatch):
    chain(5)
    monkeypatch.setattr(scraper_module, "_monotonic", FakeClock(step=10_000))

    with make_story(max_scrape_seconds=0) as story:
        assert len(list(story.iter_chapters())) == 5


# --- page size ----------------------------------------------------------------------------


@respx.mock
def test_a_page_over_the_size_limit_is_refused_by_its_declared_length():
    respx.get(BASE + "c1").mock(return_value=httpx.Response(200, content=b"x" * 5000))

    with make_story(max_page_bytes=1000) as story, pytest.raises(PageTooLargeError, match="5000"):
        list(story.iter_chapters())


@respx.mock
def test_a_page_over_the_size_limit_is_refused_when_no_length_is_declared():
    def chunks():
        for _ in range(50):
            yield b"y" * 100

    respx.get(BASE + "c1").mock(side_effect=lambda request: httpx.Response(200, content=chunks()))

    with make_story(max_page_bytes=1000) as story, pytest.raises(PageTooLargeError):
        list(story.iter_chapters())


@respx.mock
def test_the_limit_applies_to_the_decompressed_size():
    """A tiny compressed body that expands enormously must not get through."""
    bomb = gzip.compress(b"a" * 5_000_000)
    assert len(bomb) < 10_000
    respx.get(BASE + "c1").mock(
        return_value=httpx.Response(200, content=bomb, headers={"content-encoding": "gzip"})
    )

    with make_story(max_page_bytes=100_000) as story, pytest.raises(PageTooLargeError):
        list(story.iter_chapters())


@respx.mock
def test_a_page_just_under_the_limit_is_fine():
    body = page("<p>" + "word " * 100 + "</p>")
    respx.get(BASE + "c1").mock(return_value=httpx.Response(200, text=body))

    with make_story(max_page_bytes=len(body.encode()) + 1) as story:
        assert len(list(story.iter_chapters())) == 1


@respx.mock
def test_a_page_limit_of_zero_means_no_limit():
    respx.get(BASE + "c1").mock(
        return_value=httpx.Response(200, text=page("<p>" + "word " * 20_000 + "</p>"))
    )

    with make_story(max_page_bytes=0) as story:
        assert len(list(story.iter_chapters())) == 1


@respx.mock
def test_an_oversized_page_mid_story_fails_but_keeps_the_chapters_so_far(tmp_path):
    mount(c1=page("<p>One.</p>", "c2"))
    respx.get(BASE + "c2").mock(return_value=httpx.Response(200, content=b"z" * 50_000))

    with make_story(work_dir=tmp_path, max_page_bytes=10_000) as story:
        with pytest.raises(PageTooLargeError):
            story.scrape()

    assert story.chapters_done == 1 and not story.store.done  # resumable


@respx.mock
def test_an_oversized_page_is_not_retried():
    route = respx.get(BASE + "c1").mock(return_value=httpx.Response(200, content=b"x" * 5000))

    with make_story(max_page_bytes=1000) as story, pytest.raises(PageTooLargeError):
        story.fetch(BASE + "c1")

    assert route.call_count == 1


# --- configuration ----------------------------------------------------------------------------


@respx.mock
def test_limits_default_to_the_settings(monkeypatch):
    chain(5)
    monkeypatch.setattr(settings, "max_chapters", 2)

    with make_story() as story:
        assert story.max_chapters == 2
        assert len(list(story.iter_chapters())) == 2


def test_the_default_limits_leave_room_for_a_whole_job_inside_the_broker_timeout():
    """A job past the visibility timeout is handed to a second worker."""
    fields = type(settings).model_fields
    scrape = fields["max_scrape_seconds"].default
    convert = fields["conversion_timeout_seconds"].default
    redelivery = fields["broker_visibility_timeout_seconds"].default

    assert scrape + convert < redelivery
