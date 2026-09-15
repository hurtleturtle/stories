from app.models import Artifact, UserSettings
from app.security import encrypt_secret
from app.services.email import missing_smtp_fields, pick_sendable_artifact, smtp_config


def make_settings(**overrides) -> UserSettings:
    values = {
        "kindle_address": "me@kindle.com",
        "email_from": "library@example.com",
        "smtp_host": "smtp.example.com",
        "smtp_port": 465,
        "smtp_username": "smtp-login@example.com",
        "smtp_password_encrypted": encrypt_secret("app-password"),
    }
    values.update(overrides)
    return UserSettings(**values)


def test_complete_settings_have_nothing_missing():
    assert missing_smtp_fields(make_settings()) == []


def test_missing_settings_are_named():
    row = make_settings(kindle_address=None, smtp_password_encrypted=None)
    assert missing_smtp_fields(row) == ["Kindle address", "SMTP password"]


def test_absent_settings_row_reports_everything():
    assert missing_smtp_fields(None) == [
        "Kindle address",
        "send-from address",
        "SMTP password",
    ]


def test_smtp_username_alone_satisfies_the_send_from_address():
    assert missing_smtp_fields(make_settings(email_from=None)) == []


def test_smtp_config_carries_the_stored_username_and_decrypted_password():
    cfg = smtp_config(make_settings())

    assert cfg is not None
    assert cfg.username == "smtp-login@example.com"
    assert cfg.login_user() == "smtp-login@example.com"
    assert cfg.password == "app-password"
    assert cfg.from_addr == "library@example.com"
    assert cfg.to_addr == "me@kindle.com"
    assert (cfg.host, cfg.port) == ("smtp.example.com", 465)


def test_smtp_config_is_none_when_incomplete():
    assert smtp_config(make_settings(smtp_password_encrypted=None)) is None


def artifact(kind: str) -> Artifact:
    return Artifact(kind=kind, filename=f"book.{kind}", path=f"/tmp/book.{kind}")


def test_pick_sendable_artifact_prefers_the_jobs_own_format():
    chosen = pick_sendable_artifact(
        [artifact("html"), artifact("epub"), artifact("mobi")], preferred_kind="mobi"
    )
    assert chosen is not None and chosen.kind == "mobi"


def test_pick_sendable_artifact_never_returns_the_intermediate_html():
    assert pick_sendable_artifact([artifact("html")]) is None


def test_pick_sendable_artifact_falls_back_when_the_preferred_format_is_absent():
    chosen = pick_sendable_artifact([artifact("html"), artifact("epub")], preferred_kind="mobi")
    assert chosen is not None and chosen.kind == "epub"


def test_pick_sendable_artifact_with_no_preference_picks_an_ebook():
    chosen = pick_sendable_artifact([artifact("html"), artifact("mobi"), artifact("epub")])
    assert chosen is not None and chosen.kind == "epub"
