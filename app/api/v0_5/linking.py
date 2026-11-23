# app/api/v0_5/linking.py
from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.models.entities import GatewayTransaction, TransactionStatus
from app.schemas.abdm.linking import LinkConfirmRequest, LinkInitRequest
from app.services.linking_service import LinkingService

router = APIRouter(prefix="/links/link", tags=["ABDM M2 - Care Context Linking"])


async def _handle_link_init_background(request_data: LinkInitRequest):
    async with AsyncSessionLocal() as db:
        payload = await LinkingService.process_link_init(db, request_data)
        await LinkingService.dispatch_on_link_init(payload)


async def _handle_link_confirm_background(request_data: LinkConfirmRequest):
    async with AsyncSessionLocal() as db:
        payload = await LinkingService.process_link_confirm(db, request_data)
        await LinkingService.dispatch_on_link_confirm(payload)


@router.post(
    "/init",
    status_code=status.HTTP_202_ACCEPTED,
    summary="ABDM Inbound: Initialize Care Context Linking",
    description="Invoked by ABDM Gateway when patient clicks Link Records in PHR app."
)
async def link_init(
    request: LinkInitRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    tx = GatewayTransaction(
        operation_type="CARE_CONTEXT_LINK_INIT",
        status=TransactionStatus.CREATED,
        abdm_request_id=str(request.requestId),
        idempotency_key=str(request.requestId),
    )
    db.add(tx)
    await db.commit()

    background_tasks.add_task(_handle_link_init_background, request)
    return {"status": "ACCEPTED", "requestId": str(request.requestId)}


@router.post(
    "/confirm",
    status_code=status.HTTP_202_ACCEPTED,
    summary="ABDM Inbound: Confirm Care Context Linking with OTP",
    description="Invoked by ABDM Gateway when patient inputs OTP."
)
async def link_confirm(
    request: LinkConfirmRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    tx = GatewayTransaction(
        operation_type="CARE_CONTEXT_LINK_CONFIRM",
        status=TransactionStatus.CREATED,
        abdm_request_id=str(request.requestId),
        idempotency_key=str(request.requestId),
    )
    db.add(tx)
    await db.commit()

    background_tasks.add_task(_handle_link_confirm_background, request)
    return {"status": "ACCEPTED", "requestId": str(request.requestId)}