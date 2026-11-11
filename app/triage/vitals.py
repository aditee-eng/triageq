"""Age-aware vital-sign thresholds. Educational ESI-style values, pending clinical review."""
from app.triage.models import Avpu, Reason, Vitals


def min_systolic_bp(age_years: float) -> int:
    if age_years < 1:
        return 70
    if age_years < 10:
        return int(70 + 2 * age_years)
    return 90


def danger_zone_limits(age_years: float) -> tuple[int, int]:
    """(max heart rate, max respiratory rate) before the vital is 'in the danger zone'."""
    if age_years < 0.25:
        return 180, 50
    if age_years < 3:
        return 160, 40
    if age_years < 8:
        return 140, 30
    return 100, 20


def critical_vital_reasons(age: float, v: Vitals) -> list[Reason]:
    out: list[Reason] = []

    def add(rule_id: str, text: str) -> None:
        out.append(Reason(rule_id, 1, text))

    if v.spo2 is not None and v.spo2 < 90:
        add("VIT:spo2_critical", f"Oxygen saturation {v.spo2}% is critically low (<90%)")
    if v.systolic_bp is not None and v.systolic_bp < min_systolic_bp(age):
        add("VIT:hypotension", f"Systolic BP {v.systolic_bp} is below the minimum for age ({min_systolic_bp(age)})")
    if v.resp_rate is not None:
        if v.resp_rate < 8:
            add("VIT:rr_critical_low", f"Respiratory rate {v.resp_rate} is critically low")
        elif age >= 8 and v.resp_rate > 30:
            add("VIT:rr_critical_high", f"Respiratory rate {v.resp_rate} is critically high")
    if v.heart_rate is not None:
        if v.heart_rate < 40:
            add("VIT:hr_critical_low", f"Heart rate {v.heart_rate} is critically low")
        elif age >= 8 and v.heart_rate > 150:
            add("VIT:hr_critical_high", f"Heart rate {v.heart_rate} is critically high")
    if v.avpu in (Avpu.PAIN, Avpu.UNRESPONSIVE):
        add("VIT:avpu_critical", "Responds only to pain or is unresponsive")
    if v.gcs is not None and v.gcs <= 8:
        add("VIT:gcs_critical", f"GCS {v.gcs} (<=8): severely reduced consciousness")
    return out


def neuro_reasons(v: Vitals) -> list[Reason]:
    out: list[Reason] = []
    if v.avpu == Avpu.VOICE:
        out.append(Reason("VIT:avpu_voice", 2, "Responds only to voice: altered consciousness"))
    if v.gcs is not None and 9 <= v.gcs <= 13:
        out.append(Reason("VIT:gcs_reduced", 2, f"GCS {v.gcs}: reduced consciousness"))
    return out


def danger_zone_hits(age: float, v: Vitals) -> list[str]:
    max_hr, max_rr = danger_zone_limits(age)
    hits: list[str] = []
    if v.heart_rate is not None and v.heart_rate > max_hr:
        hits.append(f"heart rate {v.heart_rate} (>{max_hr})")
    if v.resp_rate is not None and v.resp_rate > max_rr:
        hits.append(f"respiratory rate {v.resp_rate} (>{max_rr})")
    if v.spo2 is not None and v.spo2 < 92:
        hits.append(f"oxygen saturation {v.spo2}% (<92%)")
    return hits
