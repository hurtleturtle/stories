"""Creating, cancelling, retrying and running jobs.

The worker tests call the Celery task function directly, with the scraper and
converter swapped for fakes, so they cover the claim/skip logic and the
resulting job state without a broker, network or Calibre.
"""

import uuid

import pytest

RUN_TASK = "app.worker.tasks.run_story_job"


def load_job(job_id: str):
    from app.db import get_sync_db
    from app.models import Job

    session = get_sync_db()
    try:
        return session.get(Job, uuid.UUID(job_id))
    finally:
        session.close()


def set_status(job_id: str, status: str) -> None:
    from app.db import get_sync_db
    from app.models import Job, JobStatus

    session = get_sync_db()
    try:
        session.get(Job, uuid.UUID(job_id)).status = JobStatus(status)
        session.commit()
    finally:
        session.close()


async def create_job(auth_client, url="https://example.com/chapter-1") -> dict:
    resp = await auth_client.post("/api/jobs", json={"url": url})
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def revoked(monkeypatch) -> list[str]:
    """Stand in for Celery's revoke, which would otherwise need a broker."""
    from app.worker.celery_app import celery_app

    calls: list[str] = []
    monkeypatch.setattr(celery_app.control, "revoke", lambda task_id, **kw: calls.append(task_id))
    return calls


@pytest.fixture
def fake_pipeline(monkeypatch, tmp_path):
    """Replace scraping and conversion in the worker; records what ran."""
    ran: list[str] = []

    class FakeStory:
        def __init__(self, config, progress=None):
            self.config = config
            self.progress = progress

        def __enter__(self):
            ran.append("scrape")
            return self

        def __exit__(self, *exc_info):
            pass

        def write(self, output_dir):
            self.progress(1, "https://example.com/chapter-1")
            html = output_dir / f"{self.config.resolved_filename()}.html"
            html.write_text("<html></html>")
            return html

    def fake_convert(html_file, ebook_file, title):
        ran.append("convert")
        ebook_file.write_text("ebook")
        return ebook_file

    monkeypatch.setattr("app.worker.tasks.Story", FakeStory)
    monkeypatch.setattr("app.worker.tasks.convert", fake_convert)
    monkeypatch.setattr("app.worker.tasks.job_dir", lambda owner_id, job_id: tmp_path)
    return ran


# --- creating jobs ---------------------------------------------------------


async def test_a_new_job_is_dispatched_under_the_task_id_stored_on_it(auth_client, queued_tasks):
    body = await create_job(auth_client)

    (name, args), kwargs = queued_tasks[-1], queued_tasks.kwargs[-1]
    assert (name, args) == (RUN_TASK, [body["id"]])
    assert kwargs["task_id"]
    assert load_job(body["id"]).celery_task_id == kwargs["task_id"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:6379/",
        "http://10.0.0.5/chapter-1",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.com/chapter-1",
        "not a url",
    ],
)
async def test_jobs_cannot_target_internal_or_non_http_urls(auth_client, queued_tasks, url):
    resp = await auth_client.post("/api/jobs", json={"url": url})

    assert resp.status_code == 422, resp.text
    assert queued_tasks == []
    assert (await auth_client.get("/api/jobs")).json()["total"] == 0


async def test_a_hostname_resolving_to_a_private_address_is_refused(
    auth_client, queued_tasks, monkeypatch
):
    monkeypatch.setattr("story_scraper.urlsafety.resolve_host", lambda host, port: ["172.18.0.3"])

    resp = await auth_client.post("/api/jobs", json={"url": "http://redis:6379/"})

    assert resp.status_code == 422
    assert "non-public" in resp.json()["detail"]
    assert queued_tasks == []


async def test_an_ebook_type_that_could_carry_a_path_is_refused(auth_client, queued_tasks):
    resp = await auth_client.post(
        "/api/jobs", json={"url": "https://example.com/1", "ebook_type": "../../x"}
    )

    assert resp.status_code == 422
    assert queued_tasks == []


async def test_a_title_with_path_characters_is_accepted(auth_client):
    """The title is display text; only the filename derived from it is made safe."""
    resp = await auth_client.post(
        "/api/jobs", json={"url": "https://example.com/1", "title": "Fate/Zero"}
    )

    assert resp.status_code == 201
    assert resp.json()["title"] == "Fate/Zero"


# --- cancelling ------------------------------------------------------------


async def test_cancelling_revokes_the_task_it_was_dispatched_as(
    auth_client, queued_tasks, revoked
):
    body = await create_job(auth_client)

    resp = await auth_client.post(f"/api/jobs/{body['id']}/cancel")

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"
    assert revoked == [queued_tasks.kwargs[-1]["task_id"]]


