"""Failures put into words: what happened to the story and what to do next."""

import httpx
import pytest

from story_scraper.converter import ConversionError
from story_scraper.errors import describe_failure, failure_report, is_bot_challenge
from story_scraper.scraper import ChapterNotFoundError, PageTooLargeError
from story_scraper.urlsafety import UnsafeURLError

URL = "https://novels.example/story/chapter-1"


def status_error(code: int, headers: dict | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", URL)
    response = httpx.Response(code, headers=headers, request=request)
    return httpx.HTTPStatusError(f"{code} for {URL}", request=request, response=response)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (401, "needs a login"),
        (403, "refused the request"),
        (404, "no page at that address"),
        (410, "no page at that address"),
        (429, "rate limiting"),
        (451, "not available from the worker's location"),
        (500, "problems of its own"),
        (503, "problems of its own"),
        (418, "answered 418 I'm a Teapot"),
    ],
)
def test_each_kind_of_http_error_is_explained(code, expected):
    message = describe_failure(status_error(code))

    assert expected in message
    assert "novels.example" in message  # which site
    assert str(code) in message  # and what it actually said


def test_a_status_code_with_no_standard_name_is_still_reported():
    assert "answered 499," in describe_failure(status_error(499))


@pytest.mark.parametrize(
    ("code", "headers"),
    [
        (403, {"cf-mitigated": "challenge"}),
        (403, {"server": "cloudflare"}),
        (503, {"server": "cloudflare"}),
        (403, {"server": "ddos-guard"}),
    ],
)
def test_a_bot_check_is_told_apart_from_the_site_refusing(code, headers):
    message = describe_failure(status_error(code, headers))

    assert "bot check" in message
    assert "Retrying will not help" in message


def test_a_site_merely_served_through_cloudflare_is_not_called_a_bot_check():
    # Cloudflare passes the origin's own 404s and 500s through under its name.
    assert not is_bot_challenge(status_error(404, {"server": "cloudflare"}).response)
    assert not is_bot_challenge(status_error(500, {"server": "cloudflare"}).response)
    assert not is_bot_challenge(status_error(403, {"server": "nginx"}).response)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (httpx.ReadTimeout("timed out"), "did not answer in time"),
        (httpx.ConnectTimeout("timed out"), "did not answer in time"),
        (httpx.ConnectError("Name or service not known"), "Could not connect to"),
        (httpx.TooManyRedirects("too many"), "kept redirecting"),
        (httpx.RemoteProtocolError("peer closed connection"), "connection to"),
    ],
)
def test_network_failures_are_explained(exc, expected):
    exc.request = httpx.Request("GET", URL)

    message = describe_failure(exc)

    assert expected in message and "novels.example" in message


def test_a_network_failure_with_no_request_attached_is_still_explained():
    assert "the site did not answer in time" in describe_failure(httpx.ReadTimeout("timed out"))


def test_selectors_that_match_nothing_point_at_the_template():
    message = describe_failure(ChapterNotFoundError("No elements matched 'div.x'"))

    assert "div.x" in message
    assert "Retry with a different template" in message


def test_other_scraper_failures_are_explained():
    assert "MAX_PAGE_BYTES" in describe_failure(PageTooLargeError("page is 99 bytes"))
    assert "will not fetch" in describe_failure(UnsafeURLError("non-public address"))
    assert "without scraping again" in describe_failure(ConversionError("calibre: boom"))


def test_an_unknown_error_is_left_alone():
    assert describe_failure(RuntimeError("something else")) is None


def test_a_failure_partway_through_says_a_retry_will_resume():
    first_page = describe_failure(status_error(403))
    partway = describe_failure(status_error(403), chapters_done=12)

    assert "carries on from the chapters already scraped" not in first_page
    assert partway.endswith("Retrying carries on from the chapters already scraped.")


def test_the_report_leads_with_the_explanation_then_the_detail():
    report = failure_report(status_error(403), "HTTPStatusError: 403 for " + URL)

    summary, detail = report.split("\n\n", 1)
    assert "refused the request" in summary
    assert detail == "HTTPStatusError: 403 for " + URL


def test_the_report_for_an_unknown_error_leads_with_its_message():
    assert failure_report(RuntimeError("boom"), "Traceback...") == "boom\n\nTraceback..."
    assert failure_report(RuntimeError(), "Traceback...") == "RuntimeError\n\nTraceback..."
