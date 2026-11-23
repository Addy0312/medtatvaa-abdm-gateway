# tests/integration/test_m2_linking.py
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.database import AsyncSessionLocal
from app.models.entities import CareContextRecord, LinkSession
from app.schemas.abdm.linking import (
    CareContextRef,
    LinkConfirmRequest,
    LinkConfirmationQuery,
    LinkInitRequest,
    PatientLinkInitQuery,
)
from app.services.linking_service import LinkingService


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
async def test_inbound_link_init_endpoint_returns_202(client: AsyncClient):
    req_id = str(uuid4())
    payload = {
        "requestId": req_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "transactionId": str(uuid4()),
        "patient": {
            "id": "aditya@sbx",
            "referenceNumber": "PAT-101",
            "careContexts": [{"referenceNumber": "STUDY-USG-001"}]
        }
    }
    response = await client.post("/v0.5/links/link/init", json=payload)
    assert response.status_code == 202
    assert response.json()["status"] == "ACCEPTED"
    assert response.json()["requestId"] == req_id


@pytest.mark.asyncio
async def test_inbound_link_confirm_endpoint_returns_202(client: AsyncClient):
    req_id = str(uuid4())
    payload = {
        "requestId": req_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "confirmation": {
            "linkRefNumber": "LR-SAMPLE123",
            "token": "123456"
        }
    }
    response = await client.post("/v0.5/links/link/confirm", json=payload)
    assert response.status_code == 202
    assert response.json()["status"] == "ACCEPTED"
    assert response.json()["requestId"] == req_id


@pytest.mark.asyncio
async def test_full_linking_lifecycle_success(db_session: AsyncSession):
    suffix = uuid4().hex[:6]
    abha_address = f"patient_{suffix}@sbx"
    local_pid = f"PAT-{suffix.upper()}"
    study_ref = f"STUDY-{suffix}"

    # 1. Pre-seed unlinked care context (is_linked=0)
    ctx = CareContextRecord(
        local_patient_id=local_pid,
        abha_address=abha_address,
        care_context_reference=study_ref,
        display_name="Ultrasound Whole Abdomen",
        is_linked=0,
    )
    db_session.add(ctx)
    await db_session.commit()

    # 2. Execute process_link_init
    init_req = LinkInitRequest(
        requestId=uuid4(),
        timestamp=datetime.now(timezone.utc),
        transactionId=uuid4(),
        patient=PatientLinkInitQuery(
            id=abha_address,
            referenceNumber=local_pid,
            careContexts=[CareContextRef(referenceNumber=study_ref)],
        )
    )
    init_res = await LinkingService.process_link_init(db_session, init_req)
    assert init_res.error is None
    assert init_res.link is not None
    link_ref_num = init_res.link.referenceNumber

    # Verify session persisted in DB
    session_stmt = select(LinkSession).where(LinkSession.link_ref_number == link_ref_num)
    session_db = (await db_session.execute(session_stmt)).scalar_one_or_none()
    assert session_db is not None
    assert session_db.is_confirmed == 0

    # 3. Execute process_link_confirm with valid OTP
    confirm_req = LinkConfirmRequest(
        requestId=uuid4(),
        timestamp=datetime.now(timezone.utc),
        confirmation=LinkConfirmationQuery(
            linkRefNumber=link_ref_num,
            token="123456"
        )
    )
    confirm_res = await LinkingService.process_link_confirm(db_session, confirm_req)
    assert confirm_res.error is None
    assert confirm_res.patient is not None
    assert len(confirm_res.patient.careContexts) == 1
    assert confirm_res.patient.careContexts[0].referenceNumber == study_ref

    # Verify DB state: is_linked updated to 1
    ctx_check = (
        await db_session.execute(
            select(CareContextRecord).where(CareContextRecord.care_context_reference == study_ref)
        )
    ).scalar_one()
    assert ctx_check.is_linked == 1


@pytest.mark.asyncio
async def test_linking_fails_on_wrong_otp(db_session: AsyncSession):
    suffix = uuid4().hex[:6]
    abha_address = f"patient_{suffix}@sbx"
    study_ref = f"STUDY-{suffix}"

    ctx = CareContextRecord(
        local_patient_id=f"PAT-{suffix}",
        abha_address=abha_address,
        care_context_reference=study_ref,
        display_name="Ultrasound Pelvis",
        is_linked=0,
    )
    db_session.add(ctx)
    await db_session.commit()

    init_req = LinkInitRequest(
        requestId=uuid4(),
        timestamp=datetime.now(timezone.utc),
        transactionId=uuid4(),
        patient=PatientLinkInitQuery(
            id=abha_address,
            referenceNumber=f"PAT-{suffix}",
            careContexts=[CareContextRef(referenceNumber=study_ref)],
        )
    )
    init_res = await LinkingService.process_link_init(db_session, init_req)
    link_ref_num = init_res.link.referenceNumber

    # Attempt confirmation with wrong OTP
    confirm_req = LinkConfirmRequest(
        requestId=uuid4(),
        timestamp=datetime.now(timezone.utc),
        confirmation=LinkConfirmationQuery(
            linkRefNumber=link_ref_num,
            token="999999"
        )
    )
    confirm_res = await LinkingService.process_link_confirm(db_session, confirm_req)
    assert confirm_res.patient is None
    assert confirm_res.error is not None
    assert confirm_res.error.code == 1403

    # Ensure record remains unlinked
    ctx_check = (
        await db_session.execute(
            select(CareContextRecord).where(CareContextRecord.care_context_reference == study_ref)
        )
    ).scalar_one()
    assert ctx_check.is_linked == 0