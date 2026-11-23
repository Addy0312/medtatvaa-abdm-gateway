# app/api/v0_5/hip_linking.py
from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.schemas.abdm.hip_linking import (
    AddCareContextsOnAddCallback,
    UserAuthOnConfirmCallback,
    UserAuthOnInitCallback,
)
from app.services.hip_linking_service import HipLinkingService

router = APIRouter(tags=["ABDM M2 - HIP-Initiated Linking Callbacks"])


async def _bg_auth_on_init(callback: UserAuthOnInitCallback):
    async with AsyncSessionLocal() as db:
        await HipLinkingService.handle_auth_on_init(db, callback)


async def _bg_auth_on_confirm(callback: UserAuthOnConfirmCallback):
    async with AsyncSessionLocal() as db:
        await HipLinkingService.handle_auth_on_confirm(db, callback)


async def _bg_on_add_contexts(callback: AddCareContextsOnAddCallback):
    async with AsyncSessionLocal() as db:
        await HipLinkingService.handle_on_add_contexts(db, callback)


@router.post(
    "/users/auth/on-init",
    status_code=status.HTTP_202_ACCEPTED,
    summary="ABDM Inbound Callback: Auth On-Init",
)
async def users_auth_on_init(
    callback: UserAuthOnInitCallback,
    background_tasks: BackgroundTasks,
):
    background_tasks.add_task(_bg_auth_on_init, callback)
    return {"status": "ACCEPTED", "requestId": str(callback.requestId)}


@router.post(
    "/users/auth/on-confirm",
    status_code=status.HTTP_202_ACCEPTED,
    summary="ABDM Inbound Callback: Auth On-Confirm",
)
async def users_auth_on_confirm(
    callback: UserAuthOnConfirmCallback,
    background_tasks: BackgroundTasks,
):
    background_tasks.add_task(_bg_auth_on_confirm, callback)
    return {"status": "ACCEPTED", "requestId": str(callback.requestId)}


@router.post(
    "/links/link/on-add-contexts",
    status_code=status.HTTP_202_ACCEPTED,
    summary="ABDM Inbound Callback: On-Add-Contexts",
)
async def links_on_add_contexts(
    callback: AddCareContextsOnAddCallback,
    background_tasks: BackgroundTasks,
):
    background_tasks.add_task(_bg_on_add_contexts, callback)
    return {"status": "ACCEPTED", "requestId": str(callback.requestId)}