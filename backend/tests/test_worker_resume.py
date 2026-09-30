"""The real scraper running inside the worker task: chapters are kept on disk
while a job runs, and a retried job carries on instead of starting again."""

from types import SimpleNamespace

import httpx
import pytest
import respx
from jobhelpers import load_job
from sitehelpers import BASE, mount, page

from story_scraper.converter import ConversionError

JOB = {
    "url": BASE + "c1",
    "container": "div.chapter-content",
    "next_selector": "a#next_chap",
}


@pytest.fixture
def scraper(monkeypatch, tmp_path):
    """The worker's real Story, with only conversion and the job folder faked.

    `.converted` holds the HTML each conversion was given."""
    converted: list[str] = []

    def fake_convert(html_file, ebook_file, title, timeout=None):
        converted.append(html_file.read_text(encoding="utf-8"))
        ebook_file.write_text("ebook")
        return ebook_file

    monkeypatch.setattr("app.worker.tasks.convert", fake_convert)
    monkeypatch.setattr("app.worker.tasks.job_dir", lambda owner_id, job_id: tmp_path)
    return SimpleNamespace(converted=converted, chapters_dir=tmp_path / ".chapters")


async def new_job(auth_client) -> str:
    resp = await auth_client.post("/api/jobs", json=JOB)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def retry(auth_client, job_id: str) -> None:
    resp = await auth_client.post(f"/api/jobs/{job_id}/retry")
    assert resp.status_code == 200, resp.text


def chapter_files(directory) -> list[str]:
    return sorted(p.name for p in directory.glob("chapter-*.html"))


@respx.mock
async def test_a_successful_job_leaves_no_stored_chapters_behind(auth_client, scraper):
    from app.worker.tasks import run_story_job

    mount(c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>"))
    job_id = await new_job(auth_client)

    run_story_job(job_id)

    job = load_job(job_id)
    assert job.status.value == "success", job.error
    assert job.chapters_scraped == 2
    assert sorted(a.kind for a in job.artifacts) == ["epub", "html"]
    assert not scraper.chapters_dir.exists()
    assert scraper.converted[0].count('class="chp"') == 2


@respx.mock
async def test_chapters_are_kept_on_disk_while_a_job_fails(auth_client, scraper):
    from app.worker.tasks import run_story_job

    mount(c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>", "c3"))
    respx.get(BASE + "c3").mock(return_value=httpx.Response(500))
    job_id = await new_job(auth_client)

    run_story_job(job_id)

    job = load_job(job_id)
    assert job.status.value == "failed"
    assert job.chapters_scraped == 2
    assert chapter_files(scraper.chapters_dir) == ["chapter-000001.html", "chapter-000002.html"]
    assert job.artifacts == []  # no half-built document was recorded


@respx.mock
async def test_a_retried_job_carries_on_after_the_chapters_it_already_has(auth_client, scraper):
    from app.worker.tasks import run_story_job

    c1 = respx.get(BASE + "c1").mock(
        return_value=httpx.Response(200, text=page("<p>One.</p>", "c2"))
    )
    c2 = respx.get(BASE + "c2").mock(
        return_value=httpx.Response(200, text=page("<p>Two.</p>", "c3"))
    )
    c3 = respx.get(BASE + "c3").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(503),  # the first run gives up here
            httpx.Response(200, text=page("<p>Three.</p>")),  # the retry gets through
        ]
    )
    job_id = await new_job(auth_client)
    run_story_job(job_id)
    assert load_job(job_id).status.value == "failed"

    await retry(auth_client, job_id)
    run_story_job(job_id)

    job = load_job(job_id)
    assert job.status.value == "success", job.error
    assert job.chapters_scraped == 3
    assert (c1.call_count, c2.call_count) == (1, 1)  # never fetched twice
    assert c3.call_count == 4
    html = scraper.converted[-1]
    assert html.index("One.") < html.index("Two.") < html.index("Three.")
    assert html.count('class="chp"') == 3
    assert not scraper.chapters_dir.exists()

    lines = job.log.splitlines()
    assert "Resuming after chapter 2." in lines
    assert any(line.startswith("Chapter 1:") for line in lines)  # the first run's lines survive
    assert lines[-1].startswith("Chapter 3:")


@respx.mock
async def test_a_job_that_failed_in_conversion_is_not_scraped_again(
    auth_client, scraper, monkeypatch
):
    from app.worker import tasks
    from app.worker.tasks import run_story_job

    routes = mount(c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>"))
    working_convert = tasks.convert

    def failing_convert(html_file, ebook_file, title, timeout=None):
        raise ConversionError("calibre exploded")

    monkeypatch.setattr(tasks, "convert", failing_convert)
    job_id = await new_job(auth_client)
    run_story_job(job_id)
    job = load_job(job_id)
    assert job.status.value == "failed"
    assert [a.kind for a in job.artifacts] == ["html"]
    assert chapter_files(scraper.chapters_dir)  # kept, so the retry need not scrape

    monkeypatch.setattr(tasks, "convert", working_convert)
    await retry(auth_client, job_id)
    run_story_job(job_id)

    job = load_job(job_id)
    assert job.status.value == "success", job.error
    assert job.chapters_scraped == 2
    assert [route.call_count for route in routes.values()] == [1, 1]  # not scraped again
    assert sorted(a.kind for a in job.artifacts) == ["epub", "html"]  # and nothing doubled
    assert scraper.converted[-1].count('class="chp"') == 2
    assert not scraper.chapters_dir.exists()


@respx.mock
async def test_a_story_that_ends_on_a_repeat_says_so_in_the_job_log(auth_client, scraper):
    from app.worker.tasks import run_story_job

    mount(
        c1=page("<p>The one chapter.</p>", "c2"),
        c2=page("<p>The one chapter.</p>", "c3"),
        c3=page("<p>Never reached.</p>"),
    )
    job_id = await new_job(auth_client)

    run_story_job(job_id)

    job = load_job(job_id)
    assert job.status.value == "success"
    assert job.chapters_scraped == 1
    assert "same text as chapter 1" in job.log
    assert scraper.converted[0].count('class="chp"') == 1


@respx.mock
async def test_a_story_that_runs_to_its_natural_end_adds_no_stop_note(auth_client, scraper):
    from app.worker.tasks import run_story_job

    mount(c1=page("<p>One.</p>", "c2"), c2=page("<p>Two.</p>"))
    job_id = await new_job(auth_client)

    run_story_job(job_id)

    assert "Stopped" not in load_job(job_id).log


@respx.mock
async def test_a_job_with_nothing_stored_does_not_claim_to_resume(auth_client, scraper):
    from app.worker.tasks import run_story_job

    mount(c1=page("<p>One.</p>"))
    job_id = await new_job(auth_client)

    run_story_job(job_id)

    assert "Resuming" not in load_job(job_id).log
