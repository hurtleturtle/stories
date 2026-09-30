"""Scraped chapter HTML must not carry anything active into the ebook."""

import pytest
from bs4 import BeautifulSoup

from story_scraper.sanitize import sanitize


def clean(html: str) -> str:
    """Sanitise `html` (one root element) and return what is left."""
    soup = BeautifulSoup(html, "lxml")
    root = soup.body.find(True, recursive=False)
    result = sanitize(root)
    return str(result) if result is not None else ""


@pytest.mark.parametrize(
    "tag",
    ["script", "style", "iframe", "object", "embed", "applet", "noscript", "template", "frameset"],
)
def test_blocked_elements_are_removed_with_their_content(tag):
    html = f"<div><p>Story.</p><{tag}>payload</{tag}><p>More.</p></div>"

    result = clean(html)

    assert "payload" not in result
    assert f"<{tag}" not in result
    assert "<p>Story.</p><p>More.</p>" in result


@pytest.mark.parametrize("tag", ["base", "link", "meta"])
def test_head_only_elements_are_removed(tag):
    result = clean(f'<div><p>Story.</p><{tag} href="https://evil.test/" content="x"></div>')

    assert f"<{tag}" not in result
    assert "Story." in result


def test_a_blocked_element_nested_in_another_is_handled():
    result = clean("<div><iframe><script>alert(1)</script><p>inner</p></iframe><p>kept</p></div>")

    assert result == "<div><p>kept</p></div>"


def test_a_root_that_is_itself_blocked_leaves_nothing():
    soup = BeautifulSoup("<html><body><script>alert(1)</script></body></html>", "lxml")

    assert sanitize(soup.script) is None


@pytest.mark.parametrize(
    "attribute", ["onclick", "onerror", "onload", "onmouseover", "ONCLICK", "OnError"]
)
def test_event_handler_attributes_are_removed(attribute):
    result = clean(f'<p {attribute}="alert(1)" class="x">Text</p>')

    assert attribute.lower() not in result.lower()
    assert 'class="x"' in result


def test_event_handlers_on_nested_elements_are_removed():
    result = clean('<div><p><img src="a.png" onerror="alert(1)"/></p></div>')

    assert "onerror" not in result
    assert 'src="a.png"' in result


def test_srcdoc_is_removed():
    assert "srcdoc" not in clean('<div srcdoc="<script>alert(1)</script>">x</div>')


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "  javascript:alert(1)",
        "java\tscript:alert(1)",
        "java\nscript:alert(1)",
        "jav&#x09;ascript:alert(1)",
        "\x01javascript:alert(1)",
        "vbscript:msgbox(1)",
    ],
)
def test_script_urls_are_removed_however_they_are_disguised(href):
    result = clean(f'<p><a href="{href}">click</a></p>')

    assert "href" not in result
    assert "click" in result


@pytest.mark.parametrize(
    "href",
    ["https://example.com/next", "http://example.com/", "/chapter-2", "chapter-2", "#top",
     "mailto:a@example.com", "//example.com/x"],
)
def test_ordinary_links_are_kept(href):
    assert f'href="{href}"' in clean(f'<p><a href="{href}">link</a></p>')


def test_other_url_attributes_are_checked_too():
    result = clean(
        '<div><form action="javascript:alert(1)"><button formaction="javascript:alert(2)">'
        'go</button></form><img src="javascript:alert(3)"/><video poster="javascript:alert(4)">'
        "</video></div>"
    )

    assert "javascript" not in result


def test_svg_links_are_checked():
    soup = BeautifulSoup(
        '<html><body><svg><a xlink:href="javascript:alert(1)">'
        "<text>x</text></a></svg></body></html>",
        "lxml",
    )

    sanitize(soup.body.svg)

    assert "javascript" not in str(soup)


def test_data_urls_are_removed_except_for_inline_images():
    result = clean(
        '<div><a href="data:text/html,&lt;script&gt;alert(1)&lt;/script&gt;">a</a>'
        '<img src="data:text/html,x"/>'
        '<img src="data:image/png;base64,iVBORw0KGgo="/></div>'
    )

    assert 'href="data:' not in result
    assert 'src="data:text/html' not in result
    assert 'src="data:image/png;base64,iVBORw0KGgo="' in result


def test_comments_are_removed():
    result = clean(
        "<div><!-- tracking id 42 --><p>Text</p><!--[if IE]><script>x</script><![endif]--></div>"
    )

    assert result == "<div><p>Text</p></div>"


def test_ordinary_prose_markup_is_untouched():
    html = (
        '<div class="chapter-content"><p>He said <em>no</em>, <strong>twice</strong>.</p>'
        '<p><a href="https://example.com/">A link</a> and an <img src="cover.jpg" alt="x"/></p>'
        "<blockquote>Quoted</blockquote><hr/><ul><li>one</li></ul><br/></div>"
    )

    # Compared with the same parse left alone, since the parser normalises
    # things like attribute order whether or not anything is sanitised.
    unsanitised = str(BeautifulSoup(html, "lxml").body.find(True, recursive=False))
    assert clean(html) == unsanitised
    assert "<em>no</em>" in unsanitised and 'href="https://example.com/"' in unsanitised
