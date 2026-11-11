import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import visit_service
from app.db import get_session
from app.deps import require_role
from app.models import Role, User, Visit
from app.queue import QueueService
from app.redis_client import get_queues
from app.schemas import CalledVisit, QueueEntry, ReconcileOut

router = APIRouter(prefix="/queues", tags=["queues"])
staff = require_role(Role.NURSE, Role.DOCTOR, Role.ADMIN)
admin_only = require_role(Role.ADMIN)


def _minutes_since(dt: datetime) -> int:
    return max(0, int((datetime.now(timezone.utc).timestamp() - visit_service.epoch(dt)) // 60))


async def _dept_or_404(session: AsyncSession, code: str):
    dept = await visit_service.get_department(session, code)
    if dept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown department")
    return dept


@router.get("/{dept_code}", response_model=list[QueueEntry])
async def view_queue(
    dept_code: str,
    limit: int = 100,
    _user: User = Depends(staff),
    session: AsyncSession = Depends(get_session),
    queues: QueueService = Depends(get_queues),
):
    dept = await _dept_or_404(session, dept_code)
    ordered = await queues.list(dept.code, min(max(limit, 1), 500))
    ids = [uuid.UUID(v) for v, _ in ordered]
    visits = {
        v.id: v
        for v in (
            await session.execute(
                select(Visit)
                .where(Visit.id.in_(ids))
                .options(selectinload(Visit.assessments), selectinload(Visit.patient))
            )
        ).scalars()
    }
    out = []
    for i, vid in enumerate(ids, start=1):
        v = visits.get(vid)
        if v is None:
            continue
        out.append(
            QueueEntry(
                position=i, visit_id=v.id, uhid=v.patient.uhid, patient_name=v.patient.full_name,
                esi_level=visit_service.current_level(v), chief_complaint=v.chief_complaint,
                waiting_minutes=_minutes_since(v.checked_in_at),
            )
        )
    return out


@router.post("/{dept_code}/call-next", response_model=CalledVisit,
             responses={204: {"description": "Queue is empty"}})
async def call_next(
    dept_code: str,
    user: User = Depends(require_role(Role.NURSE, Role.DOCTOR)),
    session: AsyncSession = Depends(get_session),
    queues: QueueService = Depends(get_queues),
):
    dept = await _dept_or_404(session, dept_code)
    visit = await visit_service.call_next(session, queues, dept, user)
    if visit is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return CalledVisit(
        visit_id=visit.id, uhid=visit.patient.uhid, patient_name=visit.patient.full_name,
        esi_level=visit_service.current_level(visit), chief_complaint=visit.chief_complaint,
        waited_minutes=_minutes_since(visit.checked_in_at),
    )


@router.post("/admin/reconcile", response_model=ReconcileOut)
async def reconcile(
    _admin: User = Depends(admin_only),
    session: AsyncSession = Depends(get_session),
    queues: QueueService = Depends(get_queues),
):
    return await visit_service.reconcile(session, queues)
