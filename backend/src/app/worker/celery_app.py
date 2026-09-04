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
)
