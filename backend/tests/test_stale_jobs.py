"""A job whose worker dies must not stay `running` for ever.

The worker refreshes `heartbeat_at` while it runs; the API sweeps for running
jobs that have stopped doing so and fails them, so they can be retried.
"""

import asyncio
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from jobhelpers import create_job, load_job, set_job_fields, set_status

from story_scraper.config import settings

MINUTES = timedelta(minutes=1)


def ago(delta: timedelta) -> datetime:
    return datetime.now(UTC) - delta


async def sweep() -> int:
    from app.db import AsyncSessionLocal
    from app.services.jobs import fail_stale_jobs

    async with AsyncSessionLocal() as db:
        return await fail_stale_jobs(db)


async def running_job(auth_client, heartbeat_age: timedelta | None, started_age=10 * MINUTES):
    body = await create_job(auth_client)
    set_job_fields(
        body["id"],
        status="running",
        started_at=ago(started_age),
        heartbeat_at=ago(heartbeat_age) if heartbeat_age is not None else None,
    )
    return body["id"]


# --- the sweep --------------------------------------------------------------


async def test_a_running_job_with_a_stale_heartbeat_is_failed(auth_client):
    from app.services.jobs import STALE_JOB_ERROR

    job_id = await running_job(
        auth_client, heartbeat_age=timedelta(seconds=settings.job_stale_after_seconds * 2)
    )

    assert await sweep() == 1

    job = load_job(job_id)
    assert job.status.value == "failed"
    assert job.error == STALE_JOB_ERROR
    assert job.finished_at is not None


async def test_a_running_job_with_a_recent_heartbeat_is_left_alone(auth_client):
    job_id = await running_job(auth_client, heartbeat_age=timedelta(seconds=5))

    assert await sweep() == 0

    job = load_job(job_id)
    assert job.status.value == "running"
    assert job.error is None and job.finished_at is None


async def test_a_long_running_job_is_not_stale_while_it_keeps_beating(auth_client):
    """Age is measured from the last heartbeat, not from when the job started."""
    job_id = await running_job(
        auth_client, heartbeat_age=timedelta(seconds=5), started_age=timedelta(hours=6)
    )

    assert await sweep() == 0
    assert load_job(job_id).status.value == "running"


async def test_a_job_with_no_heartbeat_falls_back_to_when_it_started(auth_client):
    """Jobs that were already running when heartbeats were introduced."""
    old = await running_job(auth_client, heartbeat_age=None, started_age=timedelta(hours=1))
    fresh = await running_job(auth_client, heartbeat_age=None, started_age=timedelta(seconds=10))

    assert await sweep() == 1

    assert load_job(old).status.value == "failed"
    assert load_job(fresh).status.value == "running"


@pytest.mark.parametrize("status", ["pending", "success", "failed", "cancelled"])
async def test_jobs_that_are_not_running_are_never_touched(auth_client, status):
    body = await create_job(auth_client)
    set_job_fields(body["id"], status=status, heartbeat_at=ago(timedelta(hours=5)))
    before = load_job(body["id"])

    assert await sweep() == 0

    after = load_job(body["id"])
    assert (after.status, after.error, after.finished_at) == (
        before.status,
        before.error,
        before.finished_at,
    )


async def test_a_failed_stale_job_can_be_retried(auth_client, queued_tasks):
    job_id = await running_job(auth_client, heartbeat_age=10 * MINUTES)
    await sweep()

    resp = await auth_client.post(f"/api/jobs/{job_id}/retry")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["error"] is None
    assert queued_tasks[-1][1] == [job_id]


async def test_the_reason_is_visible_to_the_user(auth_client):
    job_id = await running_job(auth_client, heartbeat_age=10 * MINUTES)
    await sweep()

    body = (await auth_client.get(f"/api/jobs/{job_id}")).json()

    assert body["status"] == "failed"
    assert "worker" in body["error"] and "Retry" in body["error"]


# --- the sweep running inside the API ---------------------------------------


async def test_the_api_sweeps_in_the_background(auth_client, monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "stale_job_sweep_interval_seconds", 0.05)
    job_id = await running_job(auth_client, heartbeat_age=10 * MINUTES)

    async with app.router.lifespan_context(app):
        for _ in range(100):
            if load_job(job_id).status.value == "failed":
                break
            await asyncio.sleep(0.05)

    assert load_job(job_id).status.value == "failed"


