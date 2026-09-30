"""Configuration models for the story scraper."""

from __future__ import annotations

import re
from importlib import resources
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, StringConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

# Used as a file extension and passed to Calibre, so it must not be able to
# carry a path or option. Calibre decides which formats it can actually write.
EbookType = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[A-Za-z0-9]{1,10}$")
]



def asset_names(kind: str) -> list[str]:
    """Names of the bundled files of one kind ("styles" or "scripts")."""
    folder = resources.files("story_scraper.assets") / kind
    return sorted(entry.name for entry in folder.iterdir() if entry.is_file())


def read_asset(kind: str, name: str) -> str:
    """Contents of a bundled asset. Only bundled names are accepted, so a
    user-supplied value cannot select any other file on the machine."""
    if name not in asset_names(kind):
        raise ValueError(f"Unknown {kind.rstrip('s')} {name!r}")
    return (resources.files("story_scraper.assets") / kind / name).read_text(encoding="utf-8")


def _bundled(kind: str):
    def check(name: str) -> str:
        available = asset_names(kind)
        if name not in available:
            raise ValueError(
                f"Unknown {kind.rstrip('s')} {name!r}; available: {', '.join(available)}"
            )
        return name

    return AfterValidator(check)


StyleName = Annotated[str, _bundled("styles")]
ScriptName = Annotated[str, _bundled("scripts")]

_UNSAFE_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')
_MAX_FILENAME_BYTES = 200  # leaves room for an extension under the usual 255 limit


def safe_filename(name: str, fallback: str = "book") -> str:
    """Turn arbitrary text (a story title) into one safe path component.

    Path separators and characters some filesystems reject are dropped,
    whitespace becomes underscores, and leading/trailing dots go so the
    result can be neither hidden nor `..`. Length is capped in bytes, since
    non-Latin titles take several bytes per character.
    """
    cleaned = re.sub(r"\s", "_", name.strip())  # before the strip below, which drops \t and \n
    cleaned = _UNSAFE_FILENAME_CHARS.sub("", cleaned).strip(".")
    cleaned = cleaned.encode("utf-8")[:_MAX_FILENAME_BYTES].decode("utf-8", errors="ignore")
    return cleaned or fallback


class StoryConfig(BaseModel):
    """Fully resolved parameters for a single scrape job."""

    url: str
    title: str = "book"
    filename: str | None = None
    container: str = "div.chapter-content"
    next_selector: str = "a#next_chap"
    detect_title: str | None = None
    style: StyleName = "white-style.css"
    scripts: list[ScriptName] = Field(default_factory=list)
    ebook_type: EbookType = "epub"
    num_chapters: int | None = None
    verbosity: int = 0

    def resolved_filename(self) -> str:
        return safe_filename(self.filename or self.title)


class Settings(BaseSettings):
    """Process-wide settings sourced from the environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    story_folder: str = "/data/artifacts"
    database_url: str = "postgresql+asyncpg://story:story@db:5432/story"
    database_url_sync: str = "postgresql+psycopg://story:story@db:5432/story"
    redis_url: str = "redis://redis:6379/0"
    secret_key: str = "change-me"
    allow_registration: bool = True
    access_token_expire_minutes: int = 60 * 24

    # ebook-convert has been seen to hang; without a limit it holds a worker forever.
    conversion_timeout_seconds: int = 30 * 60

    # A running job's worker refreshes jobs.heartbeat_at this often. A job with
    # no heartbeat for stale_after seconds is taken to have lost its worker and
    # is failed; the API sweeps for such jobs every sweep_interval seconds.
    # stale_after must comfortably exceed the heartbeat interval.
    job_heartbeat_interval_seconds: float = 30
    job_stale_after_seconds: float = 5 * 60
    stale_job_sweep_interval_seconds: float = 60
    # How long the broker waits for a task to finish before handing it to
    # another worker. Must exceed the longest scrape, or a long job runs twice.
    broker_visibility_timeout_seconds: int = 12 * 60 * 60

    email_from: str | None = None
    email_to: str | None = None
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    email_password: str | None = None


settings = Settings()
