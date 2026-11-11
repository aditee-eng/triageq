from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import visit_service
from app.db import get_session
from app.deps import require_role
from app.models import Role, User
from app.queue import QueueService
from app.redis_client import get_queues
from app.schemas import CheckInIn, CheckInOut
from app.triage import TriageInputError

router = APIRouter(prefix="/visits", tags=["visits"])
staff = require_role(Role.NURSE, Role.DOCTOR, Role.ADMIN)


@router.post("/check-in", response_model=CheckInOut, status_code=status.HTTP_201_CREATED)
async def check_in(
    body: CheckInIn,
    user: User = Depends(staff),
    session: AsyncSession = Depends(get_session),
    queues: QueueService = Depends(get_queues),
):
    try:
        return await visit_service.check_in(session, queues, body, user)
    except TriageInputError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
