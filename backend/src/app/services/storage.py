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


def stored_path(path: Path) -> str:
    """How an artifact's location is recorded: relative to the artifact folder
    when it is inside it, so the folder can be moved or remounted without
    breaking every recorded path. Anything outside is kept absolute."""
    try:
        return path.relative_to(Path(settings.story_folder)).as_posix()
    except ValueError:
        return str(path)


def resolve_stored_path(stored: str) -> Path:
    """The file a recorded artifact path refers to. Absolute paths (recorded
    before paths were relative) are used as they are; relative ones are taken
    from the artifact folder and may not climb out of it."""
    path = Path(stored)
    if path.is_absolute():
        return path
    root = Path(settings.story_folder).resolve()
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Artifact path {stored!r} leaves the artifact folder")
    return resolved


def remove_job_files(owner_id: UUID, job_id: UUID) -> None:
    shutil.rmtree(user_dir(owner_id) / str(job_id), ignore_errors=True)


def remove_user_files(owner_id: UUID) -> None:
    shutil.rmtree(user_dir(owner_id), ignore_errors=True)
