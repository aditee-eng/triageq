"""Check-in, call-next and reconcile. Postgres is the source of truth; Redis is rebuildable."""
import logging
import uuid
from datetime import datetime, timezone

from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AuditLog,
    Department,
    Patient,
    TriageAssessment,
    TriageSource,
    User,
    Visit,
    VisitStatus,
)
from app.queue import QueueService, score_for
from app.schemas import CheckInIn, CheckInOut
from app.triage import PatientInput, Vitals, triage

log = logging.getLogger(__name__)


def epoch(dt: datetime) -> float:
    """SQLite returns naive datetimes; treat them as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def current_level(visit: Visit) -> int:
    return visit.assessments[-1].esi_level  # relationship is ordered by created_at


async def get_department(session: AsyncSession, code: str) -> Department | None:
    return (await session.execute(select(Department).where(Department.code == code))).scalar_one_or_none()


async def check_in(session: AsyncSession, queues: QueueService, body: CheckInIn, actor: User) -> CheckInOut:
    now = datetime.now(timezone.utc)
    age = (now.date() - body.patient.date_of_birth).days / 365.25
    result = triage(
        PatientInput(age, tuple(body.symptoms), Vitals(**body.vitals.model_dump()), body.pain_score)
    )  # raises TriageInputError on impossible input

    dept = await get_department(session, result.department)
    if dept is None:
        raise RuntimeError(f"department '{result.department}' is not seeded")

    patient = (
        await session.execute(select(Patient).where(Patient.uhid == body.patient.uhid))
    ).scalar_one_or_none()
    if patient is None:  # an existing UHID keeps its stored demographics
        patient = Patient(**body.patient.model_dump())
        session.add(patient)
        await session.flush()

    visit = Visit(
        patient_id=patient.id,
        department_id=dept.id,
        chief_complaint=body.chief_complaint,
        checked_in_at=now,
    )
    session.add(visit)
    await session.flush()
    session.add(
        TriageAssessment(
            visit_id=visit.id,
            esi_level=result.esi_level,
            source=TriageSource.RULES,
            vitals=body.vitals.model_dump(mode="json", exclude_none=True),
            symptoms=list(body.symptoms),
            red_flags=list(result.red_flags),
            explanation=result.explanation,
            created_by=actor.id,
        )
    )
    session.add(
        AuditLog(
            actor_id=actor.id,
            action="visit.check_in",
            entity_type="visit",
            entity_id=str(visit.id),
            payload={"esi_level": result.esi_level, "department": dept.code,
                     "rules": [r.rule_id for r in result.reasons]},
        )
    )
    await session.commit()  # durable first: from here on the visit survives a Redis outage

    position = None
    try:
        await queues.add(dept.code, str(visit.id), result.esi_level, now.timestamp())
        position = await queues.position(dept.code, str(visit.id))
    except RedisError:
        log.warning("Redis unavailable at check-in; visit %s saved, reconcile will enqueue it", visit.id)

    return CheckInOut(
        visit_id=visit.id,
        esi_level=result.esi_level,
        department=dept.code,
        explanation=result.explanation,
        red_flags=list(result.red_flags),
        missing_info=list(result.missing_info),
        unrecognized_symptoms=list(result.unrecognized_symptoms),
        queue_position=position,
    )


async def call_next(session: AsyncSession, queues: QueueService, dept: Department, caller: User) -> Visit | None:
    """Atomically take the next patient. Returns None when the queue is empty.

    1. ZPOPMIN removes the head in one atomic Redis command: no two callers get the same visit.
    2. A conditional UPDATE (... WHERE status='waiting') is a second guard against stale entries.
    3. If the DB step fails, the entry goes back with its original score.
    """
    # copy plain values now: session.rollback() expires loaded ORM objects, and touching an
    # expired attribute in async code triggers a lazy load that fails (MissingGreenlet)
    dept_code, caller_id = dept.code, caller.id
    while True:
        popped = await queues.pop_next(dept_code)
        if popped is None:
            return None
        visit_id, score = popped
        try:
            res = await session.execute(
                update(Visit)
                .where(Visit.id == uuid.UUID(visit_id), Visit.status == VisitStatus.WAITING)
                .values(status=VisitStatus.CALLED, called_at=datetime.now(timezone.utc), called_by=caller_id)
            )
            if res.rowcount == 0:  # stale entry (cancelled, already called): drop it, try the next
                await session.rollback()
                continue
            session.add(
                AuditLog(actor_id=caller_id, action="visit.called", entity_type="visit",
                         entity_id=visit_id, payload={"department": dept_code})
            )
            await session.commit()
        except Exception:
            await session.rollback()
            await queues.restore(dept_code, visit_id, score)
            raise
        return (
            await session.execute(
                select(Visit)
                .where(Visit.id == uuid.UUID(visit_id))
                .options(selectinload(Visit.assessments), selectinload(Visit.patient))
                .execution_options(populate_existing=True)
            )
        ).scalar_one()


async def reconcile(session: AsyncSession, queues: QueueService) -> dict[str, int]:
    """Make Redis match Postgres: re-add waiting visits that are missing, drop entries that
    should not be there. Idempotent, and safe to run while the system is live."""
    depts = (await session.execute(select(Department))).scalars().all()
    added = removed = 0
    for dept in depts:
        visits = (
            await session.execute(
                select(Visit)
                .where(Visit.status == VisitStatus.WAITING, Visit.department_id == dept.id)
                .options(selectinload(Visit.assessments))
            )
        ).scalars().all()
        expected = {
            str(v.id): score_for(current_level(v), epoch(v.checked_in_at)) for v in visits if v.assessments
        }
        actual = await queues.members(dept.code)
        for vid, score in expected.items():
            if vid not in actual:
                added += 1
            await queues.restore(dept.code, vid, score)  # idempotent; also repairs wrong scores
        for vid in actual - expected.keys():
            await queues.remove(dept.code, vid)
            removed += 1
    return {"added": added, "removed": removed}
