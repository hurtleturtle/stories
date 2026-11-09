"""Turning a failed scrape into something a person can act on.

The scraper raises httpx's own errors (and a few of its own), which say what
happened in terms of the request. `describe_failure` says what it means for
the story: whether the site refused, is down or was not found, and whether
retrying, waiting or changing the template is the thing to do.
"""

from __future__ import annotations

from http import HTTPStatus

import httpx

from story_scraper.converter import ConversionError
from story_scraper.scraper import ChapterNotFoundError, PageTooLargeError
from story_scraper.urlsafety import UnsafeURLError

RESUME_HINT = "Retrying carries on from the chapters already scraped."


def _status_text(code: int) -> str:
    try:
        return f"{code} {HTTPStatus(code).phrase}"
    except ValueError:
        return str(code)


def is_bot_challenge(response: httpx.Response) -> bool:
    """Whether a refusal came from a bot check in front of the site rather than
    the site itself. Cloudflare marks its challenge pages with `cf-mitigated`;
    a 403/503 it serves under its own name is, in practice, one too."""
    if "challenge" in response.headers.get("cf-mitigated", "").lower():
        return True
    served_by = response.headers.get("server", "").lower()
    return response.status_code in (403, 503) and served_by.startswith(
        ("cloudflare", "ddos-guard", "sucuri")
    )


def _describe_status(response: httpx.Response) -> str:
    code = response.status_code
    host = response.request.url.host
    said = f"{host} answered {_status_text(code)}"

    if is_bot_challenge(response):
        return (
            f"{host} is behind a bot check ({_status_text(code)}) that the scraper cannot "
            "pass, so the page was never reached. Retrying will not help while the check "
            "is in place; the site may let requests through at other times, or the story "
            "may be available from another site."
        )
    if code == 401:
        return f"{said}: the page needs a login, which the scraper does not have."
    if code == 403:
        return (
            f"{said}: the site refused the request. Sites do this to block automated "
            "readers or to keep a chapter for logged-in or paying readers. Retrying is "
            "unlikely to help unless the block was temporary."
        )
    if code in (404, 410):
        return f"{said}: there is no page at that address. Check the job's URL."
    if code == 429:
        return (
            f"{said}: the site is rate limiting the scraper and was still doing so after "
            "several attempts. Wait a while before retrying."
        )
    if code == 451:
        return f"{said}: the page is not available from the worker's location."
    if code >= 500:
        return (
            f"{said}: the site is having problems of its own and was still failing after "
            "several attempts. Try again later."
        )
    return f"{said}, which the scraper cannot do anything about."


def _describe_network(exc: httpx.HTTPError) -> str:
    try:
        host = exc.request.url.host
    except RuntimeError:  # raised by httpx when no request is attached
        host = "the site"

    if isinstance(exc, httpx.TimeoutException):
        return f"{host} did not answer in time, on several attempts. Try again later."
    if isinstance(exc, httpx.ConnectError):
        return (
            f"Could not connect to {host}. The address may be wrong, or the site may be "
            "down or unreachable from the worker."
        )
    if isinstance(exc, httpx.TooManyRedirects):
        return f"{host} kept redirecting without ever serving a page."
    if isinstance(exc, httpx.DecodingError):
        return f"{host} sent a page that could not be decoded."
    return f"The connection to {host} failed, on several attempts. Try again later."


def describe_failure(exc: BaseException, chapters_done: int = 0) -> str | None:
    """A plain-language account of why a job failed and what to do about it,
    or None for an error this module knows nothing about.

    `chapters_done` is how many chapters were stored before the failure; with
    any at all, the advice includes that a retry will resume."""
    if isinstance(exc, httpx.HTTPStatusError):
        message = _describe_status(exc.response)
        if chapters_done and exc.response.status_code in (404, 410):
            # Not reachable through the scraper (it ends the story there), but
            # "check the job's URL" would be wrong advice this far in.
            message = message.replace(" Check the job's URL.", "")
    elif isinstance(exc, httpx.HTTPError):
        message = _describe_network(exc)
    elif isinstance(exc, ChapterNotFoundError):
        return (
            "The page was fetched, but the template's selectors found no chapter text on "
            f"it ({exc}). The template probably does not fit this site, or the site served "
            "something other than the chapter (a login or bot-check page). Retry with a "
            "different template, or correct this one and retry with it."
        )
    elif isinstance(exc, PageTooLargeError):
        message = f"A page was too large to scrape: {exc} (MAX_PAGE_BYTES)."
    elif isinstance(exc, UnsafeURLError):
        return f"The scraper will not fetch that address: {exc}."
    elif isinstance(exc, ConversionError):
        return (
            "The story was scraped, but converting it to an ebook failed. The scraped "
            "HTML is under Artifacts. Retrying converts it again without scraping again."
        )
    else:
        return None

    return f"{message} {RESUME_HINT}" if chapters_done else message


def failure_report(exc: BaseException, technical: str, chapters_done: int = 0) -> str:
    """The text stored as a job's error: the plain-language account first, then
    a blank line and the technical detail. Without an account, the exception's
    own message stands in for it."""
    summary = describe_failure(exc, chapters_done) or str(exc) or exc.__class__.__name__
    return f"{summary}\n\n{technical}"
