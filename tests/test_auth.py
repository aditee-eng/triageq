from datetime import datetime, timedelta, timezone

from jose import jwt

from app.config import settings
from app.models import Role
from tests.conftest import login, make_user


async def test_login_success_and_me(client, session_factory, auth_header):
    await make_user(session_factory, "nurse@h.in", Role.NURSE)
    r = await login(client, "nurse@h.in")
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"
    me = await client.get("/auth/me", headers=await auth_header(client, "nurse@h.in"))
    assert me.status_code == 200
    assert me.json()["role"] == "nurse"
    assert "password_hash" not in me.json()


async def test_wrong_password_and_unknown_user_look_identical(client, session_factory):
    await make_user(session_factory, "nurse@h.in", Role.NURSE)
    bad_pw = await login(client, "nurse@h.in", "wrong-password-xx")
    no_user = await login(client, "ghost@h.in")
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json()


async def test_inactive_user_cannot_login(client, session_factory):
    await make_user(session_factory, "old@h.in", Role.NURSE, active=False)
    assert (await login(client, "old@h.in")).status_code == 401


async def test_missing_and_garbage_token_rejected(client):
    assert (await client.get("/auth/me")).status_code == 401
    r = await client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


async def test_expired_token_rejected(client, session_factory):
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000", "role": "nurse",
         "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


async def test_token_signed_with_wrong_key_rejected(client, session_factory):
    await make_user(session_factory, "nurse@h.in", Role.NURSE)
    forged = jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000", "role": "admin",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "attacker-key", algorithm="HS256",
    )
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_role_in_token_is_ignored_db_role_wins(client, session_factory):
    """A valid token claiming role=admin for a nurse must not grant admin access."""
    await make_user(session_factory, "nurse@h.in", Role.NURSE)
    async with session_factory() as s:
        from sqlalchemy import select
        from app.models import User
        uid = (await s.execute(select(User.id))).scalar_one()
    token = jwt.encode(
        {"sub": str(uid), "role": "admin",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )
    r = await client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


async def test_deactivated_user_token_stops_working(client, session_factory, auth_header):
    await make_user(session_factory, "nurse@h.in", Role.NURSE)
    headers = await auth_header(client, "nurse@h.in")
    assert (await client.get("/auth/me", headers=headers)).status_code == 200
    async with session_factory() as s:
        from sqlalchemy import update
        from app.models import User
        await s.execute(update(User).values(is_active=False))
        await s.commit()
    assert (await client.get("/auth/me", headers=headers)).status_code == 401
