"""Core chapter-by-chapter scraper."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from importlib import resources
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from story_scraper.config import StoryConfig

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0"
)
CHAPTER_TITLE_RE = re.compile(
    r"((chapter)?[:\s]*(\d+))?[:\-.\s]*(.*)", flags=re.IGNORECASE
)

ProgressCallback = Callable[[int, str], None]


class ChapterNotFoundError(RuntimeError):
    """Raised when the configured container selector matches nothing."""


class Story:
    """Fetches chapters from a serial and assembles them into one HTML document."""

    def __init__(
        self,
        config: StoryConfig,
        client: httpx.Client | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.config = config
        self.progress = progress or (lambda count, message: None)
        self._owns_client = client is None
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True
        )

        parsed = urlparse(config.url)
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
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
        html = resources.files("story_scraper.assets").joinpath("template.html").read_text()
        return BeautifulSoup(html, features="lxml")

    def fetch(self, url: str, retries: int = 3) -> str:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                response = self.client.get(url)
                response.raise_for_status()
                return response.text
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code == 404:
                    raise
                logger.warning(
                    "Request to %s failed (attempt %d/%d): %s", url, attempt + 1, retries, exc
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "Request to %s failed (attempt %d/%d): %s", url, attempt + 1, retries, exc
                )

        assert last_error is not None
        raise last_error

    def _chapter_title(self, soup: BeautifulSoup) -> Tag:
        heading = soup.new_tag("h2")
        heading["class"] = "chapter-heading"
        title = ""
        chapter_number: str | None = None

        if self.config.detect_title:
            tag = soup.select_one(self.config.detect_title)
            if tag is not None and tag.string:
                match = CHAPTER_TITLE_RE.match(tag.string)
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

    def _next_url(self, soup: BeautifulSoup) -> str | None:
        matches = soup.select(self.config.next_selector)
        if not matches:
            logger.info("Could not locate next-chapter link with %r", self.config.next_selector)
            return None

        href = matches[0].get("href")
        if not href:
            return None
        if isinstance(href, list):
            href = href[0]
        if href.startswith("http"):
            return href
        return self.base_url + href

    def iter_chapters(self) -> Iterator[tuple[int, str]]:
        """Yield (chapter_count, url) for each chapter fetched, starting at 1."""
        url: str | None = self.config.url
        count = 0

        while url:
            page = self.fetch(url)
            soup = BeautifulSoup(page, features="lxml")
            self._append_chapter(soup)
            count += 1
            yield count, url
            if self.config.num_chapters and count >= self.config.num_chapters:
                break
            url = self._next_url(soup)

    def _apply_style(self) -> None:
        style_path = resources.files("story_scraper.assets") / "styles" / self.config.style
        link = self.doc.new_tag("link")
        link["rel"] = "stylesheet"
        link["type"] = "text/css"
        link["href"] = str(style_path)
        assert self.doc.head is not None
        self.doc.head.append(link)

    def _apply_scripts(self) -> None:
        assets_scripts = resources.files("story_scraper.assets") / "scripts"
        for script in self.config.scripts:
            script_path = assets_scripts / script if "/" not in script else Path(script)
            tag = self.doc.new_tag("script")
            tag["src"] = str(script_path)
            assert self.doc.head is not None
            self.doc.head.append(tag)

    def download(self) -> str:
        """Scrape all configured chapters and return the assembled HTML."""
        self._apply_style()
        self._apply_scripts()

        for count, url in self.iter_chapters():
            self.progress(count, url)

        return self.doc.prettify()

    def write(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        html_file = output_dir / f"{self.config.resolved_filename()}.html"
        html_file.write_text(self.download())
        return html_file
