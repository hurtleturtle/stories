from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import current_user, get_user_by_email
from app.models import User, UserRole
from app.schemas import RegistrationStatus, Token, UserCreate, UserOut
from app.security import create_access_token, hash_password, verify_password
from app.services.app_settings import get_app_settings, has_users, registration_open

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Arbitrary key for pg_advisory_xact_lock, serialising registrations so two
# simultaneous first sign-ups cannot both see an empty table and become admin.
_REGISTRATION_LOCK = 0x5709_0001


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)) -> User:
    # Held until the commit below.
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _REGISTRATION_LOCK})

    first_user = not await has_users(db)
    if not first_user and not (await get_app_settings(db)).allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled")

    if await get_user_by_email(db, data.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        role=UserRole.admin if first_user else UserRole.user,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)
) -> Token:
    user = await get_user_by_email(db, form_data.username)
    # Disabled accounts get the same answer as a wrong password, so the
    # endpoint does not reveal which accounts exist.
    if (
        not user
        or not verify_password(form_data.password, user.hashed_password)
        or not user.is_active
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return Token(access_token=create_access_token(user.id))


@router.get("/registration", response_model=RegistrationStatus)
async def registration_status(db: AsyncSession = Depends(get_db)) -> RegistrationStatus:
    return RegistrationStatus(open=await registration_open(db))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> User:
    return user
