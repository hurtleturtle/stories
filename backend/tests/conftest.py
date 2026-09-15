"""Test fixtures.

The API tests need a real Postgres (the models use JSONB and native enums).
Point TEST_DATABASE_URL at a throwaway database to run them:

    TEST_DATABASE_URL=postgresql://story@localhost:5432/story_test uv run pytest

Without it they skip, so the default `uv run pytest` still needs no DB.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# story_scraper.config builds its Settings at import time, so the app must not
# be imported before these are in place.
if TEST_DATABASE_URL:
    _bare = TEST_DATABASE_URL.split("://", 1)[1]
    os.environ["DATABASE_URL"] = f"postgresql+asyncpg://{_bare}"
    os.environ["DATABASE_URL_SYNC"] = f"postgresql+psycopg://{_bare}"
    os.environ.setdefault("SECRET_KEY", "test-secret-key")

@pytest.fixture
async def db_engine():
    """A schema created fresh for each test. Skips when no DB is configured,
    which is what keeps the rest of the suite runnable without one."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")

    from app import models  # noqa: F401 - registers the tables on Base
    from app.db import Base, async_engine

    # Each test runs in its own event loop, and pooled connections belong to
    # the loop that opened them - so the pool is emptied either side.
    await async_engine.dispose()
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_engine
    finally:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await async_engine.dispose()


@pytest.fixture
async def queued_tasks(monkeypatch) -> list[tuple]:
    """Capture Celery dispatches instead of needing a live broker."""
    from app.worker import celery_app as celery_module

    sent: list[tuple] = []

    def fake_send_task(name, args=None, **kwargs):
        sent.append((name, list(args or [])))

    monkeypatch.setattr(celery_module.celery_app, "send_task", fake_send_task)
    return sent


@pytest.fixture
async def client(db_engine, queued_tasks) -> AsyncIterator:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


SMTP_SETTINGS = {
    "kindle_address": "me@kindle.com",
    "email_from": "library@example.com",
    "smtp_host": "smtp.example.com",
    "smtp_port": 465,
    "smtp_username": "smtp-login@example.com",
    "smtp_password": "app-password",
    "auto_send_default": False,
}


@pytest.fixture
def smtp_settings() -> dict:
    """A complete set of send-to-Kindle settings, as the PUT body wants them."""
    return dict(SMTP_SETTINGS)


@pytest.fixture
def make_job():
    """Factory inserting a job (with artifacts) owned by the registered user."""

    async def _make_job(status="success", kinds=("html", "epub"), ebook_type="epub") -> str:
        from sqlalchemy import select

        from app.db import AsyncSessionLocal
        from app.models import Artifact, Job, JobStatus, User

        async with AsyncSessionLocal() as db:
            user = (await db.execute(select(User))).scalars().first()
            job = Job(
                owner_id=user.id,
                url="https://example.com/chapter-1",
                title="My Book",
                status=JobStatus(status),
                config={"url": "https://example.com/chapter-1", "ebook_type": ebook_type},
            )
            db.add(job)
            await db.flush()
            for kind in kinds:
                db.add(
                    Artifact(
                        job_id=job.id,
                        kind=kind,
                        filename=f"My_Book.{kind}",
                        path=f"/data/My_Book.{kind}",
                        size_bytes=10,
                        content_type="application/octet-stream",
                    )
                )
            await db.commit()
            return str(job.id)

    return _make_job


@pytest.fixture
async def auth_client(client):
    """A client already registered and carrying a bearer token."""
    email = f"user-{uuid4()}@example.com"
    resp = await client.post("/api/auth/register", json={"email": email, "password": "pw12345"})
    assert resp.status_code == 201, resp.text

    resp = await client.post(
        "/api/auth/login", data={"username": email, "password": "pw12345"}
    )
    assert resp.status_code == 200, resp.text
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return client
