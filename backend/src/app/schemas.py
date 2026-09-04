"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models import JobStatus


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TemplateBase(BaseModel):
    name: str
    site_hostname: str | None = None
    container: str
    next_selector: str
    detect_title: str | None = None
    style: str = "white-style.css"
    scripts: list[str] = []
    ebook_type: str = "epub"
    extra: dict = {}


class TemplateCreate(TemplateBase):
    pass


class TemplateUpdate(BaseModel):
    name: str | None = None
    site_hostname: str | None = None
    container: str | None = None
    next_selector: str | None = None
    detect_title: str | None = None
    style: str | None = None
    scripts: list[str] | None = None
    ebook_type: str | None = None
    extra: dict | None = None


class TemplateOut(TemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class UserSettingsIn(BaseModel):
    kindle_address: str | None = None
    email_from: str | None = None
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_username: str | None = None
    smtp_password: str | None = None
    auto_send_default: bool = False


class UserSettingsOut(BaseModel):
    kindle_address: str | None
    email_from: str | None
    smtp_host: str
    smtp_port: int
    smtp_username: str | None
    smtp_password_set: bool
    auto_send_default: bool


class JobCreate(BaseModel):
    url: str
    template_id: UUID | None = None
    title: str | None = None
    container: str | None = None
    next_selector: str | None = None
    detect_title: str | None = None
    style: str | None = None
    scripts: list[str] | None = None
    ebook_type: str | None = None
    num_chapters: int | None = None
    send_email: bool = False


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    filename: str
    size_bytes: int
    content_type: str


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    title: str
    status: JobStatus
    config: dict
    num_chapters: int | None
    chapters_scraped: int
    error: str | None
    log: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    artifacts: list[ArtifactOut] = []


class JobList(BaseModel):
    items: list[JobOut]
    total: int
