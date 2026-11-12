from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.patient import PatientCreateRequest, PatientResponse
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/patients", tags=["Patients"])

@router.post("", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
async def register_patient(
    payload: PatientCreateRequest,
    x_idempotency_key: str = Header(..., description="Unique client request key to prevent duplicate submissions"),
    db: AsyncSession = Depends(get_db)
):
    """
    Registers a synthetic/local patient reference in the Medtatvaa Gateway.
    """
    # Create or fetch an idempotent transaction record
    await TransactionService.get_or_create_transaction(
        db=db,
        idempotency_key=x_idempotency_key,
        operation_type="PATIENT_REGISTER"
    )

    return PatientResponse(
        local_patient_id=payload.local_patient_id,
        abha_address=payload.abha_address,
        name=payload.name,
        gender=payload.gender,
        year_of_birth=payload.year_of_birth,
        is_registered=True
    )