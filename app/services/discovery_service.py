# app/services/discovery_service.py
import logging
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.abdm.client import abdm_client
from app.models.entities import CareContextRecord
from app.schemas.abdm.discovery import (
    CareContextDiscoverRequest,
    CareContextOnDiscoverPayload,
    CareContextRepresentation,
    ErrorRepresentation,
    GatewayResponseReference,
    PatientDiscoveryRepresentation,
)

logger = logging.getLogger(__name__)


class DiscoveryService:
    @staticmethod
    async def process_discovery(
        db: AsyncSession,
        request: CareContextDiscoverRequest,
    ) -> CareContextOnDiscoverPayload:
        abha_address = request.patient.id.strip().lower()
        
        # Query unlinked care contexts (is_linked == 0)
        stmt = (
            select(CareContextRecord)
            .where(
                CareContextRecord.abha_address == abha_address,
                CareContextRecord.is_linked == 0
            )
        )
        result = await db.execute(stmt)
        matched_records = result.scalars().all()

        callback_id = uuid4()
        now_utc = datetime.now(timezone.utc)

        if not matched_records:
            return CareContextOnDiscoverPayload(
                requestId=callback_id,
                timestamp=now_utc,
                transactionId=request.transactionId,
                patient=None,
                resp=GatewayResponseReference(requestId=request.requestId),
                error=ErrorRepresentation(
                    code=1404,
                    message="No care context records found for the provided patient identifier"
                )
            )

        first_record = matched_records[0]
        local_patient_id = first_record.local_patient_id
        patient_name = request.patient.name or "Medtatvaa Patient"

        care_contexts = [
            CareContextRepresentation(
                referenceNumber=rec.care_context_reference,
                display=rec.display_name
            )
            for rec in matched_records
        ]

        patient_repr = PatientDiscoveryRepresentation(
            referenceNumber=local_patient_id,
            display=patient_name,
            careContexts=care_contexts,
            matchedBy=["ABHA_ADDRESS"]
        )

        return CareContextOnDiscoverPayload(
            requestId=callback_id,
            timestamp=now_utc,
            transactionId=request.transactionId,
            patient=patient_repr,
            resp=GatewayResponseReference(requestId=request.requestId),
            error=None
        )

    @staticmethod
    async def dispatch_on_discover(payload: CareContextOnDiscoverPayload) -> None:
        logger.info(f"Dispatching /v0.5/care-contexts/on-discover for txn {payload.transactionId}")
        await abdm_client.post_on_discover(payload.model_dump(mode="json"))