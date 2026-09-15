"""Resending a finished job's ebook to Kindle."""

import uuid

import pytest

EMAIL_TASK = "app.worker.tasks.email_artifact_task"


def email_dispatches(queued_tasks) -> list:
    return [t for t in queued_tasks if t[0] == EMAIL_TASK]


async def test_new_job_reports_no_email_sent(auth_client, make_job):
    job_id = await make_job()

    body = (await auth_client.get(f"/api/jobs/{job_id}")).json()

    assert body["email_status"] == "not_sent"
    assert body["email_sent_at"] is None
    assert body["email_error"] is None


async def test_resend_queues_the_ebook_and_marks_the_job_pending(
    auth_client, make_job, smtp_settings, queued_tasks
):
    await auth_client.put("/api/settings", json=smtp_settings)
    job_id = await make_job()

    resp = await auth_client.post(f"/api/jobs/{job_id}/email", json={})

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["email_status"] == "pending"
    assert body["email_recipient"] == "me@kindle.com"

    name, args = email_dispatches(queued_tasks)[-1]
    assert name == EMAIL_TASK
    assert args[0] == job_id

    # The epub, not the intermediate HTML.
    artifacts = {a["id"]: a["kind"] for a in body["artifacts"]}
    assert artifacts[args[1]] == "epub"


async def test_resend_works_with_an_empty_body(
    auth_client, make_job, smtp_settings, queued_tasks
):
    await auth_client.put("/api/settings", json=smtp_settings)
    job_id = await make_job()

    resp = await auth_client.post(f"/api/jobs/{job_id}/email")

    assert resp.status_code == 202, resp.text
    assert len(email_dispatches(queued_tasks)) == 1


async def test_resend_honours_an_explicitly_chosen_artifact(
    auth_client, make_job, smtp_settings, queued_tasks
):
    await auth_client.put("/api/settings", json=smtp_settings)
    job_id = await make_job(kinds=("html", "epub", "mobi"))

    job = (await auth_client.get(f"/api/jobs/{job_id}")).json()
    mobi = next(a for a in job["artifacts"] if a["kind"] == "mobi")

    resp = await auth_client.post(
        f"/api/jobs/{job_id}/email", json={"artifact_id": mobi["id"]}
    )

    assert resp.status_code == 202, resp.text
    assert email_dispatches(queued_tasks)[-1][1][1] == mobi["id"]


async def test_resend_picks_the_format_the_job_produced(
    auth_client, make_job, smtp_settings, queued_tasks
):
    await auth_client.put("/api/settings", json=smtp_settings)
    job_id = await make_job(kinds=("html", "epub", "mobi"), ebook_type="mobi")

    resp = await auth_client.post(f"/api/jobs/{job_id}/email", json={})

    artifacts = {a["id"]: a["kind"] for a in resp.json()["artifacts"]}
    assert artifacts[email_dispatches(queued_tasks)[-1][1][1]] == "mobi"


@pytest.mark.parametrize("status", ["pending", "running", "failed", "cancelled"])
async def test_only_completed_jobs_can_be_emailed(
    auth_client, make_job, smtp_settings, queued_tasks, status
):
    await auth_client.put("/api/settings", json=smtp_settings)
    job_id = await make_job(status=status)

    resp = await auth_client.post(f"/api/jobs/{job_id}/email", json={})

    assert resp.status_code == 409
    assert email_dispatches(queued_tasks) == []


async def test_resend_reports_missing_settings_instead_of_queueing(
    auth_client, make_job, queued_tasks
):
    job_id = await make_job()

    resp = await auth_client.post(f"/api/jobs/{job_id}/email", json={})

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "Kindle address" in detail and "SMTP password" in detail
    assert email_dispatches(queued_tasks) == []


async def test_resend_needs_a_sendable_artifact(
    auth_client, make_job, smtp_settings, queued_tasks
):
    await auth_client.put("/api/settings", json=smtp_settings)
    job_id = await make_job(kinds=("html",))

    resp = await auth_client.post(f"/api/jobs/{job_id}/email", json={})

    assert resp.status_code == 404
    assert email_dispatches(queued_tasks) == []


async def test_resend_on_an_unknown_job_is_not_found(auth_client):
    resp = await auth_client.post(f"/api/jobs/{uuid.uuid4()}/email", json={})
    assert resp.status_code == 404


async def test_another_users_job_cannot_be_emailed(auth_client, client, make_job):
    job_id = await make_job()

    resp = await client.post(
        "/api/auth/register", json={"email": "other@example.com", "password": "pw12345"}
    )
    assert resp.status_code == 201
    token = (
        await client.post(
            "/api/auth/login", data={"username": "other@example.com", "password": "pw12345"}
        )
    ).json()["access_token"]

    resp = await client.post(
        f"/api/jobs/{job_id}/email",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 404


async def test_retry_clears_a_previous_delivery_result(auth_client, make_job):
    from sqlalchemy import select

    from app.db import AsyncSessionLocal
    from app.models import EmailStatus, Job, JobStatus

    job_id = await make_job(status="failed")
    async with AsyncSessionLocal() as db:
        job = (await db.execute(select(Job))).scalar_one()
        job.email_status = EmailStatus.failed
        job.email_error = "SMTP auth failed"
        await db.commit()

    resp = await auth_client.post(f"/api/jobs/{job_id}/retry")

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == JobStatus.pending
    assert resp.json()["email_status"] == "not_sent"
    assert resp.json()["email_error"] is None
