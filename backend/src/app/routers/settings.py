from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import current_user
from app.models import User, UserSettings
from app.schemas import UserSettingsIn, UserSettingsOut
from app.security import encrypt_secret

router = APIRouter(prefix="/api/settings", tags=["settings"])


async def _get_or_create(db: AsyncSession, user: User) -> UserSettings:
    """Fetch the user's settings row, creating it on first use.

    The row is loaded with an explicit query rather than through
    ``user.settings``: the relationship only populates when the User was
    loaded with it eagerly, and a lazy load here would be emitted from
    async code, which SQLAlchemy refuses.
    """
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    row = result.scalar_one_or_none()
    if row is not None:
        return row

    row = UserSettings(user_id=user.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _to_out(row: UserSettings) -> UserSettingsOut:
    return UserSettingsOut(
        kindle_address=row.kindle_address,
        email_from=row.email_from,
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_username=row.smtp_username,
        smtp_password_set=bool(row.smtp_password_encrypted),
        auto_send_default=row.auto_send_default,
    )


@router.get("", response_model=UserSettingsOut)
async def get_settings(
    db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> UserSettingsOut:
    return _to_out(await _get_or_create(db, user))


@router.put("", response_model=UserSettingsOut)
async def update_settings(
    data: UserSettingsIn, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> UserSettingsOut:
    row = await _get_or_create(db, user)
    row.kindle_address = data.kindle_address
    row.email_from = data.email_from
    row.smtp_host = data.smtp_host
    row.smtp_port = data.smtp_port
    row.smtp_username = data.smtp_username
    row.auto_send_default = data.auto_send_default
    # An omitted/empty password keeps the stored one, so the client never has
    # to round-trip the secret back to us just to change another field.
    if data.smtp_password:
        row.smtp_password_encrypted = encrypt_secret(data.smtp_password)
    elif data.clear_smtp_password:
        row.smtp_password_encrypted = None

    await db.commit()
    await db.refresh(row)
    return _to_out(row)
