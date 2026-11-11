"""Input and output types for the triage engine. Pure Python: no DB, no web, no LLM."""
from dataclasses import dataclass, field
from enum import Enum


class TriageInputError(ValueError):
    """Raised for impossible input (e.g. heart rate 900) instead of silently triaging garbage."""


class Avpu(str, Enum):
    ALERT = "A"
    VOICE = "V"  # responds only to voice
    PAIN = "P"  # responds only to pain
    UNRESPONSIVE = "U"


def _check(name: str, value, lo, hi) -> None:
    if value is not None and not (lo <= value <= hi):
        raise TriageInputError(f"{name}={value} is outside the plausible range {lo}-{hi}")


@dataclass(frozen=True)
class Vitals:
    """All fields optional: rural clinics often cannot measure everything."""

    heart_rate: int | None = None
    resp_rate: int | None = None
    systolic_bp: int | None = None
    spo2: int | None = None
    temperature_c: float | None = None
    avpu: Avpu | None = None
    gcs: int | None = None

    def __post_init__(self) -> None:
        _check("heart_rate", self.heart_rate, 0, 300)
        _check("resp_rate", self.resp_rate, 0, 100)
        _check("systolic_bp", self.systolic_bp, 0, 300)
        _check("spo2", self.spo2, 0, 100)
        _check("temperature_c", self.temperature_c, 25, 45)
        _check("gcs", self.gcs, 3, 15)


@dataclass(frozen=True)
class PatientInput:
    age_years: float
    symptoms: tuple[str, ...] = ()
    vitals: Vitals = field(default_factory=Vitals)
    pain_score: int | None = None  # 0-10

    def __post_init__(self) -> None:
        _check("age_years", self.age_years, 0, 120)
        _check("pain_score", self.pain_score, 0, 10)
        # normalise: lowercase, trimmed, de-duplicated, order kept
        cleaned = tuple(dict.fromkeys(s.strip().lower() for s in self.symptoms if s.strip()))
        object.__setattr__(self, "symptoms", cleaned)


@dataclass(frozen=True)
class Reason:
    rule_id: str
    level: int  # the ESI level this rule alone would assign (1 = most urgent)
    text: str


@dataclass(frozen=True)
class TriageResult:
    esi_level: int
    department: str
    reasons: tuple[Reason, ...]  # every rule that fired, most urgent first
    red_flags: tuple[str, ...]  # rule ids that pushed the level to 1 or 2
    missing_info: tuple[str, ...]
    unrecognized_symptoms: tuple[str, ...]
    explanation: str
