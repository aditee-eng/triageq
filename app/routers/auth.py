from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.ratelimit import ensure_not_locked, record_failure, record_success
from app.redis_client import get_redis
from app.schemas import Token, UserOut
from app.security import DUMMY_HASH, create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    email = form.username.lower()
    # request.client is the direct peer. Behind a reverse proxy, configure the proxy
    # (e.g. uvicorn --proxy-headers) rather than trusting X-Forwarded-For here.
    ip = request.client.host if request.client else "unknown"
    await ensure_not_locked(redis, email, ip)

    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()

    ok = verify_password(form.password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok or not user.is_active:
        await record_failure(redis, email, ip)
        # one message for every failure mode: don't reveal which part was wrong
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await record_success(redis, email, ip)
    return Token(access_token=create_access_token(str(user.id), user.role.value))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
