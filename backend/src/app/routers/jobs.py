from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import current_user
from app.models import EmailStatus, Job, JobStatus, Template, User, UserSettings
from app.schemas import JobCreate, JobEmailRequest, JobList, JobOut
from app.services.email import missing_smtp_fields, pick_sendable_artifact
from app.services.jobs import build_job_config
from app.services.storage import remove_job_files
from app.worker.celery_app import celery_app
from story_scraper.urlsafety import UnsafeURLError, assert_public_url

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


async def _get_owned_job(db: AsyncSession, user: User, job_id: UUID) -> Job:
    result = await db.execute(
        select(Job)
        .options(selectinload(Job.artifacts))
        .where(Job.id == job_id, Job.owner_id == user.id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    data: JobCreate, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> Job:
    try:
        # Resolves DNS, so keep it off the event loop.
        await run_in_threadpool(assert_public_url, data.url)
    except UnsafeURLError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    template = None
    if data.template_id is not None:
        template = await db.get(Template, data.template_id)
        if template is None or template.owner_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")

    overrides = data.model_dump(exclude={"url", "template_id", "send_email"})
    config = build_job_config(data.url, template, overrides)

    # Chosen up front so the id is on the job from the moment it can be
    # cancelled, rather than only once a worker picks it up.
    task_id = str(uuid4())
    job = Job(
        owner_id=user.id,
        template_id=template.id if template else None,
        url=data.url,
        title=config.title,
        status=JobStatus.pending,
        celery_task_id=task_id,
        config={**config.model_dump(), "send_email": data.send_email},
        num_chapters=config.num_chapters,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    celery_app.send_task("app.worker.tasks.run_story_job", args=[str(job.id)], task_id=task_id)
    return job


@router.get("", response_model=JobList)
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
    status_filter: JobStatus | None = Query(None, alias="status"),
    limit: int = Query(20, le=100),
    offset: int = 0,
) -> JobList:
    stmt = (
        select(Job)
        .options(selectinload(Job.artifacts))
        .where(Job.owner_id == user.id)
        .order_by(Job.created_at.desc())
    )
    count_stmt = select(func.count()).select_from(Job).where(Job.owner_id == user.id)
    if status_filter is not None:
        stmt = stmt.where(Job.status == status_filter)
        count_stmt = count_stmt.where(Job.status == status_filter)

    total = (await db.execute(count_stmt)).scalar_one()
    items = list((await db.execute(stmt.limit(limit).offset(offset))).scalars())
    return JobList(items=items, total=total)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> Job:
    return await _get_owned_job(db, user, job_id)


@router.post("/{job_id}/retry", response_model=JobOut)
async def retry_job(
    job_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> Job:
    job = await _get_owned_job(db, user, job_id)
    if job.status not in (JobStatus.failed, JobStatus.cancelled):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only failed or cancelled jobs can be retried"
        )

    task_id = str(uuid4())
    job.status = JobStatus.pending
    job.celery_task_id = task_id
    job.error = None
    job.chapters_scraped = 0
    job.started_at = None
    job.finished_at = None
    job.email_status = EmailStatus.not_sent
    job.email_error = None
    job.email_sent_at = None
    await db.commit()
    await db.refresh(job)

    celery_app.send_task("app.worker.tasks.run_story_job", args=[str(job.id)], task_id=task_id)
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> Job:
    job = await _get_owned_job(db, user, job_id)
    if job.status != JobStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only pending jobs can be cancelled")

    # Conditional, so a worker that claims the job between the check above and
    # this write is not silently overwritten.
    cancelled = await db.execute(
        update(Job)
        .where(Job.id == job.id, Job.status == JobStatus.pending)
        .values(status=JobStatus.cancelled)
    )
    await db.commit()
    if cancelled.rowcount == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Job has already started")

    # Best effort: the worker also refuses any job that is no longer pending.
    if job.celery_task_id:
        celery_app.control.revoke(job.celery_task_id)
    await db.refresh(job)
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> None:
    job = await _get_owned_job(db, user, job_id)
    await db.delete(job)
    await db.commit()
    remove_job_files(job.owner_id, job.id)


@router.get("/{job_id}/artifacts/{artifact_id}")
async def download_artifact(
    job_id: UUID,
    artifact_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> FileResponse:
    job = await _get_owned_job(db, user, job_id)
    artifact = next((a for a in job.artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")

    if not Path(artifact.path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact file is no longer available")

    return FileResponse(
        artifact.path, media_type=artifact.content_type, filename=artifact.filename
    )


@router.post("/{job_id}/email", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def email_job(
    job_id: UUID,
    body: JobEmailRequest = Body(default_factory=JobEmailRequest),
    artifact_id: UUID | None = Query(None, deprecated=True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Job:
    """(Re)send a completed job's ebook to the owner's Kindle address.

    The artifact is optional - by default the job's own ebook is sent, which
    is what "resend this job" means. Settings problems are reported here
    rather than queued and silently dropped in the worker.
    """
    job = await _get_owned_job(db, user, job_id)
    if job.status != JobStatus.success:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only completed jobs can be emailed to Kindle"
        )

    chosen_id = body.artifact_id or artifact_id
    if chosen_id is not None:
        artifact = next((a for a in job.artifacts if a.id == chosen_id), None)
    else:
        artifact = pick_sendable_artifact(job.artifacts, job.config.get("ebook_type"))
    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No ebook artifact to send")

    settings_row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    ).scalar_one_or_none()
    missing = missing_smtp_fields(settings_row)
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Email settings incomplete - set your {', '.join(missing)} on the Settings page",
        )

    job.email_status = EmailStatus.pending
    job.email_error = None
    job.email_recipient = settings_row.kindle_address if settings_row else None
    await db.commit()
    await db.refresh(job)

    celery_app.send_task(
        "app.worker.tasks.email_artifact_task", args=[str(job.id), str(artifact.id)]
    )
    return job
