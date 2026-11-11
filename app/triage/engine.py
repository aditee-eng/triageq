"""Deterministic ESI-style triage.

Design rule: every rule that matches emits a *candidate* level, and the final level is the
MOST URGENT candidate. So adding information can never make a patient look less urgent, and
nothing here (certainly not an LLM) can lower a level that a safety rule has set.

Safety floors: when we cannot fully understand the patient (no info, or an unrecognised
symptom), the level is capped at ESI 3 so such a patient is never labelled 4 or 5.
"""
from app.triage.models import PatientInput, Reason, TriageResult
from app.triage.symptoms import CATALOG
from app.triage.vitals import (
    critical_vital_reasons,
    danger_zone_hits,
    neuro_reasons,
)

LEVEL_NAMES = {1: "Resuscitation", 2: "Emergent", 3: "Urgent", 4: "Less urgent", 5: "Non-urgent"}
_TRACKED_VITALS = ("heart_rate", "resp_rate", "systolic_bp", "spo2", "temperature_c")


def triage(p: PatientInput) -> TriageResult:
    known = [CATALOG[c] for c in p.symptoms if c in CATALOG]
    unknown = tuple(c for c in p.symptoms if c not in CATALOG)
    v = p.vitals
    reasons: list[Reason] = []

    # 1. high-risk symptoms with a fixed level
    for s in known:
        if s.level is not None:
            reasons.append(Reason(f"SYM:{s.code}", s.level, s.label))

    # 2. vital signs and consciousness
    reasons += critical_vital_reasons(p.age_years, v)
    reasons += neuro_reasons(v)
    hits = danger_zone_hits(p.age_years, v)
    if len(hits) >= 2:
        reasons.append(Reason("VIT:danger_zone_multiple", 2, "Multiple danger-zone vitals: " + ", ".join(hits)))
    elif hits:
        reasons.append(Reason("VIT:danger_zone", 3, "Danger-zone vital: " + hits[0]))

    # 3. pain and age-specific rules
    if p.pain_score is not None and p.pain_score >= 8:
        reasons.append(Reason("PAIN:severe", 2, f"Severe pain ({p.pain_score}/10)"))
    if p.age_years < 0.25:
        febrile = (v.temperature_c is not None and v.temperature_c >= 38.0) or "fever" in p.symptoms
        if febrile:
            reasons.append(Reason("AGE:febrile_infant", 2, "Fever in an infant under 3 months"))

    # 4. resource-based baseline (ESI: 2+ resources -> 3, 1 -> 4, 0 -> 5)
    if known:
        needed = frozenset().union(*(s.resources for s in known))
        level = 3 if len(needed) >= 2 else 4 if len(needed) == 1 else 5
        label = ", ".join(sorted(needed)) if needed else "no special resources"
        reasons.append(Reason("RES:baseline", level, f"Expected resources: {label}"))

    # 5. safety floors: if we do not fully understand the patient, never go below ESI 3
    if unknown:
        reasons.append(Reason("SAFE:unrecognized", 3, "Unrecognised symptom(s): " + ", ".join(unknown)))
    if not known and not unknown:
        reasons.append(Reason("SAFE:no_info", 3, "No symptoms recorded: nurse assessment needed"))

    reasons.sort(key=lambda r: r.level)
    level = reasons[0].level
    department = _department(level, known, p.age_years)
    red_flags = tuple(r.rule_id for r in reasons if r.level <= 2)
    missing = tuple(n for n in _TRACKED_VITALS if getattr(v, n) is None) + (
        ("pain_score",) if p.pain_score is None else ()
    )

    return TriageResult(
        esi_level=level,
        department=department,
        reasons=tuple(reasons),
        red_flags=red_flags,
        missing_info=missing,
        unrecognized_symptoms=unknown,
        explanation=_explain(level, department, reasons, missing),
    )


def _department(level: int, known, age: float) -> str:
    if level <= 2:
        return "emergency"
    # the symptom that needs the most resources decides; ties keep input order
    dept = "general_medicine"
    if known:
        dept = max(known, key=lambda s: len(s.resources)).department
    if age < 14 and dept == "general_medicine":
        return "pediatrics"
    return dept


def _explain(level: int, department: str, reasons: list[Reason], missing: tuple[str, ...]) -> str:
    top = [r.text for r in reasons if r.level == level]
    text = f"ESI {level} ({LEVEL_NAMES[level]}) -> {department}. Because: " + "; ".join(top) + "."
    if missing:
        text += " Not recorded: " + ", ".join(missing) + "."
    return text
