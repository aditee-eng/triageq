"""Create the first admin from ADMIN_EMAIL / ADMIN_PASSWORD. Safe to run repeatedly."""
import asyncio

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, engine
from app.models import Role, User
from app.security import hash_password


async def seed_admin() -> None:
    if not settings.admin_email or not settings.admin_password:
        print("ADMIN_EMAIL / ADMIN_PASSWORD not set; skipping admin seed")
        return
    async with SessionLocal() as session:
        existing = (
            await session.execute(select(User).where(User.role == Role.ADMIN).limit(1))
        ).scalar_one_or_none()
        if existing:
            print("Admin already exists; skipping")
            return
        session.add(
            User(
                email=settings.admin_email.lower(),
                password_hash=hash_password(settings.admin_password),
                full_name="System Admin",
                role=Role.ADMIN,
            )
        )
        await session.commit()
        print(f"Seeded admin {settings.admin_email}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_admin())
