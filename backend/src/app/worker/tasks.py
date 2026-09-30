"""Celery tasks: running one scrape job end to end, and (re)sending its
finished ebook to Kindle."""

from __future__ import annotations

import logging
import shutil
import threading
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from sqlalchemy import case, delete, func, select, update

from app.db import get_sync_db
from app.models import Artifact, EmailStatus, Job, JobStatus, UserSettings
from app.services.email import missing_smtp_fields, pick_sendable_artifact, smtp_config
from app.services.storage import job_dir, resolve_stored_path, stored_path
from app.worker.celery_app import celery_app
from story_scraper.config import StoryConfig, settings
from story_scraper.converter import convert
from story_scraper.mailer import send_ebook
from story_scraper.scraper import Story

logger = logging.getLogger(__name__)

# Where a job's chapters are kept while it is being scraped, inside its own
# folder. A retry finds them there and carries on; they go once the job succeeds.
CHAPTERS_DIR = ".chapters"

CONTENT_TYPES = {
    "html": "text/html",
    "epub": "application/epub+zip",
    "mobi": "application/x-mobipocket-ebook",  # no longer produced; old artifacts still download
    "azw3": "application/vnd.amazon.ebook",
    "pdf": "application/pdf",
}


def _record_artifact(session, job: Job, kind: str, path) -> None:
    artifact = Artifact(
        job_id=job.id,
        kind=kind,
        filename=path.name,
        path=stored_path(path),
        size_bytes=path.stat().st_size,
        content_type=CONTENT_TYPES.get(kind, "application/octet-stream"),
    )
    session.add(artifact)


def _append_log(session, job_id: UUID, *lines: str) -> None:
    """Add lines to a job's log, in SQL.

    Appended in the database rather than by assigning a new whole log, so it
    can never overwrite lines another writer added (the batched chapter lines,
    an email note), and only the new lines are sent."""
    if not lines:
        return
    existing = func.coalesce(Job.log, "")
    separator = case((existing == "", ""), else_="\n")
    session.execute(
        update(Job).where(Job.id == job_id).values(log=existing + separator + "\n".join(lines))
    )


class _ProgressLog:
    """Chapter lines for the job log, written to the database in batches.

    One write per chapter meant sending, and the database rewriting, the whole
    growing log each time, so the total grew with the square of the chapter
    count. Lines are held back and written once FLUSH_LINES have built up or
    FLUSH_SECONDS have passed since the last write, and whenever `flush` is
    called (when the scrape ends, or fails, so no progress is lost)."""

    FLUSH_LINES = 25
    FLUSH_SECONDS = 3.0

    def __init__(self, session, job_id: UUID, clock=time.monotonic) -> None:
        self._session = session
        self._job_id = job_id
        self._clock = clock
        self._pending: list[str] = []
        self._last_flush = clock()

    def add(self, line: str) -> None:
        self._pending.append(line)
        if (
            len(self._pending) >= self.FLUSH_LINES
            or self._clock() - self._last_flush >= self.FLUSH_SECONDS
        ):
            self.flush()

    def flush(self) -> None:
        if self._pending:
            _append_log(self._session, self._job_id, *self._pending)
            self._session.commit()
            self._pending.clear()
        self._last_flush = self._clock()


class _JobStopped(Exception):
    """This run should stop: the job was cancelled, deleted or swept as lost, or
    a retry gave it to a new task. Not a failure; the run just ends.

    `superseded` means a new task owns the job now. That run is writing the job's
    log, so this one must leave it alone."""

    def __init__(self, status: JobStatus | None, superseded: bool = False) -> None:
        super().__init__(f"job is {status.value if status else 'gone'}")
        self.status = status
        self.superseded = superseded


def _claim_job(session, job_id: UUID, task_id: str | None) -> bool:
    """Move a pending job to running, atomically. False if it was not pending
    - cancelled while queued, or already claimed by another delivery of the
    same task (a redelivery after a broker visibility timeout, say)."""
    # The worker never reads its own clock: every timestamp it records is the
    # database's now(). The stale-job sweep compares heartbeat_at against the
    # database's now(), so writer and sweep must agree on the time whatever
    # this machine's clock says, and one clock everywhere keeps every
    # timestamp comparable.
    claimed = session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.pending)
        .values(
            status=JobStatus.running,
            started_at=func.now(),
            heartbeat_at=func.now(),
            celery_task_id=task_id,
        )
    )
    if claimed.rowcount == 1:
        # Anything left by an earlier run (a retry after a failed conversion
        # keeps the scraped HTML) is about to be regenerated under the same
        # names; without this the job would list each artifact twice.
        session.execute(delete(Artifact).where(Artifact.job_id == job_id))
    session.commit()
    return claimed.rowcount == 1


