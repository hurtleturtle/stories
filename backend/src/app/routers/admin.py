from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_user_by_email, require_admin
from app.models import Job, JobStatus, Template, User, UserRole
from app.schemas import AdminUserList, AdminUserOut, AdminUserUpdate, AppSettingsIO
from app.security import hash_password
from app.services.app_settings import get_app_settings
from app.services.storage import remove_user_files
from app.worker.celery_app import celery_app

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

_job_count = (
    select(func.count(Job.id)).where(Job.owner_id == User.id).correlate(User).scalar_subquery()
)
_template_count = (
    select(func.count(Template.id))
    .where(Template.owner_id == User.id)
    .correlate(User)
    .scalar_subquery()
)


def _to_out(user: User, job_count: int, template_count: int) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        job_count=job_count,
        template_count=template_count,
    )


async def _user_out(db: AsyncSession, user_id: UUID) -> AdminUserOut:
    row = (
        await db.execute(select(User, _job_count, _template_count).where(User.id == user_id))
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return _to_out(*row)


async def _get_user(db: AsyncSession, user_id: UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


async def _ensure_another_admin(db: AsyncSession, user: User) -> None:
    """Refuse a change that would leave no active admin.

    The active admin rows are locked so two admins demoting each other at
    the same moment cannot both see the other one still standing.
    """
    admins = (
        await db.execute(
            select(User.id)
            .where(User.role == UserRole.admin, User.is_active.is_(True))
            .with_for_update()
        )
    ).scalars()
    if not any(admin_id != user.id for admin_id in admins):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot remove the last active admin")


@router.get("/users", response_model=AdminUserList)
async def list_users(
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, description="Case-insensitive email search"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AdminUserList:
    stmt = select(User, _job_count, _template_count).order_by(User.created_at, User.id)
    count_stmt = select(func.count()).select_from(User)
    if q:
        stmt = stmt.where(User.email.icontains(q, autoescape=True))
        count_stmt = count_stmt.where(User.email.icontains(q, autoescape=True))

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(stmt.limit(limit).offset(offset))).all()
    return AdminUserList(items=[_to_out(*row) for row in rows], total=total)


@router.get("/users/{user_id}", response_model=AdminUserOut)
async def get_user(user_id: UUID, db: AsyncSession = Depends(get_db)) -> AdminUserOut:
    return await _user_out(db, user_id)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: UUID, data: AdminUserUpdate, db: AsyncSession = Depends(get_db)
) -> AdminUserOut:
    user = await _get_user(db, user_id)

    if data.email is not None and data.email != user.email:
        if await get_user_by_email(db, data.email):
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
        user.email = data.email

    loses_admin = (
        user.role == UserRole.admin
        and user.is_active
        and ((data.role is not None and data.role != UserRole.admin) or data.is_active is False)
    )
    if loses_admin:
        await _ensure_another_admin(db, user)

    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.password:
        user.hashed_password = hash_password(data.password)

    await db.commit()
    return await _user_out(db, user.id)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
) -> None:
    # Deleting yourself would also be the only way the acting admin could
    # remove the last admin, so this covers that too.
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete your own account")

    user = await _get_user(db, user_id)
    task_ids = (
        await db.execute(
            select(Job.celery_task_id).where(
                Job.owner_id == user.id,
                Job.status.in_([JobStatus.pending, JobStatus.running]),
                Job.celery_task_id.is_not(None),
            )
        )
    ).scalars()
    for task_id in task_ids:
        celery_app.control.revoke(task_id, terminate=True)

    await db.delete(user)
    await db.commit()
    remove_user_files(user.id)


@router.get("/settings", response_model=AppSettingsIO)
async def get_settings(db: AsyncSession = Depends(get_db)) -> AppSettingsIO:
    row = await get_app_settings(db)
    await db.commit()
    return AppSettingsIO.model_validate(row)


@router.put("/settings", response_model=AppSettingsIO)
async def update_settings(data: AppSettingsIO, db: AsyncSession = Depends(get_db)) -> AppSettingsIO:
    row = await get_app_settings(db)
    row.allow_registration = data.allow_registration
    await db.commit()
    return AppSettingsIO.model_validate(row)