async def test_a_running_job_cannot_be_cancelled(auth_client, revoked):
    body = await create_job(auth_client)
    set_status(body["id"], "running")

    resp = await auth_client.post(f"/api/jobs/{body['id']}/cancel")

    assert resp.status_code == 409
    assert revoked == []
    assert load_job(body["id"]).status.value == "running"


async def test_cancel_does_not_overwrite_a_job_a_worker_claimed_meanwhile(
    auth_client, revoked, monkeypatch
):
    """The request checked `pending`, then a worker started the job before the
    cancel was written. The write is conditional, so the job keeps running."""
    from sqlalchemy.orm.attributes import set_committed_value

    from app.models import JobStatus
    from app.routers import jobs as jobs_router

    body = await create_job(auth_client)
    set_status(body["id"], "running")

    real_get = jobs_router._get_owned_job

    async def stale_view(db, user, job_id):
        job = await real_get(db, user, job_id)
        set_committed_value(job, "status", JobStatus.pending)  # what the request saw
        return job

    monkeypatch.setattr(jobs_router, "_get_owned_job", stale_view)

    resp = await auth_client.post(f"/api/jobs/{body['id']}/cancel")

    assert resp.status_code == 409
    assert revoked == []
    assert load_job(body["id"]).status.value == "running"


# --- retrying --------------------------------------------------------------


async def test_retry_dispatches_under_a_fresh_task_id(auth_client, queued_tasks):
    body = await create_job(auth_client)
    first_task_id = queued_tasks.kwargs[-1]["task_id"]
    set_status(body["id"], "failed")

    resp = await auth_client.post(f"/api/jobs/{body['id']}/retry")

    assert resp.status_code == 200, resp.text
    retry_task_id = queued_tasks.kwargs[-1]["task_id"]
    assert retry_task_id and retry_task_id != first_task_id
    assert load_job(body["id"]).celery_task_id == retry_task_id


# --- the worker ------------------------------------------------------------


async def test_the_worker_runs_a_pending_job(auth_client, fake_pipeline):
    from app.worker.tasks import run_story_job

    body = await create_job(auth_client)

    run_story_job(body["id"])

    job = load_job(body["id"])
    assert job.status.value == "success", job.error
    assert fake_pipeline == ["scrape", "convert"]
    assert job.started_at is not None and job.finished_at is not None
    assert job.chapters_scraped == 1
    assert sorted(a.kind for a in job.artifacts) == ["epub", "html"]


async def test_the_worker_skips_a_job_cancelled_while_it_was_queued(
    auth_client, revoked, fake_pipeline
):
    """Revoking only reaches workers that hear the broadcast, so a cancelled
    job can still be delivered. It must not be resurrected and scraped."""
    from app.worker.tasks import run_story_job

    body = await create_job(auth_client)
    await auth_client.post(f"/api/jobs/{body['id']}/cancel")

    run_story_job(body["id"])

    job = load_job(body["id"])
    assert job.status.value == "cancelled"
    assert job.started_at is None and job.finished_at is None
    assert fake_pipeline == []


@pytest.mark.parametrize("status", ["running", "success", "failed"])
async def test_the_worker_ignores_a_redelivered_job_that_is_not_pending(
    auth_client, fake_pipeline, status
):
    """A long job can be handed to a second worker once the broker's
    visibility timeout passes. The second delivery must leave the job alone,
    including not stamping a finish time on one that is still running."""
    from app.worker.tasks import run_story_job

    body = await create_job(auth_client)
    set_status(body["id"], status)

    run_story_job(body["id"])

    job = load_job(body["id"])
    assert job.status.value == status
    assert job.finished_at is None
    assert fake_pipeline == []


async def test_the_worker_ignores_a_job_that_no_longer_exists(db_engine, fake_pipeline):
    from app.worker.tasks import run_story_job

    run_story_job(str(uuid.uuid4()))

    assert fake_pipeline == []


async def test_a_second_delivery_of_the_same_job_runs_nothing(auth_client, fake_pipeline):
    from app.worker.tasks import run_story_job

    body = await create_job(auth_client)
    run_story_job(body["id"])
    fake_pipeline.clear()

    run_story_job(body["id"])

    assert fake_pipeline == []
    assert load_job(body["id"]).status.value == "success"


async def test_a_scrape_failure_is_recorded_on_the_job(auth_client, monkeypatch, fake_pipeline):
    from app.worker.tasks import run_story_job

    class Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("site is down")

    monkeypatch.setattr("app.worker.tasks.Story", Boom)
    body = await create_job(auth_client)

    run_story_job(body["id"])

    job = load_job(body["id"])
    assert job.status.value == "failed"
    assert "site is down" in job.error
    assert job.finished_at is not None
