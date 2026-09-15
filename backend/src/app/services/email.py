"""Turning stored user settings into a usable SMTP config, and picking which
artifact of a job gets sent to Kindle."""

from __future__ import annotations

from collections.abc import Iterable

from app.models import Artifact, UserSettings
from app.security import decrypt_secret
from story_scraper.mailer import SmtpConfig

# Kindle's personal-document service rejects anything else.
SENDABLE_KINDS = ("epub", "mobi", "azw3", "pdf")


def missing_smtp_fields(row: UserSettings | None) -> list[str]:
    """Human-readable names of the settings still needed before email can be
    sent, so the API can explain exactly what to go and fill in."""
    if row is None:
        return ["Kindle address", "send-from address", "SMTP password"]

    missing = []
    if not row.kindle_address:
        missing.append("Kindle address")
    if not (row.email_from or row.smtp_username):
        missing.append("send-from address")
    if not row.smtp_password_encrypted:
        missing.append("SMTP password")
    return missing


def smtp_config(row: UserSettings | None) -> SmtpConfig | None:
    """Build an SmtpConfig from stored settings, or None if they are incomplete."""
    if row is None or missing_smtp_fields(row):
        return None

    return SmtpConfig(
        from_addr=row.email_from or row.smtp_username or "",
        to_addr=row.kindle_address or "",
        password=decrypt_secret(row.smtp_password_encrypted or ""),
        host=row.smtp_host,
        port=row.smtp_port,
        username=row.smtp_username,
    )


def pick_sendable_artifact(
    artifacts: Iterable[Artifact], preferred_kind: str | None = None
) -> Artifact | None:
    """Choose the artifact to send to Kindle: the job's own ebook format when
    it is there, otherwise any other sendable ebook. The intermediate HTML is
    never a candidate - Kindle will not take it."""
    candidates = [a for a in artifacts if a.kind in SENDABLE_KINDS]
    if not candidates:
        return None

    if preferred_kind:
        preferred = next((a for a in candidates if a.kind == preferred_kind), None)
        if preferred is not None:
            return preferred

    return min(candidates, key=lambda a: SENDABLE_KINDS.index(a.kind))
