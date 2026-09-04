"""Celery task that runs one scrape job end to end."""

from __future__ import annotations

import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.db import get_sync_db
from app.models import Artifact, Job, JobStatus, UserSettings
from app.security import decrypt_secret
from app.services.storage import job_dir
from app.worker.celery_app import celery_app
from story_scraper.config import StoryConfig
from story_scraper.converter import ConversionError, convert
from story_scraper.mailer import SmtpConfig, send_ebook
from story_scraper.scraper import Story

CONTENT_TYPES = {
    "html": "text/html",
    "epub": "application/epub+zip",
    "mobi": "application/x-mobipocket-ebook",
}


def _record_artifact(session, job: Job, kind: str, path) -> None:
    artifact = Artifact(
        job_id=job.id,
        kind=kind,
        filename=path.name,
        path=str(path),
        size_bytes=path.stat().st_size,
        content_type=CONTENT_TYPES.get(kind, "application/octet-stream"),
    )
    session.add(artifact)


@celery_app.task(bind=True)
def run_story_job(self, job_id: str) -> None:
    session = get_sync_db()
    try:
        job = session.get(Job, UUID(job_id))
        if job is None:
            return

        job.status = JobStatus.running
        job.started_at = datetime.now(UTC)
        job.celery_task_id = self.request.id
        session.commit()

        config = StoryConfig(**job.config)
        log_lines: list[str] = []

        def progress(count: int, url: str) -> None:
            log_lines.append(f"Chapter {count}: {url}")
            job.chapters_scraped = count
            job.log = "\n".join(log_lines)
            session.commit()

        output_dir = job_dir(job.owner_id, job.id)
        with Story(config, progress=progress) as story:
            html_file = story.write(output_dir)

        _record_artifact(session, job, "html", html_file)

        ebook_file = output_dir / f"{config.resolved_filename()}.{config.ebook_type}"
        convert(html_file, ebook_file, config.title)
        _record_artifact(session, job, config.ebook_type, ebook_file)

        if job.config.get("send_email"):
            _send_to_kindle(session, job, ebook_file)

        job.status = JobStatus.success
    except Exception as exc:  # noqa: BLE001 - job failures must not crash the worker
        session.rollback()
        job = session.get(Job, UUID(job_id))
        if job is not None:
            job.status = JobStatus.failed
            job.error = f"{exc}\n\n{traceback.format_exc()}"
    finally:
        job = session.get(Job, UUID(job_id))
        if job is not None:
            job.finished_at = datetime.now(UTC)
            session.commit()
        session.close()


def _smtp_config(session, owner_id: UUID) -> SmtpConfig | None:
    settings_row = session.execute(
        select(UserSettings).where(UserSettings.user_id == owner_id)
    ).scalar_one_or_none()

    incomplete = (
        not settings_row
        or not settings_row.kindle_address
        or not settings_row.smtp_password_encrypted
    )
    if incomplete:
        return None

    return SmtpConfig(
        from_addr=settings_row.email_from or settings_row.smtp_username or "",
        to_addr=settings_row.kindle_address,
        password=decrypt_secret(settings_row.smtp_password_encrypted),
        host=settings_row.smtp_host,
        port=settings_row.smtp_port,
    )


def _send_to_kindle(session, job: Job, ebook_file: Path) -> None:
    smtp = _smtp_config(session, job.owner_id)
    if smtp is None:
        job.log = (job.log or "") + "\nSkipped email: SMTP settings not fully configured."
        return

    try:
        send_ebook(job.title, ebook_file, smtp)
        job.log = (job.log or "") + f"\nEmailed {ebook_file.name} to {smtp.to_addr}."
    except (OSError, ConversionError) as exc:
        job.log = (job.log or "") + f"\nFailed to send email: {exc}"


@celery_app.task
def email_artifact_task(job_id: str, artifact_id: str) -> None:
    session = get_sync_db()
    try:
        job = session.get(Job, UUID(job_id))
        artifact = session.get(Artifact, UUID(artifact_id))
        if job is None or artifact is None or artifact.job_id != job.id:
            return

        smtp = _smtp_config(session, job.owner_id)
        if smtp is None:
            job.log = (job.log or "") + "\nSkipped email: SMTP settings not fully configured."
        else:
            send_ebook(job.title, Path(artifact.path), smtp)
            job.log = (job.log or "") + f"\nEmailed {artifact.filename} to {smtp.to_addr}."
        session.commit()
    finally:
        session.close()
