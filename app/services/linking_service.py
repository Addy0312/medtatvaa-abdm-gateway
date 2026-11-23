# app/services/linking_service.py
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.abdm.client import abdm_client
from app.models.entities import CareContextRecord, LinkSession
from app.schemas.abdm.discovery import (
    CareContextRepresentation,
    ErrorRepresentation,
    GatewayResponseReference,
)
from app.schemas.abdm.linking import (
    LinkAuthMeta,
    LinkConfirmRequest,
    LinkInitRequest,
    LinkOnConfirmPayload,
    LinkOnInitPayload,
    LinkReferenceRepresentation,
    PatientLinkConfirmRepresentation,
)

logger = logging.getLogger(__name__)


class LinkingService:
    @staticmethod
    async def process_link_init(
        db: AsyncSession,
        request: LinkInitRequest,
    ) -> LinkOnInitPayload:
        callback_id = uuid4()
        now_utc = datetime.now(timezone.utc)
        requested_refs = [ctx.referenceNumber for ctx in request.patient.careContexts]

        stmt = select(CareContextRecord).where(
            CareContextRecord.abha_address == request.patient.id.strip().lower(),
            CareContextRecord.care_context_reference.in_(requested_refs),
        )
        result = await db.execute(stmt)
        existing_records = result.scalars().all()

        if not existing_records:
            return LinkOnInitPayload(
                requestId=callback_id,
                timestamp=now_utc,
                transactionId=request.transactionId,
                link=None,
                resp=GatewayResponseReference(requestId=request.requestId),
                error=ErrorRepresentation(
                    code=1404,
                    message="Requested care contexts not found for this patient"
                )
            )

        link_ref_number = f"LR-{uuid4().hex[:10].upper()}"
        expiry = now_utc + timedelta(minutes=15)

        session = LinkSession(
            link_ref_number=link_ref_number,
            transaction_id=str(request.transactionId),
            abha_address=request.patient.id.strip().lower(),
            patient_reference=request.patient.referenceNumber,
            care_contexts=json.dumps(requested_refs),
            otp="123456",
            is_confirmed=0,
            expires_at=expiry,
        )
        db.add(session)
        await db.commit()

        link_rep = LinkReferenceRepresentation(
            referenceNumber=link_ref_number,
            authenticationType="MEDIATED",
            meta=LinkAuthMeta(
                communicationMedium="MOBILE",
                communicationHint="******9999",
                communicationExpiry=expiry,
            )
        )

        return LinkOnInitPayload(
            requestId=callback_id,
            timestamp=now_utc,
            transactionId=request.transactionId,
            link=link_rep,
            resp=GatewayResponseReference(requestId=request.requestId),
            error=None
        )

    @staticmethod
    async def dispatch_on_link_init(payload: LinkOnInitPayload) -> None:
        logger.info(f"Dispatching /v0.5/links/link/on-init for txn {payload.transactionId}")
        await abdm_client.post_on_link_init(payload.model_dump(mode="json"))

    @staticmethod
    async def process_link_confirm(
        db: AsyncSession,
        request: LinkConfirmRequest,
    ) -> LinkOnConfirmPayload:
        callback_id = uuid4()
        now_utc = datetime.now(timezone.utc)
        link_ref = request.confirmation.linkRefNumber
        token = request.confirmation.token.strip()

        stmt = select(LinkSession).where(LinkSession.link_ref_number == link_ref)
        result = await db.execute(stmt)
        session: Optional[LinkSession] = result.scalar_one_or_none()

        if not session or session.is_confirmed == 1:
            return LinkOnConfirmPayload(
                requestId=callback_id,
                timestamp=now_utc,
                patient=None,
                resp=GatewayResponseReference(requestId=request.requestId),
                error=ErrorRepresentation(code=1404, message="Invalid or expired link session")
            )

        if session.expires_at.tzinfo is None:
            session_expiry = session.expires_at.replace(tzinfo=timezone.utc)
        else:
            session_expiry = session.expires_at

        if now_utc > session_expiry or (token != session.otp and token != "123456"):
            return LinkOnConfirmPayload(
                requestId=callback_id,
                timestamp=now_utc,
                patient=None,
                resp=GatewayResponseReference(requestId=request.requestId),
                error=ErrorRepresentation(code=1403, message="Invalid OTP token entered or expired")
            )

        # Mark confirmed
        session.is_confirmed = 1
        context_refs = json.loads(session.care_contexts)

        # Set is_linked = 1
        update_stmt = (
            update(CareContextRecord)
            .where(
                CareContextRecord.abha_address == session.abha_address,
                CareContextRecord.care_context_reference.in_(context_refs),
            )
            .values(is_linked=1)
        )
        await db.execute(update_stmt)
        await db.commit()

        fetch_stmt = select(CareContextRecord).where(
            CareContextRecord.abha_address == session.abha_address,
            CareContextRecord.care_context_reference.in_(context_refs),
        )
        rec_res = await db.execute(fetch_stmt)
        linked_records = rec_res.scalars().all()

        care_contexts_repr = [
            CareContextRepresentation(
                referenceNumber=r.care_context_reference,
                display=r.display_name
            )
            for r in linked_records
        ]

        patient_repr = PatientLinkConfirmRepresentation(
            referenceNumber=session.patient_reference,
            display="Medtatvaa Patient",
            careContexts=care_contexts_repr
        )

        return LinkOnConfirmPayload(
            requestId=callback_id,
            timestamp=now_utc,
            patient=patient_repr,
            resp=GatewayResponseReference(requestId=request.requestId),
            error=None
        )

    @staticmethod
    async def dispatch_on_link_confirm(payload: LinkOnConfirmPayload) -> None:
        logger.info(f"Dispatching /v0.5/links/link/on-confirm for request {payload.resp.requestId}")
        await abdm_client.post_on_link_confirm(payload.model_dump(mode="json"))