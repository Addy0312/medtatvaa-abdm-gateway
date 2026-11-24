# app/schemas/abdm/consent.py
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.abdm.discovery import ErrorRepresentation, GatewayResponseReference


class ConsentPatientRef(BaseModel):
    id: str = Field(..., description="Patient ABHA address")


class ConsentCareContextRef(BaseModel):
    patientReference: str
    careContextReference: str


class ConsentPurpose(BaseModel):
    text: str
    code: str
    refUri: Optional[str] = None


class ConsentEntityRef(BaseModel):
    id: str
    name: Optional[str] = None


class ConsentDateRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_date: datetime = Field(..., alias="from")
    to_date: datetime = Field(..., alias="to")


class ConsentFrequency(BaseModel):
    unit: str = "HOUR"
    value: int = 1
    repeats: int = 0


class ConsentPermission(BaseModel):
    accessMode: str = Field(default="VIEW")
    dateRange: ConsentDateRange
    dataEraseAt: datetime
    frequency: Optional[ConsentFrequency] = None


class ConsentDetail(BaseModel):
    schemaVersion: Optional[str] = "v1"
    consentId: str
    createdAt: datetime
    patient: ConsentPatientRef
    careContexts: List[ConsentCareContextRef] = Field(default_factory=list)
    purpose: Optional[ConsentPurpose] = None
    hip: Optional[ConsentEntityRef] = None
    hiu: Optional[ConsentEntityRef] = None
    consentManager: Optional[ConsentEntityRef] = None
    hiTypes: List[str] = Field(default_factory=list)
    permission: ConsentPermission


class ConsentNotificationBody(BaseModel):
    status: str = Field(..., description="GRANTED, REVOKED, or EXPIRED")
    consentId: str
    consentDetail: Optional[ConsentDetail] = None
    signature: Optional[str] = None


class ConsentHipNotifyRequest(BaseModel):
    requestId: UUID
    timestamp: datetime
    notification: ConsentNotificationBody


class ConsentNotifyAcknowledgement(BaseModel):
    status: str = Field(default="OK")
    consentId: str


class ConsentHipOnNotifyPayload(BaseModel):
    requestId: UUID
    timestamp: datetime
    acknowledgement: Optional[ConsentNotifyAcknowledgement] = None
    error: Optional[ErrorRepresentation] = None
    resp: GatewayResponseReference