"""Seed departments and the first admin (from ADMIN_EMAIL / ADMIN_PASSWORD). Idempotent."""
import asyncio

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, engine
from app.models import Department, Role, User
from app.security import hash_password

DEPARTMENTS = {
    "emergency": "Emergency",
    "general_medicine": "General Medicine",
    "pediatrics": "Pediatrics",
    "surgery": "Surgery",
    "orthopedics": "Orthopedics",
    "obstetrics_gynecology": "Obstetrics & Gynecology",
    "psychiatry": "Psychiatry",
    "ent": "ENT",
    "ophthalmology": "Ophthalmology",
    "dermatology": "Dermatology",
}


async def seed_departments(session) -> int:
    have = set((await session.execute(select(Department.code))).scalars())
    new = [Department(code=c, name=n) for c, n in DEPARTMENTS.items() if c not in have]
    session.add_all(new)
    await session.commit()
    return len(new)


async def seed_admin(session) -> None:
    if not settings.admin_email or not settings.admin_password:
        print("ADMIN_EMAIL / ADMIN_PASSWORD not set; skipping admin seed")
        return
    existing = (await session.execute(select(User).where(User.role == Role.ADMIN).limit(1))).scalar_one_or_none()
    if existing:
        print("Admin already exists; skipping")
        return
    session.add(User(email=settings.admin_email.lower(), password_hash=hash_password(settings.admin_password),
                     full_name="System Admin", role=Role.ADMIN))
    await session.commit()
    print(f"Seeded admin {settings.admin_email}")


async def main() -> None:
    async with SessionLocal() as session:
        print(f"Seeded {await seed_departments(session)} new department(s)")
        await seed_admin(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
