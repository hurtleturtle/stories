# stories

Download web-based serial stories, convert them to an ebook and send them to Kindle.

A FastAPI + React web app for configuring per-site scrape templates and running
scrape jobs asynchronously, plus the original `story-scraper` CLI.

## Running

```
cp .env.example .env   # edit SECRET_KEY, SMTP defaults, etc.
docker compose up --build
```

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs

Register an account, then use "Import built-in templates" on the Templates page to
load the site templates below.

The first account registered is the admin. Admins get a **Users** page where they
can see every account, change emails, roles and passwords, disable or delete
accounts, and open or close registration. The first account can always be
registered, even with registration closed, so a fresh install is never locked out.

## Architecture

- `backend/src/story_scraper` - the scraper library (CSS-selector based chapter
  fetching, ebook conversion via Calibre's `ebook-convert`, SMTP delivery) and the
  `story-scraper` CLI, unchanged in behaviour from the original script.
- `backend/src/app` - the FastAPI app: JWT auth, template/settings/job CRUD, and
  the Celery worker that runs jobs.
- `frontend` - a Vite + React + TypeScript SPA.
- `docker-compose.yml` - postgres, redis, api, worker (with Calibre installed) and
  the built frontend behind nginx.

## Send to Kindle

Per-user email settings live on the Settings page and are stored in the
`user_settings` table; the SMTP password is encrypted at rest with a key derived
from `SECRET_KEY`, and is never returned by the API. `SMTP username` is what the
app authenticates as, which can differ from the send-from address.

A job can email its ebook automatically when it finishes ("Email to Kindle when
done", defaulted from the `Email new jobs to Kindle by default` setting). A
completed job can also be **resent** at any time from its detail page, which is
useful when delivery failed or the book never showed up on the device. The job
records the outcome - recipient, timestamp and any SMTP error - so a failed send
is visible rather than buried in the log.

## Templates

A template is a set of CSS selectors for one site:
- `container` *mandatory* - selector for the `<p>` tags containing chapter text
- `next_selector` *mandatory* - selector for the next-chapter link
- `detect_title` *optional* - selector for the chapter title
- `style` *optional* - stylesheet filename bundled in `story_scraper/assets/styles` (other names are rejected); it is inlined into the generated HTML
- `scripts` *optional* - script filenames bundled in `story_scraper/assets/scripts` (other names are rejected), inlined into the generated HTML's `<head>`
- `ebook_type` *optional* - `epub` (default), `azw3` or `pdf`. MOBI is no longer offered (Send to Kindle takes EPUB); a migration switched templates and unfinished jobs that used it to `epub`, and finished `.mobi` books still download. `GET /api/options` lists the valid formats and stylesheets, which the template form uses for its dropdowns.

`backend/templates/*.yml` ships the original site templates (Royal Road,
ReadNovelFull, etc.) as seed data for "Import built-in templates".

## How a scrape works

The scraper follows each chapter's `next_selector` link and writes every chapter to
disk as it arrives (under the job's own folder, in `.chapters`), so memory stays flat
however long the story is and nothing is lost if the worker dies.

- **Retrying resumes.** A failed job that is retried carries on after its last stored
  chapter instead of starting again, and one that failed only in conversion is not
  scraped a second time. The stored chapters are removed once the job succeeds. They
  are for the same story read the same way; change the URL or selectors and it starts
  afresh. A finished story is not re-fetched, so a retry will not pick up chapters
  published since.
- **The story ends** when the next link runs out, `num_chapters` is reached, or the next
  page is a 404/410, has no chapter content, was already fetched, or has **the same text
  as an earlier chapter**. That last check hashes each chapter's text (and which pictures
  it shows, but not its heading or markup) before it is stored, and stops sites that keep
  serving their final page under new URLs. Why a story ended early is written to the job
  log. Two genuinely different chapters with identical text (a repeated "on hiatus"
  notice, say) would end the story at the second.
- **Content is sanitised.** Scripts, styles, frames, plugins, event handlers, `javascript:`
  links and comments are stripped from chapter text before it is stored, which also
  removes the ad scripts many sites embed.
- **Running jobs can be cancelled.** The worker checks after every chapter whether its job
  is still running (and still its own), so Cancel stops it at the next chapter. The chapters
  scraped so far are kept, and Retry carries on from them. A run replaced by a retry, or
  whose job was deleted, stops too, and only a run that still finds its job `running` can
  mark it finished, so a cancelled job is never turned back into a success.
- **Limits.** One scrape is capped at `MAX_CHAPTERS` chapters and `MAX_SCRAPE_SECONDS`, and a
  page at `MAX_PAGE_BYTES` (decompressed). Reaching the first two ends the story with a note
  in the job log, and raising the limit and retrying carries on. `0` turns a limit off.
- **Conversion.** Calibre is given the chapter headings as the table of contents (it used to
  guess), plus an optional `author` and `language` from the new-job form or the CLI's
  `--author` / `--language`. The table of contents relies on Calibre accepting the
  expression `//h:h2[@class='chapter-heading']`; that is untested here, since Calibre is not
  installed in the test environment.
- **The job log** is written in batches (every 25 chapters or 3 seconds) rather than once per
  chapter, so a long story does not rewrite an ever-growing log thousands of times.
- **Lost workers are noticed.** A running job's worker records a heartbeat, and the API
  fails any running job that has been silent for two minutes, so a job killed by a deploy
  or the OOM killer shows as failed with a reason and can be retried. See
  `.env.example` for the intervals.

## CLI

The original command-line workflow still works, without the web app running:

```
cd backend
uv sync
uv run story-scraper -i royalroad -u <chapter-url> -t "My Book"
```

## Tests

```
cd backend
uv run pytest
uv run ruff check .
```

The API tests need a Postgres (the models use JSONB and native enums). They skip
unless you point them at a throwaway database, which they create and drop tables
in on every test:

```
TEST_DATABASE_URL=postgresql://story:story@localhost:5432/story_test uv run pytest
```

## Deploying

`.github/workflows/release.yml` builds and pushes `ghcr.io/hurtleturtle/stories-{api,worker,frontend}`
on every `vX.Y.Z` tag (or manual dispatch). `deploy/` holds the production compose file plus
provisioning/backup/auto-deploy automation for a fresh host:

```
scp deploy/* <host>:/tmp/ && ssh <host> sudo /tmp/provision.sh   # one-time host setup
# fill in /opt/stories/.env (see deploy/env.example), then:
sudo /tmp/install-backup.sh                                     # optional nightly pg_dump backup
```

`story-autodeploy.timer` then polls `APP_TAG` every 5 minutes and redeploys on change; pin
`APP_TAG` to a fixed version in `.env` to pause auto-deploy.
