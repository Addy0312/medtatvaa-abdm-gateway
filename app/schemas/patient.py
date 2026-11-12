from pydantic import BaseModel, Field
from typing import Optional

class PatientCreateRequest(BaseModel):
    local_patient_id: str = Field(..., description="Local RIS/PACS Patient ID", example="P12345")
    abha_address: str = Field(..., description="Patient ABHA Address", example="patient@sbx")
    name: str = Field(..., description="Patient Full Name", example="Test Patient")
    gender: str = Field(..., pattern="^(M|F|O)$", description="M, F, or O", example="F")
    year_of_birth: int = Field(..., ge=1900, le=2026, example=1980)

class PatientResponse(BaseModel):
    local_patient_id: str
    abha_address: str
    name: str
    gender: str
    year_of_birth: int
    is_registered: bool = True