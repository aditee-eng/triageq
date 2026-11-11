import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Role


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)
    role: Role


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool


# ---------- check-in and queues ----------
from datetime import date  # noqa: E402

from app.models import Sex  # noqa: E402
from app.triage import Avpu  # noqa: E402


class PatientIn(BaseModel):
    uhid: str = Field(min_length=3, max_length=32)
    full_name: str = Field(min_length=1, max_length=120)
    date_of_birth: date
    sex: Sex
    phone: str | None = Field(default=None, max_length=20)


class VitalsIn(BaseModel):
    heart_rate: int | None = Field(default=None, ge=0, le=300)
    resp_rate: int | None = Field(default=None, ge=0, le=100)
    systolic_bp: int | None = Field(default=None, ge=0, le=300)
    spo2: int | None = Field(default=None, ge=0, le=100)
    temperature_c: float | None = Field(default=None, ge=25, le=45)
    avpu: Avpu | None = None
    gcs: int | None = Field(default=None, ge=3, le=15)


class CheckInIn(BaseModel):
    patient: PatientIn
    chief_complaint: str = Field(min_length=1, max_length=500)
    symptoms: list[str] = Field(default_factory=list, max_length=20)
    vitals: VitalsIn = Field(default_factory=VitalsIn)
    pain_score: int | None = Field(default=None, ge=0, le=10)


class CheckInOut(BaseModel):
    visit_id: uuid.UUID
    esi_level: int
    department: str
    explanation: str
    red_flags: list[str]
    missing_info: list[str]
    unrecognized_symptoms: list[str]
    queue_position: int | None  # null if Redis was unavailable; reconcile will restore it


class QueueEntry(BaseModel):
    position: int
    visit_id: uuid.UUID
    uhid: str
    patient_name: str
    esi_level: int
    chief_complaint: str
    waiting_minutes: int


class CalledVisit(BaseModel):
    visit_id: uuid.UUID
    uhid: str
    patient_name: str
    esi_level: int
    chief_complaint: str
    waited_minutes: int


class ReconcileOut(BaseModel):
    added: int
    removed: int
