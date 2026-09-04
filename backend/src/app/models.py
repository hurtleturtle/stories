"""ORM models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    hashed_password: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    settings: Mapped[UserSettings | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    templates: Mapped[list[Template]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[Job]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    kindle_address: Mapped[str | None]
    email_from: Mapped[str | None]
    smtp_host: Mapped[str] = mapped_column(default="smtp.gmail.com")
    smtp_port: Mapped[int] = mapped_column(default=465)
    smtp_username: Mapped[str | None]
    smtp_password_encrypted: Mapped[str | None]
    auto_send_default: Mapped[bool] = mapped_column(default=False)

    user: Mapped[User] = relationship(back_populates="settings")


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_template_owner_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str]
    site_hostname: Mapped[str | None]
    container: Mapped[str]
    next_selector: Mapped[str]
    detect_title: Mapped[str | None]
    style: Mapped[str] = mapped_column(default="white-style.css")
    scripts: Mapped[list[str]] = mapped_column(JSONB, default=list)
    ebook_type: Mapped[str] = mapped_column(default="epub")
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped[User] = relationship(back_populates="templates")
    jobs: Mapped[list[Job]] = relationship(back_populates="template")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL")
    )
    url: Mapped[str]
    title: Mapped[str]
    status: Mapped[JobStatus] = mapped_column(default=JobStatus.pending)
    config: Mapped[dict] = mapped_column(JSONB)
    num_chapters: Mapped[int | None]
    chapters_scraped: Mapped[int] = mapped_column(default=0)
    celery_task_id: Mapped[str | None]
    error: Mapped[str | None] = mapped_column(Text)
    log: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    owner: Mapped[User] = relationship(back_populates="jobs")
    template: Mapped[Template | None] = relationship(back_populates="jobs")
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    kind: Mapped[str]
    filename: Mapped[str]
    path: Mapped[str]
    size_bytes: Mapped[int]
    content_type: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    job: Mapped[Job] = relationship(back_populates="artifacts")
