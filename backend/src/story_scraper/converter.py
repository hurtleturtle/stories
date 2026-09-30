"""Wrapper around Calibre's ebook-convert."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class ConversionError(RuntimeError):
    pass


DEFAULT_TIMEOUT_SECONDS = 30 * 60


def convert(
    html_file: Path, output_file: Path, title: str, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> Path:
    if shutil.which("ebook-convert") is None:
        raise ConversionError("ebook-convert (Calibre) is not installed or not on PATH")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [
                "ebook-convert",
                str(html_file),
                str(output_file),
                "--title",
                title,
                "--linearize-tables",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(f"ebook-convert did not finish within {timeout:.0f}s") from exc
    if result.returncode != 0:
        raise ConversionError(result.stderr or result.stdout)

    return output_file
