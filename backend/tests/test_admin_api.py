"""Roles, the admin user-management API and the registration switch.

The first account registered becomes the admin; everyone after is a plain
user. Each helper below registers and logs in, returning auth headers so one
client can act as several people.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PASSWORD = "pw12345678"


async def _signup(client, email: str) -> dict:
    resp = await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return await _login(client, email)


async def _login(client, email: str, password: str = PASSWORD) -> dict:
    resp = await client.post("/api/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _user_id(client, headers: dict) -> str:
    return (await client.get("/api/auth/me", headers=headers)).json()["id"]


@pytest.fixture
async def admin(client) -> dict:
    return await _signup(client, "admin@example.com")


@pytest.fixture
async def user(client, admin) -> dict:
    return await _signup(client, "user@example.com")


# --- roles on registration -------------------------------------------------


async def test_first_user_is_admin_and_later_users_are_not(client, admin, user):
    me = (await client.get("/api/auth/me", headers=admin)).json()
    assert me["role"] == "admin"
    assert me["is_active"] is True

    assert (await client.get("/api/auth/me", headers=user)).json()["role"] == "user"


# --- registration switch ---------------------------------------------------


async def test_registration_status_is_open_on_a_fresh_install(client):
    resp = await client.get("/api/auth/registration")
    assert resp.json() == {"open": True}


async def test_closing_registration_blocks_new_accounts(client, admin):
    resp = await client.put(
        "/api/admin/settings", json={"allow_registration": False}, headers=admin
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"allow_registration": False}

    assert (await client.get("/api/auth/registration")).json() == {"open": False}
    resp = await client.post(
        "/api/auth/register", json={"email": "late@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 403

    await client.put("/api/admin/settings", json={"allow_registration": True}, headers=admin)
    resp = await client.post(
        "/api/auth/register", json={"email": "late@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 201


async def test_first_account_can_register_even_when_registration_is_closed(client, monkeypatch):
    from story_scraper.config import settings

    monkeypatch.setattr(settings, "allow_registration", False)
    assert (await client.get("/api/auth/registration")).json() == {"open": True}

    headers = await _signup(client, "founder@example.com")
    assert (await client.get("/api/auth/me", headers=headers)).json()["role"] == "admin"

    # The env var seeded the stored setting, so the next sign-up is refused.
    assert (await client.get("/api/admin/settings", headers=headers)).json() == {
        "allow_registration": False
    }
    resp = await client.post(
        "/api/auth/register", json={"email": "second@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 403


# --- access control --------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/admin/users", None),
        ("GET", "/api/admin/users/00000000-0000-0000-0000-000000000000", None),
        ("PATCH", "/api/admin/users/00000000-0000-0000-0000-000000000000", {}),
        ("DELETE", "/api/admin/users/00000000-0000-0000-0000-000000000000", None),
        ("GET", "/api/admin/settings", None),
        ("PUT", "/api/admin/settings", {"allow_registration": False}),
    ],
)
async def test_admin_routes_refuse_non_admins(client, user, method, path, body):
    resp = await client.request(method, path, json=body, headers=user)
    assert resp.status_code == 403

    resp = await client.request(method, path, json=body)
    assert resp.status_code == 401


# --- listing ---------------------------------------------------------------


async def test_list_users_with_counts_and_search(client, admin, user):
    await client.post(
        "/api/templates",
        json={"name": "t", "container": "div", "next_selector": "a"},
        headers=user,
    )

    body = (await client.get("/api/admin/users", headers=admin)).json()
    assert body["total"] == 2
    assert [u["email"] for u in body["items"]] == ["admin@example.com", "user@example.com"]
    assert body["items"][1]["template_count"] == 1
    assert body["items"][1]["job_count"] == 0

    body = (await client.get("/api/admin/users", params={"q": "USER@"}, headers=admin)).json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == "user@example.com"

    # LIKE wildcards in the search are literal.
    body = (await client.get("/api/admin/users", params={"q": "%"}, headers=admin)).json()
    assert body["total"] == 0


async def test_get_unknown_user_is_not_found(client, admin):
    resp = await client.get("/api/admin/users/00000000-0000-0000-0000-000000000000", headers=admin)
    assert resp.status_code == 404


# --- updating --------------------------------------------------------------


async def test_admin_can_change_email_and_password(client, admin, user):
    user_id = await _user_id(client, user)

    resp = await client.patch(
        f"/api/admin/users/{user_id}",
        json={"email": "renamed@example.com", "password": "new-password"},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "renamed@example.com"

    await _login(client, "renamed@example.com", "new-password")


async def test_email_change_to_a_taken_address_conflicts(client, admin, user):
    user_id = await _user_id(client, user)
    resp = await client.patch(
        f"/api/admin/users/{user_id}", json={"email": "admin@example.com"}, headers=admin
    )
    assert resp.status_code == 409


async def test_short_password_is_rejected(client, admin, user):
    user_id = await _user_id(client, user)
    resp = await client.patch(
        f"/api/admin/users/{user_id}", json={"password": "short"}, headers=admin
    )
    assert resp.status_code == 422


async def test_promotion_takes_effect_on_the_next_request(client, admin, user):
    user_id = await _user_id(client, user)
    assert (await client.get("/api/admin/users", headers=user)).status_code == 403

    resp = await client.patch(f"/api/admin/users/{user_id}", json={"role": "admin"}, headers=admin)
    assert resp.json()["role"] == "admin"

    # Same token as before - the role is read from the database, not the JWT.
    assert (await client.get("/api/admin/users", headers=user)).status_code == 200


async def test_disabled_user_cannot_log_in_or_use_an_existing_token(client, admin, user):
    user_id = await _user_id(client, user)

    resp = await client.patch(
        f"/api/admin/users/{user_id}", json={"is_active": False}, headers=admin
    )
    assert resp.json()["is_active"] is False

    assert (await client.get("/api/auth/me", headers=user)).status_code == 401
    resp = await client.post(
        "/api/auth/login", data={"username": "user@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 401

    await client.patch(f"/api/admin/users/{user_id}", json={"is_active": True}, headers=admin)
    await _login(client, "user@example.com")


@pytest.mark.parametrize("change", [{"role": "user"}, {"is_active": False}])
async def test_last_admin_cannot_demote_or_disable_themselves(client, admin, change):
    admin_id = await _user_id(client, admin)
    resp = await client.patch(f"/api/admin/users/{admin_id}", json=change, headers=admin)
    assert resp.status_code == 409
    assert (await client.get("/api/auth/me", headers=admin)).json()["role"] == "admin"


async def test_admin_can_step_down_once_another_admin_exists(client, admin, user):
    admin_id = await _user_id(client, admin)
    user_id = await _user_id(client, user)
    await client.patch(f"/api/admin/users/{user_id}", json={"role": "admin"}, headers=admin)

    resp = await client.patch(f"/api/admin/users/{admin_id}", json={"role": "user"}, headers=admin)
    assert resp.status_code == 200
    assert resp.json()["role"] == "user"


async def test_disabled_admin_does_not_count_towards_the_last_admin(client, admin, user):
    admin_id = await _user_id(client, admin)
    user_id = await _user_id(client, user)
    await client.patch(
        f"/api/admin/users/{user_id}", json={"role": "admin", "is_active": False}, headers=admin
    )

    resp = await client.patch(f"/api/admin/users/{admin_id}", json={"role": "user"}, headers=admin)
    assert resp.status_code == 409


# --- deleting --------------------------------------------------------------


async def test_delete_user_removes_their_data_and_files(client, admin, user, monkeypatch, tmp_path):
    from sqlalchemy import func, select

    from app.db import AsyncSessionLocal
    from app.models import Job, JobStatus, Template
    from app.worker.celery_app import celery_app
    from story_scraper.config import settings

    monkeypatch.setattr(settings, "story_folder", str(tmp_path))
    revoked: list[str] = []
    monkeypatch.setattr(
        celery_app.control, "revoke", lambda task_id, **kwargs: revoked.append(task_id)
    )

    user_id = await _user_id(client, user)
    await client.post(
        "/api/templates",
        json={"name": "t", "container": "div", "next_selector": "a"},
        headers=user,
    )
    async with AsyncSessionLocal() as db:
        job = Job(
            owner_id=user_id,
            url="https://example.com",
            title="Running",
            status=JobStatus.running,
            celery_task_id="task-123",
            config={},
        )
        db.add(job)
        await db.commit()
        files = Path(tmp_path) / user_id / str(job.id)
    files.mkdir(parents=True)
    (files / "book.epub").write_text("x")

    resp = await client.delete(f"/api/admin/users/{user_id}", headers=admin)
    assert resp.status_code == 204

    assert revoked == ["task-123"]
    assert not (Path(tmp_path) / user_id).exists()
    assert (await client.get(f"/api/admin/users/{user_id}", headers=admin)).status_code == 404
    async with AsyncSessionLocal() as db:
        assert (await db.execute(select(func.count()).select_from(Job))).scalar_one() == 0
        assert (await db.execute(select(func.count()).select_from(Template))).scalar_one() == 0

    # The old token dies with the account.
    assert (await client.get("/api/auth/me", headers=user)).status_code == 401


async def test_admin_cannot_delete_themselves(client, admin):
    admin_id = await _user_id(client, admin)
    resp = await client.delete(f"/api/admin/users/{admin_id}", headers=admin)
    assert resp.status_code == 400


async def test_delete_unknown_user_is_not_found(client, admin):
    resp = await client.delete(
        "/api/admin/users/00000000-0000-0000-0000-000000000000", headers=admin
    )
    assert resp.status_code == 404


# --- migration -------------------------------------------------------------


async def test_migration_promotes_the_oldest_existing_user(db_engine):
    """Upgrading an install that already has users must leave it with an admin."""
    import asyncio

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.db import Base

    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))

    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TYPE IF EXISTS userrole"))
    await db_engine.dispose()

    try:
        await asyncio.to_thread(command.upgrade, config, "f308ff6e21d7")
        async with db_engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO users (id, email, hashed_password, is_active, created_at)
                    VALUES (gen_random_uuid(), 'newer@example.com', 'x', true, now()),
                           (gen_random_uuid(), 'oldest@example.com', 'x', true,
                            now() - interval '1 day')
                    """
                )
            )
        await db_engine.dispose()

        await asyncio.to_thread(command.upgrade, config, "head")

        async with db_engine.begin() as conn:
            roles = dict((await conn.execute(text("SELECT email, role::text FROM users"))).all())
        assert roles == {"oldest@example.com": "admin", "newer@example.com": "user"}
    finally:
        async with db_engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        await db_engine.dispose()