async def test_the_sweeper_survives_a_failing_sweep_and_stops_with_the_api(monkeypatch):
    from app import main
    from app.services import jobs as jobs_service

    calls = 0

    async def flaky(db):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database hiccup")
        return 0

    monkeypatch.setattr(settings, "stale_job_sweep_interval_seconds", 0.02)
    monkeypatch.setattr(jobs_service, "fail_stale_jobs", flaky)

    async with main.app.router.lifespan_context(main.app):
        for _ in range(100):
            if calls >= 3:
                break
            await asyncio.sleep(0.02)
    stopped_at = calls
    await asyncio.sleep(0.1)

    assert stopped_at >= 3  # kept going after the first sweep raised
    assert calls == stopped_at  # and stopped when the API shut down


# --- the worker's side --------------------------------------------------------


async def test_claiming_a_job_records_its_first_heartbeat(auth_client, fake_pipeline):
    from app.worker.tasks import run_story_job

    body = await create_job(auth_client)
    assert load_job(body["id"]).heartbeat_at is None

    run_story_job(body["id"])

    job = load_job(body["id"])
    assert job.heartbeat_at is not None
    assert job.heartbeat_at >= job.started_at


async def test_the_heartbeat_keeps_beating_while_the_job_is_busy(
    auth_client, fake_pipeline, monkeypatch
):
    """The scrape below touches the database only at the start; without the
    background thread the heartbeat would never move past the claim."""
    from app.worker import tasks
    from app.worker.tasks import run_story_job

    class SlowStory(tasks.Story):
        def write(self, output_dir):
            time.sleep(0.5)
            return super().write(output_dir)

    monkeypatch.setattr(tasks, "Story", SlowStory)
    monkeypatch.setattr(settings, "job_heartbeat_interval_seconds", 0.05)
    body = await create_job(auth_client)

    run_story_job(body["id"])

    job = load_job(body["id"])
    assert job.status.value == "success"
    assert job.heartbeat_at - job.started_at > timedelta(seconds=0.2)


def recorded_by_db_clock(job_id: str, column: str) -> bool:
    """Is the column within the last minute, and not in the future, by the
    database's own clock? Judged in SQL so no Python clock is involved."""
    import uuid

    from sqlalchemy import text

    from app.db import get_sync_db

    assert column in ("started_at", "heartbeat_at", "finished_at", "email_sent_at")
    with get_sync_db() as session:
        return session.execute(
            text(
                f"SELECT {column} > now() - interval '1 minute' AND {column} <= now() "
                "FROM jobs WHERE id = :id"
            ),
            {"id": uuid.UUID(job_id)},
        ).scalar_one()


async def test_the_worker_never_reads_its_own_clock(
    auth_client, fake_pipeline, smtp_settings, monkeypatch
):
    """Every timestamp the worker records comes from the database's now(), so a
    worker with a wrong clock can neither look dead nor immortal to the sweep,
    and all the job's timestamps can be compared with each other.

    Any use of `datetime` in the worker module would hit the trap below."""
    from app.worker import tasks
    from app.worker.tasks import run_story_job

    class NoWorkerClock:
        @classmethod
        def now(cls, *args, **kwargs):
            raise AssertionError("the worker read its own clock")

    class SlowStory(tasks.Story):
        def write(self, output_dir):
            time.sleep(0.3)  # long enough for several beats
            return super().write(output_dir)

    monkeypatch.setattr(tasks, "datetime", NoWorkerClock, raising=False)
    monkeypatch.setattr(tasks, "Story", SlowStory)
    monkeypatch.setattr(tasks, "send_ebook", lambda title, path, cfg: None)
    monkeypatch.setattr(settings, "job_heartbeat_interval_seconds", 0.05)
    await auth_client.put("/api/settings", json=smtp_settings)
    resp = await auth_client.post(
        "/api/jobs", json={"url": "https://example.com/chapter-1", "send_email": True}
    )
    job_id = resp.json()["id"]

    run_story_job(job_id)

    job = load_job(job_id)
    assert job.status.value == "success", job.error
    assert job.email_status.value == "sent"
    for column in ("started_at", "heartbeat_at", "finished_at", "email_sent_at"):
        assert recorded_by_db_clock(job_id, column), column


