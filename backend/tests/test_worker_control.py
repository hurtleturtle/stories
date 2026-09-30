"""How the worker reports progress, and how a running job can be stopped."""

import uuid

import pytest
from jobhelpers import create_job, load_job, set_job_fields, set_status
from sqlalchemy import event

CHAPTER_URL = "https://example.com/chapter-{n}"


def chapter_lines(job) -> list[str]:
    return [line for line in (job.log or "").splitlines() if line.startswith("Chapter ")]


@pytest.fixture
def chapters(monkeypatch, fake_pipeline):
    """Make the worker's fake Story scrape a chosen number of chapters.

    `hook(n)` runs after chapter n's progress report (a chance to act as the API
    or the sweep would), `after()` once the last chapter is done, and
    `stop_reason` is what the story reports for having ended early."""
    from app.worker import tasks

    def configure(count: int, hook=None, after=None, stop_reason=None):
        class Story(tasks.Story):
            def write(self, output_dir):
                for n in range(1, count + 1):
                    self.progress(n, CHAPTER_URL.format(n=n))
                    if hook:
                        hook(n)
                self.stop_reason = stop_reason
                html = output_dir / f"{self.config.resolved_filename()}.html"
                html.write_text("<html></html>")
                if after:
                    after()
                return html

        monkeypatch.setattr(tasks, "Story", Story)

    return configure


# --- the chapter log is written in batches -----------------------------------------------


