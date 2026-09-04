from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import current_user, get_user_by_email
from app.models import User
from app.schemas import Token, UserCreate, UserOut
from app.security import create_access_token, hash_password, verify_password
from story_scraper.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)) -> User:
    if not settings.allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled")

    if await get_user_by_email(db, data.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    user = User(email=data.email, hashed_password=hash_password(data.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)
) -> Token:
    user = await get_user_by_email(db, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> User:
    return user
