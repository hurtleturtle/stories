"""Configuration models for the story scraper."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StoryConfig(BaseModel):
    """Fully resolved parameters for a single scrape job."""

    url: str
    title: str = "book"
    filename: str | None = None
    container: str = "div.chapter-content"
    next_selector: str = "a#next_chap"
    detect_title: str | None = None
    style: str = "white-style.css"
    scripts: list[str] = Field(default_factory=list)
    ebook_type: str = "epub"
    num_chapters: int | None = None
    verbosity: int = 0

    def resolved_filename(self) -> str:
        return self.filename or self.title.replace(" ", "_")


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

    email_from: str | None = None
    email_to: str | None = None
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    email_password: str | None = None


settings = Settings()
