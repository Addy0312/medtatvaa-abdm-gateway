from pydantic import BaseModel, Field
from datetime import datetime

class FacilityInfo(BaseModel):
    facility_id: str = Field(..., description="ABDM HFR Facility ID", example="SBX-FACILITY-ID")
    name: str = Field(..., description="Name of Clinic/Imaging Centre", example="Demo Imaging Centre")

class PatientDemographics(BaseModel):
    local_patient_id: str = Field(..., example="P12345")
    abha_address: str = Field(..., example="sandbox-user@sbx")
    name: str = Field(..., example="Test Patient")
    gender: str = Field(..., pattern="^(M|F|O)$", example="F")
    year_of_birth: int = Field(..., ge=1900, le=2026, example=1980)

class StudyInfo(BaseModel):
    local_study_id: str = Field(..., example="US-2026-0001")
    study_instance_uid: str = Field(..., example="1.2.840.113619.2.55.3.12345")
    modality: str = Field(default="US", example="US")
    study_date_time: datetime = Field(..., example="2026-10-31T10:00:00+05:30")
    description: str = Field(..., example="Ultrasound Abdomen")

class ReportInfo(BaseModel):
    local_report_id: str = Field(..., example="RPT-0001")
    status: str = Field(default="FINAL", example="FINAL")
    title: str = Field(..., example="US Abdomen")
    findings: str = Field(..., example="Synthetic test findings only. Liver and kidneys appear normal.")
    impression: str = Field(..., example="Synthetic test impression only. No focal abnormalities.")
    finalized_at: datetime = Field(..., example="2026-10-31T10:20:00+05:30")

class ReportingPractitioner(BaseModel):
    name: str = Field(..., example="Dr Test")
    registration_number: str = Field(..., example="TEST-REG-1234")

class CanonicalDiagnosticReportPayload(BaseModel):
    schema_version: str = Field(default="1.0", example="1.0")
    facility: FacilityInfo
    patient: PatientDemographics
    study: StudyInfo
    report: ReportInfo
    reporting_practitioner: ReportingPractitioner