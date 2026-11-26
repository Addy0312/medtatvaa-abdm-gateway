# app/services/diagnostic_report_service.py
import hashlib
import json
import uuid
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.entities import CareContextRecord, DiagnosticReportStore, GatewayTransaction
from app.schemas.canonical_report import CanonicalDiagnosticReportPayload


class DiagnosticReportConflictError(Exception):
    """Raised when a report submission conflicts with an existing record, identity, or idempotency key."""

    def __init__(
        self,
        message: str,
        code: str = "DIAGNOSTIC_REPORT_CONFLICT",
        details: Optional[Any] = None,
        transaction_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details
        self.transaction_id = transaction_id


class DiagnosticReportService:
    """
    Async service managing canonical diagnostic report persistence keyed by
    (abha_address, care_context_reference, local_report_id) with patient identity
    validation and safe conflict handling without overwriting existing records.
    """

    @staticmethod
    def canonicalize_payload(payload: CanonicalDiagnosticReportPayload) -> tuple[str, str]:
        canonical_dict = payload.model_dump(mode="json")
        canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        payload_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        return canonical_json, payload_hash

    @staticmethod
    async def get_by_key_tuple(
        db: AsyncSession,
        abha_address: str,
        care_context_reference: str,
        local_report_id: str,
    ) -> Optional[DiagnosticReportStore]:
        stmt = select(DiagnosticReportStore).where(
            DiagnosticReportStore.abha_address == abha_address,
            DiagnosticReportStore.care_context_reference == care_context_reference,
            DiagnosticReportStore.local_report_id == local_report_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_idempotency_key(
        db: AsyncSession,
        idempotency_key: str,
    ) -> Optional[DiagnosticReportStore]:
        stmt = select(DiagnosticReportStore).where(
            DiagnosticReportStore.idempotency_key == idempotency_key
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_existing_care_context(
        db: AsyncSession,
        abha_address: str,
        care_context_reference: str,
    ) -> Optional[CareContextRecord]:
        stmt = select(CareContextRecord).where(
            CareContextRecord.abha_address == abha_address,
            CareContextRecord.care_context_reference == care_context_reference,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def validate_patient_identity_consistency(
        cls,
        db: AsyncSession,
        payload: CanonicalDiagnosticReportPayload,
    ) -> None:
        abha_address = payload.patient.abha_address
        local_patient_id = payload.patient.local_patient_id
        care_context_reference = payload.study.local_study_id
        local_report_id = payload.report.local_report_id

        existing_cc = await cls.get_existing_care_context(
            db=db,
            abha_address=abha_address,
            care_context_reference=care_context_reference,
        )
        if existing_cc is not None and existing_cc.local_patient_id != local_patient_id:
            raise DiagnosticReportConflictError(
                message="Patient local_patient_id does not match existing care context patient identity.",
                code="PATIENT_IDENTITY_CONFLICT",
                details={
                    "care_context_reference": care_context_reference,
                    "abha_address": abha_address,
                    "provided_local_patient_id": local_patient_id,
                    "existing_local_patient_id": existing_cc.local_patient_id,
                },
            )

        existing_reports_in_cc = (
            await db.execute(
                select(DiagnosticReportStore).where(
                    DiagnosticReportStore.abha_address == abha_address,
                    DiagnosticReportStore.care_context_reference == care_context_reference,
                )
            )
        ).scalars().all()

        for report in existing_reports_in_cc:
            if report.local_patient_id != local_patient_id:
                raise DiagnosticReportConflictError(
                    message="Patient local_patient_id does not match existing diagnostic reports for this care context.",
                    code="PATIENT_IDENTITY_CONFLICT",
                    details={
                        "care_context_reference": care_context_reference,
                        "abha_address": abha_address,
                        "provided_local_patient_id": local_patient_id,
                        "existing_local_patient_id": report.local_patient_id,
                    },
                )

        existing_report = await cls.get_by_key_tuple(
            db=db,
            abha_address=abha_address,
            care_context_reference=care_context_reference,
            local_report_id=local_report_id,
        )
        if existing_report is not None and existing_report.local_patient_id != local_patient_id:
            raise DiagnosticReportConflictError(
                message="Patient local_patient_id does not match existing diagnostic report identity.",
                code="PATIENT_IDENTITY_CONFLICT",
                details={
                    "care_context_reference": care_context_reference,
                    "local_report_id": local_report_id,
                    "abha_address": abha_address,
                    "provided_local_patient_id": local_patient_id,
                    "existing_local_patient_id": existing_report.local_patient_id,
                },
                transaction_id=existing_report.gateway_transaction_id,
            )

    @classmethod
    async def persist_canonical_report(
        cls,
        db: AsyncSession,
        payload: CanonicalDiagnosticReportPayload,
        idempotency_key: str,
        gateway_transaction: GatewayTransaction,
        commit: bool = False,
    ) -> tuple[DiagnosticReportStore, bool]:
        """
        Persists the entire canonical diagnostic report JSON under
        (abha_address, care_context_reference, local_report_id) and patient identity.
        Never overwrites existing records on conflict.
        """
        abha_address = payload.patient.abha_address
        local_patient_id = payload.patient.local_patient_id
        care_context_reference = payload.study.local_study_id
        local_report_id = payload.report.local_report_id

        canonical_json, payload_hash = cls.canonicalize_payload(payload)

        await cls.validate_patient_identity_consistency(db=db, payload=payload)

        existing_by_key = await cls.get_by_idempotency_key(db, idempotency_key)
        existing_by_tuple = await cls.get_by_key_tuple(
            db=db,
            abha_address=abha_address,
            care_context_reference=care_context_reference,
            local_report_id=local_report_id,
        )

        if existing_by_key is not None:
            if (
                existing_by_key.payload_hash != payload_hash
                or existing_by_key.abha_address != abha_address
                or existing_by_key.local_patient_id != local_patient_id
                or existing_by_key.care_context_reference != care_context_reference
                or existing_by_key.local_report_id != local_report_id
                or existing_by_key.gateway_transaction_id != gateway_transaction.gateway_transaction_id
            ):
                raise DiagnosticReportConflictError(
                    message="Idempotency key already used with a different diagnostic report payload, identity, or transaction.",
                    code="IDEMPOTENCY_PAYLOAD_CONFLICT",
                    details={
                        "idempotency_key": idempotency_key,
                        "care_context_reference": care_context_reference,
                        "local_report_id": local_report_id,
                        "abha_address": abha_address,
                        "local_patient_id": local_patient_id,
                    },
                    transaction_id=existing_by_key.gateway_transaction_id,
                )
            if existing_by_tuple is not None and existing_by_tuple.id != existing_by_key.id:
                raise DiagnosticReportConflictError(
                    message="Conflicting records found for idempotency key and report identity.",
                    code="DIAGNOSTIC_REPORT_CONFLICT",
                    transaction_id=existing_by_key.gateway_transaction_id,
                )
            return existing_by_key, False

        if existing_by_tuple is not None:
            if (
                existing_by_tuple.payload_hash == payload_hash
                and existing_by_tuple.local_patient_id == local_patient_id
                and existing_by_tuple.idempotency_key == idempotency_key
                and existing_by_tuple.gateway_transaction_id == gateway_transaction.gateway_transaction_id
            ):
                return existing_by_tuple, False
            raise DiagnosticReportConflictError(
                message="A diagnostic report already exists for this patient, care_context_reference, and local_report_id and cannot be overwritten.",
                code="CARE_CONTEXT_REPORT_CONFLICT",
                details={
                    "care_context_reference": care_context_reference,
                    "local_report_id": local_report_id,
                    "abha_address": abha_address,
                    "local_patient_id": local_patient_id,
                },
                transaction_id=existing_by_tuple.gateway_transaction_id,
            )

        record = DiagnosticReportStore(
            id=str(uuid.uuid4()),
            abha_address=abha_address,
            local_patient_id=local_patient_id,
            care_context_reference=care_context_reference,
            local_report_id=local_report_id,
            idempotency_key=idempotency_key,
            gateway_transaction_id=gateway_transaction.gateway_transaction_id,
            payload_json=canonical_json,
            payload_hash=payload_hash,
        )
        db.add(record)

        try:
            await db.flush()
            if commit:
                await db.commit()
                await db.refresh(record)
        except IntegrityError as exc:
            if commit:
                await db.rollback()
            raise DiagnosticReportConflictError(
                message="Conflict persisting diagnostic report for patient identity, care_context_reference, and local_report_id.",
                code="DIAGNOSTIC_REPORT_CONFLICT",
                details={
                    "care_context_reference": care_context_reference,
                    "local_report_id": local_report_id,
                    "abha_address": abha_address,
                    "local_patient_id": local_patient_id,
                },
            ) from exc

        return record, True

    @staticmethod
    def load_canonical_dict(record: DiagnosticReportStore) -> dict[str, Any]:
        return json.loads(record.payload_json)
