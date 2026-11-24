# app/api/v0_5/consent.py
from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.models.entities import GatewayTransaction, TransactionStatus
from app.schemas.abdm.consent import ConsentHipNotifyRequest
from app.services.consent_service import ConsentService

router = APIRouter(prefix="/consents/hip", tags=["ABDM M2 - Consent Notification"])


async def _handle_consent_notify_background(request_data: ConsentHipNotifyRequest):
    async with AsyncSessionLocal() as db:
        payload = await ConsentService.process_consent_notify(db, request_data)
        await ConsentService.dispatch_on_notify(payload)


@router.post(
    "/notify",
    status_code=status.HTTP_202_ACCEPTED,
    summary="ABDM Inbound: Consent Notification",
    description="Invoked by ABDM Gateway when a patient grants, revokes, or expires a consent artefact."
)
async def consents_hip_notify(
    request: ConsentHipNotifyRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    tx = GatewayTransaction(
        operation_type="CONSENT_NOTIFY",
        status=TransactionStatus.CREATED,
        abdm_request_id=str(request.requestId),
        idempotency_key=str(request.requestId),
    )
    db.add(tx)
    await db.commit()

    background_tasks.add_task(_handle_consent_notify_background, request)
    return {"status": "ACCEPTED", "requestId": str(request.requestId)}