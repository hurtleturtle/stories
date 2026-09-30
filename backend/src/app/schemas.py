"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import EmailStatus, JobStatus, UserRole
from story_scraper.config import EbookType


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime


class RegistrationStatus(BaseModel):
    open: bool


class AdminUserOut(UserOut):
    job_count: int
    template_count: int


class AdminUserList(BaseModel):
    items: list[AdminUserOut]
    total: int


class AdminUserUpdate(BaseModel):
    """Fields an admin can change on an account. Omitted fields are left alone."""

    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8)


class AppSettingsIO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allow_registration: bool


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
    ebook_type: EbookType = "epub"


class TemplateUpdate(BaseModel):
    name: str | None = None
    site_hostname: str | None = None
    container: str | None = None
    next_selector: str | None = None
    detect_title: str | None = None
    style: str | None = None
    scripts: list[str] | None = None
    ebook_type: EbookType | None = None
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
    # A blank smtp_password leaves the stored one alone; this asks for it to
    # be forgotten instead.
    clear_smtp_password: bool = False
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
    ebook_type: EbookType | None = None
    num_chapters: int | None = None
    send_email: bool = False


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    filename: str
    size_bytes: int
    content_type: str


class JobEmailRequest(BaseModel):
    """Which artifact to send to Kindle. Omitting it picks the job's ebook."""

    artifact_id: UUID | None = None


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
    email_status: EmailStatus
    email_recipient: str | None
    email_error: str | None
    email_sent_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    artifacts: list[ArtifactOut] = []


class JobList(BaseModel):
    items: list[JobOut]
    total: int
