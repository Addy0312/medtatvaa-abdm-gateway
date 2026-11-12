import pytest
from pydantic import ValidationError
from datetime import datetime
from app.schemas.canonical_report import (
    CanonicalDiagnosticReportPayload,
    FacilityInfo,
    PatientDemographics,
    StudyInfo,
    ReportInfo,
    ReportingPractitioner
)

def test_valid_canonical_payload():
    payload = CanonicalDiagnosticReportPayload(
        facility=FacilityInfo(facility_id="SBX-001", name="Demo Imaging"),
        patient=PatientDemographics(
            local_patient_id="P12345",
            abha_address="test@sbx",
            name="John Doe",
            gender="M",
            year_of_birth=1990
        ),
        study=StudyInfo(
            local_study_id="US-001",
            study_instance_uid="1.2.840.113619.2.55.3",
            modality="US",
            study_date_time=datetime.now(),
            description="Ultrasound Abdomen"
        ),
        report=ReportInfo(
            local_report_id="RPT-001",
            status="FINAL",
            title="US Abdomen",
            findings="Normal liver and kidneys.",
            impression="Normal study.",
            finalized_at=datetime.now()
        ),
        reporting_practitioner=ReportingPractitioner(
            name="Dr. Smith",
            registration_number="REG-12345"
        )
    )
    assert payload.patient.abha_address == "test@sbx"
    assert payload.study.modality == "US"

def test_invalid_gender_rejection():
    with pytest.raises(ValidationError):
        PatientDemographics(
            local_patient_id="P12345",
            abha_address="test@sbx",
            name="John Doe",
            gender="INVALID_GENDER",  # Must be M, F, or O
            year_of_birth=1990
        )