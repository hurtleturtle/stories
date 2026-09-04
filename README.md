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

## Architecture

- `backend/src/story_scraper` - the scraper library (CSS-selector based chapter
  fetching, ebook conversion via Calibre's `ebook-convert`, SMTP delivery) and the
  `story-scraper` CLI, unchanged in behaviour from the original script.
- `backend/src/app` - the FastAPI app: JWT auth, template/settings/job CRUD, and
  the Celery worker that runs jobs.
- `frontend` - a Vite + React + TypeScript SPA.
- `docker-compose.yml` - postgres, redis, api, worker (with Calibre installed) and
  the built frontend behind nginx.

## Templates

A template is a set of CSS selectors for one site:
- `container` *mandatory* - selector for the `<p>` tags containing chapter text
- `next_selector` *mandatory* - selector for the next-chapter link
- `detect_title` *optional* - selector for the chapter title
- `style` *optional* - stylesheet filename bundled in `story_scraper/assets/styles`
- `scripts` *optional* - script filenames to add to the generated HTML's `<head>`
- `ebook_type` *optional* - `epub` (default) or `mobi`

`backend/templates/*.yml` ships the original site templates (Royal Road,
ReadNovelFull, etc.) as seed data for "Import built-in templates".

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
