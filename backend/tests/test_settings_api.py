"""The settings endpoints previously lazy-loaded User.settings from async
code, which SQLAlchemy refuses - so nothing was ever persisted. These pin the
round trip down."""

FULL_SETTINGS = {
    "kindle_address": "me@kindle.com",
    "email_from": "library@example.com",
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_username": "smtp-login@example.com",
    "smtp_password": "app-password",
    "auto_send_default": True,
}


async def test_get_settings_returns_defaults_for_a_new_user(auth_client):
    resp = await auth_client.get("/api/settings")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kindle_address"] is None
    assert body["smtp_host"] == "smtp.gmail.com"
    assert body["smtp_port"] == 465
    assert body["smtp_password_set"] is False
    assert body["auto_send_default"] is False


async def test_settings_survive_a_round_trip(auth_client):
    resp = await auth_client.put("/api/settings", json=FULL_SETTINGS)
    assert resp.status_code == 200, resp.text

    body = (await auth_client.get("/api/settings")).json()
    assert body["kindle_address"] == "me@kindle.com"
    assert body["email_from"] == "library@example.com"
    assert body["smtp_host"] == "smtp.example.com"
    assert body["smtp_port"] == 587
    assert body["smtp_username"] == "smtp-login@example.com"
    assert body["auto_send_default"] is True
    # The password itself is never handed back, only the fact that it is set.
    assert body["smtp_password_set"] is True
    assert "smtp_password" not in body


async def test_stored_password_is_encrypted_and_decryptable(auth_client):
    from sqlalchemy import select

    from app.db import AsyncSessionLocal
    from app.models import UserSettings
    from app.security import decrypt_secret

    await auth_client.put("/api/settings", json=FULL_SETTINGS)

    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(UserSettings))).scalar_one()

    assert row.smtp_username == "smtp-login@example.com"
    assert row.smtp_password_encrypted != "app-password"
    assert decrypt_secret(row.smtp_password_encrypted) == "app-password"


async def test_blank_password_keeps_the_stored_one(auth_client):
    await auth_client.put("/api/settings", json=FULL_SETTINGS)

    resp = await auth_client.put(
        "/api/settings", json={**FULL_SETTINGS, "smtp_password": "", "smtp_port": 465}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["smtp_password_set"] is True
    assert resp.json()["smtp_port"] == 465


async def test_password_can_be_cleared_explicitly(auth_client):
    await auth_client.put("/api/settings", json=FULL_SETTINGS)

    resp = await auth_client.put(
        "/api/settings",
        json={**FULL_SETTINGS, "smtp_password": None, "clear_smtp_password": True},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["smtp_password_set"] is False


async def test_updating_settings_twice_does_not_create_a_second_row(auth_client):
    from sqlalchemy import func, select

    from app.db import AsyncSessionLocal
    from app.models import UserSettings

    await auth_client.get("/api/settings")
    await auth_client.put("/api/settings", json=FULL_SETTINGS)
    await auth_client.put("/api/settings", json={**FULL_SETTINGS, "smtp_port": 25})

    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(UserSettings))).scalar_one()

    assert count == 1


async def test_settings_require_authentication(client):
    assert (await client.get("/api/settings")).status_code == 401
