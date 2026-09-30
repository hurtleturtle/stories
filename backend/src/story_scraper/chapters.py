"""On-disk storage for chapters as they are scraped.

Each chapter is written to its own file the moment it is fetched, and a line
describing it is appended to a manifest. That keeps memory flat however long
the story is, and lets a scrape that was interrupted (a crash, a failed
retry, a deploy) carry on from the last chapter instead of starting again.

Layout of a store directory:

    manifest.jsonl         first line: {"fingerprint": ...}; then one
                           {"n", "url", "sha256", "chapter", "next"} per chapter;
                           finally {"done": true} once the story has ended
    chapter-000001.html    the HTML of chapter 1, and so on

The manifest is append-only, so recording a chapter is one small write rather
than a rewrite of everything so far. The chapter file is always written first
and the manifest line second; a crash between the two leaves a chapter file the
manifest does not mention, which is simply overwritten on resume.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST = "manifest.jsonl"


@dataclass(frozen=True)
class ChapterRecord:
    n: int  # 1-based position in the story
    url: str  # the page it was fetched from
    sha256: str  # hash of the chapter's text, for spotting repeats
    chapter: str  # the number shown in its heading
    next: str | None  # where the following chapter lives, if anywhere


class ChapterStore:
    """The chapters of one story, kept in `directory`.

    `fingerprint` identifies the scrape (start URL and selectors). A store
    left by a different scrape is discarded rather than mixed in.
    """

    def __init__(self, directory: Path, fingerprint: str) -> None:
        self.directory = directory
        self.fingerprint = fingerprint
        self.records: list[ChapterRecord] = []
        self.done = False
        self._hashes: dict[str, int] = {}
        directory.mkdir(parents=True, exist_ok=True)
        self._load()

    # --- what has been stored -------------------------------------------------

    @property
    def count(self) -> int:
        return len(self.records)

    @property
    def last(self) -> ChapterRecord | None:
        return self.records[-1] if self.records else None

    def urls(self) -> set[str]:
        return {record.url for record in self.records}

    def chapter_with_hash(self, sha256: str) -> int | None:
        """Position of the chapter whose text has this hash, if there is one."""
        return self._hashes.get(sha256)

    def fragments(self) -> Iterator[str]:
        """The HTML of every stored chapter, in order, one at a time."""
        for record in self.records:
            yield self._chapter_path(record.n).read_text(encoding="utf-8")

    # --- recording -----------------------------------------------------------

    def add(self, record: ChapterRecord, fragment: str) -> None:
        if record.n != self.count + 1:
            raise ValueError(f"Expected chapter {self.count + 1}, got {record.n}")
        path = self._chapter_path(record.n)
        partial = path.with_name(path.name + ".part")
        partial.write_text(fragment, encoding="utf-8")
        os.replace(partial, path)  # a chapter file is never seen half-written
        self._append(asdict(record))
        self.records.append(record)
        self._hashes.setdefault(record.sha256, record.n)

    def mark_done(self) -> None:
        if not self.done:
            self._append({"done": True})
            self.done = True

    # --- internals -----------------------------------------------------------

    def _chapter_path(self, n: int) -> Path:
        return self.directory / f"chapter-{n:06d}.html"

    @property
    def _manifest_path(self) -> Path:
        return self.directory / MANIFEST

    def _append(self, entry: dict) -> None:
        with self._manifest_path.open("a", encoding="utf-8") as manifest:
            manifest.write(json.dumps(entry) + "\n")

    def _reset(self, reason: str) -> None:
        if reason:
            logger.warning("Discarding stored chapters in %s: %s", self.directory, reason)
        for stale in self.directory.glob("chapter-*"):
            stale.unlink()
        self._manifest_path.unlink(missing_ok=True)
        self.records = []
        self.done = False
        self._hashes = {}
        self._append({"fingerprint": self.fingerprint})

    def _load(self) -> None:
        if not self._manifest_path.exists():
            self._reset("")
            return

        text = self._manifest_path.read_text(encoding="utf-8")
        lines = [line for line in text.split("\n") if line]
        try:
            header = json.loads(lines[0])
        except (IndexError, json.JSONDecodeError):
            self._reset("unreadable manifest")
            return
        if header.get("fingerprint") != self.fingerprint:
            self._reset("it belongs to a different scrape")
            return

        records: list[ChapterRecord] = []
        done = False
        # A missing final newline would make the next append run onto the last line.
        rewrite = not text.endswith("\n")
        for position, line in enumerate(lines[1:], start=1):
            try:
                entry = json.loads(line)
                if entry.get("done") is True:
                    done = True
                    continue
                if done:
                    raise ValueError("chapter recorded after the story ended")
                record = ChapterRecord(**entry)
                if record.n != len(records) + 1:
                    raise ValueError(f"chapter {record.n} out of order")
                if not self._chapter_path(record.n).is_file():
                    raise ValueError(f"chapter file {record.n} is missing")
            except (ValueError, TypeError, AttributeError) as exc:  # incl. JSONDecodeError
                if position == len(lines) - 1:
                    # Only the last line can be a write that was cut short. Drop it.
                    logger.warning("Ignoring an incomplete last manifest entry: %s", exc)
                    rewrite = True
                    break
                self._reset(f"corrupt manifest ({exc})")
                return
            records.append(record)

        self.records = records
        self.done = done
        for record in records:
            self._hashes.setdefault(record.sha256, record.n)

        if rewrite:
            self._rewrite()

    def _rewrite(self) -> None:
        """Rewrite the manifest from what was loaded, dropping a damaged tail
        so the next append starts on a fresh line."""
        partial = self._manifest_path.with_name(MANIFEST + ".part")
        with partial.open("w", encoding="utf-8") as manifest:
            manifest.write(json.dumps({"fingerprint": self.fingerprint}) + "\n")
            for record in self.records:
                manifest.write(json.dumps(asdict(record)) + "\n")
            if self.done:
                manifest.write(json.dumps({"done": True}) + "\n")
        os.replace(partial, self._manifest_path)
