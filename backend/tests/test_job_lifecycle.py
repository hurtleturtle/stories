"""Creating, cancelling, retrying and running jobs.

The worker tests call the Celery task function directly, with the scraper and
converter swapped for fakes, so they cover the claim/skip logic and the
resulting job state without a broker, network or Calibre.
"""

import uuid

import pytest
from jobhelpers import create_job, load_job, set_status

RUN_TASK = "app.worker.tasks.run_story_job"


@pytest.fixture
def revoked(monkeypatch) -> list[str]:
    """Stand in for Celery's revoke, which would otherwise need a broker."""
    from app.worker.celery_app import celery_app

    calls: list[str] = []
    monkeypatch.setattr(celery_app.control, "revoke", lambda task_id, **kw: calls.append(task_id))
    return calls


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


async def test_an_unsupported_ebook_type_is_refused_and_the_choices_listed(
    auth_client, queued_tasks
):
    resp = await auth_client.post(
        "/api/jobs", json={"url": "https://example.com/1", "ebook_type": "docx"}
    )

    assert resp.status_code == 422
    assert "choose one of: epub, azw3, pdf" in resp.json()["detail"][0]["msg"]
    assert queued_tasks == []


@pytest.mark.parametrize("ebook_type", ["epub", "azw3", "pdf", "PDF"])
async def test_every_supported_ebook_type_can_be_requested(auth_client, ebook_type):
    resp = await auth_client.post(
        "/api/jobs", json={"url": "https://example.com/1", "ebook_type": ebook_type}
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["artifacts"] == []


def test_every_supported_ebook_type_has_a_content_type_and_an_email_mime_type():
    from pathlib import Path

    from app.worker.tasks import CONTENT_TYPES
    from story_scraper.config import EBOOK_TYPES
    from story_scraper.mailer import _mime_type

    for kind in EBOOK_TYPES:
        assert CONTENT_TYPES[kind] != "application/octet-stream", kind
        assert _mime_type(Path(f"Book.{kind}"))[0] == "application", kind
    assert _mime_type(Path("Book.azw3")) == ("application", "vnd.amazon.ebook")


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


async def test_a_running_job_can_be_cancelled(auth_client, revoked):
    """Nothing to revoke: the worker is already on it and stops at its next chapter."""
    body = await create_job(auth_client)
    set_status(body["id"], "running")

    resp = await auth_client.post(f"/api/jobs/{body['id']}/cancel")

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"
    assert revoked == []
    assert load_job(body["id"]).status.value == "cancelled"


@pytest.mark.parametrize("status", ["success", "failed", "cancelled"])
async def test_a_finished_job_cannot_be_cancelled(auth_client, revoked, status):
    body = await create_job(auth_client)
    set_status(body["id"], status)

    resp = await auth_client.post(f"/api/jobs/{body['id']}/cancel")

    assert resp.status_code == 409
    assert "pending or running" in resp.json()["detail"]
    assert load_job(body["id"]).status.value == status


async def test_cancelling_a_job_the_worker_has_claimed_meanwhile_still_cancels_it(
    auth_client, revoked, monkeypatch
):
    """The request saw `pending`, and a worker started the job before the cancel
    was written. It is running now, which can be cancelled too."""
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

    assert resp.status_code == 200
    assert load_job(body["id"]).status.value == "cancelled"


async def test_cancel_does_not_overwrite_a_job_that_finished_meanwhile(
    auth_client, revoked, monkeypatch
):
    """The request saw `running`, and the job finished before the cancel was
    written. The write is conditional, so the finished job is left alone."""
    from sqlalchemy.orm.attributes import set_committed_value

    from app.models import JobStatus
    from app.routers import jobs as jobs_router

    body = await create_job(auth_client)
    set_status(body["id"], "success")
    real_get = jobs_router._get_owned_job

    async def stale_view(db, user, job_id):
        job = await real_get(db, user, job_id)
        set_committed_value(job, "status", JobStatus.running)  # what the request saw
        return job

    monkeypatch.setattr(jobs_router, "_get_owned_job", stale_view)

    resp = await auth_client.post(f"/api/jobs/{body['id']}/cancel")

    assert resp.status_code == 409
    assert revoked == []
    assert load_job(body["id"]).status.value == "success"


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


async def test_a_conversion_failure_keeps_the_scraped_html(auth_client, monkeypatch, fake_pipeline):
    """Calibre failing should not throw away a book that was fully scraped."""
    from app.worker.tasks import run_story_job
    from story_scraper.converter import ConversionError

    def failing_convert(html_file, ebook_file, title, timeout=None, **metadata):
        raise ConversionError("calibre exploded")

    monkeypatch.setattr("app.worker.tasks.convert", failing_convert)
    body = await create_job(auth_client)

    run_story_job(body["id"])

    job = load_job(body["id"])
    assert job.status.value == "failed"
    assert "calibre exploded" in job.error
    assert [a.kind for a in job.artifacts] == ["html"]


async def test_the_worker_bounds_how_long_conversion_can_take(
    auth_client, monkeypatch, fake_pipeline
):
    from app.worker.tasks import run_story_job
    from story_scraper.config import settings

    timeouts: list[float] = []

    def recording_convert(html_file, ebook_file, title, timeout=None, **metadata):
        timeouts.append(timeout)
        ebook_file.write_text("ebook")
        return ebook_file

    monkeypatch.setattr("app.worker.tasks.convert", recording_convert)
    body = await create_job(auth_client)

    run_story_job(body["id"])

    assert timeouts == [settings.conversion_timeout_seconds]


def test_the_broker_waits_longer_than_an_hour_before_redelivering_a_task():
    """Redis' default of one hour is shorter than a big scrape, and with
    acks_late the task stays unacknowledged until it finishes."""
    from app.worker.celery_app import celery_app
    from story_scraper.config import settings

    timeout = celery_app.conf.broker_transport_options["visibility_timeout"]
    assert timeout == settings.broker_visibility_timeout_seconds
    assert timeout > 60 * 60


# --- style, scripts and ebook type from the request --------------------------


@pytest.mark.parametrize("style", ["../../etc/passwd", "/etc/passwd", "nope.css", ""])
async def test_a_job_cannot_name_a_stylesheet_outside_the_bundled_ones(
    auth_client, queued_tasks, style
):
    resp = await auth_client.post(
        "/api/jobs", json={"url": "https://example.com/1", "style": style}
    )

    assert resp.status_code == 422
    assert queued_tasks == []


@pytest.mark.parametrize("script", ["/etc/passwd", "../x.js", "scripts/scroll_tracker.js", "x.js"])
async def test_a_job_cannot_name_a_script_outside_the_bundled_ones(
    auth_client, queued_tasks, script
):
    resp = await auth_client.post(
        "/api/jobs", json={"url": "https://example.com/1", "scripts": [script]}
    )

    assert resp.status_code == 422
    assert queued_tasks == []


async def test_a_job_can_use_the_bundled_style_and_script(auth_client):
    resp = await auth_client.post(
        "/api/jobs",
        json={
            "url": "https://example.com/1",
            "style": "black-style.css",
            "scripts": ["scroll_tracker.js"],
        },
    )

    assert resp.status_code == 201, resp.text


async def test_templates_cannot_name_files_outside_the_bundled_assets(auth_client):
    base = {"name": "t", "container": "div", "next_selector": "a"}

    bad_style = await auth_client.post("/api/templates", json={**base, "style": "../../x.css"})
    bad_script = await auth_client.post("/api/templates", json={**base, "scripts": ["/etc/passwd"]})
    bad_type = await auth_client.post("/api/templates", json={**base, "ebook_type": "../x"})
    ok = await auth_client.post(
        "/api/templates", json={**base, "style": "black-style.css", "ebook_type": "PDF"}
    )

    assert (bad_style.status_code, bad_script.status_code, bad_type.status_code) == (422, 422, 422)
    assert ok.status_code == 201
    assert ok.json()["ebook_type"] == "pdf"

    template_id = ok.json()["id"]
    update = await auth_client.put(f"/api/templates/{template_id}", json={"style": "../../x.css"})
    assert update.status_code == 422


# --- downloading -----------------------------------------------------------


async def _job_with_artifact_at(auth_client, path) -> tuple[str, str]:
    from app.db import AsyncSessionLocal
    from app.models import Artifact

    body = await create_job(auth_client)
    artifact = Artifact(
        job_id=uuid.UUID(body["id"]),
        kind="epub",
        filename="Book.epub",
        path=str(path),
        size_bytes=5,
        content_type="application/epub+zip",
    )
    async with AsyncSessionLocal() as db:
        db.add(artifact)
        await db.commit()
    return body["id"], str(artifact.id)


async def test_downloading_an_artifact_returns_the_file(auth_client, tmp_path):
    book = tmp_path / "Book.epub"
    book.write_bytes(b"ebook")
    job_id, artifact_id = await _job_with_artifact_at(auth_client, book)

    resp = await auth_client.get(f"/api/jobs/{job_id}/artifacts/{artifact_id}")

    assert resp.status_code == 200
    assert resp.content == b"ebook"


async def test_downloading_an_artifact_whose_file_is_gone_is_a_404(auth_client, tmp_path):
    job_id, artifact_id = await _job_with_artifact_at(auth_client, tmp_path / "missing.epub")

    resp = await auth_client.get(f"/api/jobs/{job_id}/artifacts/{artifact_id}")

    assert resp.status_code == 404


# --- MOBI is no longer offered ---------------------------------------------------


@pytest.mark.parametrize("ebook_type", ["mobi", "MOBI"])
async def test_mobi_is_no_longer_accepted_for_jobs_or_templates(
    auth_client, queued_tasks, ebook_type
):
    job = await auth_client.post(
        "/api/jobs", json={"url": "https://example.com/1", "ebook_type": ebook_type}
    )
    template = await auth_client.post(
        "/api/templates",
        json={"name": "t", "container": "div", "next_selector": "a", "ebook_type": ebook_type},
    )

    assert (job.status_code, template.status_code) == (422, 422)
    assert "choose one of: epub, azw3, pdf" in job.json()["detail"][0]["msg"]
    assert queued_tasks == []


async def test_a_mobi_artifact_from_before_still_downloads(auth_client, tmp_path):
    """Only new production is dropped: books already made stay retrievable."""
    from test_storage import _artifact_with_path

    book = tmp_path / "Old_Book.mobi"
    book.write_bytes(b"old mobi")
    job_id, artifact_id = await _artifact_with_path(auth_client, str(book))

    resp = await auth_client.get(f"/api/jobs/{job_id}/artifacts/{artifact_id}")

    assert resp.status_code == 200 and resp.content == b"old mobi"


def test_a_legacy_mobi_artifact_is_never_chosen_for_kindle():
    from types import SimpleNamespace

    from app.services.email import pick_sendable_artifact

    artifacts = [SimpleNamespace(kind="html"), SimpleNamespace(kind="mobi")]

    assert pick_sendable_artifact(artifacts, preferred_kind="mobi") is None
    epub = SimpleNamespace(kind="epub")
    assert pick_sendable_artifact([*artifacts, epub], preferred_kind="mobi") is epub


# --- the options the UI offers ---------------------------------------------------


async def test_options_list_what_a_template_or_job_may_name(auth_client):
    resp = await auth_client.get("/api/options")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ebook_types"] == ["epub", "azw3", "pdf"]
    assert "white-style.css" in body["styles"] and "black-style.css" in body["styles"]
    assert body["scripts"] == ["scroll_tracker.js"]


async def test_every_option_offered_is_accepted_by_the_api(auth_client):
    options = (await auth_client.get("/api/options")).json()

    for style in options["styles"]:
        for ebook_type in options["ebook_types"]:
            resp = await auth_client.post(
                "/api/jobs",
                json={"url": "https://example.com/1", "style": style, "ebook_type": ebook_type},
            )
            assert resp.status_code == 201, (style, ebook_type, resp.text)


async def test_options_need_a_login(client):
    assert (await client.get("/api/options")).status_code == 401


# --- a template holding values that are no longer valid ---------------------------


async def _template_with(auth_client, **stored) -> str:
    """Create a template, then overwrite columns directly - as old data would be."""
    from sqlalchemy import update

    from app.db import AsyncSessionLocal
    from app.models import Template

    base = {"name": "old", "container": "div.chapter-content", "next_selector": "a#next_chap"}
    template_id = (await auth_client.post("/api/templates", json=base)).json()["id"]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Template).where(Template.id == uuid.UUID(template_id)).values(**stored)
        )
        await db.commit()
    return template_id