class Statements:
    """Collects the SQL the worker's sync engine runs."""

    def __init__(self) -> None:
        self.sql: list[str] = []

    def __enter__(self):
        from app.db import sync_engine

        self._engine = sync_engine
        event.listen(sync_engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc_info):
        event.remove(self._engine, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.sql.append(statement)

    def log_writes(self) -> int:
        return sum(1 for s in self.sql if s.startswith("UPDATE jobs SET log="))


async def test_the_chapter_log_is_written_in_batches_not_once_per_chapter(
    auth_client, chapters, fake_pipeline
):
    from app.worker.tasks import run_story_job

    chapters(100)
    body = await create_job(auth_client)

    with Statements() as statements:
        run_story_job(body["id"])

    job = load_job(body["id"])
    assert job.status.value == "success", job.error
    assert job.chapters_scraped == 100
    assert chapter_lines(job) == [f"Chapter {n}: {CHAPTER_URL.format(n=n)}" for n in range(1, 101)]
    # 100 chapters in batches of 25, plus the reset at the start and a final flush.
    assert 1 <= statements.log_writes() <= 8, statements.log_writes()


async def test_the_log_has_no_blank_first_line(auth_client, chapters, fake_pipeline):
    from app.worker.tasks import run_story_job

    chapters(3)
    body = await create_job(auth_client)

    run_story_job(body["id"])

    assert load_job(body["id"]).log.splitlines()[0].startswith("Chapter 1:")


async def test_lines_are_flushed_by_time_when_chapters_come_slowly(auth_client):
    from app.db import get_sync_db
    from app.worker.tasks import _ProgressLog

    body = await create_job(auth_client)
    now = [0.0]
    session = get_sync_db()
    try:
        log = _ProgressLog(session, uuid.UUID(body["id"]), clock=lambda: now[0])

        log.add("Chapter 1: a")
        assert load_job(body["id"]).log is None  # too soon and too few to write

        now[0] += _ProgressLog.FLUSH_SECONDS  # a slow site: time, not count, triggers it
        log.add("Chapter 2: b")
        assert load_job(body["id"]).log == "Chapter 1: a\nChapter 2: b"

        log.add("Chapter 3: c")
        assert load_job(body["id"]).log == "Chapter 1: a\nChapter 2: b"  # held back again
        log.flush()
        assert load_job(body["id"]).log == "Chapter 1: a\nChapter 2: b\nChapter 3: c"
    finally:
        session.close()


async def test_lines_are_flushed_by_count_when_chapters_come_fast(auth_client):
    from app.db import get_sync_db
    from app.worker.tasks import _ProgressLog

    body = await create_job(auth_client)
    session = get_sync_db()
    try:
        log = _ProgressLog(session, uuid.UUID(body["id"]), clock=lambda: 0.0)
        for n in range(1, _ProgressLog.FLUSH_LINES):
            log.add(f"Chapter {n}: x")
        assert load_job(body["id"]).log is None

        log.add("one more")

        assert len(load_job(body["id"]).log.splitlines()) == _ProgressLog.FLUSH_LINES
    finally:
        session.close()


async def test_a_flush_with_nothing_pending_writes_nothing(auth_client):
    from app.db import get_sync_db
    from app.worker.tasks import _ProgressLog

    body = await create_job(auth_client)
    session = get_sync_db()
    try:
        with Statements() as statements:
            _ProgressLog(session, uuid.UUID(body["id"])).flush()
    finally:
        session.close()

    assert statements.log_writes() == 0


async def test_lines_still_waiting_when_a_job_fails_are_not_lost(
    auth_client, monkeypatch, fake_pipeline
):
    from app.worker import tasks
    from app.worker.tasks import run_story_job

    class FailsAfterThree(tasks.Story):
        def write(self, output_dir):
            for n in (1, 2, 3):
                self.progress(n, CHAPTER_URL.format(n=n))
            raise RuntimeError("site fell over")

    monkeypatch.setattr(tasks, "Story", FailsAfterThree)
    body = await create_job(auth_client)

    run_story_job(body["id"])

    job = load_job(body["id"])
    assert job.status.value == "failed" and "site fell over" in job.error
    assert len(chapter_lines(job)) == 3
    assert job.chapters_scraped == 3


async def test_a_fresh_run_starts_a_new_log(auth_client, fake_pipeline):
    from app.worker.tasks import run_story_job

    body = await create_job(auth_client)
    set_job_fields(body["id"], log="Chapter 9: left over from an earlier attempt")

    run_story_job(body["id"])

    assert "left over" not in load_job(body["id"]).log


async def test_notes_are_appended_to_the_chapter_lines_never_replacing_them(
    auth_client, chapters, smtp_settings, monkeypatch
):
    from app.worker import tasks
    from app.worker.tasks import run_story_job

    chapters(3, stop_reason="Stopped after 3 chapters: no more pages")
    monkeypatch.setattr(tasks, "send_ebook", lambda title, path, cfg: None)
    await auth_client.put("/api/settings", json=smtp_settings)
    resp = await auth_client.post(
        "/api/jobs", json={"url": "https://example.com/chapter-1", "send_email": True}
    )
    job_id = resp.json()["id"]

    run_story_job(job_id)

    lines = load_job(job_id).log.splitlines()
    assert [line.split(":")[0] for line in lines[:3]] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert lines[3] == "Stopped after 3 chapters: no more pages"
    assert lines[4].startswith("Emailed ")


# --- stopping a running job ------------------------------------------------------------------


async def test_a_running_job_that_is_cancelled_stops_at_the_next_chapter(
    auth_client, chapters, fake_pipeline
):
    from app.worker.tasks import run_story_job

    reached: list[int] = []
    body = await create_job(auth_client)

    def cancel_after_two(n: int) -> None:
        reached.append(n)
        if n == 2:
            set_status(body["id"], "cancelled")  # what the API does

    chapters(10, hook=cancel_after_two)

    run_story_job(body["id"])

    job = load_job(body["id"])
    # Chapter 3's report is what noticed, so its hook never ran and nothing went further.
    assert reached == [1, 2]
    assert job.status.value == "cancelled"
    assert job.artifacts == [] and "convert" not in fake_pipeline
    assert job.finished_at is not None
    assert job.chapters_scraped == 3
    assert job.log.splitlines()[-1] == "Stopped: the job was cancelled."
    assert len(chapter_lines(job)) == 3


async def test_a_run_replaced_by_a_retry_stops_and_leaves_the_new_run_alone(
    auth_client, chapters, fake_pipeline
):
    """Cancel then Retry before the old worker notices: the job is pending (or
    running) under a new task, and the old run must neither carry on nor write."""
    from app.worker.tasks import run_story_job

    body = await create_job(auth_client)
    reached: list[int] = []

    def replaced_by_retry(n: int) -> None:
        reached.append(n)
        if n == 1:
            set_job_fields(
                body["id"],
                status="pending",
                celery_task_id="the-retrys-task",
                log="written by the new run",
            )

    chapters(10, hook=replaced_by_retry)

    run_story_job(body["id"])

    job = load_job(body["id"])
    assert reached == [1]  # chapter 2's report noticed
    assert job.status.value == "pending"  # not touched
    assert job.celery_task_id == "the-retrys-task"
    assert job.finished_at is None  # not stamped by the run that lost the job
    assert job.log == "written by the new run"  # no flush, no "Stopped" note
    assert job.artifacts == [] and "convert" not in fake_pipeline


async def test_a_job_deleted_while_running_stops_the_run_quietly(
    auth_client, chapters, fake_pipeline
):
    from app.db import get_sync_db
    from app.models import Job
    from app.worker.tasks import run_story_job

    body = await create_job(auth_client)

    def delete_job(n: int) -> None:
        if n == 1:
            with get_sync_db() as session:
                session.delete(session.get(Job, uuid.UUID(body["id"])))
                session.commit()

    chapters(10, hook=delete_job)

    run_story_job(body["id"])  # must not raise

    assert load_job(body["id"]) is None
    assert "convert" not in fake_pipeline


async def test_a_job_swept_as_lost_is_not_turned_back_into_a_success(
    auth_client, chapters, fake_pipeline
):
    """A worker that stalled long enough to be failed by the sweep, then finishes,
    must not overwrite that verdict. Only a run that still finds the job
    `running` may decide how it ends."""
    from app.worker.tasks import run_story_job

    body = await create_job(auth_client)
    chapters(2, after=lambda: set_status(body["id"], "failed"))

    run_story_job(body["id"])

    job = load_job(body["id"])
    assert job.status.value == "failed"


async def test_a_run_that_still_owns_its_job_finishes_it(auth_client, chapters, fake_pipeline):
    from app.worker.tasks import run_story_job

    body = await create_job(auth_client)
    chapters(2)

    run_story_job(body["id"])

    job = load_job(body["id"])
    assert job.status.value == "success" and job.finished_at is not None
