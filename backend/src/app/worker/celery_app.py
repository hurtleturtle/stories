"""Celery application definition."""

from __future__ import annotations

from celery import Celery

from story_scraper.config import settings

celery_app = Celery(
    "story_scraper",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="story_jobs",
    # Redis redelivers an unacknowledged task after this long (default 1 hour),
    # and with acks_late a long scrape is unacknowledged until it finishes.
    broker_transport_options={"visibility_timeout": settings.broker_visibility_timeout_seconds},
)
