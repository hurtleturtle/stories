"""Job config resolution, shared by the create and retry endpoints."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.models import Job, JobStatus, Template
from story_scraper.config import StoryConfig, settings
from story_scraper.resolve import resolve_config

logger = logging.getLogger(__name__)

STALE_JOB_ERROR = (
    "The worker running this job stopped unexpectedly, so the job was marked as "
    "failed. Retry it to run it again."
)


def build_job_config(url: str, template: Template | None, overrides: dict) -> StoryConfig:
    template_dict = {}
    if template is not None:
        template_dict = {
            "container": template.container,
            "next_selector": template.next_selector,
            "detect_title": template.detect_title,
            "style": template.style,
            "scripts": template.scripts,
            "ebook_type": template.ebook_type,
        }

    return resolve_config(url, template_dict, overrides)


async def fail_stale_jobs(db: AsyncSession) -> int:
    """Fail every running job whose worker has stopped reporting in, and
    return how many there were.

    A worker that dies mid-job (killed by a deploy, the OOM killer, a host
    failure) never gets to write a final status, and the broker will not
    re-run the job. Jobs from before heartbeats existed fall back to started_at.
    """
    # The database's own clock, not Python's: these are timezone-less columns
    # (asyncpg will not take an aware datetime for them), and the worker's
    # timestamps were converted by the server's timezone on the way in, so
    # comparing against now() applies that same conversion.
    cutoff = func.now() - timedelta(seconds=settings.job_stale_after_seconds)
    result = await db.execute(
        update(Job)
        .where(
            Job.status == JobStatus.running,
            func.coalesce(Job.heartbeat_at, Job.started_at, Job.created_at) < cutoff,
        )
        .values(status=JobStatus.failed, finished_at=func.now(), error=STALE_JOB_ERROR)
    )
    await db.commit()
    return result.rowcount


async def sweep_stale_jobs_forever() -> None:
    """Run fail_stale_jobs on a timer for the life of the API process. It is
    safe for several API processes to do this at once."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                failed = await fail_stale_jobs(db)
            if failed:
                logger.warning("Marked %d job(s) failed: their worker stopped reporting", failed)
        except Exception:  # noqa: BLE001 - a bad sweep must not end the loop
            logger.exception("Stale job sweep failed")
        await asyncio.sleep(settings.stale_job_sweep_interval_seconds)
