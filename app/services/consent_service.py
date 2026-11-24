# app/services/consent_service.py
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.abdm.client import abdm_client
from app.models.entities import ConsentArtefactRecord
from app.schemas.abdm.consent import (
    ConsentHipNotifyRequest,
    ConsentHipOnNotifyPayload,
    ConsentNotifyAcknowledgement,
)
from app.schemas.abdm.discovery import ErrorRepresentation, GatewayResponseReference

logger = logging.getLogger(__name__)

VALID_CONSENT_STATUSES = {"GRANTED", "REVOKED", "EXPIRED"}


class ConsentService:
    @staticmethod
    async def process_consent_notify(
        db: AsyncSession,
        request: ConsentHipNotifyRequest,
    ) -> ConsentHipOnNotifyPayload:
        """
        Processes inbound ABDM consent notification:
        - GRANTED: Validates consentDetail and creates/updates ConsentArtefactRecord.
        - REVOKED / EXPIRED: Updates existing record status to block future data fetches.
        """
        callback_id = uuid4()
        now_utc = datetime.now(timezone.utc)
        notif = request.notification
        consent_id = notif.consentId.strip()
        status_val = notif.status.strip().upper()

        if status_val not in VALID_CONSENT_STATUSES:
            return ConsentHipOnNotifyPayload(
                requestId=callback_id,
                timestamp=now_utc,
                acknowledgement=None,
                error=ErrorRepresentation(code=1400, message=f"Unsupported consent status: {status_val}"),
                resp=GatewayResponseReference(requestId=request.requestId),
            )

        existing = (
            await db.execute(
                select(ConsentArtefactRecord).where(ConsentArtefactRecord.consent_id == consent_id)
            )
        ).scalar_one_or_none()

        if status_val == "GRANTED":
            if not notif.consentDetail:
                return ConsentHipOnNotifyPayload(
                    requestId=callback_id,
                    timestamp=now_utc,
                    acknowledgement=None,
                    error=ErrorRepresentation(code=1400, message="consentDetail is required when status is GRANTED"),
                    resp=GatewayResponseReference(requestId=request.requestId),
                )

            detail = notif.consentDetail
            care_contexts_json = json.dumps([cc.model_dump() for cc in detail.careContexts])
            hi_types_json = json.dumps(detail.hiTypes)
            raw_json = detail.model_dump_json(by_alias=True)

            if existing:
                existing.status = status_val
                existing.abha_address = detail.patient.id.strip().lower()
                existing.care_contexts = care_contexts_json
                existing.hi_types = hi_types_json
                existing.date_range_from = detail.permission.dateRange.from_date
                existing.date_range_to = detail.permission.dateRange.to_date
                existing.data_erase_at = detail.permission.dataEraseAt
                existing.raw_consent_detail = raw_json
            else:
                record = ConsentArtefactRecord(
                    consent_id=consent_id,
                    status=status_val,
                    abha_address=detail.patient.id.strip().lower(),
                    care_contexts=care_contexts_json,
                    hi_types=hi_types_json,
                    date_range_from=detail.permission.dateRange.from_date,
                    date_range_to=detail.permission.dateRange.to_date,
                    data_erase_at=detail.permission.dataEraseAt,
                    raw_consent_detail=raw_json,
                    created_at=now_utc,
                )
                db.add(record)

            await db.commit()

        else:
            # REVOKED or EXPIRED
            if not existing:
                return ConsentHipOnNotifyPayload(
                    requestId=callback_id,
                    timestamp=now_utc,
                    acknowledgement=None,
                    error=ErrorRepresentation(code=1404, message=f"Consent artefact '{consent_id}' not found"),
                    resp=GatewayResponseReference(requestId=request.requestId),
                )

            existing.status = status_val
            await db.commit()

        return ConsentHipOnNotifyPayload(
            requestId=callback_id,
            timestamp=now_utc,
            acknowledgement=ConsentNotifyAcknowledgement(status="OK", consentId=consent_id),
            error=None,
            resp=GatewayResponseReference(requestId=request.requestId),
        )

    @staticmethod
    async def dispatch_on_notify(payload: ConsentHipOnNotifyPayload) -> None:
        """Dispatches callback to ABDM Gateway at POST /v0.5/consents/hip/on-notify."""
        logger.info(f"Dispatching /v0.5/consents/hip/on-notify for request {payload.resp.requestId}")
        await abdm_client.post_consent_on_notify(payload.model_dump(mode="json"))

    @staticmethod
    async def get_valid_consent(db: AsyncSession, consent_id: str) -> Optional[ConsentArtefactRecord]:
        """
        Helper used during Health Information Request to enforce active, unexpired consent.
        """
        record = (
            await db.execute(
                select(ConsentArtefactRecord).where(ConsentArtefactRecord.consent_id == consent_id)
            )
        ).scalar_one_or_none()

        if not record or record.status != "GRANTED":
            return None

        if record.data_erase_at:
            erase_at = (
                record.data_erase_at.replace(tzinfo=timezone.utc)
                if record.data_erase_at.tzinfo is None
                else record.data_erase_at
            )
            if datetime.now(timezone.utc) > erase_at:
                return None

        return record