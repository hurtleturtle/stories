# Local dev environment, in Docker. See docker-compose.yml for the full stack.

# Run the full stack (postgres, redis, api, worker, frontend) at http://localhost:3000.
# Data lives in the stories_db_data volume, so it survives restarts (`docker compose down -v` wipes it).
dev:
    docker compose up --build

# Run the backend test suite (the API tests skip without a DB - see test-db).
test:
    cd backend && uv run pytest

# Run the whole suite, API tests included, against the dev stack's postgres.
test-db:
    cd backend && TEST_DATABASE_URL=postgresql://story:story@localhost:5432/story_test uv run pytest

lint:
    cd backend && uv run ruff check .

# Apply pending Alembic migrations against the running dev stack.
migrate:
    docker compose run --rm api alembic upgrade head
