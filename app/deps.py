import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Role, User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

_unauthorized = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    claims = decode_access_token(token)
    if not claims or "sub" not in claims:
        raise _unauthorized
    try:
        user_id = uuid.UUID(claims["sub"])
    except ValueError:
        raise _unauthorized
    # Load from DB every request so a deactivated user loses access immediately,
    # and the role comes from the DB, not from the (possibly stale) token.
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized
    return user


def require_role(*roles: Role):
    allowed = set(roles)

    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return checker
