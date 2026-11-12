import uuid
from fastapi import APIRouter, Depends, Header, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.entities import CareContextRecord
from app.schemas.care_context import CareContextCreateRequest, CareContextResponse
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/care-contexts", tags=["Care Contexts"])

@router.post("", response_model=CareContextResponse, status_code=status.HTTP_201_CREATED)
async def create_care_context(
    payload: CareContextCreateRequest,
    x_idempotency_key: str = Header(..., description="Unique client request key"),
    db: AsyncSession = Depends(get_db)
):
    """
    Creates/registers a local ultrasound/imaging care context in the database.
    """
    # 1. Enforce transaction tracking
    await TransactionService.get_or_create_transaction(
        db=db,
        idempotency_key=x_idempotency_key,
        operation_type="CARE_CONTEXT_CREATE"
    )

    # 2. Check if this exact care context reference is already registered for this patient
    query = select(CareContextRecord).where(
        CareContextRecord.abha_address == payload.abha_address,
        CareContextRecord.care_context_reference == payload.care_context_reference
    )
    result = await db.execute(query)
    existing_record = result.scalar_one_or_none()

    if existing_record:
        return CareContextResponse(
            id=existing_record.id,
            local_patient_id=existing_record.local_patient_id,
            abha_address=existing_record.abha_address,
            care_context_reference=existing_record.care_context_reference,
            display_name=existing_record.display_name,
            is_linked=bool(existing_record.is_linked)
        )

    # 3. Insert new care context record
    new_record = CareContextRecord(
        id=str(uuid.uuid4()),
        local_patient_id=payload.local_patient_id,
        abha_address=payload.abha_address,
        care_context_reference=payload.care_context_reference,
        display_name=payload.display_name,
        is_linked=0
    )
    db.add(new_record)
    await db.commit()
    await db.refresh(new_record)

    return CareContextResponse(
        id=new_record.id,
        local_patient_id=new_record.local_patient_id,
        abha_address=new_record.abha_address,
        care_context_reference=new_record.care_context_reference,
        display_name=new_record.display_name,
        is_linked=False
    )