"""Three-layer config resolution: defaults -> template -> explicit overrides."""

from __future__ import annotations

from typing import Any

from story_scraper.config import StoryConfig

_TEMPLATE_KEY_ALIASES = {"next": "next_selector", "type": "ebook_type"}


def _normalize(template: dict[str, Any]) -> dict[str, Any]:
    return {_TEMPLATE_KEY_ALIASES.get(k, k): v for k, v in template.items() if k != "verbosity"}


def resolve_config(
    url: str,
    template: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> StoryConfig:
    """Build a StoryConfig from a base URL, an optional template dict, and
    explicit overrides. Overrides always win; template values fill in
    anything the overrides did not explicitly set; StoryConfig field
    defaults fill in the rest.
    """
    merged: dict[str, Any] = {"url": url}
    if template:
        merged.update(_normalize(template))
    if overrides:
        merged.update({k: v for k, v in overrides.items() if v is not None})

    return StoryConfig(**merged)
