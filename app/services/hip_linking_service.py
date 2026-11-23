# app/services/hip_linking_service.py
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.abdm.client import abdm_client
from app.core.config import settings
from app.core.exceptions import AbhaInvalidException
from app.models.entities import CareContextRecord, GatewayTransaction, LinkSession, TransactionStatus
from app.schemas.abdm.hip_linking import (
    AddCareContextsOnAddCallback,
    AddCareContextsRequest,
    AddContextItem,
    AddContextPatient,
    AddContextsLinkPayload,
    AuthCredential,
    AuthRequester,
    UserAuthConfirmRequest,
    UserAuthInitQuery,
    UserAuthInitRequest,
    UserAuthOnConfirmCallback,
    UserAuthOnInitCallback,
)

logger = logging.getLogger(__name__)


class HipLinkingService:
    @staticmethod
    async def initiate_hip_auth(
        db: AsyncSession,
        abha_address: str,
        local_patient_id: str,
        care_context_refs: List[str],
        auth_mode: str = "DEMOGRAPHICS",
    ) -> str:
        """
        Step 1 of HIP-initiated linking:
        Creates audit transaction + LinkSession, and calls ABDM /v0.5/users/auth/init.
        Returns our internal gateway_transaction_id.
        """
        normalized_abha = abha_address.strip().lower()

        # Verify target care contexts exist
        stmt = select(CareContextRecord).where(
            CareContextRecord.abha_address == normalized_abha,
            CareContextRecord.care_context_reference.in_(care_context_refs),
        )
        records = (await db.execute(stmt)).scalars().all()
        if not records:
            raise AbhaInvalidException(
                f"No care contexts found for ABHA '{normalized_abha}' matching {care_context_refs}"
            )

        req_id = uuid4()
        now_utc = datetime.now(timezone.utc)
        hip_id = getattr(settings, "ABDM_HIP_ID", "MEDTATVAA_HIP_01")

        # Audit transaction
        tx = GatewayTransaction(
            idempotency_key=f"hip-auth-{req_id}",
            abdm_request_id=str(req_id),
            operation_type="HIP_AUTH_INIT",
            status=TransactionStatus.PENDING,
        )
        db.add(tx)

        # Correlation session storing care contexts to be linked
        session = LinkSession(
            link_ref_number=str(req_id),
            transaction_id=str(req_id),  # Will be updated with ABDM auth.transactionId in on-init
            abha_address=normalized_abha,
            patient_reference=local_patient_id,
            care_contexts=json.dumps(care_context_refs),
            otp="123456",
            is_confirmed=0,
            expires_at=now_utc + timedelta(minutes=15),
            created_at=now_utc,
        )
        db.add(session)
        await db.commit()
        await db.refresh(tx)

        # Dispatch outbound /v0.5/users/auth/init
        payload = UserAuthInitRequest(
            requestId=req_id,
            timestamp=now_utc,
            query=UserAuthInitQuery(
                id=normalized_abha,
                purpose="LINK",
                authMode=auth_mode,
                requester=AuthRequester(type="HIP", id=hip_id),
            ),
        )
        await abdm_client.post_users_auth_init(payload.model_dump(mode="json"))

        return tx.gateway_transaction_id

    @staticmethod
    async def handle_auth_on_init(db: AsyncSession, callback: UserAuthOnInitCallback) -> None:
        """
        Handles ABDM callback POST /v0.5/users/auth/on-init.
        Saves the ABDM auth transactionId for step 2 (auth/confirm).
        """
        orig_req_id = str(callback.resp.requestId)
        tx = (
            await db.execute(
                select(GatewayTransaction).where(GatewayTransaction.abdm_request_id == orig_req_id)
            )
        ).scalar_one_or_none()

        if not tx:
            logger.warning(f"on-init callback received for unknown requestId: {orig_req_id}")
            return

        if callback.error:
            tx.status = TransactionStatus.FAILED_FINAL
            tx.last_error_code = str(callback.error.code)
            tx.last_provider_error = callback.error.message
            await db.commit()
            return

        if callback.auth:
            tx.abdm_transaction_id = callback.auth.transactionId
            tx.status = TransactionStatus.COMPLETED

            # Update LinkSession with ABDM's auth transactionId
            session = (
                await db.execute(
                    select(LinkSession).where(LinkSession.link_ref_number == orig_req_id)
                )
            ).scalar_one_or_none()
            if session:
                session.transaction_id = callback.auth.transactionId

            await db.commit()

    @staticmethod
    async def confirm_hip_auth(
        db: AsyncSession,
        abdm_transaction_id: str,
        auth_code: Optional[str] = "123456",
        demographic: Optional[dict] = None,
    ) -> str:
        """
        Step 2 of HIP-initiated linking: Calls ABDM /v0.5/users/auth/confirm.
        """
        req_id = uuid4()
        now_utc = datetime.now(timezone.utc)

        tx = GatewayTransaction(
            idempotency_key=f"hip-confirm-{req_id}",
            abdm_request_id=str(req_id),
            abdm_transaction_id=abdm_transaction_id,
            operation_type="HIP_AUTH_CONFIRM",
            status=TransactionStatus.PENDING,
        )
        db.add(tx)
        await db.commit()
        await db.refresh(tx)

        payload = UserAuthConfirmRequest(
            requestId=req_id,
            timestamp=now_utc,
            transactionId=abdm_transaction_id,
            credential=AuthCredential(authCode=auth_code, demographic=demographic),
        )
        await abdm_client.post_users_auth_confirm(payload.model_dump(mode="json", exclude_none=True))

        return tx.gateway_transaction_id

    @staticmethod
    async def handle_auth_on_confirm(db: AsyncSession, callback: UserAuthOnConfirmCallback) -> Optional[str]:
        """
        Handles ABDM callback POST /v0.5/users/auth/on-confirm.
        Extracts the accessToken needed to push care contexts.
        """
        orig_req_id = str(callback.resp.requestId)
        tx = (
            await db.execute(
                select(GatewayTransaction).where(GatewayTransaction.abdm_request_id == orig_req_id)
            )
        ).scalar_one_or_none()

        if not tx:
            logger.warning(f"on-confirm callback received for unknown requestId: {orig_req_id}")
            return None

        if callback.error:
            tx.status = TransactionStatus.FAILED_FINAL
            tx.last_error_code = str(callback.error.code)
            tx.last_provider_error = callback.error.message
            await db.commit()
            return None

        if callback.auth and callback.auth.accessToken:
            tx.status = TransactionStatus.COMPLETED
            await db.commit()
            return callback.auth.accessToken

        return None

    @staticmethod
    async def add_care_contexts(
        db: AsyncSession,
        access_token: str,
        abha_address: str,
        local_patient_id: str,
        patient_display: str,
        care_context_refs: List[str],
    ) -> str:
        """
        Step 3 of HIP-initiated linking: Pushes care contexts to ABDM /v0.5/links/link/add-contexts.
        """
        normalized_abha = abha_address.strip().lower()
        stmt = select(CareContextRecord).where(
            CareContextRecord.abha_address == normalized_abha,
            CareContextRecord.care_context_reference.in_(care_context_refs),
        )
        records = (await db.execute(stmt)).scalars().all()

        req_id = uuid4()
        now_utc = datetime.now(timezone.utc)

        tx = GatewayTransaction(
            idempotency_key=f"hip-add-ctx-{req_id}",
            abdm_request_id=str(req_id),
            operation_type="HIP_ADD_CONTEXTS",
            status=TransactionStatus.PENDING,
        )
        db.add(tx)

        session = LinkSession(
            link_ref_number=str(req_id),
            transaction_id=str(req_id),
            abha_address=normalized_abha,
            patient_reference=local_patient_id,
            care_contexts=json.dumps(care_context_refs),
            otp="TOKEN_AUTH",
            is_confirmed=0,
            expires_at=now_utc + timedelta(minutes=15),
            created_at=now_utc,
        )
        db.add(session)
        await db.commit()
        await db.refresh(tx)

        items = [
            AddContextItem(referenceNumber=r.care_context_reference, display=r.display_name)
            for r in records
        ]

        payload = AddCareContextsRequest(
            requestId=req_id,
            timestamp=now_utc,
            link=AddContextsLinkPayload(
                accessToken=access_token,
                patient=AddContextPatient(
                    referenceNumber=local_patient_id,
                    display=patient_display,
                    careContexts=items,
                ),
            ),
        )
        await abdm_client.post_add_contexts(payload.model_dump(mode="json"))

        return tx.gateway_transaction_id

    @staticmethod
    async def handle_on_add_contexts(db: AsyncSession, callback: AddCareContextsOnAddCallback) -> None:
        """
        Handles ABDM callback POST /v0.5/links/link/on-add-contexts.
        If status == SUCCESS, marks CareContextRecord.is_linked = 1.
        """
        orig_req_id = str(callback.resp.requestId)
        tx = (
            await db.execute(
                select(GatewayTransaction).where(GatewayTransaction.abdm_request_id == orig_req_id)
            )
        ).scalar_one_or_none()

        session = (
            await db.execute(
                select(LinkSession).where(LinkSession.link_ref_number == orig_req_id)
            )
        ).scalar_one_or_none()

        if callback.error or not callback.acknowledgement or callback.acknowledgement.status != "SUCCESS":
            if tx:
                tx.status = TransactionStatus.FAILED_FINAL
                if callback.error:
                    tx.last_error_code = str(callback.error.code)
                    tx.last_provider_error = callback.error.message
                await db.commit()
            return

        # Mark session confirmed and care contexts linked
        if session:
            session.is_confirmed = 1
            refs = json.loads(session.care_contexts)
            await db.execute(
                update(CareContextRecord)
                .where(
                    CareContextRecord.abha_address == session.abha_address,
                    CareContextRecord.care_context_reference.in_(refs),
                )
                .values(is_linked=1)
            )

        if tx:
            tx.status = TransactionStatus.LINKED

        await db.commit()