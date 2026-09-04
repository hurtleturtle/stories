FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

FROM base AS api
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

FROM base AS worker
# Calibre's own installer bundles its own Qt, so this skips the apt-resolved
# desktop dependency chain (webengine, multimedia, etc.) that apt's `calibre`
# package pulls in - ebook-convert still needs a handful of runtime libs
# even in headless/offscreen mode, listed explicitly below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        wget xz-utils ca-certificates \
        libxrender1 libxext6 libxkbcommon0 libxcb-cursor0 \
        libgl1 libegl1 libopengl0 libglx0 \
        libfontconfig1 libfreetype6 libdbus-1-3 libnss3 \
    && wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sh /dev/stdin \
    && apt-get purge -y wget \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
CMD ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=info"]
