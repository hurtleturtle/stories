"""Wrapper around Calibre's ebook-convert."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class ConversionError(RuntimeError):
    pass


DEFAULT_TIMEOUT_SECONDS = 30 * 60

# Where each chapter starts, for the ebook's table of contents. Calibre's XPath
# dialect: `h:` is the XHTML namespace. This must match the heading the scraper
# writes (an <h2 class="chapter-heading">); without it Calibre guesses.
CHAPTER_TOC_XPATH = "//h:h2[@class='chapter-heading']"


def convert(
    html_file: Path,
    output_file: Path,
    title: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    authors: str | None = None,
    language: str | None = None,
) -> Path:
    if shutil.which("ebook-convert") is None:
        raise ConversionError("ebook-convert (Calibre) is not installed or not on PATH")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Values are joined to their option with "=", so one that starts with "-"
        # can never be taken for an option of its own.
        command = [
            "ebook-convert",
            str(html_file),
            str(output_file),
            f"--title={title}",
            "--linearize-tables",
            f"--level1-toc={CHAPTER_TOC_XPATH}",
        ]
        if authors:
            command.append(f"--authors={authors}")
        if language:
            command.append(f"--language={language}")
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(f"ebook-convert did not finish within {timeout:.0f}s") from exc
    if result.returncode != 0:
        raise ConversionError(result.stderr or result.stdout)

    return output_file
