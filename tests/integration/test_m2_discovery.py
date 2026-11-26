# tests/integration/test_m2_discovery.py
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v0_5.discovery import _handle_discovery_background, router as discovery_router
from app.core.database import Base, get_db
from app.models.entities import CareContextRecord, GatewayTransaction, TransactionStatus
from app.schemas.abdm.discovery import CareContextDiscoverRequest
from app.services.discovery_service import DiscoveryService


def _discover_payload(**overrides) -> dict:
    payload = {
        "requestId": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "transactionId": str(uuid4()),
        "patient": {
            "id": "Sandbox-User@SBX",
            "verifiedIdentifiers": [{"type": "MOBILE", "value": "9999999999"}],
            "unverifiedIdentifiers": [],
            "name": "Asha Rao",
            "gender": "F",
            "yearOfBirth": 1990,
        },
        "hipId": "SBX-FACILITY-ID",
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(payload.get(k), dict):
            payload[k].update(v)
        else:
            payload[k] = v
    return payload


@pytest_asyncio.fixture
async def isolated_discovery_db() -> AsyncGenerator[tuple[AsyncSession, async_sessionmaker[AsyncSession]], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        yield session, session_factory

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(isolated_discovery_db) -> AsyncGenerator[AsyncSession, None]:
    session, _ = isolated_discovery_db
    yield session


@pytest_asyncio.fixture
async def discovery_client(isolated_discovery_db) -> AsyncGenerator[AsyncClient, None]:
    _, session_factory = isolated_discovery_db
    app = FastAPI()
    app.include_router(discovery_router, prefix="/v0.5")

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_normalization_unlinked_only_and_no_patient_leakage(db_session: AsyncSession):
    db_session.add_all(
        [
            CareContextRecord(
                local_patient_id="PAT-101",
                abha_address="sandbox-user@sbx",
                care_context_reference="CC-UNLINKED-1",
                display_name="USG Abdomen",
                is_linked=0,
            ),
            CareContextRecord(
                local_patient_id="PAT-101",
                abha_address="sandbox-user@sbx",
                care_context_reference="CC-LINKED-1",
                display_name="Already Linked Study",
                is_linked=1,
            ),
            CareContextRecord(
                local_patient_id="PAT-999",
                abha_address="other-patient@sbx",
                care_context_reference="CC-OTHER-1",
                display_name="Other Patient Study",
                is_linked=0,
            ),
        ]
    )
    await db_session.commit()

    req = CareContextDiscoverRequest.model_validate(
        _discover_payload(patient={"id": "  Sandbox-User@SBX  ", "name": "Asha Rao"})
    )
    callback = await DiscoveryService.process_discovery(db_session, req)

    assert callback.error is None
    assert callback.patient is not None
    assert callback.patient.referenceNumber == "PAT-101"
    refs = [cc.referenceNumber for cc in callback.patient.careContexts]
    assert refs == ["CC-UNLINKED-1"]
    assert "CC-LINKED-1" not in refs
    assert "CC-OTHER-1" not in refs


@pytest.mark.asyncio
async def test_empty_discovery_returns_error_1404_and_correlation(db_session: AsyncSession):
    req = CareContextDiscoverRequest.model_validate(_discover_payload(patient={"id": "missing@sbx"}))
    callback = await DiscoveryService.process_discovery(db_session, req)

    assert callback.patient is None
    assert callback.error is not None
    assert callback.error.code == 1404
    assert callback.transactionId == req.transactionId
    assert callback.resp.requestId == req.requestId
    assert callback.requestId != req.requestId


@pytest.mark.asyncio
async def test_dispatch_on_discover_mock_and_background_flow(isolated_discovery_db):
    session, session_factory = isolated_discovery_db
    session.add(
        CareContextRecord(
            local_patient_id="PAT-202",
            abha_address="asha@sbx",
            care_context_reference="CC-202",
            display_name="X-Ray Chest",
            is_linked=0,
        )
    )
    await session.commit()

    req = CareContextDiscoverRequest.model_validate(_discover_payload(patient={"id": "asha@sbx"}))
    with patch("app.api.v0_5.discovery.AsyncSessionLocal", session_factory), patch(
        "app.services.discovery_service.abdm_client.post_on_discover",
        new_callable=AsyncMock,
    ) as mock_post:
        await _handle_discovery_background(req)
        mock_post.assert_awaited_once()
        sent_payload = mock_post.await_args.args[0]
        assert sent_payload["transactionId"] == str(req.transactionId)
        assert sent_payload["resp"]["requestId"] == str(req.requestId)


@pytest.mark.asyncio
async def test_endpoint_malformed_422_and_idempotent_duplicate_request_id_without_real_callback(
    discovery_client: AsyncClient,
    db_session: AsyncSession,
):
    bad_res = await discovery_client.post(
        "/v0.5/care-contexts/discover",
        json={"requestId": "not-a-uuid"},
    )
    assert bad_res.status_code == 422

    req_id = str(uuid4())
    payload = _discover_payload(requestId=req_id)

    with patch("app.api.v0_5.discovery._handle_discovery_background", new_callable=AsyncMock) as mock_bg:
        res1 = await discovery_client.post("/v0.5/care-contexts/discover", json=payload)
        assert res1.status_code == 202

        res2 = await discovery_client.post("/v0.5/care-contexts/discover", json=payload)
        assert res2.status_code == 202

        assert mock_bg.call_count == 1

    tx_count = (
        await db_session.execute(
            select(func.count())
            .select_from(GatewayTransaction)
            .where(GatewayTransaction.idempotency_key == req_id)
        )
    ).scalar_one()
    assert tx_count == 1


@pytest.mark.asyncio
async def test_cross_operation_idempotency_collision_returns_409(
    discovery_client: AsyncClient,
    db_session: AsyncSession,
):
    req_id = str(uuid4())
    db_session.add(
        GatewayTransaction(
            gateway_transaction_id="gw_existing_link_1",
            idempotency_key=req_id,
            abdm_request_id=req_id,
            operation_type="CARE_CONTEXT_LINK",
            status=TransactionStatus.LINKED.value,
            retry_count=0,
        )
    )
    await db_session.commit()

    with patch("app.api.v0_5.discovery._handle_discovery_background", new_callable=AsyncMock) as mock_bg:
        res = await discovery_client.post(
            "/v0.5/care-contexts/discover",
            json=_discover_payload(requestId=req_id),
        )
        assert res.status_code == 409
        assert mock_bg.call_count == 0
