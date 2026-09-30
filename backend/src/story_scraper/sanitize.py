"""Cleaning scraped chapter HTML before it goes into an ebook.

Chapter content comes from arbitrary third-party pages and ends up in a file
the user opens in a browser or an e-reader. This removes everything that can
execute or load active content - scripts, frames, plugins, event handlers,
`javascript:` links - and also the ad and tracking scripts sites embed in
their chapter text. Ordinary prose markup (paragraphs, emphasis, links to
http(s) pages, images) is left alone.
"""

from __future__ import annotations

import re

from bs4 import Comment, Tag

# Removed together with everything inside them.
BLOCKED_TAGS = frozenset(
    {
        "script",
        "style",
        "iframe",
        "frame",
        "frameset",
        "object",
        "embed",
        "applet",
        "noscript",
        "template",
        # Change how the rest of the page is interpreted or where it goes.
        "base",
        "link",
        "meta",
    }
)

# Attributes whose value is a URL that a browser will act on.
URL_ATTRIBUTES = frozenset(
    {"href", "src", "action", "formaction", "poster", "background", "data", "xlink:href"}
)

# Schemes that run code, whatever the tag.
SCRIPT_SCHEMES = ("javascript:", "vbscript:")

# Browsers ignore tabs, newlines and other control characters inside a URL,
# so "jav\tascript:" is still javascript:. Normalise before looking.
_URL_NOISE = re.compile(r"[\x00-\x20\x7f]+")


def _scheme_blocked(tag_name: str, attribute: str, value: str) -> bool:
    normalised = _URL_NOISE.sub("", value).lower()
    if normalised.startswith(SCRIPT_SCHEMES):
        return True
    if normalised.startswith("data:"):
        # Inline images are harmless in <img>; data: anywhere else (an <a>
        # to data:text/html, say) can carry a page of its own.
        is_inline_image = (
            tag_name == "img" and attribute == "src" and normalised.startswith("data:image/")
        )
        return not is_inline_image
    return False


def _clean_attributes(tag: Tag) -> None:
    for name in list(tag.attrs):
        lowered = name.lower()
        if lowered.startswith("on") or lowered == "srcdoc":
            del tag.attrs[name]
            continue
        if lowered in URL_ATTRIBUTES:
            value = tag.attrs[name]
            if isinstance(value, list):
                value = " ".join(value)
            if _scheme_blocked(tag.name.lower(), lowered, str(value)):
                del tag.attrs[name]


def sanitize(root: Tag) -> Tag | None:
    """Clean `root` and everything under it in place.

    Returns `root`, or None if `root` is itself a blocked element (in which
    case it has been removed and there is nothing left to use).
    """
    if root.name.lower() in BLOCKED_TAGS:
        root.decompose()
        return None

    # Materialise the list first: decomposing while iterating skips nodes.
    for tag in list(root.find_all(True)):
        if tag.decomposed:
            continue  # inside a blocked element that was already removed
        if tag.name.lower() in BLOCKED_TAGS:
            tag.decompose()
        else:
            _clean_attributes(tag)

    for comment in root.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    _clean_attributes(root)
    return root
