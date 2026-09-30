"""Artifact paths are recorded relative to the artifact folder."""

import shutil
import uuid
from pathlib import Path

import pytest
from jobhelpers import load_job
from sitehelpers import BASE, mount, page

from app.services.storage import job_dir, resolve_stored_path, stored_path
from story_scraper.config import settings


@pytest.fixture
def store(monkeypatch, tmp_path) -> Path:
    root = tmp_path / "artifacts"
    root.mkdir()
    monkeypatch.setattr(settings, "story_folder", str(root))
    return root


def test_a_path_inside_the_folder_is_recorded_relative_to_it(store):
    assert stored_path(store / "user" / "job" / "Book.epub") == "user/job/Book.epub"


def test_a_path_with_spaces_and_unicode_survives(store):
    path = store / "user" / "job" / "Café Ünï 転生.epub"

    assert stored_path(path) == "user/job/Café Ünï 転生.epub"
    assert resolve_stored_path(stored_path(path)) == path.resolve()


def test_a_path_outside_the_folder_is_kept_absolute(store, tmp_path):
    outside = tmp_path / "elsewhere" / "Book.epub"

    assert stored_path(outside) == str(outside)


def test_a_folder_with_a_lookalike_name_is_not_inside_it(store):
    lookalike = store.parent / "artifacts-old" / "Book.epub"

    assert stored_path(lookalike) == str(lookalike)


def test_a_relative_path_is_resolved_from_the_folder(store):
    assert resolve_stored_path("user/job/Book.epub") == (store / "user/job/Book.epub").resolve()


def test_an_absolute_path_from_before_the_change_is_used_as_it_is(store):
    assert resolve_stored_path("/somewhere/old/Book.epub") == Path("/somewhere/old/Book.epub")


@pytest.mark.parametrize(
    "stored", ["../outside.epub", "user/../../outside.epub", "user/job/../../../etc/passwd", ".."]
)
def test_a_relative_path_may_not_climb_out_of_the_folder(store, stored):
    with pytest.raises(ValueError, match="leaves the artifact folder"):
        resolve_stored_path(stored)


def test_a_relative_path_may_not_escape_through_a_symlink(store, tmp_path):
    outside = tmp_path / "secret"
    outside.mkdir()
    (store / "link").symlink_to(outside)

    with pytest.raises(ValueError):
        resolve_stored_path("link/passwd")


def test_recorded_paths_follow_the_folder_when_it_moves(store, tmp_path):
    owner, job = uuid.uuid4(), uuid.uuid4()
    file = job_dir(owner, job) / "Book.epub"
    file.write_text("ebook")
    recorded = stored_path(file)
    assert not recorded.startswith("/")

    moved = tmp_path / "new-mount"
    shutil.move(str(store), str(moved))
    settings.story_folder = str(moved)

    assert resolve_stored_path(recorded).read_text() == "ebook"


# --- through the API and the worker ------------------------------------------------------


async def test_the_worker_records_relative_paths_that_download_and_survive_a_move(
    auth_client, store, tmp_path, monkeypatch
):
    from app.worker.tasks import run_story_job

    def fake_convert(html_file, ebook_file, title, timeout=None):
        ebook_file.write_text("ebook bytes")
        return ebook_file

    monkeypatch.setattr("app.worker.tasks.convert", fake_convert)
    import respx

    with respx.mock:
        mount(c1=page("<p>One.</p>"))
        resp = await auth_client.post(
            "/api/jobs",
            json={"url": BASE + "c1", "container": "div.chapter-content", "next_selector": "a"},
        )
        job_id = resp.json()["id"]
        run_story_job(job_id)

    job = load_job(job_id)
    assert job.status.value == "success", job.error
    assert job.artifacts and all(not a.path.startswith("/") for a in job.artifacts)
    epub = next(a for a in job.artifacts if a.kind == "epub")

    assert (
        await auth_client.get(f"/api/jobs/{job_id}/artifacts/{epub.id}")
    ).content == b"ebook bytes"

    moved = tmp_path / "new-mount"
    shutil.move(str(store), str(moved))
    monkeypatch.setattr(settings, "story_folder", str(moved))
    after = await auth_client.get(f"/api/jobs/{job_id}/artifacts/{epub.id}")
    assert after.status_code == 200 and after.content == b"ebook bytes"


async def _artifact_with_path(auth_client, path: str) -> tuple[str, str]:
    from jobhelpers import create_job

    from app.db import AsyncSessionLocal
    from app.models import Artifact

    body = await create_job(auth_client)
    artifact = Artifact(
        job_id=uuid.UUID(body["id"]),
        kind="epub",
        filename="Book.epub",
        path=path,
        size_bytes=5,
        content_type="application/epub+zip",
    )
    async with AsyncSessionLocal() as db:
        db.add(artifact)
        await db.commit()
    return body["id"], str(artifact.id)


async def test_a_path_recorded_before_the_change_still_downloads(auth_client, store, tmp_path):
    legacy = tmp_path / "legacy" / "Book.epub"
    legacy.parent.mkdir()
    legacy.write_bytes(b"old book")
    job_id, artifact_id = await _artifact_with_path(auth_client, str(legacy))

    resp = await auth_client.get(f"/api/jobs/{job_id}/artifacts/{artifact_id}")

    assert resp.status_code == 200 and resp.content == b"old book"


async def test_a_recorded_path_that_climbs_out_of_the_folder_is_never_served(
    auth_client, store, tmp_path
):
    (tmp_path / "secret.txt").write_text("secret")
    job_id, artifact_id = await _artifact_with_path(auth_client, "../secret.txt")

    resp = await auth_client.get(f"/api/jobs/{job_id}/artifacts/{artifact_id}")

    assert resp.status_code == 404
    assert b"secret" not in resp.content


async def test_a_resent_email_finds_a_file_recorded_by_relative_path(
    auth_client, store, smtp_settings, monkeypatch
):
    from unittest.mock import patch

    from app.worker.tasks import email_artifact_task

    await auth_client.put("/api/settings", json=smtp_settings)
    job_id, artifact_id = await _artifact_with_path(auth_client, "u/j/Book.epub")
    from jobhelpers import set_status

    set_status(job_id, "success")
    (store / "u" / "j").mkdir(parents=True)
    (store / "u" / "j" / "Book.epub").write_text("ebook")

    with patch("app.worker.tasks.send_ebook") as send_ebook:
        email_artifact_task(job_id, artifact_id)

    _, path, _ = send_ebook.call_args.args
    assert path == (store / "u" / "j" / "Book.epub").resolve()
