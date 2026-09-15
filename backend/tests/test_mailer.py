from pathlib import Path
from unittest.mock import MagicMock, patch

from story_scraper.mailer import SmtpConfig, build_message, send_ebook


def test_login_user_prefers_explicit_username():
    cfg = SmtpConfig(
        from_addr="library@example.com",
        to_addr="me@kindle.com",
        password="pw",
        username="smtp-login@example.com",
    )
    assert cfg.login_user() == "smtp-login@example.com"


def test_login_user_falls_back_to_from_address():
    cfg = SmtpConfig(from_addr="me@example.com", to_addr="me@kindle.com", password="pw")
    assert cfg.login_user() == "me@example.com"


def test_send_ebook_authenticates_with_the_configured_username(tmp_path: Path):
    ebook = tmp_path / "Book.epub"
    ebook.write_bytes(b"epub-bytes")
    cfg = SmtpConfig(
        from_addr="library@example.com",
        to_addr="me@kindle.com",
        password="pw",
        username="smtp-login@example.com",
    )

    session = MagicMock()
    with patch("story_scraper.mailer.smtplib.SMTP_SSL") as smtp_ssl:
        smtp_ssl.return_value.__enter__.return_value = session
        send_ebook("My Book", ebook, cfg)

    smtp_ssl.assert_called_once_with("smtp.gmail.com", 465)
    session.login.assert_called_once_with("smtp-login@example.com", "pw")
    sent = session.send_message.call_args.args[0]
    # The From header stays the configured sender, not the login account.
    assert sent["From"] == "library@example.com"
    assert sent["To"] == "me@kindle.com"


def test_build_message_uses_the_title_as_subject(tmp_path: Path):
    ebook = tmp_path / "My_Book.epub"
    ebook.write_bytes(b"epub-bytes")
    cfg = SmtpConfig(from_addr="a@b.com", to_addr="me@kindle.com", password="pw")

    message = build_message("My_Book", ebook, cfg)

    assert message["Subject"] == "My Book"
    attachment = next(part for part in message.iter_attachments())
    assert attachment.get_filename() == "My_Book.epub"
    assert attachment.get_content_type() == "application/epub+zip"
