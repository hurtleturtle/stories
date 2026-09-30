"""The standalone command line."""

from story_scraper.cli import parse_args


def test_author_and_language_can_be_given():
    args = parse_args(["-u", "https://example.com/1", "--author", "Jane Doe", "--language", "en"])

    assert (args.author, args.language) == ("Jane Doe", "en")


def test_author_and_language_default_to_unset():
    args = parse_args(["-u", "https://example.com/1"])

    assert (args.author, args.language) == (None, None)
