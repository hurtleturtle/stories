"""ebook-convert is run as a subprocess; a fake stands in for Calibre."""

import stat

import pytest

from story_scraper.converter import ConversionError, convert


def install_fake_calibre(tmp_path, monkeypatch, script: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "ebook-convert"
    exe.write_text("#!/bin/sh\n" + script)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")


def test_a_successful_conversion_returns_the_output_path(tmp_path, monkeypatch):
    install_fake_calibre(tmp_path, monkeypatch, 'echo "$@" > "$2"\n')
    html = tmp_path / "book.html"
    html.write_text("<html/>")

    result = convert(html, tmp_path / "out" / "book.epub", "My Book")

    assert result == tmp_path / "out" / "book.epub"
    assert "--title My Book" in result.read_text()


def test_a_calibre_error_is_reported_with_its_message(tmp_path, monkeypatch):
    install_fake_calibre(tmp_path, monkeypatch, 'echo "bad input" >&2\nexit 1\n')

    with pytest.raises(ConversionError, match="bad input"):
        convert(tmp_path / "book.html", tmp_path / "book.epub", "t")


def test_a_hung_conversion_is_killed_and_reported(tmp_path, monkeypatch):
    install_fake_calibre(tmp_path, monkeypatch, "exec sleep 30\n")

    with pytest.raises(ConversionError, match="did not finish within 1s"):
        convert(tmp_path / "book.html", tmp_path / "book.epub", "t", timeout=1)


def test_a_missing_calibre_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(ConversionError, match="not installed"):
        convert(tmp_path / "book.html", tmp_path / "book.epub", "t")
