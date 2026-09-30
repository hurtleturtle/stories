"""Reading chapter headings: "Chapter One" and "1984 Revisited" used to come
out wrong ("Chapter 1 - Chapter One", chapter number 1984)."""

import httpx
import pytest
import respx
from bs4 import BeautifulSoup
from sitehelpers import BASE, mount, page

from story_scraper.config import StoryConfig
from story_scraper.scraper import Story


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Chapter number and title, in the shapes sites use.
        ("Chapter 5: A New Beginning", ("5", "A New Beginning", None)),
        ("Chapter 5 - A New Beginning", ("5", "A New Beginning", None)),
        ("Chapter 5 A New Beginning", ("5", "A New Beginning", None)),
        ("Chapter 5. A New Beginning", ("5", "A New Beginning", None)),
        ("Chapter 5) A New Beginning", ("5", "A New Beginning", None)),
        ("Chapter 5 – A New Beginning", ("5", "A New Beginning", None)),
        ("Chapter 5 : A New Beginning", ("5", "A New Beginning", None)),
        ("chapter 12 - The Return", ("12", "The Return", None)),
        ("CHAPTER 7. Seven", ("7", "Seven", None)),
        ("Ch. 9: Nine", ("9", "Nine", None)),
        ("Ch 9 Nine", ("9", "Nine", None)),
        ("Chapter 5", ("5", "", None)),
        ("Chapter5: X", ("5", "X", None)),
        # Decimals: an interlude between chapters 5 and 6.
        ("Chapter 5.5: Interlude", ("5.5", "Interlude", None)),
        ("Chapter 5.5", ("5.5", "", None)),
        # After the word "chapter" a number is a chapter number, even a big one.
        ("Chapter 1984 Revisited", ("1984", "Revisited", None)),
        # A bare number counts only when a separator (or the end) follows it.
        ("12: Title", ("12", "Title", None)),
        ("12. Title", ("12", "Title", None)),
        ("12 - Title", ("12", "Title", None)),
        ("12) Title", ("12", "Title", None)),
        ("12 — Title", ("12", "Title", None)),
        ("12", ("12", "", None)),
        ("3.5: Between", ("3.5", "Between", None)),
        ("1984 Revisited", (None, "1984 Revisited", None)),
        ("12 Angry Men", (None, "12 Angry Men", None)),
        ("2001: A Space Odyssey", ("2001", "A Space Odyssey", None)),  # ambiguous; separator wins
        # Already a heading, with the number in words or numerals we do not parse.
        ("Chapter One", (None, "", "Chapter One")),
        ("Chapter One: The Beginning", (None, "", "Chapter One: The Beginning")),
        ("Chapter IV: The End", (None, "", "Chapter IV: The End")),
        ("Chapter 5A", (None, "", "Chapter 5A")),
        ("chapter twenty", (None, "", "chapter twenty")),
        # Not headings at all, even though they start with the same letters.
        ("Chapterhouse Dune", (None, "Chapterhouse Dune", None)),
        ("Chase Scene", (None, "Chase Scene", None)),
        ("Prologue", (None, "Prologue", None)),
        ("The 5th Wave", (None, "The 5th Wave", None)),
    ],
)
def test_headings_are_read_as_number_title_or_verbatim(text, expected):
    assert Story._parse_heading(text) == expected


def heading_for(detected: str | None) -> str:
    """The heading a one-chapter story gets when its page says `detected`."""
    with respx.mock:
        respx.get(BASE + "c1").mock(
            return_value=httpx.Response(200, text=page("<p>Body.</p>", title=detected))
        )
        config = StoryConfig(
            url=BASE + "c1",
            container="div.chapter-content",
            next_selector="a#next_chap",
            detect_title="span.title",
        )
        with Story(config) as story:
            html = story.download()
    return BeautifulSoup(html, "lxml").select_one("h2.chapter-heading").text


@pytest.mark.parametrize(
    ("detected", "heading"),
    [
        ("Chapter 5: A New Beginning", "Chapter 5 - A New Beginning"),
        ("Ch. 9: Nine", "Chapter 9 - Nine"),
        ("Chapter 5.5: Interlude", "Chapter 5.5 - Interlude"),
        ("12. Title", "Chapter 12 - Title"),
        ("Chapter 12", "Chapter 12"),
        ("Chapter One", "Chapter One"),  # was "Chapter 1 - Chapter One"
        ("Chapter IV: The End", "Chapter IV: The End"),
        ("1984 Revisited", "Chapter 1 - 1984 Revisited"),  # was chapter 1984
        ("12 Angry Men", "Chapter 1 - 12 Angry Men"),
        ("Prologue", "Chapter 1 - Prologue"),
        ("Chapterhouse Dune", "Chapter 1 - Chapterhouse Dune"),
        (None, "Chapter 1"),  # nothing found to read
    ],
)
def test_the_stored_heading(detected, heading):
    assert heading_for(detected) == heading


@respx.mock
def test_untitled_chapters_carry_on_from_the_last_number():
    mount(
        c1=page("<p>a</p>", "c2", title="Chapter 5.5: Interlude"),
        c2=page("<p>b</p>", "c3"),  # int(5.5) + 1
        c3=page("<p>c</p>", "c4", title="Chapter One"),  # a heading with no parsed number
        c4=page("<p>d</p>", "c5"),
        c5=page("<p>e</p>"),
    )
    config = StoryConfig(
        url=BASE + "c1",
        container="div.chapter-content",
        next_selector="a#next_chap",
        detect_title="span.title",
    )

    with Story(config) as story:
        html = story.download()

    headings = [h.text for h in BeautifulSoup(html, "lxml").select("h2.chapter-heading")]
    assert headings == [
        "Chapter 5.5 - Interlude",
        "Chapter 6",  # int(5.5) + 1
        "Chapter One",  # shown as the site wrote it, but still the 7th chapter...
        "Chapter 8",  # ...so the count carries on from 7
        "Chapter 9",
    ]
