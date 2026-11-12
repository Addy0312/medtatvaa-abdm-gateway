from pydantic import BaseModel, Field

class CareContextCreateRequest(BaseModel):
    local_patient_id: str = Field(..., example="P12345")
    abha_address: str = Field(..., example="patient@sbx")
    care_context_reference: str = Field(..., description="Study ID or Accession Number", example="US-2026-0001")
    display_name: str = Field(..., description="Readable study label", example="Ultrasound Abdomen - 31 Oct 2026")

class CareContextResponse(BaseModel):
    id: str
    local_patient_id: str
    abha_address: str
    care_context_reference: str
    display_name: str
    is_linked: bool