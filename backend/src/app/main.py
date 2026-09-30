"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import admin, auth, jobs, options, settings, templates
from app.services.jobs import sweep_stale_jobs_forever


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Lives here rather than in the worker because the API survives a worker
    # crash, which is exactly when the sweep is needed.
    sweeper = asyncio.create_task(sweep_stale_jobs_forever())
    try:
        yield
    finally:
        sweeper.cancel()
        with suppress(asyncio.CancelledError):
            await sweeper


app = FastAPI(title="Story Scraper", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(templates.router)
app.include_router(settings.router)
app.include_router(options.router)
app.include_router(jobs.router)
app.include_router(admin.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
