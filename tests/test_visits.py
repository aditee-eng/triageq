import asyncio
import itertools

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import update

from app.models import Role, Visit, VisitStatus
from app.queue import QueueService
from tests.conftest import make_user

_uhid = itertools.count(1)


def body(symptoms, complaint="complaint", **extra):
    n = next(_uhid)
    return {
        "patient": {"uhid": f"UH{n:05d}", "full_name": f"Patient {n}", "date_of_birth": "1990-05-01", "sex": "female"},
        "chief_complaint": complaint,
        "symptoms": symptoms,
        **extra,
    }


@pytest.fixture()
async def nurse(client, session_factory, auth_header):
    await make_user(session_factory, "nurse@h.in", Role.NURSE)
    return await auth_header(client, "nurse@h.in")


@pytest.fixture()
async def admin(client, session_factory, auth_header):
    await make_user(session_factory, "admin@h.in", Role.ADMIN)
    return await auth_header(client, "admin@h.in")


async def check_in(client, h, symptoms, **extra):
    r = await client.post("/visits/check-in", json=body(symptoms, **extra), headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- check-in ----------
async def test_check_in_runs_triage_and_enqueues(client, nurse):
    r = await check_in(client, nurse, ["chest_pain"])
    assert r["esi_level"] == 2 and r["department"] == "emergency" and r["queue_position"] == 1
    assert "SYM:chest_pain" in r["red_flags"] and "Chest pain" in r["explanation"]


async def test_more_urgent_patient_who_arrives_later_goes_first(client, nurse):
    await check_in(client, nurse, ["chest_pain"])
    bleeding = await check_in(client, nurse, ["severe_bleeding"])
    assert bleeding["esi_level"] == 1 and bleeding["queue_position"] == 1
    queue = (await client.get("/queues/emergency", headers=nurse)).json()
    assert [e["esi_level"] for e in queue] == [1, 2]
    assert queue[0]["position"] == 1 and queue[0]["patient_name"].startswith("Patient")


async def test_impossible_vitals_rejected(client, nurse):
    r = await client.post("/visits/check-in", json=body(["cough"], vitals={"heart_rate": 900}), headers=nurse)
    assert r.status_code == 422


async def test_future_date_of_birth_rejected(client, nurse):
    b = body(["cough"])
    b["patient"]["date_of_birth"] = "2999-01-01"
    assert (await client.post("/visits/check-in", json=b, headers=nurse)).status_code == 422


async def test_existing_uhid_is_reused(client, nurse):
    b = body(["cough"])
    assert (await client.post("/visits/check-in", json=b, headers=nurse)).status_code == 201
    assert (await client.post("/visits/check-in", json=b, headers=nurse)).status_code == 201  # second visit


# ---------- call next ----------
async def test_call_next_serves_in_priority_order_then_204(client, nurse):
    await check_in(client, nurse, ["chest_pain"])
    await check_in(client, nurse, ["severe_bleeding"])
    first = (await client.post("/queues/emergency/call-next", headers=nurse)).json()
    second = (await client.post("/queues/emergency/call-next", headers=nurse)).json()
    assert (first["esi_level"], second["esi_level"]) == (1, 2)
    assert (await client.post("/queues/emergency/call-next", headers=nurse)).status_code == 204
    assert (await client.get("/queues/emergency", headers=nurse)).json() == []


async def test_20_nurses_racing_for_10_patients_each_patient_called_exactly_once(
    client, session_factory, auth_header
):
    headers = []
    for i in range(20):
        await make_user(session_factory, f"n{i}@h.in", Role.NURSE)
        headers.append(await auth_header(client, f"n{i}@h.in"))
    admin_h = await auth_header(client, "n0@h.in")
    for _ in range(10):
        await check_in(client, admin_h, ["chest_pain"])

    responses = await asyncio.gather(
        *(client.post("/queues/emergency/call-next", headers=h) for h in headers)
    )
    ok = [r.json()["visit_id"] for r in responses if r.status_code == 200]
    assert len(ok) == 10 and len(set(ok)) == 10  # nobody got a duplicate
    assert sum(r.status_code == 204 for r in responses) == 10


async def test_stale_queue_entry_is_skipped(client, nurse, session_factory):
    a = await check_in(client, nurse, ["chest_pain"])
    b = await check_in(client, nurse, ["chest_pain"])
    async with session_factory() as s:  # first patient cancelled in DB, Redis still lists them
        await s.execute(update(Visit).where(Visit.id == __import__("uuid").UUID(a["visit_id"]))
                        .values(status=VisitStatus.CANCELLED))
        await s.commit()
    called = (await client.post("/queues/emergency/call-next", headers=nurse)).json()
    assert called["visit_id"] == b["visit_id"]


async def test_call_next_marks_visit_called_in_postgres_and_audits(client, nurse, session_factory):
    from sqlalchemy import select
    from app.models import AuditLog

    v = await check_in(client, nurse, ["chest_pain"])
    await client.post("/queues/emergency/call-next", headers=nurse)
    async with session_factory() as s:
        visit = (await s.execute(select(Visit))).scalar_one()
        actions = (await s.execute(select(AuditLog.action))).scalars().all()
    assert visit.status == VisitStatus.CALLED and visit.called_at is not None
    assert "visit.check_in" in actions and "visit.called" in actions and str(visit.id) == v["visit_id"]


async def test_db_failure_after_pop_puts_patient_back(client, nurse, redis, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    v = await check_in(client, nurse, ["chest_pain"])
    real_commit = AsyncSession.commit

    async def failing_commit(self):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        await client.post("/queues/emergency/call-next", headers=nurse)
    monkeypatch.setattr(AsyncSession, "commit", real_commit)
    assert await QueueService(redis).position("emergency", v["visit_id"]) == 1  # not lost


# ---------- recovery ----------
async def test_redis_wiped_then_reconcile_restores_queue_in_the_right_order(client, nurse, admin, redis):
    await check_in(client, nurse, ["chest_pain"])
    await check_in(client, nurse, ["severe_bleeding"])
    await check_in(client, nurse, ["fever"])
    before = (await client.get("/queues/emergency", headers=nurse)).json()

    await redis.flushall()  # Redis dies and comes back empty
    assert (await client.get("/queues/emergency", headers=nurse)).json() == []

    r = await client.post("/queues/admin/reconcile", headers=admin)
    assert r.json() == {"added": 3, "removed": 0}
    assert (await client.get("/queues/emergency", headers=nurse)).json() == before
    assert len((await client.get("/queues/general_medicine", headers=nurse)).json()) == 1
    # idempotent
    assert (await client.post("/queues/admin/reconcile", headers=admin)).json() == {"added": 0, "removed": 0}


async def test_reconcile_removes_entries_that_do_not_belong(client, nurse, admin, redis):
    await redis.zadd("queue:emergency", {"00000000-0000-0000-0000-000000000000": 1.0})
    r = await client.post("/queues/admin/reconcile", headers=admin)
    assert r.json() == {"added": 0, "removed": 1}


async def test_redis_down_at_check_in_still_saves_visit_and_reconcile_enqueues_it(
    client, nurse, admin, monkeypatch
):
    async def boom(self, *a, **k):
        raise RedisConnectionError("redis is down")

    with monkeypatch.context() as m:
        m.setattr(QueueService, "add", boom)
        r = await check_in(client, nurse, ["chest_pain"])
    assert r["queue_position"] is None  # degraded, but the visit is safe in Postgres
    assert (await client.get("/queues/emergency", headers=nurse)).json() == []
    assert (await client.post("/queues/admin/reconcile", headers=admin)).json()["added"] == 1
    assert len((await client.get("/queues/emergency", headers=nurse)).json()) == 1


# ---------- access control ----------
@pytest.mark.parametrize("role", [Role.PATIENT])
async def test_patients_cannot_use_staff_endpoints(client, session_factory, auth_header, role):
    await make_user(session_factory, "p@h.in", role)
    h = await auth_header(client, "p@h.in")
    assert (await client.post("/visits/check-in", json=body(["cough"]), headers=h)).status_code == 403
    assert (await client.get("/queues/emergency", headers=h)).status_code == 403
    assert (await client.post("/queues/emergency/call-next", headers=h)).status_code == 403


async def test_only_admin_can_reconcile(client, nurse):
    assert (await client.post("/queues/admin/reconcile", headers=nurse)).status_code == 403


async def test_unauthenticated_requests_rejected(client):
    assert (await client.post("/visits/check-in", json=body(["cough"]))).status_code == 401
    assert (await client.get("/queues/emergency")).status_code == 401


async def test_unknown_department_404(client, nurse):
    assert (await client.get("/queues/nope", headers=nurse)).status_code == 404