@contextmanager
def _heartbeat(job_id: UUID) -> Iterator[None]:
    """Refresh the job's heartbeat in the background while the body runs.

    A thread, because the main thread can go a long time without touching the
    database - a slow site, or Calibre for up to the conversion timeout - and
    a job must not look dead just because it is busy.
    """
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(settings.job_heartbeat_interval_seconds):
            try:
                with get_sync_db() as session:
                    session.execute(
                        update(Job)
                        .where(Job.id == job_id, Job.status == JobStatus.running)
                        .values(heartbeat_at=func.now())
                    )
                    session.commit()
            except Exception:  # noqa: BLE001 - keep beating through a database blip
                logger.exception("Could not record heartbeat for job %s", job_id)

    thread = threading.Thread(target=beat, name=f"heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)


@celery_app.task(bind=True)
def run_story_job(self, job_id: str) -> None:
    session = get_sync_db()
    try:
        if not _claim_job(session, UUID(job_id), self.request.id):
            logger.info("Not running job %s: it is no longer pending", job_id)
            return
        with _heartbeat(UUID(job_id)):
            _run_claimed_job(session, job_id, self.request.id)
    finally:
        session.close()


def _owns(job_id: UUID, task_id: str | None):
    """Condition for a row this run may still write: the job with this id whose
    task is this one. A retry gives the job a new task id, so a run that was
    cancelled and superseded stops being able to touch it."""
    return (Job.id == job_id) & Job.celery_task_id.is_not_distinct_from(task_id)


def _finish(session, job_id: UUID, task_id: str | None, status: JobStatus, **values) -> None:
    """Set the final status, but only while the job is still running and ours:
    a job cancelled mid-run stays cancelled rather than turning `success`."""
    session.execute(
        update(Job)
        .where(_owns(job_id, task_id), Job.status == JobStatus.running)
        .values(status=status, **values)
    )


def _run_claimed_job(session, job_id: str, task_id: str | None = None) -> None:
    job_uuid = UUID(job_id)
    log: _ProgressLog | None = None
    try:
        job = session.get(Job, job_uuid)
        config = StoryConfig(**job.config)
        log = _ProgressLog(session, job_uuid)

        def progress(count: int, url: str) -> None:
            log.add(f"Chapter {count}: {url}")
            # The chapter count, and in the same statement whether to carry on.
            row = session.execute(
                update(Job)
                .where(Job.id == job_uuid)
                .values(chapters_scraped=count)
                .returning(Job.status, Job.celery_task_id)
            ).one_or_none()
            session.commit()
            if row is None:
                raise _JobStopped(None)
            if row.celery_task_id != task_id:
                raise _JobStopped(row.status, superseded=True)
            if row.status != JobStatus.running:
                raise _JobStopped(row.status)

        output_dir = job_dir(job.owner_id, job.id)
        work_dir = output_dir / CHAPTERS_DIR
        with Story(config, progress=progress, work_dir=work_dir) as story:
            stored = story.chapters_done
            if stored:
                # An earlier attempt stored these; the scrape picks up after them.
                _append_log(session, job_uuid, f"Resuming after chapter {stored}.")
                session.execute(
                    update(Job).where(Job.id == job_uuid).values(chapters_scraped=stored)
                )
            else:
                # A fresh scrape has its own log; a resumed one carries on from the last.
                session.execute(update(Job).where(Job.id == job_uuid).values(log=None))
            session.commit()

            html_file = story.write(output_dir)
            if story.stop_reason:
                log.add(story.stop_reason)
        log.flush()

        # Committed now: if conversion fails, the scraped book is still worth
        # having, and the failure handler below rolls back to this point.
        _record_artifact(session, job, "html", html_file)
        session.commit()

        ebook_file = output_dir / f"{config.resolved_filename()}.{config.ebook_type}"
        convert(
            html_file,
            ebook_file,
            config.title,
            timeout=settings.conversion_timeout_seconds,
            authors=config.author,
            language=config.language,
        )
        _record_artifact(session, job, config.ebook_type, ebook_file)

        if job.config.get("send_email"):
            _send_to_kindle(session, job, ebook_file)

        shutil.rmtree(work_dir, ignore_errors=True)  # only kept so a retry can resume
        _finish(session, job_uuid, task_id, JobStatus.success)
    except _JobStopped as stopped:
        session.rollback()
        if not stopped.superseded:
            if log:
                log.flush()
            if stopped.status is not None:
                _append_log(session, job_uuid, f"Stopped: the job was {stopped.status.value}.")
    except Exception as exc:  # noqa: BLE001 - job failures must not crash the worker
        session.rollback()
        if log:
            log.flush()  # keep the progress made before the failure
        _finish(
            session,
            job_uuid,
            task_id,
            JobStatus.failed,
            error=f"{exc}\n\n{traceback.format_exc()}",
        )
    finally:
        session.execute(update(Job).where(_owns(job_uuid, task_id)).values(finished_at=func.now()))
        session.commit()


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
        _append_log(session, job.id, f"Skipped email: {reason}")
        return

    job.email_recipient = smtp.to_addr
    try:
        send_ebook(job.title, ebook_file, smtp)
    except Exception as exc:  # noqa: BLE001 - surfaced on the job, not raised
        job.email_status = EmailStatus.failed
        job.email_error = str(exc) or exc.__class__.__name__
        _append_log(session, job.id, f"Failed to send email: {exc}")
        return

    job.email_status = EmailStatus.sent
    job.email_error = None
    job.email_sent_at = func.now()
    _append_log(session, job.id, f"Emailed {ebook_file.name} to {smtp.to_addr}.")


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

        _send_to_kindle(session, job, resolve_stored_path(artifact.path))
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
