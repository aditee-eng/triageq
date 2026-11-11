import itertools

import pytest

from app.triage import Avpu, PatientInput, TriageInputError, Vitals, triage
from app.triage.symptoms import CATALOG


def level(age=30, symptoms=(), pain=None, **vitals) -> int:
    return triage(PatientInput(age, tuple(symptoms), Vitals(**vitals), pain)).esi_level


# ---------- fixed-level symptoms ----------
@pytest.mark.parametrize("code", [c for c, s in CATALOG.items() if s.level == 1])
def test_every_level1_symptom_is_esi1(code):
    assert level(symptoms=[code]) == 1


@pytest.mark.parametrize("code", [c for c, s in CATALOG.items() if s.level == 2])
def test_every_level2_symptom_is_esi2(code):
    assert level(symptoms=[code]) == 2


def test_high_risk_symptoms_go_to_emergency():
    assert triage(PatientInput(50, ("chest_pain",))).department == "emergency"


# ---------- resource-based baseline ----------
@pytest.mark.parametrize(
    "symptoms, expected",
    [
        (["sore_throat"], 5),  # 0 resources
        (["rash"], 5),
        (["cough"], 4),  # 1 resource
        (["laceration"], 4),
        (["abdominal_pain"], 3),  # 2 resources
        (["suspected_fracture"], 3),
        (["cough", "urinary_symptoms"], 3),  # 1 + 1 distinct resources = 2
        (["cough", "limb_injury"], 4),  # same resource (xray) twice still counts once
    ],
)
def test_resource_baseline(symptoms, expected):
    assert level(symptoms=symptoms) == expected


# ---------- safety floors ----------
def test_no_information_defaults_to_esi3_not_5():
    r = triage(PatientInput(30))
    assert r.esi_level == 3 and "SAFE:no_info" in [x.rule_id for x in r.reasons]


def test_unrecognised_symptom_is_floored_at_esi3():
    r = triage(PatientInput(30, ("sore_throat", "banana_pain")))
    assert r.esi_level == 3
    assert r.unrecognized_symptoms == ("banana_pain",)


def test_unrecognised_symptom_cannot_hide_a_red_flag():
    assert level(symptoms=["banana_pain", "chest_pain"]) == 2


def test_symptom_input_is_normalised():
    assert level(symptoms=["  Chest_Pain ", "chest_pain"]) == 2


# ---------- vital signs ----------
@pytest.mark.parametrize(
    "vitals",
    [
        {"spo2": 85},
        {"systolic_bp": 80},
        {"resp_rate": 5},
        {"resp_rate": 35},
        {"heart_rate": 30},
        {"heart_rate": 170},
        {"avpu": Avpu.PAIN},
        {"avpu": Avpu.UNRESPONSIVE},
        {"gcs": 7},
    ],
)
def test_critical_vitals_alone_give_esi1(vitals):
    assert level(symptoms=["sore_throat"], **vitals) == 1


def test_reduced_consciousness_gives_esi2():
    assert level(symptoms=["sore_throat"], avpu=Avpu.VOICE) == 2
    assert level(symptoms=["sore_throat"], gcs=12) == 2


def test_single_danger_zone_vital_floors_at_3():
    assert level(symptoms=["sore_throat"], heart_rate=110) == 3


def test_two_danger_zone_vitals_give_esi2():
    assert level(symptoms=["sore_throat"], heart_rate=110, resp_rate=24) == 2


def test_normal_vitals_do_not_change_result():
    assert level(symptoms=["sore_throat"], heart_rate=75, resp_rate=16, systolic_bp=120, spo2=98) == 5


@pytest.mark.parametrize(
    "age, hr, expected",
    [
        (30, 110, 3),  # adult: 110 is in the danger zone
        (5, 110, 5),  # 5-year-old: 110 is normal
        (5, 150, 3),  # 5-year-old: 150 is in the danger zone
        (0.1, 170, 5),  # infant: 170 is still normal
    ],
)
def test_danger_zone_depends_on_age(age, hr, expected):
    assert level(age=age, symptoms=["sore_throat"], heart_rate=hr) == expected


