# app/schemas/abha.py
from pydantic import BaseModel, Field
from typing import Optional
from app.models.entities import TransactionStatus

class AbhaVerifyRequest(BaseModel):
    abha_address: str = Field(..., description="Patient ABHA Address", example="sandbox-user@sbx")
    auth_mode: str = Field(default="MOBILE_OTP", description="Authentication mode: MOBILE_OTP or AADHAAR_OTP", example="MOBILE_OTP")

class AbhaOtpConfirmRequest(BaseModel):
    transaction_id: str = Field(..., description="Transaction ID returned from verify-or-link", example="gw_01J8K9...")
    otp: str = Field(..., min_length=6, max_length=6, description="6-digit verification OTP", example="123456")

class AbhaProfileData(BaseModel):
    abha_address: str
    abha_number: Optional[str] = None
    name: str
    gender: str
    year_of_birth: int
    mobile: Optional[str] = None

class AbhaVerificationResponse(BaseModel):
    transaction_id: str
    status: TransactionStatus
    action_required: Optional[str] = Field(None, description="Next client action, e.g. OTP_REQUIRED", example="OTP_REQUIRED")
    message: str
    profile: Optional[AbhaProfileData] = None