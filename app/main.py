import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from sqlalchemy import text

from app import visit_service
from app.db import SessionLocal, engine
from app.queue import QueueService
from app.redis_client import redis_client
from app.routers import auth, queues, users, visits


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis may have restarted empty: rebuild queues from Postgres before serving traffic
    try:
        async with SessionLocal() as session:
            stats = await visit_service.reconcile(session, QueueService(redis_client))
        logging.getLogger(__name__).info("queue reconcile on startup: %s", stats)
    except Exception:
        logging.getLogger(__name__).exception("startup reconcile failed; run POST /queues/admin/reconcile")
    yield
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title="TriageQ", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(visits.router)
app.include_router(queues.router)


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
