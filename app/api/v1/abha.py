# app/api/v1/abha.py
from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.abha import (
    AbhaVerifyRequest,
    AbhaOtpConfirmRequest,
    AbhaVerificationResponse
)
from app.services.abha_service import AbhaService

router = APIRouter(prefix="/abha", tags=["ABHA Identity (M1)"])

@router.post(
    "/verify-or-link",
    response_model=AbhaVerificationResponse,
    status_code=status.HTTP_200_OK
)
async def verify_or_link_abha(
    payload: AbhaVerifyRequest,
    x_idempotency_key: str = Header(..., description="Unique client request ID"),
    db: AsyncSession = Depends(get_db)
):
    """
    Step 1 (M1): Initiate ABHA identity verification via Mobile OTP.
    """
    return await AbhaService.initiate_verification(
        db=db,
        abha_address=payload.abha_address,
        auth_mode=payload.auth_mode,
        idempotency_key=x_idempotency_key
    )

@router.post(
    "/confirm-otp",
    response_model=AbhaVerificationResponse,
    status_code=status.HTTP_200_OK
)
async def confirm_abha_otp(
    payload: AbhaOtpConfirmRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 2 (M1): Submit OTP to verify identity and retrieve patient profile.
    """
    return await AbhaService.confirm_otp(
        db=db,
        transaction_id=payload.transaction_id,
        otp=payload.otp
    )