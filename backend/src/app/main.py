"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, jobs, settings, templates

app = FastAPI(title="Story Scraper")

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
app.include_router(jobs.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
