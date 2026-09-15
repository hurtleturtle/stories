"""Celery tasks: running one scrape job end to end, and (re)sending its
finished ebook to Kindle."""

from __future__ import annotations

import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.db import get_sync_db
from app.models import Artifact, EmailStatus, Job, JobStatus, UserSettings
from app.services.email import missing_smtp_fields, pick_sendable_artifact, smtp_config
from app.services.storage import job_dir
from app.worker.celery_app import celery_app
from story_scraper.config import StoryConfig
from story_scraper.converter import convert
from story_scraper.mailer import send_ebook
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


def _append_log(job: Job, line: str) -> None:
    job.log = (job.log or "") + f"\n{line}"


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


def _user_settings(session, owner_id: UUID) -> UserSettings | None:
    return session.execute(
        select(UserSettings).where(UserSettings.user_id == owner_id)
    ).scalar_one_or_none()


def _send_to_kindle(session, job: Job, ebook_file: Path) -> None:
    """Send `ebook_file` to the owner's Kindle, recording the outcome on the
    job. Never raises: a delivery problem is reported, not a job failure."""
    settings_row = _user_settings(session, job.owner_id)
    smtp = smtp_config(settings_row)
    if smtp is None:
        missing = ", ".join(missing_smtp_fields(settings_row))
        reason = f"SMTP settings incomplete - missing {missing}."
        job.email_status = EmailStatus.failed
        job.email_error = reason
        _append_log(job, f"Skipped email: {reason}")
        return

    job.email_recipient = smtp.to_addr
    try:
        send_ebook(job.title, ebook_file, smtp)
    except Exception as exc:  # noqa: BLE001 - surfaced on the job, not raised
        job.email_status = EmailStatus.failed
        job.email_error = str(exc) or exc.__class__.__name__
        _append_log(job, f"Failed to send email: {exc}")
        return

    job.email_status = EmailStatus.sent
    job.email_error = None
    job.email_sent_at = datetime.now(UTC)
    _append_log(job, f"Emailed {ebook_file.name} to {smtp.to_addr}.")


@celery_app.task
def email_artifact_task(job_id: str, artifact_id: str | None = None) -> None:
    """Send a finished job's ebook to Kindle. Used by the resend endpoint, so
    `artifact_id` may be omitted to pick the job's ebook automatically."""
    session = get_sync_db()
    try:
        job = session.get(Job, UUID(job_id))
        if job is None:
            return

        artifact = None
        if artifact_id is not None:
            artifact = session.get(Artifact, UUID(artifact_id))
            if artifact is None or artifact.job_id != job.id:
                artifact = None
        else:
            artifact = pick_sendable_artifact(job.artifacts, job.config.get("ebook_type"))

        if artifact is None:
            job.email_status = EmailStatus.failed
            job.email_error = "No sendable ebook artifact found for this job."
            session.commit()
            return

        _send_to_kindle(session, job, Path(artifact.path))
        session.commit()
    except Exception as exc:  # noqa: BLE001 - a resend must not crash the worker
        session.rollback()
        job = session.get(Job, UUID(job_id))
        if job is not None:
            job.email_status = EmailStatus.failed
            job.email_error = f"{exc}"
            session.commit()
    finally:
        session.close()
