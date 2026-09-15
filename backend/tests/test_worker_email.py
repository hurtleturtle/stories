"""The worker half of send-to-Kindle: recording what happened on the job."""

import uuid
from unittest.mock import patch


def load_job(job_id: str):
    """Re-read a job through a fresh sync session, as the worker would."""
    from app.db import get_sync_db
    from app.models import Job

    session = get_sync_db()
    try:
        return session.get(Job, uuid.UUID(job_id))
    finally:
        session.close()


async def test_successful_send_is_recorded_on_the_job(auth_client, make_job, smtp_settings):
    from app.models import EmailStatus
    from app.worker.tasks import email_artifact_task

    await auth_client.put("/api/settings", json=smtp_settings)
    job_id = await make_job()

    with patch("app.worker.tasks.send_ebook") as send_ebook:
        email_artifact_task(job_id)

    title, path, cfg = send_ebook.call_args.args
    assert title == "My Book"
    assert path.name == "My_Book.epub"
    # The stored SMTP username is what gets authenticated with.
    assert cfg.login_user() == "smtp-login@example.com"
    assert cfg.password == "app-password"

    job = load_job(job_id)
    assert job.email_status == EmailStatus.sent
    assert job.email_recipient == "me@kindle.com"
    assert job.email_sent_at is not None
    assert job.email_error is None
    assert "Emailed My_Book.epub to me@kindle.com." in job.log


async def test_smtp_failure_is_recorded_not_raised(auth_client, make_job, smtp_settings):
    from app.models import EmailStatus
    from app.worker.tasks import email_artifact_task

    await auth_client.put("/api/settings", json=smtp_settings)
    job_id = await make_job()

    with patch("app.worker.tasks.send_ebook", side_effect=OSError("535 auth failed")):
        email_artifact_task(job_id)

    job = load_job(job_id)
    assert job.email_status == EmailStatus.failed
    assert "535 auth failed" in job.email_error
    assert job.email_sent_at is None


async def test_incomplete_settings_are_reported_on_the_job(
    auth_client, make_job, smtp_settings
):
    from app.models import EmailStatus
    from app.worker.tasks import email_artifact_task

    await auth_client.put("/api/settings", json={**smtp_settings, "kindle_address": None})
    job_id = await make_job()

    with patch("app.worker.tasks.send_ebook") as send_ebook:
        email_artifact_task(job_id)

    send_ebook.assert_not_called()
    job = load_job(job_id)
    assert job.email_status == EmailStatus.failed
    assert "Kindle address" in job.email_error


async def test_task_without_an_artifact_id_sends_the_ebook(
    auth_client, make_job, smtp_settings
):
    from app.worker.tasks import email_artifact_task

    await auth_client.put("/api/settings", json=smtp_settings)
    job_id = await make_job(kinds=("html", "epub", "mobi"), ebook_type="mobi")

    with patch("app.worker.tasks.send_ebook") as send_ebook:
        email_artifact_task(job_id)

    assert send_ebook.call_args.args[1].name == "My_Book.mobi"


async def test_task_reports_a_job_with_nothing_sendable(auth_client, make_job, smtp_settings):
    from app.models import EmailStatus
    from app.worker.tasks import email_artifact_task

    await auth_client.put("/api/settings", json=smtp_settings)
    job_id = await make_job(kinds=("html",))

    with patch("app.worker.tasks.send_ebook") as send_ebook:
        email_artifact_task(job_id)

    send_ebook.assert_not_called()
    job = load_job(job_id)
    assert job.email_status == EmailStatus.failed
    assert "No sendable ebook artifact" in job.email_error
