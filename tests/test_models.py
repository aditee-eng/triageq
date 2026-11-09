import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    Department,
    Patient,
    Sex,
    TriageAssessment,
    TriageSource,
    Visit,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _visit(session):
    dept = Department(code="MED", name="General Medicine")
    patient = Patient(uhid="UH001", full_name="Test Patient", date_of_birth=date(1990, 1, 1), sex=Sex.FEMALE)
    session.add_all([dept, patient])
    session.flush()
    visit = Visit(patient_id=patient.id, department_id=dept.id, chief_complaint="chest pain")
    session.add(visit)
    session.flush()
    return visit


def test_visit_defaults_to_waiting(session):
    visit = _visit(session)
    assert visit.status.value == "waiting"


def test_latest_assessment_is_current(session):
    visit = _visit(session)
    session.add(TriageAssessment(visit_id=visit.id, esi_level=3, source=TriageSource.RULES))
    session.add(TriageAssessment(visit_id=visit.id, esi_level=2, source=TriageSource.STAFF_OVERRIDE))
    session.commit()
    session.refresh(visit)
    assert [a.esi_level for a in visit.assessments] == [3, 2]


@pytest.mark.parametrize("bad_level", [0, 6])
def test_esi_level_constraint(session, bad_level):
    visit = _visit(session)
    session.add(TriageAssessment(visit_id=visit.id, esi_level=bad_level, source=TriageSource.RULES))
    with pytest.raises(IntegrityError):
        session.flush()
