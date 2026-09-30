"""Template CRUD over the API."""

TEMPLATE = {"name": "royalroad", "container": "div.chapter-content", "next_selector": "a.next"}


async def test_create_duplicate_name_conflicts(auth_client):
    assert (await auth_client.post("/api/templates", json=TEMPLATE)).status_code == 201

    resp = await auth_client.post("/api/templates", json=TEMPLATE)

    assert resp.status_code == 409
    assert resp.json()["detail"] == 'You already have a template called "royalroad"'


async def test_rename_onto_an_existing_name_conflicts(auth_client):
    await auth_client.post("/api/templates", json=TEMPLATE)
    other = (await auth_client.post("/api/templates", json={**TEMPLATE, "name": "other"})).json()

    resp = await auth_client.put(f"/api/templates/{other['id']}", json={"name": "royalroad"})

    assert resp.status_code == 409
    # The failed rename left the template as it was.
    names = sorted(t["name"] for t in (await auth_client.get("/api/templates")).json())
    assert names == ["other", "royalroad"]


async def test_other_users_can_reuse_a_name(auth_client, client):
    await auth_client.post("/api/templates", json=TEMPLATE)
    await client.post(
        "/api/auth/register", json={"email": "other@example.com", "password": "pw12345"}
    )
    token = (
        await client.post(
            "/api/auth/login", data={"username": "other@example.com", "password": "pw12345"}
        )
    ).json()["access_token"]

    resp = await client.post(
        "/api/templates", json=TEMPLATE, headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 201