async def test_a_resent_email_is_timestamped_by_the_database_clock(
    auth_client, make_job, smtp_settings, monkeypatch
):
    from app.worker import tasks
    from app.worker.tasks import email_artifact_task

    class NoWorkerClock:
        @classmethod
        def now(cls, *args, **kwargs):
            raise AssertionError("the worker read its own clock")

    monkeypatch.setattr(tasks, "datetime", NoWorkerClock, raising=False)
    monkeypatch.setattr(tasks, "send_ebook", lambda title, path, cfg: None)
    await auth_client.put("/api/settings", json=smtp_settings)
    job_id = await make_job()

    email_artifact_task(job_id)

    assert load_job(job_id).email_status.value == "sent"
    assert recorded_by_db_clock(job_id, "email_sent_at")


def test_the_default_threshold_tolerates_several_missed_heartbeats():
    fields = type(settings).model_fields
    interval = fields["job_heartbeat_interval_seconds"].default
    stale_after = fields["job_stale_after_seconds"].default

    assert stale_after >= 3 * interval


async def test_the_heartbeat_thread_stops_when_the_job_ends(
    auth_client, fake_pipeline, monkeypatch
):
    from app.worker.tasks import run_story_job

    monkeypatch.setattr(settings, "job_heartbeat_interval_seconds", 0.05)
    body = await create_job(auth_client)

    run_story_job(body["id"])

    assert [t for t in threading.enumerate() if t.name.startswith("heartbeat-")] == []


async def test_the_heartbeat_stops_when_the_job_fails(auth_client, monkeypatch, fake_pipeline):
    from app.worker import tasks
    from app.worker.tasks import run_story_job

    class Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("site is down")

    monkeypatch.setattr(tasks, "Story", Boom)
    monkeypatch.setattr(settings, "job_heartbeat_interval_seconds", 0.05)
    body = await create_job(auth_client)

    run_story_job(body["id"])

    assert load_job(body["id"]).status.value == "failed"
    assert [t for t in threading.enumerate() if t.name.startswith("heartbeat-")] == []


async def test_a_late_heartbeat_does_not_revive_a_job_the_sweep_has_failed(
    auth_client, fake_pipeline, monkeypatch
):
    """A worker that stalled past the threshold and was failed by the sweep is
    still running its heartbeat thread. The beat only writes while the job is
    `running`, so it cannot stamp a fresh heartbeat onto the failed job."""
    from app.worker import tasks
    from app.worker.tasks import run_story_job

    body = await create_job(auth_client)
    snapshot = {}

    class ReapedMidRun(tasks.Story):
        def write(self, output_dir):
            set_status(body["id"], "failed")  # what the sweep would have done
            snapshot["heartbeat_at"] = load_job(body["id"]).heartbeat_at
            time.sleep(0.3)  # many beats' worth
            return super().write(output_dir)

    monkeypatch.setattr(tasks, "Story", ReapedMidRun)
    monkeypatch.setattr(settings, "job_heartbeat_interval_seconds", 0.05)

    run_story_job(body["id"])

    assert load_job(body["id"]).heartbeat_at == snapshot["heartbeat_at"]


# --- retrying a job that already produced artifacts ---------------------------


async def test_retrying_after_a_failed_conversion_does_not_duplicate_artifacts(
    auth_client, fake_pipeline, monkeypatch
):
    from app.worker import tasks
    from app.worker.tasks import run_story_job
    from story_scraper.converter import ConversionError

    working_convert = tasks.convert

    def failing_convert(html_file, ebook_file, title, timeout=None, **metadata):
        raise ConversionError("calibre exploded")

    monkeypatch.setattr(tasks, "convert", failing_convert)
    body = await create_job(auth_client)
    run_story_job(body["id"])
    assert [a.kind for a in load_job(body["id"]).artifacts] == ["html"]

    monkeypatch.setattr(tasks, "convert", working_convert)
    assert (await auth_client.post(f"/api/jobs/{body['id']}/retry")).status_code == 200
    run_story_job(body["id"])

    job = load_job(body["id"])
    assert job.status.value == "success"
    assert sorted(a.kind for a in job.artifacts) == ["epub", "html"]
