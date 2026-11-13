import uuid
from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.entities import CareContextRecord, TransactionStatus
from app.schemas.canonical_report import CanonicalDiagnosticReportPayload
from app.schemas.transaction import TransactionResponse
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/records", tags=["Diagnostic Records"])

@router.post(
    "/diagnostic-report",
    response_model=TransactionResponse,
    status_code=status.HTTP_202_ACCEPTED
)
async def submit_diagnostic_report(
    payload: CanonicalDiagnosticReportPayload,
    x_idempotency_key: str = Header(..., description="Unique client request ID to prevent duplicates"),
    db: AsyncSession = Depends(get_db)
):
    """
    Submits a Medtatvaa canonical ultrasound/radiology report.
    Validates report fields, indexes care context, and queues for FHIR conversion.
    """
    # 1. Create or retrieve an idempotent transaction
    tx, is_created = await TransactionService.get_or_create_transaction(
        db=db,
        idempotency_key=x_idempotency_key,
        operation_type="REPORT_SHARE"
    )

    # 2. Automatically register/ensure Care Context exists in the database
    query = select(CareContextRecord).where(
        CareContextRecord.abha_address == payload.patient.abha_address,
        CareContextRecord.care_context_reference == payload.study.local_study_id
    )
    result = await db.execute(query)
    existing_cc = result.scalar_one_or_none()

    if not existing_cc:
        new_cc = CareContextRecord(
            id=str(uuid.uuid4()),
            local_patient_id=payload.patient.local_patient_id,
            abha_address=payload.patient.abha_address,
            care_context_reference=payload.study.local_study_id,
            display_name=f"{payload.study.description} - {payload.report.title}",
            is_linked=0
        )
        db.add(new_cc)
        await db.commit()

    # 3. Return normalized transaction response (HTTP 202 Accepted)
    return TransactionResponse(
        transaction_id=tx.gateway_transaction_id,
        status=TransactionStatus.PENDING,
        abdm_request_id=tx.abdm_request_id,
        message="Diagnostic report accepted and queued for NRCeS FHIR conversion."
    )