import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Role(str, enum.Enum):
    PATIENT = "patient"
    NURSE = "nurse"
    DOCTOR = "doctor"
    ADMIN = "admin"


class Sex(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class VisitStatus(str, enum.Enum):
    WAITING = "waiting"
    CALLED = "called"
    IN_CONSULTATION = "in_consultation"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class TriageSource(str, enum.Enum):
    RULES = "rules"  # deterministic ESI rules from structured input
    LLM_ASSISTED = "llm_assisted"  # rules engine fed by LLM-extracted fields
    STAFF_OVERRIDE = "staff_override"  # manual change by nurse/doctor


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    """Store the lowercase values ('waiting'), not the member names ('WAITING')."""
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = _created_at()


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = _uuid_pk()
    uhid: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    date_of_birth: Mapped[date] = mapped_column(Date)
    sex: Mapped[Sex] = mapped_column(_enum(Sex, "sex"))
    phone: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = _created_at()

    visits: Mapped[list["Visit"]] = relationship(back_populates="patient")


class Visit(Base):
    """One hospital visit. Queue position lives in Redis; this is the source of truth."""

    __tablename__ = "visits"
    __table_args__ = (Index("ix_visits_dept_status", "department_id", "status"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    status: Mapped[VisitStatus] = mapped_column(
        _enum(VisitStatus, "visit_status"), default=VisitStatus.WAITING
    )
    chief_complaint: Mapped[str] = mapped_column(Text)
    checked_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    called_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    patient: Mapped[Patient] = relationship(back_populates="visits")
    assessments: Mapped[list["TriageAssessment"]] = relationship(
        back_populates="visit", order_by="TriageAssessment.created_at"
    )


class TriageAssessment(Base):
    """Append-only: an override adds a new row, the latest row is the current priority."""

    __tablename__ = "triage_assessments"
    __table_args__ = (
        CheckConstraint("esi_level BETWEEN 1 AND 5", name="ck_esi_level_range"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), index=True)
    esi_level: Mapped[int] = mapped_column(Integer)  # 1 = resuscitation ... 5 = non-urgent
    source: Mapped[TriageSource] = mapped_column(_enum(TriageSource, "triage_source"))
    vitals: Mapped[dict | None] = mapped_column(JSON)
    symptoms: Mapped[list | None] = mapped_column(JSON)
    red_flags: Mapped[list | None] = mapped_column(JSON)
    explanation: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()

    visit: Mapped[Visit] = relationship(back_populates="assessments")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = _created_at()
