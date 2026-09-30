"""ebook-convert is run as a subprocess; a fake stands in for Calibre."""

import stat
from pathlib import Path

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
    assert "--title=My Book" in result.read_text()


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


# --- what Calibre is asked to do -------------------------------------------------


def recording_calibre(tmp_path, monkeypatch):
    """A fake ebook-convert that writes the arguments it received, NUL-separated,
    so nothing about them (spaces, newlines, quotes) is lost. Returns a function
    that reads them back."""
    install_fake_calibre(
        tmp_path,
        monkeypatch,
        'printf \'%s\\0\' "$@" > "$(dirname "$0")/args.bin"\n: > "$2"\n',
    )

    def received() -> list[str]:
        raw = (tmp_path / "bin" / "args.bin").read_bytes().decode("utf-8")
        return raw.split("\0")[:-1]

    return received


def run(tmp_path, **kwargs) -> Path:
    return convert(tmp_path / "book.html", tmp_path / "out" / "book.epub", **kwargs)


def test_calibre_is_given_the_input_output_title_and_an_explicit_table_of_contents(
    tmp_path, monkeypatch
):
    received = recording_calibre(tmp_path, monkeypatch)

    run(tmp_path, title="My Book")

    assert received() == [
        str(tmp_path / "book.html"),
        str(tmp_path / "out" / "book.epub"),
        "--title=My Book",
        "--linearize-tables",
        "--level1-toc=//h:h2[@class='chapter-heading']",
    ]


def test_an_author_and_language_are_passed_when_given(tmp_path, monkeypatch):
    received = recording_calibre(tmp_path, monkeypatch)

    run(tmp_path, title="T", authors="Jane Doe & John Roe", language="en-GB")

    args = received()
    assert "--authors=Jane Doe & John Roe" in args
    assert "--language=en-GB" in args


@pytest.mark.parametrize("value", [None, ""])
def test_an_absent_or_empty_author_and_language_are_left_out(tmp_path, monkeypatch, value):
    received = recording_calibre(tmp_path, monkeypatch)

    run(tmp_path, title="T", authors=value, language=value)

    assert not [a for a in received() if a.startswith(("--authors", "--language"))]


@pytest.mark.parametrize("value", ["--output-profile=evil", "-x", "--"])
def test_a_value_that_looks_like_an_option_stays_a_value(tmp_path, monkeypatch, value):
    """Joined to its option with "=", so it cannot be read as an option itself."""
    received = recording_calibre(tmp_path, monkeypatch)

    run(tmp_path, title=value, authors=value, language=value)

    args = received()
    assert f"--title={value}" in args
    assert f"--authors={value}" in args
    assert f"--language={value}" in args
    assert value not in args  # never on its own


def test_awkward_characters_reach_calibre_untouched(tmp_path, monkeypatch):
    received = recording_calibre(tmp_path, monkeypatch)
    title = "It's \"quoted\" $HOME `id` ; rm -rf / \n new line 转生"

    run(tmp_path, title=title, authors=title)

    args = received()
    assert f"--title={title}" in args and f"--authors={title}" in args


def test_the_toc_xpath_selects_exactly_the_headings_the_scraper_writes():
    """The table of contents is built from this expression, so it has to keep
    matching what the scraper emits for a chapter heading."""
    import httpx
    import respx
    from lxml import html as lxml_html
    from sitehelpers import BASE, mount, page

    from story_scraper.config import StoryConfig
    from story_scraper.converter import CHAPTER_TOC_XPATH
    from story_scraper.scraper import Story

    with respx.mock:
        mount(
            c1=page("<p>One.</p>", "c2", title="Chapter 1: A"),
            c2=page("<h2>Not a chapter heading</h2><p>Two.</p>", "c3", title="Chapter 2: B"),
            c3=page("<p>Three.</p>", title="Chapter 3: C"),
        )
        config = StoryConfig(
            url=BASE + "c1",
            container="div.chapter-content",
            next_selector="a#next_chap",
            detect_title="span.title",
        )
        with Story(config) as story:
            document = lxml_html.fromstring(story.download())
    assert httpx  # (imported for respx)

    # Calibre's dialect names the XHTML namespace as "h:"; plain lxml HTML has none.
    matches = document.xpath(CHAPTER_TOC_XPATH.replace("h:", ""))

    assert [m.text_content() for m in matches] == [
        "Chapter 1 - A",
        "Chapter 2 - B",
        "Chapter 3 - C",
    ]
