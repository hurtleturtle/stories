"""Artifact filesystem layout."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID

from story_scraper.config import settings


def job_dir(owner_id: UUID, job_id: UUID) -> Path:
    path = Path(settings.story_folder) / str(owner_id) / str(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_dir(owner_id: UUID) -> Path:
    """Where a user's artifacts live. Unlike job_dir, this does not create it."""
    return Path(settings.story_folder) / str(owner_id)


def remove_job_files(owner_id: UUID, job_id: UUID) -> None:
    shutil.rmtree(user_dir(owner_id) / str(job_id), ignore_errors=True)


def remove_user_files(owner_id: UUID) -> None:
    shutil.rmtree(user_dir(owner_id), ignore_errors=True)
