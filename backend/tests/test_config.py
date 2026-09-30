"""Filenames and ebook types derived from user input end up in file paths."""

import httpx
import pytest
import respx
from pydantic import ValidationError

from story_scraper.config import StoryConfig, safe_filename


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("My Book", "My_Book"),
        ("Fate/Zero", "FateZero"),
        ("a\\b:c*d?e\"f<g>h|i", "abcdefghi"),
        ("../escaped", "escaped"),
        ("../../../etc/passwd", "etcpasswd"),
        ("..", "book"),
        ("...", "book"),
        (".hidden", "hidden"),
        ("", "book"),
        ("   ", "book"),
        ("/", "book"),
        ("tab\tand\nnewline", "tab_and_newline"),
        ("nul\x00byte", "nulbyte"),
        ("trailing dot.", "trailing_dot"),
        ("Café 転生", "Café_転生"),
    ],
)
def test_safe_filename(title, expected):
    assert safe_filename(title) == expected


def test_safe_filename_caps_length_in_bytes_without_splitting_a_character():
    name = safe_filename("転" * 500)

    assert len(name.encode("utf-8")) <= 200
    assert set(name) == {"転"}


def test_resolved_filename_prefers_an_explicit_filename_and_sanitises_it():
    config = StoryConfig(url="https://example.com/1", title="Ignored", filename="../../x/y")

    assert config.resolved_filename() == "xy"


def test_resolved_filename_falls_back_when_the_title_has_nothing_usable():
    assert StoryConfig(url="https://example.com/1", title="///").resolved_filename() == "book"


@pytest.mark.parametrize("value", ["../epub", "epub/../../x", "ep ub", "", "epub --evil", "a" * 11])
def test_ebook_type_rejects_anything_that_could_carry_a_path_or_option(value):
    with pytest.raises(ValidationError):
        StoryConfig(url="https://example.com/1", ebook_type=value)


@pytest.mark.parametrize(
    ("value", "expected"), [("epub", "epub"), ("MOBI", "mobi"), (" azw3 ", "azw3")]
)
def test_ebook_type_is_normalised(value, expected):
    assert StoryConfig(url="https://example.com/1", ebook_type=value).ebook_type == expected


@respx.mock
@pytest.mark.parametrize("title", ["Fate/Zero", "../escaped", "a/../../b", ".."])
def test_write_keeps_the_file_inside_the_output_directory(tmp_path, title):
    from story_scraper.scraper import Story

    respx.get("https://example.com/1").mock(
        return_value=httpx.Response(200, text='<div class="chapter-content"><p>x</p></div>')
    )
    output_dir = tmp_path / "job"

    with Story(StoryConfig(url="https://example.com/1", title=title)) as story:
        written = story.write(output_dir)

    assert written.parent == output_dir
    assert written.read_text().count('class="chp"') == 1
    assert [p.name for p in tmp_path.iterdir()] == ["job"]
