"""Core chapter-by-chapter scraper."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import tempfile
import time
from collections.abc import Callable, Iterator
from importlib import resources
from pathlib import Path
from typing import TextIO
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from story_scraper.chapters import ChapterRecord, ChapterStore
from story_scraper.config import StoryConfig, read_asset
from story_scraper.sanitize import sanitize
from story_scraper.urlsafety import assert_public_url

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0"
)
# How a scraped chapter heading is read. Numbers may be decimals ("Chapter 5.5",
# an interlude). Separators between the number and the title are any of : - . )
_NUMBER = r"\d+(?:\.\d+)?"
_SEPARATORS = r"[:\-\u2013\u2014.)]"
# "Chapter 12: Title", "Ch. 12 - Title", "chapter 12 Title" - the word says it is a chapter.
PREFIXED_HEADING_RE = re.compile(
    rf"^(?:chapter|ch\.?)\s*({_NUMBER})\b\s*{_SEPARATORS}*\s*(.*)$", flags=re.IGNORECASE
)
# "12: Title", "12. Title", "12 - Title" or just "12". A bare number counts only when
# a separator (or the end) follows it: "1984 Revisited" is a title, not chapter 1984.
BARE_HEADING_RE = re.compile(rf"^({_NUMBER})\s*(?:{_SEPARATORS}+\s*|$)(.*)$")
# "Chapter One", "Chapter IV: The End": already a heading, with a number in words.
WORDED_HEADING_RE = re.compile(r"^(?:chapter|ch\.?)\b", flags=re.IGNORECASE)

ProgressCallback = Callable[[int, str], None]

# A chapter with none of these and no text has nothing in it.
MEDIA_TAGS = ["img", "picture", "svg", "video", "audio"]

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
    """Fetches the chapters of a serial and assembles them into one HTML document.

    Chapters are written to `work_dir` as they are fetched, not held in memory,
    and the final document is streamed from those files. If `work_dir` already
    holds the chapters of an earlier, interrupted scrape of the same story, the
    scrape carries on after the last one. Without a `work_dir` a temporary one
    is used and removed on close.
    """

    def __init__(
        self,
        config: StoryConfig,
        client: httpx.Client | None = None,
        progress: ProgressCallback | None = None,
        allow_private_hosts: bool = False,
        work_dir: Path | None = None,
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

        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        if work_dir is None:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="story-chapters-")
            work_dir = Path(self._temp_dir.name)
        self.store = ChapterStore(work_dir, self._fingerprint())

        last = self.store.last
        self.current_chapter: int | str = last.chapter if last else 0
        # Why the story ended early, if it did: a dead link, a repeated page.
        self.stop_reason: str | None = None

    @property
    def chapters_done(self) -> int:
        """Chapters already stored - after a resume, the ones from before."""
        return self.store.count

    def __enter__(self) -> Story:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()
        if self._temp_dir is not None:
            self._temp_dir.cleanup()

    def _fingerprint(self) -> str:
        """Identifies what is being scraped, so stored chapters are only reused
        for the same story read the same way."""
        identity = [
            self.config.url,
            self.config.container,
            self.config.next_selector,
            self.config.detect_title,
        ]
        return hashlib.sha256(json.dumps(identity).encode("utf-8")).hexdigest()

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

    @staticmethod
    def _parse_heading(text: str) -> tuple[str | None, str, str | None]:
        """Read a detected chapter heading: (number, title, verbatim).

        `number` is a chapter number found in the text, `title` what follows it,
        and `verbatim` the whole text when it is a heading in its own right that
        this cannot pick a number out of ("Chapter One"). At most one of `number`
        and `verbatim` is set; with neither, the text is just a title."""
        for pattern in (PREFIXED_HEADING_RE, BARE_HEADING_RE):
            match = pattern.match(text)
            if match:
                return match.group(1), match.group(2).strip(), None
        if WORDED_HEADING_RE.match(text):
            return None, "", text
        return None, text, None

    def _chapter_title(self, soup: BeautifulSoup) -> Tag:
        heading = soup.new_tag("h2")
        heading["class"] = "chapter-heading"
        number: str | None = None
        title = ""
        verbatim: str | None = None

        if self.config.detect_title:
            tag = soup.select_one(self.config.detect_title)
            # get_text rather than .string, which is None for a tag holding
            # any child markup (<h3><span>Chapter 7</span>: The Return</h3>).
            text = " ".join(tag.get_text(" ").split()) if tag is not None else ""
            if text:
                number, title, verbatim = self._parse_heading(text)

        # Untitled chapters continue from the last one. Int-of-float so that an
        # interlude numbered 5.5 is followed by 6.
        self.current_chapter = number or int(float(self.current_chapter)) + 1
        if verbatim:
            heading.string = NavigableString(verbatim)
        else:
            text = f"Chapter {self.current_chapter}"
            if title:
                text += f" - {title}"
            heading.string = NavigableString(text)
        return heading

    def _chapter_content(self, soup: BeautifulSoup) -> list[Tag]:
        """The sanitised elements holding this page's chapter text, still in place.

        Sanitising comes first so that what is hashed and stored is the story
        only: scripts and ads are neither kept nor able to make one copy of a
        chapter differ from another.
        """
        selector = self.config.container
        matched = soup.select(selector)
        if not matched:
            raise ChapterNotFoundError(f"No elements matched container selector {selector!r}")

        content = [tag for tag in matched if not tag.decomposed and sanitize(tag) is not None]
        if not any(self._has_content(tag) for tag in content):
            # e.g. only scripts, or text the site fills in with JavaScript.
            raise ChapterNotFoundError(f"Nothing usable in the elements matching {selector!r}")
        return content

    @staticmethod
    def _media(tag: Tag) -> list[Tag]:
        """Images and the like in `tag`, including `tag` itself if it is one."""
        found = [tag] if tag.name in MEDIA_TAGS else []
        return found + tag.find_all(MEDIA_TAGS)

    @classmethod
    def _has_content(cls, tag: Tag) -> bool:
        """Text, or pictures: a chapter of images alone is still a chapter."""
        return bool(tag.get_text(strip=True)) or bool(cls._media(tag))

    @classmethod
    def _content_hash(cls, content: list[Tag]) -> str:
        """Hash of what the chapter says - its text and which pictures it shows,
        but not its heading, markup or whitespace - so the same chapter
        reached under another URL matches. Pictures count so that chapters
        made of images alone, which have no text, are not all "the same"."""
        text = " ".join(" ".join(tag.get_text(" ") for tag in content).split())
        pictures = [
            str(media.get("src") or media.get("data-src") or "")
            for tag in content
            for media in cls._media(tag)
        ]
        return hashlib.sha256("\n".join([text, *pictures]).encode("utf-8")).hexdigest()

    def _build_chapter(self, soup: BeautifulSoup, content: list[Tag]) -> tuple[str, str]:
        """Assemble the stored chapter: (html, number shown in its heading).

        Only for chapters that are going to be kept: this numbers the heading,
        which advances the running chapter count."""
        # Read while the page is still whole: the title element can sit inside
        # the content, which is about to be moved out of the page.
        heading = self._chapter_title(soup)

        chapter = soup.new_tag("div")
        chapter["class"] = "chp"
        chapter.append(heading)
        for tag in content:
            chapter.append(tag)
        return str(chapter), str(self.current_chapter)

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

    def _limit_reached(self, count: int) -> bool:
        return bool(self.config.num_chapters) and count >= (self.config.num_chapters or 0)

    def _stop(self, count: int, detail: str) -> None:
        self.stop_reason = f"Stopped after {count} chapters: {detail}"
        logger.warning(self.stop_reason)

    def iter_chapters(self) -> Iterator[tuple[int, str]]:
        """Fetch and store the chapters, yielding (chapter_count, url) for each
        as it is stored. A resumed scrape carries on counting from the chapters
        already stored; a finished one yields nothing.

        The story ends when the "next" link runs out, `num_chapters` is
        reached, or the next page:
          - was already fetched (a link back to an earlier chapter),
          - has the same text as an earlier chapter, however it was reached
            (a site that keeps serving its last page under new URLs), or
          - is a 404/410 or has no chapter content.
        The last three are noted in `stop_reason`. Problems with the first
        page, and other errors partway through, still raise.
        """
        store = self.store
        if store.done:
            return  # nothing to do, and the reason it ended is still worth keeping

        self.stop_reason = None
        count = store.count
        url = store.last.next if store.last else self.config.url
        seen = store.urls()

        while url and not self._limit_reached(count):
            if url in seen:
                self._stop(count, f"{url} was already fetched, so the story links back on itself")
                break
            seen.add(url)
            try:
                response = self.fetch_response(url)
                # Bytes, not .text, so a <meta charset> in the page is honoured
                # when the server sends no charset (or the wrong one).
                soup = BeautifulSoup(
                    response.content, features="lxml", from_encoding=response.charset_encoding
                )
                # Before the chapter is taken out of the page, which can remove
                # a link that sits inside it. Joined against where we actually
                # ended up, in case of redirects.
                next_url = self._next_url(soup, str(response.url))
                content = self._chapter_content(soup)
            except (ChapterNotFoundError, httpx.HTTPStatusError) as exc:
                if count == 0 or not _ends_story(exc):
                    raise
                self._stop(count, str(exc))
                break

            # Hash and compare before anything is numbered, built or stored.
            digest = self._content_hash(content)
            repeat_of = store.chapter_with_hash(digest)
            if repeat_of is not None:
                self._stop(count, f"{url} has the same text as chapter {repeat_of}")
                break

            fragment, label = self._build_chapter(soup, content)
            count += 1
            record = ChapterRecord(n=count, url=url, sha256=digest, chapter=label, next=next_url)
            store.add(record, fragment)
            yield count, url
            url = next_url

        store.mark_done()

    def scrape(self) -> None:
        """Fetch every remaining chapter, reporting each to `progress`."""
        for count, url in self.iter_chapters():
            self.progress(count, url)

    @staticmethod
    def _inline_asset(doc: BeautifulSoup, tag_name: str, source: str) -> None:
        """Put an asset's content in the page itself. A link to a file on the
        worker would be dead as soon as the HTML left it."""
        tag = doc.new_tag(tag_name)
        if tag_name == "style":
            tag["type"] = "text/css"
        tag.string = source
        assert doc.head is not None
        doc.head.append(tag)

    def _shell(self) -> tuple[str, str]:
        """The document around the chapters: everything up to, and from,
        the closing </body>."""
        doc = self._load_template()
        self._inline_asset(doc, "style", read_asset("styles", self.config.style))
        for script in self.config.scripts:
            self._inline_asset(doc, "script", read_asset("scripts", script))

        # Not prettify(): it puts whitespace around inline tags, which
        # readers then show inside words (un<em>believ</em>able).
        before, closing, after = str(doc).rpartition("</body>")
        if not closing:
            raise RuntimeError("The HTML template has no </body>")
        return before, closing + after

    def assemble(self, out: TextIO) -> None:
        """Write the finished document to `out`, one stored chapter at a time."""
        before, after = self._shell()
        out.write(before)
        for fragment in self.store.fragments():
            out.write(fragment)
            out.write("\n")
        out.write(after)

    def download(self) -> str:
        """Scrape all configured chapters and return the assembled HTML."""
        self.scrape()
        buffer = io.StringIO()
        self.assemble(buffer)
        return buffer.getvalue()

    def write(self, output_dir: Path) -> Path:
        """Scrape, then write the document to `output_dir`; returns the file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        html_file = output_dir / f"{self.config.resolved_filename()}.html"
        self.scrape()
        partial = html_file.with_name(html_file.name + ".part")
        with partial.open("w", encoding="utf-8") as out:
            self.assemble(out)
        partial.replace(html_file)  # never leave a half-written document behind
        return html_file
