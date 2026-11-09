import pytest

from app.models import Role
from tests.conftest import login, make_user

NEW = {"email": "Doc@H.in", "password": "a-long-enough-pw", "full_name": "Dr Who", "role": "doctor"}


async def test_admin_can_create_user_and_new_user_can_login(client, session_factory, auth_header):
    await make_user(session_factory, "admin@h.in", Role.ADMIN)
    h = await auth_header(client, "admin@h.in")
    r = await client.post("/users", json=NEW, headers=h)
    assert r.status_code == 201
    assert r.json()["email"] == "doc@h.in"  # normalised to lowercase
    assert "password" not in r.json() and "password_hash" not in r.json()
    assert (await login(client, "doc@h.in", NEW["password"])).status_code == 200


@pytest.mark.parametrize("role", [Role.NURSE, Role.DOCTOR, Role.PATIENT])
async def test_non_admins_cannot_create_or_list_users(client, session_factory, auth_header, role):
    await make_user(session_factory, "u@h.in", role)
    h = await auth_header(client, "u@h.in")
    assert (await client.post("/users", json=NEW, headers=h)).status_code == 403
    assert (await client.get("/users", headers=h)).status_code == 403


async def test_unauthenticated_cannot_create_user(client):
    assert (await client.post("/users", json=NEW)).status_code == 401


async def test_duplicate_email_conflict(client, session_factory, auth_header):
    await make_user(session_factory, "admin@h.in", Role.ADMIN)
    h = await auth_header(client, "admin@h.in")
    assert (await client.post("/users", json=NEW, headers=h)).status_code == 201
    assert (await client.post("/users", json=NEW, headers=h)).status_code == 409


async def test_weak_password_rejected(client, session_factory, auth_header):
    await make_user(session_factory, "admin@h.in", Role.ADMIN)
    h = await auth_header(client, "admin@h.in")
    r = await client.post("/users", json={**NEW, "password": "short"}, headers=h)
    assert r.status_code == 422
