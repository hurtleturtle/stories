"""Small helpers shared by the job tests: read and poke jobs the way the
worker does, through a sync session, and create one through the API."""

import uuid


def load_job(job_id: str):
    from app.db import get_sync_db
    from app.models import Job

    session = get_sync_db()
    try:
        return session.get(Job, uuid.UUID(job_id))
    finally:
        session.close()


def set_job_fields(job_id: str, **fields) -> None:
    """Write columns straight to the job, e.g. to age its heartbeat."""
    from app.db import get_sync_db
    from app.models import Job, JobStatus

    if "status" in fields:
        fields["status"] = JobStatus(fields["status"])
    session = get_sync_db()
    try:
        job = session.get(Job, uuid.UUID(job_id))
        for name, value in fields.items():
            setattr(job, name, value)
        session.commit()
    finally:
        session.close()


def set_status(job_id: str, status: str) -> None:
    set_job_fields(job_id, status=status)


async def create_job(auth_client, url="https://example.com/chapter-1") -> dict:
    resp = await auth_client.post("/api/jobs", json={"url": url})
    assert resp.status_code == 201, resp.text
    return resp.json()
