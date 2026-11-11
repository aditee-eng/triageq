import os

# must be set before app modules import settings
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret")

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base, get_session
from app.main import app
from app.models import Department, Role, User
from app.redis_client import get_redis
from app.security import hash_password
from app.seed import DEPARTMENTS


@pytest.fixture()
async def redis():
    """fakeredis by default; set REDIS_TEST_URL=redis://localhost:6379/15 to test on real Redis."""
    url = os.environ.get("REDIS_TEST_URL")
    r = Redis.from_url(url, decode_responses=True) if url else fakeredis.aioredis.FakeRedis(decode_responses=True)
    await r.flushall()
    yield r
    await r.flushall()
    await r.aclose()


@pytest.fixture()
async def session_factory(tmp_path):
    # file-based SQLite so concurrent sessions get real separate connections
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", connect_args={"timeout": 30}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add_all([Department(code=c, name=n) for c, n in DEPARTMENTS.items()])
        await s.commit()
    yield factory
    await engine.dispose()


@pytest.fixture()
async def client(session_factory, redis):
    async def override_session():
        async with session_factory() as s:
            yield s

    async def override_redis():
        return redis

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_redis] = override_redis
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def make_user(session_factory, email, role, password="correct-horse-battery", active=True):
    async with session_factory() as s:
        s.add(User(email=email, password_hash=hash_password(password), full_name=email,
                   role=role, is_active=active))
        await s.commit()


async def login(client, email, password="correct-horse-battery"):
    return await client.post("/auth/login", data={"username": email, "password": password})


@pytest.fixture()
def auth_header():
    async def _get(client, email, password="correct-horse-battery"):
        r = await login(client, email, password)
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _get
