"""Symptom catalogue.

`level` is a fixed ESI level for high-risk symptoms (1 or 2). For everything else it is
None and the level comes from how many hospital resources the symptom is expected to need
(ESI: 2+ resources -> 3, 1 -> 4, 0 -> 5).

NOTE: this catalogue and the thresholds in vitals.py are an educational ESI-style
approximation, not a clinically validated tool. Clinical review is needed before any real use.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Symptom:
    code: str
    label: str
    level: int | None
    resources: frozenset[str]
    department: str


def _s(code, label, level=None, resources=(), dept="general_medicine") -> Symptom:
    return Symptom(code, label, level, frozenset(resources), dept)


_ALL = [
    # --- ESI 1: needs immediate life-saving intervention ---
    _s("cardiac_arrest", "Cardiac arrest", 1, dept="emergency"),
    _s("respiratory_arrest", "Not breathing", 1, dept="emergency"),
    _s("unresponsive", "Unresponsive", 1, dept="emergency"),
    _s("choking", "Choking / airway obstruction", 1, dept="emergency"),
    _s("active_seizure", "Seizure in progress", 1, dept="emergency"),
    _s("severe_bleeding", "Uncontrolled severe bleeding", 1, dept="emergency"),
    _s("anaphylaxis", "Anaphylaxis (severe allergic reaction)", 1, dept="emergency"),
    # --- ESI 2: high-risk, should not wait ---
    _s("chest_pain", "Chest pain (possible cardiac cause)", 2, dept="emergency"),
    _s("stroke_signs", "Stroke signs (face droop, slurred speech, one-sided weakness)", 2, dept="emergency"),
    _s("breathing_difficulty", "Difficulty breathing", 2, dept="emergency"),
    _s("altered_mental_status", "Confusion / altered mental status", 2, dept="emergency"),
    _s("suicidal_ideation", "Suicidal thoughts", 2, dept="psychiatry"),
    _s("overdose_poisoning", "Overdose or poisoning", 2, dept="emergency"),
    _s("head_injury_loc", "Head injury with loss of consciousness", 2, dept="emergency"),
    _s("pregnancy_bleeding", "Bleeding or severe pain in pregnancy", 2, dept="obstetrics_gynecology"),
    _s("sudden_severe_headache", "Sudden, severe 'worst ever' headache", 2, dept="emergency"),
    # --- resource-based (level decided by expected resources) ---
    _s("abdominal_pain", "Abdominal pain", None, {"labs", "ct_mri_us"}, "surgery"),
    _s("fever", "Fever", None, {"labs", "xray"}),
    _s("vomiting_diarrhea", "Vomiting / diarrhoea", None, {"labs", "iv_fluids"}),
    _s("dizziness", "Dizziness / fainting", None, {"labs", "ecg"}),
    _s("palpitations", "Palpitations", None, {"labs", "ecg"}),
    _s("suspected_fracture", "Suspected fracture", None, {"xray", "specialty_consult"}, "orthopedics"),
    _s("limb_injury", "Limb injury / sprain", None, {"xray"}, "orthopedics"),
    _s("back_pain", "Back pain", None, {"xray"}, "orthopedics"),
    _s("laceration", "Cut needing stitches", None, {"procedure"}, "surgery"),
    _s("cough", "Cough", None, {"xray"}),
    _s("urinary_symptoms", "Urinary symptoms", None, {"labs"}),
    _s("anxiety", "Anxiety / emotional distress", None, {"specialty_consult"}, "psychiatry"),
    _s("sore_throat", "Sore throat", None, (), "ent"),
    _s("ear_pain", "Ear pain", None, (), "ent"),
    _s("eye_irritation", "Eye irritation", None, (), "ophthalmology"),
    _s("rash", "Skin rash", None, (), "dermatology"),
    _s("mild_headache", "Mild headache", None, ()),
]

CATALOG: dict[str, Symptom] = {s.code: s for s in _ALL}
