from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from sqlalchemy import text

from app.db import engine
from app.redis_client import redis_client
from app.routers import auth, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title="TriageQ", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(users.router)


@app.get("/health")
async def health(response: Response):
    checks = {"postgres": "ok", "redis": "ok"}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        checks["postgres"] = "down"

    try:
        await redis_client.ping()
    except Exception:
        checks["redis"] = "down"

    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "degraded", **checks}
