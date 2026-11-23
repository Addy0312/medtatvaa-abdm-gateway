# app/schemas/abdm/hip_linking.py
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.abdm.discovery import ErrorRepresentation, GatewayResponseReference


# --- Outbound Requests to ABDM ---

class AuthRequester(BaseModel):
    type: str = Field(default="HIP")
    id: str = Field(..., description="Registered HIP Facility ID")


class UserAuthInitQuery(BaseModel):
    id: str = Field(..., description="Patient ABHA Address, e.g. aditya@sbx")
    purpose: str = Field(default="LINK", description="LINK, KYC, or KYC_AND_LINK")
    authMode: str = Field(default="DEMOGRAPHICS", description="MOBILE_OTP, AADHAAR_OTP, DEMOGRAPHICS, DIRECT")
    requester: AuthRequester


class UserAuthInitRequest(BaseModel):
    requestId: UUID
    timestamp: datetime
    query: UserAuthInitQuery


class AuthCredential(BaseModel):
    authCode: Optional[str] = Field(default=None, description="OTP code if authMode is OTP")
    demographic: Optional[dict] = Field(default=None, description="Demographic details if authMode is DEMOGRAPHICS")


class UserAuthConfirmRequest(BaseModel):
    requestId: UUID
    timestamp: datetime
    transactionId: str
    credential: AuthCredential


class AddContextItem(BaseModel):
    referenceNumber: str
    display: str


class AddContextPatient(BaseModel):
    referenceNumber: str = Field(..., description="Local patient ID")
    display: str = Field(..., description="Patient display name")
    careContexts: List[AddContextItem]


class AddContextsLinkPayload(BaseModel):
    accessToken: str
    patient: AddContextPatient


class AddCareContextsRequest(BaseModel):
    requestId: UUID
    timestamp: datetime
    link: AddContextsLinkPayload


# --- Inbound Callbacks from ABDM ---

class AuthOnInitDetail(BaseModel):
    transactionId: str
    mode: Optional[str] = None
    meta: Optional[dict] = None


class UserAuthOnInitCallback(BaseModel):
    requestId: UUID
    timestamp: datetime
    auth: Optional[AuthOnInitDetail] = None
    error: Optional[ErrorRepresentation] = None
    resp: GatewayResponseReference


class AuthOnConfirmDetail(BaseModel):
    accessToken: str
    validity: Optional[dict] = None
    patient: Optional[dict] = None


class UserAuthOnConfirmCallback(BaseModel):
    requestId: UUID
    timestamp: datetime
    auth: Optional[AuthOnConfirmDetail] = None
    error: Optional[ErrorRepresentation] = None
    resp: GatewayResponseReference


class AddContextsAcknowledgement(BaseModel):
    status: str = Field(..., description="SUCCESS or FAILURE")


class AddCareContextsOnAddCallback(BaseModel):
    requestId: UUID
    timestamp: datetime
    acknowledgement: Optional[AddContextsAcknowledgement] = None
    error: Optional[ErrorRepresentation] = None
    resp: GatewayResponseReference


# --- Internal Product API Schema ---

class HipLinkTriggerRequest(BaseModel):
    abha_address: str = Field(..., description="Verified patient ABHA address")
    local_patient_id: str = Field(..., description="Local patient ID in MistiqRad/iMagic Neo")
    patient_name: str = Field(default="Medtatvaa Patient")
    care_context_references: List[str] = Field(..., min_length=1, description="Study references to link")
    auth_mode: str = Field(default="DEMOGRAPHICS", description="MOBILE_OTP or DEMOGRAPHICS")