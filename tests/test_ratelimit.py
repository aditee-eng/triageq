from app.models import Role
from tests.conftest import login, make_user


async def test_sixth_attempt_is_blocked_even_with_the_right_password(client, session_factory):
    await make_user(session_factory, "n@h.in", Role.NURSE)
    for _ in range(5):
        assert (await login(client, "n@h.in", "wrong-password-1")).status_code == 401
    r = await login(client, "n@h.in")  # correct password, but locked
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


async def test_lockout_is_per_account_so_others_are_unaffected(client, session_factory):
    await make_user(session_factory, "a@h.in", Role.NURSE)
    await make_user(session_factory, "b@h.in", Role.NURSE)
    for _ in range(5):
        await login(client, "a@h.in", "wrong-password-1")
    assert (await login(client, "a@h.in")).status_code == 429
    assert (await login(client, "b@h.in")).status_code == 200


async def test_success_resets_the_counter(client, session_factory):
    await make_user(session_factory, "n@h.in", Role.NURSE)
    for _ in range(4):
        await login(client, "n@h.in", "wrong-password-1")
    assert (await login(client, "n@h.in")).status_code == 200
    for _ in range(4):
        assert (await login(client, "n@h.in", "wrong-password-1")).status_code == 401
    assert (await login(client, "n@h.in")).status_code == 200


async def test_unknown_emails_are_rate_limited_too(client):
    for _ in range(5):
        await login(client, "ghost@h.in", "wrong-password-1")
    assert (await login(client, "ghost@h.in", "wrong-password-1")).status_code == 429


async def test_fails_open_when_redis_is_down(client, session_factory, monkeypatch):
    from redis.asyncio import Redis
    from redis.exceptions import ConnectionError as RedisConnectionError

    await make_user(session_factory, "n@h.in", Role.NURSE)

    async def boom(self, *a, **k):
        raise RedisConnectionError("down")

    monkeypatch.setattr("fakeredis.aioredis.FakeRedis.get", boom)
    assert (await login(client, "n@h.in")).status_code == 200
