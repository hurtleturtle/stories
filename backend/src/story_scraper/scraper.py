"""Core chapter-by-chapter scraper."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterator
from importlib import resources
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from story_scraper.config import StoryConfig, read_asset
from story_scraper.urlsafety import assert_public_url

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0"
)
CHAPTER_TITLE_RE = re.compile(
    r"((chapter)?[:\s]*(\d+))?[:\-.\s]*(.*)", flags=re.IGNORECASE
)

ProgressCallback = Callable[[int, str], None]

# Worth trying again: the server is struggling or asked us to slow down. Other
# 4xx responses (403, 401, ...) will not change on a retry.
RETRY_STATUSES = frozenset({408, 425, 429}) | frozenset(range(500, 600))
RETRY_BACKOFF_SECONDS = 2.0
MAX_RETRY_WAIT_SECONDS = 60.0


def _sleep(seconds: float) -> None:
    """Indirection so tests can skip the waiting."""
    time.sleep(seconds)


def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
    """Seconds to wait after failed attempt number `attempt` (0-based):
    exponential, unless the server said how long via Retry-After."""
    if response is not None:
        try:
            requested = float(response.headers.get("Retry-After", ""))
        except ValueError:
            pass  # absent, or an HTTP-date, which is not worth parsing here
        else:
            return min(max(requested, 0.0), MAX_RETRY_WAIT_SECONDS)
    return min(RETRY_BACKOFF_SECONDS * 2**attempt, MAX_RETRY_WAIT_SECONDS)


class ChapterNotFoundError(RuntimeError):
    """Raised when the configured container selector matches nothing."""


def _ends_story(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (404, 410)
    return isinstance(exc, ChapterNotFoundError)


class Story:
    """Fetches chapters from a serial and assembles them into one HTML document."""

    def __init__(
        self,
        config: StoryConfig,
        client: httpx.Client | None = None,
        progress: ProgressCallback | None = None,
        allow_private_hosts: bool = False,
    ) -> None:
        """`allow_private_hosts` skips the check that stops the scraper
        fetching internal addresses. It only applies to the client this
        creates; a client passed in is used as given."""
        self.config = config
        self.progress = progress or (lambda count, message: None)
        self._owns_client = client is None
        # Runs for every request, so redirects and next links are covered too.
        hooks = [] if allow_private_hosts else [lambda request: assert_public_url(str(request.url))]
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
            event_hooks={"request": hooks},
        )

        self.current_chapter: int | str = 0
        self.doc = self._load_template()

    def __enter__(self) -> Story:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    @staticmethod
    def _load_template() -> BeautifulSoup:
        template = resources.files("story_scraper.assets") / "template.html"
        html = template.read_text(encoding="utf-8")
        return BeautifulSoup(html, features="lxml")

    def fetch(self, url: str, retries: int = 3) -> str:
        return self.fetch_response(url, retries).text

    def fetch_response(self, url: str, retries: int = 3) -> httpx.Response:
        """GET `url`, retrying server errors, rate limiting and network
        failures with a growing pause. Other client errors fail at once."""
        for attempt in range(retries):
            response: httpx.Response | None = None
            try:
                response = self.client.get(url)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                if response is None or response.status_code not in RETRY_STATUSES:
                    raise
                error: httpx.HTTPError = exc
            except httpx.HTTPError as exc:
                error = exc

            if attempt + 1 == retries:
                raise error
            delay = _retry_delay(attempt, response)
            logger.warning(
                "Request to %s failed (attempt %d/%d): %s; retrying in %.0fs",
                url, attempt + 1, retries, error, delay,
            )
            _sleep(delay)

        raise AssertionError("retries must be at least 1")  # pragma: no cover

    def _chapter_title(self, soup: BeautifulSoup) -> Tag:
        heading = soup.new_tag("h2")
        heading["class"] = "chapter-heading"
        title = ""
        chapter_number: str | None = None

        if self.config.detect_title:
            tag = soup.select_one(self.config.detect_title)
            # get_text rather than .string, which is None for a tag holding
            # any child markup (<h3><span>Chapter 7</span>: The Return</h3>).
            text = " ".join(tag.get_text(" ").split()) if tag is not None else ""
            if text:
                match = CHAPTER_TITLE_RE.match(text)
                if match:
                    chapter_number = match.group(3)
                    title = match.group(4) or ""

        self.current_chapter = chapter_number or int(self.current_chapter) + 1
        text = f"Chapter {self.current_chapter}"
        if title:
            text += f" - {title}"
        heading.string = NavigableString(text)
        return heading

    def _append_chapter(self, soup: BeautifulSoup) -> None:
        matched = soup.select(self.config.container)
        if not matched:
            raise ChapterNotFoundError(
                f"No elements matched container selector {self.config.container!r}"
            )

        chapter = soup.new_tag("div")
        chapter["class"] = "chp"
        chapter.append(self._chapter_title(soup))
        for tag in matched:
            chapter.append(tag)

        assert self.doc.body is not None
        self.doc.body.append(chapter)

    def _next_url(self, soup: BeautifulSoup, page_url: str) -> str | None:
        matches = soup.select(self.config.next_selector)
        if not matches:
            logger.info("Could not locate next-chapter link with %r", self.config.next_selector)
            return None

        href = matches[0].get("href")
        if isinstance(href, list):
            href = href[0]
        href = (href or "").strip()
        # A disabled "next" button is usually href="#" or javascript:void(0).
        if not href or href.startswith("#"):
            return None

        target = urljoin(page_url, href)
        if urlparse(target).scheme not in ("http", "https"):
            return None
        return urldefrag(target).url

    def iter_chapters(self) -> Iterator[tuple[int, str]]:
        """Yield (chapter_count, url) for each chapter fetched, starting at 1.

        Once at least one chapter has been fetched, a "next" link that leads
        nowhere (404/410, or a page without chapter content) is the end of
        the story rather than a failure, so the chapters gathered so far are
        kept. Problems with the first page still raise.
        """
        url: str | None = self.config.url
        count = 0
        seen: set[str] = set()

        while url:
            if url in seen:
                logger.warning("Stopping after %d chapters: %s links back to itself", count, url)
                return
            seen.add(url)
            try:
                response = self.fetch_response(url)
                # Bytes, not .text, so a <meta charset> in the page is honoured
                # when the server sends no charset (or the wrong one).
                soup = BeautifulSoup(
                    response.content, features="lxml", from_encoding=response.charset_encoding
                )
                self._append_chapter(soup)
            except (ChapterNotFoundError, httpx.HTTPStatusError) as exc:
                if count == 0 or not _ends_story(exc):
                    raise
                logger.warning("Stopping after %d chapters: %s", count, exc)
                return

            count += 1
            yield count, url
            if self.config.num_chapters and count >= self.config.num_chapters:
                break
            # Join against where we actually ended up, in case of redirects.
            url = self._next_url(soup, str(response.url))

    def _inline_asset(self, tag_name: str, source: str) -> None:
        """Put an asset's content in the page itself. A link to a file on the
        worker would be dead as soon as the HTML left it."""
        tag = self.doc.new_tag(tag_name)
        if tag_name == "style":
            tag["type"] = "text/css"
        tag.string = source
        assert self.doc.head is not None
        self.doc.head.append(tag)

    def _apply_style(self) -> None:
        css = read_asset("styles", self.config.style)
        self._inline_asset("style", css)

    def _apply_scripts(self) -> None:
        for script in self.config.scripts:
            self._inline_asset("script", read_asset("scripts", script))

    def download(self) -> str:
        """Scrape all configured chapters and return the assembled HTML."""
        self._apply_style()
        self._apply_scripts()

        for count, url in self.iter_chapters():
            self.progress(count, url)

        # Not prettify(): it puts whitespace around inline tags, which
        # readers then show inside words (un<em>believ</em>able).
        return str(self.doc)

    def write(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        html_file = output_dir / f"{self.config.resolved_filename()}.html"
        html_file.write_text(self.download(), encoding="utf-8")
        return html_file
