# tests/integration/test_m2_hip_linking.py
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.database import AsyncSessionLocal
from app.models.entities import CareContextRecord, GatewayTransaction, LinkSession, TransactionStatus
from app.schemas.abdm.discovery import ErrorRepresentation, GatewayResponseReference
from app.schemas.abdm.hip_linking import (
    AddCareContextsOnAddCallback,
    AddContextsAcknowledgement,
    AuthOnConfirmDetail,
    AuthOnInitDetail,
    UserAuthOnConfirmCallback,
    UserAuthOnInitCallback,
)
from app.services.hip_linking_service import HipLinkingService


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_hip_link_trigger_endpoint_returns_202(client: AsyncClient, db_session: AsyncSession):
    suffix = uuid4().hex[:6]
    abha = f"hip_{suffix}@sbx"
    pid = f"PAT-{suffix}"
    study_ref = f"USG-{suffix}"

    # Seed care context
    db_session.add(
        CareContextRecord(
            local_patient_id=pid,
            abha_address=abha,
            care_context_reference=study_ref,
            display_name="Ultrasound Abdomen",
            is_linked=0,
        )
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/care-contexts/hip-link",
        json={
            "abha_address": abha,
            "local_patient_id": pid,
            "patient_name": "Aditya Tiwari",
            "care_context_references": [study_ref],
            "auth_mode": "DEMOGRAPHICS",
        },
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "PENDING"
    assert "gateway_transaction_id" in data


@pytest.mark.asyncio
async def test_inbound_hip_callback_endpoints_return_202(client: AsyncClient):
    now = datetime.now(timezone.utc).isoformat()
    req_ref = str(uuid4())

    r1 = await client.post(
        "/v0.5/users/auth/on-init",
        json={
            "requestId": str(uuid4()),
            "timestamp": now,
            "auth": {"transactionId": str(uuid4()), "mode": "DEMOGRAPHICS"},
            "resp": {"requestId": req_ref},
        },
    )
    assert r1.status_code == 202

    r2 = await client.post(
        "/v0.5/users/auth/on-confirm",
        json={
            "requestId": str(uuid4()),
            "timestamp": now,
            "auth": {"accessToken": "mock-jwt-token"},
            "resp": {"requestId": req_ref},
        },
    )
    assert r2.status_code == 202

    r3 = await client.post(
        "/v0.5/links/link/on-add-contexts",
        json={
            "requestId": str(uuid4()),
            "timestamp": now,
            "acknowledgement": {"status": "SUCCESS"},
            "resp": {"requestId": req_ref},
        },
    )
    assert r3.status_code == 202


@pytest.mark.asyncio
async def test_full_hip_initiated_linking_pipeline(db_session: AsyncSession):
    suffix = uuid4().hex[:6]
    abha = f"hip_pipe_{suffix}@sbx"
    pid = f"PAT-{suffix}"
    study_ref = f"USG-{suffix}"

    ctx = CareContextRecord(
        local_patient_id=pid,
        abha_address=abha,
        care_context_reference=study_ref,
        display_name="Ultrasound Pelvis",
        is_linked=0,
    )
    db_session.add(ctx)
    await db_session.commit()

    # 1. Initiate Auth
    auth_tx_gw_id = await HipLinkingService.initiate_hip_auth(
        db=db_session,
        abha_address=abha,
        local_patient_id=pid,
        care_context_refs=[study_ref],
    )
    tx_init = (
        await db_session.execute(
            select(GatewayTransaction).where(GatewayTransaction.gateway_transaction_id == auth_tx_gw_id)
        )
    ).scalar_one()
    abdm_auth_txn_id = str(uuid4())

    # 2. Simulate ABDM /on-init callback
    await HipLinkingService.handle_auth_on_init(
        db_session,
        UserAuthOnInitCallback(
            requestId=uuid4(),
            timestamp=datetime.now(timezone.utc),
            auth=AuthOnInitDetail(transactionId=abdm_auth_txn_id, mode="DEMOGRAPHICS"),
            resp=GatewayResponseReference(requestId=tx_init.abdm_request_id),
        ),
    )
    await db_session.refresh(tx_init)
    assert tx_init.abdm_transaction_id == abdm_auth_txn_id
    assert tx_init.status == TransactionStatus.COMPLETED

    # 3. Confirm Auth & simulate /on-confirm callback
    confirm_tx_gw_id = await HipLinkingService.confirm_hip_auth(db_session, abdm_auth_txn_id)
    tx_confirm = (
        await db_session.execute(
            select(GatewayTransaction).where(GatewayTransaction.gateway_transaction_id == confirm_tx_gw_id)
        )
    ).scalar_one()

    access_token = await HipLinkingService.handle_auth_on_confirm(
        db_session,
        UserAuthOnConfirmCallback(
            requestId=uuid4(),
            timestamp=datetime.now(timezone.utc),
            auth=AuthOnConfirmDetail(accessToken="abdm-access-xyz-123"),
            resp=GatewayResponseReference(requestId=tx_confirm.abdm_request_id),
        ),
    )
    assert access_token == "abdm-access-xyz-123"

    # 4. Push Care Contexts & simulate /on-add-contexts SUCCESS
    add_tx_gw_id = await HipLinkingService.add_care_contexts(
        db=db_session,
        access_token=access_token,
        abha_address=abha,
        local_patient_id=pid,
        patient_display="Aditya Tiwari",
        care_context_refs=[study_ref],
    )
    tx_add = (
        await db_session.execute(
            select(GatewayTransaction).where(GatewayTransaction.gateway_transaction_id == add_tx_gw_id)
        )
    ).scalar_one()

    await HipLinkingService.handle_on_add_contexts(
        db_session,
        AddCareContextsOnAddCallback(
            requestId=uuid4(),
            timestamp=datetime.now(timezone.utc),
            acknowledgement=AddContextsAcknowledgement(status="SUCCESS"),
            resp=GatewayResponseReference(requestId=tx_add.abdm_request_id),
        ),
    )

    # Verify transaction status is LINKED and CareContextRecord is_linked == 1
    await db_session.refresh(tx_add)
    await db_session.refresh(ctx)
    assert tx_add.status == TransactionStatus.LINKED
    assert ctx.is_linked == 1


@pytest.mark.asyncio
async def test_on_add_contexts_failure_keeps_unlinked(db_session: AsyncSession):
    suffix = uuid4().hex[:6]
    abha = f"hip_fail_{suffix}@sbx"
    pid = f"PAT-{suffix}"
    study_ref = f"USG-{suffix}"

    ctx = CareContextRecord(
        local_patient_id=pid,
        abha_address=abha,
        care_context_reference=study_ref,
        display_name="Ultrasound Thyroid",
        is_linked=0,
    )
    db_session.add(ctx)
    await db_session.commit()

    add_tx_gw_id = await HipLinkingService.add_care_contexts(
        db=db_session,
        access_token="expired-token",
        abha_address=abha,
        local_patient_id=pid,
        patient_display="Test Patient",
        care_context_refs=[study_ref],
    )
    tx_add = (
        await db_session.execute(
            select(GatewayTransaction).where(GatewayTransaction.gateway_transaction_id == add_tx_gw_id)
        )
    ).scalar_one()

    await HipLinkingService.handle_on_add_contexts(
        db_session,
        AddCareContextsOnAddCallback(
            requestId=uuid4(),
            timestamp=datetime.now(timezone.utc),
            acknowledgement=AddContextsAcknowledgement(status="FAILURE"),
            error=ErrorRepresentation(code=1401, message="Invalid or expired accessToken"),
            resp=GatewayResponseReference(requestId=tx_add.abdm_request_id),
        ),
    )

    await db_session.refresh(tx_add)
    await db_session.refresh(ctx)
    assert tx_add.status == TransactionStatus.FAILED_FINAL
    assert tx_add.last_error_code == "1401"
    assert ctx.is_linked == 0