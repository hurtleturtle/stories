"""Wrapper around Calibre's ebook-convert."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class ConversionError(RuntimeError):
    pass


def convert(html_file: Path, output_file: Path, title: str) -> Path:
    if shutil.which("ebook-convert") is None:
        raise ConversionError("ebook-convert (Calibre) is not installed or not on PATH")

    output_file.parent.mkdir(parents=True, exist_ok=True)
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
    )
    if result.returncode != 0:
        raise ConversionError(result.stderr or result.stdout)

    return output_file
