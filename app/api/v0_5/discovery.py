# app/api/v0_5/discovery.py
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.models.entities import GatewayTransaction, TransactionStatus
from app.schemas.abdm.discovery import CareContextDiscoverRequest
from app.services.discovery_service import DiscoveryService

router = APIRouter(prefix="/care-contexts", tags=["ABDM M2 - Care Context Discovery"])


async def _handle_discovery_background(request_data: CareContextDiscoverRequest):
    async with AsyncSessionLocal() as db:
        payload = await DiscoveryService.process_discovery(db, request_data)
        await DiscoveryService.dispatch_on_discover(payload)


@router.post(
    "/discover",
    status_code=status.HTTP_202_ACCEPTED,
    summary="ABDM Inbound: Discover Care Contexts",
    description="Invoked asynchronously by ABDM Gateway when a patient initiates discovery."
)
async def care_contexts_discover(
    request: CareContextDiscoverRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    request_id_str = str(request.requestId)
    tx = GatewayTransaction(
        operation_type="CARE_CONTEXT_DISCOVER",
        status=TransactionStatus.CREATED,
        abdm_request_id=request_id_str,
        idempotency_key=request_id_str,
    )
    db.add(tx)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing_tx = (
            await db.execute(
                select(GatewayTransaction).where(GatewayTransaction.idempotency_key == request_id_str)
            )
        ).scalar_one_or_none()
        if existing_tx is None:
            raise
        if existing_tx.operation_type == "CARE_CONTEXT_DISCOVER":
            return {"status": "ACCEPTED", "requestId": request_id_str, "duplicate": True}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "transaction_id": existing_tx.gateway_transaction_id,
                "status": "FAILED_FINAL",
                "error_code": "IDEMPOTENCY_OPERATION_CONFLICT",
                "message": "Idempotency key already exists for a different operation type.",
            },
        )

    background_tasks.add_task(_handle_discovery_background, request)
    return {"status": "ACCEPTED", "requestId": request_id_str}
