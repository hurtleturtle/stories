"""Job config resolution, shared by the create and retry endpoints."""

from __future__ import annotations

from app.models import Template
from story_scraper.config import StoryConfig
from story_scraper.resolve import resolve_config


def build_job_config(url: str, template: Template | None, overrides: dict) -> StoryConfig:
    template_dict = {}
    if template is not None:
        template_dict = {
            "container": template.container,
            "next_selector": template.next_selector,
            "detect_title": template.detect_title,
            "style": template.style,
            "scripts": template.scripts,
            "ebook_type": template.ebook_type,
        }

    return resolve_config(url, template_dict, overrides)
