# Local dev environment, in Docker. See docker-compose.yml for the full stack.

# Run the full stack (postgres, redis, api, worker, frontend) at http://localhost:3000.
# Data lives in the stories_db_data volume, so it survives restarts (`docker compose down -v` wipes it).
dev:
    docker compose up --build

# Run the backend test suite (no DB needed).
test:
    cd backend && uv run pytest

lint:
    cd backend && uv run ruff check .

# Apply pending Alembic migrations against the running dev stack.
migrate:
    docker compose run --rm api alembic upgrade head
