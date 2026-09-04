"""Artifact filesystem layout."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from story_scraper.config import settings


def job_dir(owner_id: UUID, job_id: UUID) -> Path:
    path = Path(settings.story_folder) / str(owner_id) / str(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path
