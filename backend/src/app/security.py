"""Password hashing, JWT issuance and SMTP-secret encryption."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from cryptography.fernet import Fernet
from pwdlib import PasswordHash

from story_scraper.config import settings

password_hash = PasswordHash.recommended()

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user_id: UUID) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> UUID | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def _fernet() -> Fernet:
    # Derive a 32-byte urlsafe-base64 key from SECRET_KEY so any string works.
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