def test_hypotension_threshold_depends_on_age():
    assert level(age=0.5, symptoms=["sore_throat"], systolic_bp=75) == 5  # infant min is 70
    assert level(age=30, symptoms=["sore_throat"], systolic_bp=75) == 1  # adult min is 90


# ---------- pain and age rules ----------
def test_severe_pain_gives_esi2_but_moderate_does_not():
    assert level(symptoms=["back_pain"], pain=9) == 2
    assert level(symptoms=["back_pain"], pain=6) == 4


def test_fever_in_young_infant_is_esi2_but_not_in_adult():
    assert level(age=0.1, symptoms=["fever"]) == 2
    assert level(age=0.1, temperature_c=38.5, symptoms=["cough"]) == 2
    assert level(age=30, symptoms=["fever"]) == 3


# ---------- department routing ----------
def test_child_with_general_complaint_goes_to_pediatrics():
    assert triage(PatientInput(6, ("fever",))).department == "pediatrics"


def test_department_follows_the_symptom_needing_most_resources():
    assert triage(PatientInput(30, ("rash", "suspected_fracture"))).department == "orthopedics"


# ---------- explanations and missing info ----------
def test_explanation_names_the_deciding_reason_and_missing_info():
    r = triage(PatientInput(50, ("chest_pain",)))
    assert "ESI 2" in r.explanation and "Chest pain" in r.explanation
    assert "spo2" in r.missing_info and "pain_score" in r.missing_info
    assert "SYM:chest_pain" in r.red_flags


def test_reasons_are_sorted_most_urgent_first():
    r = triage(PatientInput(50, ("chest_pain", "cough"), Vitals(spo2=85)))
    levels = [x.level for x in r.reasons]
    assert levels == sorted(levels) and r.esi_level == 1


# ---------- input validation ----------
@pytest.mark.parametrize(
    "kwargs",
    [
        {"heart_rate": 900},
        {"spo2": 150},
        {"temperature_c": 10},
        {"gcs": 2},
    ],
)
def test_impossible_vitals_are_rejected(kwargs):
    with pytest.raises(TriageInputError):
        Vitals(**kwargs)


@pytest.mark.parametrize("kwargs", [{"age_years": -1}, {"age_years": 200}, {"age_years": 30, "pain_score": 11}])
def test_impossible_patient_input_is_rejected(kwargs):
    with pytest.raises(TriageInputError):
        PatientInput(**kwargs)


# ---------- properties ----------
def test_deterministic():
    p = PatientInput(40, ("abdominal_pain", "fever"), Vitals(heart_rate=105), 5)
    assert triage(p) == triage(p)


def test_adding_a_symptom_never_makes_a_patient_less_urgent():
    codes = list(CATALOG)
    for a, b in itertools.permutations(codes, 2):
        assert level(symptoms=[a, b]) <= level(symptoms=[a]), (a, b)


def test_worsening_spo2_never_lowers_urgency():
    levels = [level(symptoms=["cough"], spo2=s) for s in range(100, 70, -1)]
    assert levels == sorted(levels, reverse=True)  # level number only goes down (more urgent)


# ---------- guards against bugs SQLite hides (it ignores VARCHAR lengths) ----------
def test_every_department_the_engine_can_return_is_seeded_and_fits_the_column():
    from app.models import Department
    from app.seed import DEPARTMENTS

    max_len = Department.__table__.c.code.type.length
    engine_departments = {s.department for s in CATALOG.values()} | {"emergency", "pediatrics", "general_medicine"}
    assert engine_departments <= set(DEPARTMENTS), engine_departments - set(DEPARTMENTS)
    assert all(len(code) <= max_len for code in DEPARTMENTS), [c for c in DEPARTMENTS if len(c) > max_len]
