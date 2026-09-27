"""Instance-wide settings stored in the database."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings, User
from story_scraper.config import settings

_ROW_ID = 1


async def get_app_settings(db: AsyncSession) -> AppSettings:
    """Fetch the settings row, creating it on first use.

    The ALLOW_REGISTRATION env var only seeds the row; from then on the value
    admins set wins. Nothing is committed here so callers can use this inside
    a transaction they still need to hold (registration keeps a lock open).
    """
    row = await db.get(AppSettings, _ROW_ID)
    if row is not None:
        return row

    # ON CONFLICT covers two requests racing to create the row.
    await db.execute(
        insert(AppSettings)
        .values(id=_ROW_ID, allow_registration=settings.allow_registration)
        .on_conflict_do_nothing()
    )
    return await db.get(AppSettings, _ROW_ID)


async def has_users(db: AsyncSession) -> bool:
    return (await db.execute(select(func.count()).select_from(User))).scalar_one() > 0


async def registration_open(db: AsyncSession) -> bool:
    """Whether a new account can be created. The very first account always
    can, so a fresh install with registration closed can still get an admin."""
    return not await has_users(db) or (await get_app_settings(db)).allow_registration
