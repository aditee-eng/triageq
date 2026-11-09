import os

# must be set before app modules import settings
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app
from app.models import Role, User
from app.security import hash_password


@pytest.fixture()
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture()
async def client(session_factory):
    async def override():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def make_user(session_factory, email, role, password="correct-horse-battery", active=True):
    async with session_factory() as s:
        s.add(User(email=email, password_hash=hash_password(password), full_name=email,
                   role=role, is_active=active))
        await s.commit()


async def login(client, email, password="correct-horse-battery"):
    r = await client.post("/auth/login", data={"username": email, "password": password})
    return r


@pytest.fixture()
def auth_header():
    async def _get(client, email, password="correct-horse-battery"):
        r = await login(client, email, password)
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _get
