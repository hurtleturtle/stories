"""Filenames and ebook types derived from user input end up in file paths."""

import httpx
import pytest
import respx
from pydantic import ValidationError

from story_scraper.config import (
    EBOOK_TYPES,
    StoryConfig,
    asset_names,
    read_asset,
    safe_filename,
)


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


# --- bundled assets --------------------------------------------------------


def test_the_bundled_assets_are_listed():
    assert "white-style.css" in asset_names("styles")
    assert asset_names("scripts") == ["scroll_tracker.js"]


@pytest.mark.parametrize(
    ("kind", "name"),
    [
        ("styles", "../styles/white-style.css"),
        ("styles", "/etc/passwd"),
        ("styles", "styles/white-style.css"),
        ("styles", "missing.css"),
        ("scripts", "../../scraper.py"),
        ("scripts", "white-style.css"),
    ],
)
def test_read_asset_only_reads_bundled_files_by_name(kind, name):
    with pytest.raises(ValueError, match="Unknown"):
        read_asset(kind, name)


@pytest.mark.parametrize("style", ["../../etc/passwd", "/etc/passwd", "missing.css", ""])
def test_style_must_be_a_bundled_stylesheet(style):
    with pytest.raises(ValidationError, match="available"):
        StoryConfig(url="https://example.com/1", style=style)


@pytest.mark.parametrize("script", ["/etc/passwd", "../x.js", "scripts/scroll_tracker.js"])
def test_scripts_must_be_bundled_scripts(script):
    with pytest.raises(ValidationError):
        StoryConfig(url="https://example.com/1", scripts=[script])


def test_bundled_style_and_script_are_accepted():
    config = StoryConfig(
        url="https://example.com/1", style="black-style.css", scripts=["scroll_tracker.js"]
    )

    assert config.style == "black-style.css"


# --- ebook types -------------------------------------------------------------


@pytest.mark.parametrize("value", EBOOK_TYPES)
def test_every_supported_ebook_type_is_accepted(value):
    assert StoryConfig(url="https://example.com/1", ebook_type=value).ebook_type == value


@pytest.mark.parametrize("value", ["docx", "txt", "xyz", "epub2", "mobi.exe", "fb2", "html"])
def test_ebook_types_outside_the_supported_list_are_rejected_with_the_choices(value):
    with pytest.raises(ValidationError, match="choose one of: epub, mobi, azw3, pdf"):
        StoryConfig(url="https://example.com/1", ebook_type=value)


def test_the_supported_types_are_what_kindle_will_take():
    from app.services.email import SENDABLE_KINDS

    assert SENDABLE_KINDS == EBOOK_TYPES