async def test_a_job_from_a_template_with_stale_values_says_what_is_wrong(
    auth_client, queued_tasks
):
    """Was an unhandled validation error, so a 500 with nothing to act on."""
    template_id = await _template_with(auth_client, ebook_type="mobi", style="gone.css")

    resp = await auth_client.post(
        "/api/jobs", json={"url": "https://example.com/1", "template_id": template_id}
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "Template 'old'" in detail
    assert "ebook_type: Unsupported ebook type 'mobi'" in detail
    assert "style: Unknown style 'gone.css'" in detail
    assert queued_tasks == []


async def test_the_stale_template_can_still_be_listed_and_fixed(auth_client):
    template_id = await _template_with(auth_client, ebook_type="mobi")

    listed = (await auth_client.get("/api/templates")).json()
    assert [t["ebook_type"] for t in listed] == ["mobi"]  # shown, so it can be corrected

    fixed = await auth_client.put(f"/api/templates/{template_id}", json={"ebook_type": "epub"})
    assert fixed.status_code == 200 and fixed.json()["ebook_type"] == "epub"


async def test_overriding_a_stale_template_value_in_the_request_fixes_the_job(auth_client):
    template_id = await _template_with(auth_client, ebook_type="mobi")

    resp = await auth_client.post(
        "/api/jobs",
        json={"url": "https://example.com/1", "template_id": template_id, "ebook_type": "epub"},
    )

    assert resp.status_code == 201, resp.text


# --- author and language ---------------------------------------------------------------


async def test_an_author_and_language_are_kept_on_the_job(auth_client):
    resp = await auth_client.post(
        "/api/jobs",
        json={"url": "https://example.com/1", "author": "Jane Doe", "language": "en-GB"},
    )

    assert resp.status_code == 201, resp.text
    config = load_job(resp.json()["id"]).config
    assert (config["author"], config["language"]) == ("Jane Doe", "en-GB")


@pytest.mark.parametrize(
    ("field", "value"),
    [("author", ""), ("author", "two\nlines"), ("language", "english!"), ("language", "--x")],
)
async def test_a_bad_author_or_language_is_refused(auth_client, queued_tasks, field, value):
    resp = await auth_client.post("/api/jobs", json={"url": "https://example.com/1", field: value})

    assert resp.status_code == 422
    assert queued_tasks == []


async def test_the_worker_hands_the_author_and_language_to_the_converter(
    auth_client, fake_pipeline, monkeypatch
):
    from app.worker.tasks import run_story_job

    received: list[dict] = []

    def recording_convert(html_file, ebook_file, title, timeout=None, **metadata):
        received.append(metadata)
        ebook_file.write_text("ebook")
        return ebook_file

    monkeypatch.setattr("app.worker.tasks.convert", recording_convert)
    with_metadata = await auth_client.post(
        "/api/jobs", json={"url": "https://example.com/1", "author": "Jane", "language": "fr"}
    )
    without = await create_job(auth_client)

    run_story_job(with_metadata.json()["id"])
    run_story_job(without["id"])

    assert received == [
        {"authors": "Jane", "language": "fr"},
        {"authors": None, "language": None},
    ]
