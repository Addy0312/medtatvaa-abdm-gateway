# app/api/v1/records.py
import uuid
from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.entities import CareContextRecord, TransactionStatus
from app.schemas.canonical_report import CanonicalDiagnosticReportPayload
from app.schemas.transaction import ErrorResponse, TransactionResponse
from app.services.diagnostic_report_service import (
    DiagnosticReportConflictError,
    DiagnosticReportService,
)
from app.services.transaction_service import TransactionConflictError, TransactionService

router = APIRouter(prefix="/records", tags=["Diagnostic Records"])


def _conflict_response(
    message: str,
    error_code: str,
    transaction_id: str | None = None,
    details: object | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        transaction_id=transaction_id,
        status="FAILED_FINAL",
        error_code=error_code,
        message=message,
        details=details,
    ).model_dump(mode="json")
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body)


@router.post(
    "/diagnostic-report",
    response_model=TransactionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def submit_diagnostic_report(
    payload: CanonicalDiagnosticReportPayload,
    x_idempotency_key: str = Header(..., description="Unique client request ID to prevent duplicates"),
    db: AsyncSession = Depends(get_db),
) -> TransactionResponse | Response:
    """
    Submits a Medtatvaa canonical ultrasound/radiology report.
    Validates report fields and patient/care-context identity, ensures care context,
    persists canonical JSON atomically, and returns TransactionResponse without
    overwriting conflicting records.
    """
    existing_tx = await TransactionService.get_by_idempotency_key(db=db, idempotency_key=x_idempotency_key)
    existing_report = await DiagnosticReportService.get_by_idempotency_key(db=db, idempotency_key=x_idempotency_key)
    _, payload_hash = DiagnosticReportService.canonicalize_payload(payload)

    if existing_tx is not None or existing_report is not None:
        existing_tx_id = existing_tx.gateway_transaction_id if existing_tx is not None else None
        existing_tx_op = existing_tx.operation_type if existing_tx is not None else None
        existing_tx_status = existing_tx.status if existing_tx is not None else None
        existing_tx_req_id = existing_tx.abdm_request_id if existing_tx is not None else None

        if existing_tx is None or existing_tx_op != "REPORT_SHARE":
            return _conflict_response(
                message="Idempotency key belongs to a different operation type or missing transaction.",
                error_code="IDEMPOTENCY_OPERATION_CONFLICT",
                transaction_id=existing_tx_id,
                details={
                    "idempotency_key": x_idempotency_key,
                    "expected_operation_type": "REPORT_SHARE",
                    "actual_operation_type": existing_tx_op,
                },
            )

        if (
            existing_report is None
            or existing_report.gateway_transaction_id != existing_tx_id
            or existing_report.payload_hash != payload_hash
            or existing_report.abha_address != payload.patient.abha_address
            or existing_report.local_patient_id != payload.patient.local_patient_id
            or existing_report.care_context_reference != payload.study.local_study_id
            or existing_report.local_report_id != payload.report.local_report_id
        ):
            return _conflict_response(
                message="Idempotency key already exists with a different payload, report identity, or transaction association.",
                error_code="IDEMPOTENCY_PAYLOAD_CONFLICT",
                transaction_id=existing_tx_id,
                details={
                    "idempotency_key": x_idempotency_key,
                    "care_context_reference": payload.study.local_study_id,
                    "local_report_id": payload.report.local_report_id,
                },
            )

        return TransactionResponse(
            transaction_id=existing_tx_id,
            status=TransactionStatus(existing_tx_status),
            abdm_request_id=existing_tx_req_id,
            message="Diagnostic report accepted and queued for NRCeS FHIR conversion.",
        )

    try:
        await DiagnosticReportService.validate_patient_identity_consistency(db=db, payload=payload)

        existing_tuple_report = await DiagnosticReportService.get_by_key_tuple(
            db=db,
            abha_address=payload.patient.abha_address,
            care_context_reference=payload.study.local_study_id,
            local_report_id=payload.report.local_report_id,
        )
        if existing_tuple_report is not None:
            conflict_tx_id = existing_tuple_report.gateway_transaction_id
            await db.rollback()
            return _conflict_response(
                message="A diagnostic report already exists for this patient, care_context_reference, and local_report_id.",
                error_code="CARE_CONTEXT_REPORT_CONFLICT",
                transaction_id=conflict_tx_id,
                details={
                    "care_context_reference": payload.study.local_study_id,
                    "local_report_id": payload.report.local_report_id,
                    "abha_address": payload.patient.abha_address,
                    "local_patient_id": payload.patient.local_patient_id,
                },
            )

        tx, _ = await TransactionService.get_or_create_transaction(
            db=db,
            idempotency_key=x_idempotency_key,
            operation_type="REPORT_SHARE",
            commit=False,
        )

        existing_cc = await DiagnosticReportService.get_existing_care_context(
            db=db,
            abha_address=payload.patient.abha_address,
            care_context_reference=payload.study.local_study_id,
        )

        if not existing_cc:
            new_cc = CareContextRecord(
                id=str(uuid.uuid4()),
                local_patient_id=payload.patient.local_patient_id,
                abha_address=payload.patient.abha_address,
                care_context_reference=payload.study.local_study_id,
                display_name=f"{payload.study.description} - {payload.report.title}",
                is_linked=0,
            )
            db.add(new_cc)

        await DiagnosticReportService.persist_canonical_report(
            db=db,
            payload=payload,
            idempotency_key=x_idempotency_key,
            gateway_transaction=tx,
            commit=False,
        )

        await db.commit()
        await db.refresh(tx)
    except (DiagnosticReportConflictError, TransactionConflictError) as exc:
        await db.rollback()
        return _conflict_response(
            message=exc.message,
            error_code=exc.code,
            transaction_id=exc.transaction_id,
            details=exc.details,
        )
    except IntegrityError:
        await db.rollback()
        return _conflict_response(
            message="Concurrent conflict while persisting diagnostic report, care context, or transaction.",
            error_code="CONCURRENT_PERSISTENCE_CONFLICT",
            details={
                "care_context_reference": payload.study.local_study_id,
                "local_report_id": payload.report.local_report_id,
                "abha_address": payload.patient.abha_address,
            },
        )
    except Exception:
        await db.rollback()
        raise

    return TransactionResponse(
        transaction_id=tx.gateway_transaction_id,
        status=TransactionStatus(tx.status),
        abdm_request_id=tx.abdm_request_id,
        message="Diagnostic report accepted and queued for NRCeS FHIR conversion.",
    )
