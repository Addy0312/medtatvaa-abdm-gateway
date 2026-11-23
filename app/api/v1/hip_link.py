# app/api/v1/hip_link.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.abdm.hip_linking import HipLinkTriggerRequest
from app.services.hip_linking_service import HipLinkingService

router = APIRouter(prefix="/care-contexts", tags=["Care Contexts - HIP Initiated Link"])


@router.post(
    "/hip-link",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger HIP-Initiated Linking for Registered Care Contexts",
    description="Initiates ABDM patient authentication to push care contexts directly to patient's ABHA."
)
async def trigger_hip_link(
    payload: HipLinkTriggerRequest,
    db: AsyncSession = Depends(get_db),
):
    tx_id = await HipLinkingService.initiate_hip_auth(
        db=db,
        abha_address=payload.abha_address,
        local_patient_id=payload.local_patient_id,
        care_context_refs=payload.care_context_references,
        auth_mode=payload.auth_mode,
    )
    return {
        "gateway_transaction_id": tx_id,
        "status": "PENDING",
        "message": "HIP-initiated linking authentication dispatched to ABDM Gateway"
    }