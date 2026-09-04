from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import current_user
from app.models import Job, JobStatus, Template, User
from app.schemas import JobCreate, JobList, JobOut
from app.services.jobs import build_job_config
from app.worker.celery_app import celery_app

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
    template = None
    if data.template_id is not None:
        template = await db.get(Template, data.template_id)
        if template is None or template.owner_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")

    overrides = data.model_dump(exclude={"url", "template_id", "send_email"})
    config = build_job_config(data.url, template, overrides)

    job = Job(
        owner_id=user.id,
        template_id=template.id if template else None,
        url=data.url,
        title=config.title,
        status=JobStatus.pending,
        config={**config.model_dump(), "send_email": data.send_email},
        num_chapters=config.num_chapters,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    celery_app.send_task("app.worker.tasks.run_story_job", args=[str(job.id)])
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

    job.status = JobStatus.pending
    job.error = None
    job.chapters_scraped = 0
    job.started_at = None
    job.finished_at = None
    await db.commit()
    await db.refresh(job)

    celery_app.send_task("app.worker.tasks.run_story_job", args=[str(job.id)])
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> Job:
    job = await _get_owned_job(db, user, job_id)
    if job.status != JobStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only pending jobs can be cancelled")

    if job.celery_task_id:
        celery_app.control.revoke(job.celery_task_id)
    job.status = JobStatus.cancelled
    await db.commit()
    await db.refresh(job)
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> None:
    job = await _get_owned_job(db, user, job_id)
    await db.delete(job)
    await db.commit()


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

    return FileResponse(
        artifact.path, media_type=artifact.content_type, filename=artifact.filename
    )


@router.post("/{job_id}/email", status_code=status.HTTP_202_ACCEPTED)
async def email_artifact(
    job_id: UUID,
    artifact_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    job = await _get_owned_job(db, user, job_id)
    artifact = next((a for a in job.artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")

    celery_app.send_task(
        "app.worker.tasks.email_artifact_task", args=[str(job.id), str(artifact.id)]
    )
    return {"status": "queued"}
