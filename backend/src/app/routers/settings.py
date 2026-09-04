from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import current_user
from app.models import User, UserSettings
from app.schemas import UserSettingsIn, UserSettingsOut
from app.security import encrypt_secret

router = APIRouter(prefix="/api/settings", tags=["settings"])


async def _get_or_create(db: AsyncSession, user: User) -> UserSettings:
    if user.settings is not None:
        return user.settings

    settings_row = UserSettings(user_id=user.id)
    db.add(settings_row)
    await db.commit()
    await db.refresh(user, attribute_names=["settings"])
    return user.settings


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
    if data.smtp_password:
        row.smtp_password_encrypted = encrypt_secret(data.smtp_password)

    await db.commit()
    await db.refresh(row)
    return _to_out(row)
