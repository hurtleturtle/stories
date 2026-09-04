"""Email delivery of finished ebooks."""

from __future__ import annotations

import mimetypes
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

MIME_OVERRIDES = {
    ".mobi": ("application", "x-mobipocket-ebook"),
    ".epub": ("application", "epub+zip"),
}


@dataclass
class SmtpConfig:
    from_addr: str
    to_addr: str
    password: str
    host: str = "smtp.gmail.com"
    port: int = 465


def _mime_type(filepath: Path) -> tuple[str, str]:
    if filepath.suffix in MIME_OVERRIDES:
        return MIME_OVERRIDES[filepath.suffix]
    guessed, _ = mimetypes.guess_type(filepath.name)
    if guessed and "/" in guessed:
        maintype, subtype = guessed.split("/", 1)
        return maintype, subtype
    return "application", "octet-stream"


def build_message(title: str, filepath: Path, cfg: SmtpConfig) -> EmailMessage:
    message = EmailMessage()
    message["From"] = cfg.from_addr
    message["To"] = cfg.to_addr
    message["Subject"] = title.replace("_", " ")

    maintype, subtype = _mime_type(filepath)
    message.add_attachment(
        filepath.read_bytes(), maintype=maintype, subtype=subtype, filename=filepath.name
    )
    return message


def send_ebook(title: str, filepath: Path, cfg: SmtpConfig) -> None:
    message = build_message(title, filepath, cfg)
    with smtplib.SMTP_SSL(cfg.host, cfg.port) as session:
        session.login(cfg.from_addr, cfg.password)
        session.send_message(message)
