# app/api/v0_5/discovery.py
from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import GatewayTransaction
from app.schemas.abdm.discovery import CareContextDiscoverRequest
from app.services.discovery_service import DiscoveryService

router = APIRouter(prefix="/care-contexts", tags=["ABDM M2 - Care Context Discovery"])


async def _handle_discovery_background(request_data: CareContextDiscoverRequest):
    """Executes discovery search and sends on-discover callback."""
    # Obtain a clean session for background task
    from app.core.database import async_session_factory
    async with async_session_factory() as db:
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
    # Log discovery transaction
    tx = GatewayTransaction(
        operation_type="CARE_CONTEXT_DISCOVER",
        status="RECEIVED",
        abdm_request_id=str(request.requestId),
        idempotency_key=str(request.requestId),
    )
    db.add(tx)
    await db.commit()

    # Hand off resolution & callback dispatch to FastAPI background tasks
    background_tasks.add_task(_handle_discovery_background, request)

    return {"status": "ACCEPTED", "requestId": str(request.requestId)}