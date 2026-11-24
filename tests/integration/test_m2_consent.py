# tests/integration/test_m2_consent.py
import pytest
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.database import AsyncSessionLocal, Base, engine
from app.models.entities import ConsentArtefactRecord
from app.schemas.abdm.consent import ConsentHipNotifyRequest
from app.services.consent_service import ConsentService


@pytest.fixture(autouse=True)
async def ensure_tables():
    """Ensure consent_artefacts and other tables exist in SQLite before running tests."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


def _build_grant_payload(consent_id: str, abha_address: str = "aditya@sbx") -> dict:
    now = datetime.now(timezone.utc)
    erase_at = (now + timedelta(days=30)).isoformat()
    return {
        "requestId": str(uuid4()),
        "timestamp": now.isoformat(),
        "notification": {
            "status": "GRANTED",
            "consentId": consent_id,
            "consentDetail": {
                "schemaVersion": "v1",
                "consentId": consent_id,
                "createdAt": now.isoformat(),
                "patient": {"id": abha_address},
                "careContexts": [
                    {
                        "patientReference": "PAT-101",
                        "careContextReference": "STUDY-USG-001",
                    }
                ],
                "purpose": {"text": "Care Management", "code": "CAREMGT"},
                "hip": {"id": "MEDTATVAA_HIP_01", "name": "Medtatvaa Diagnostics"},
                "hiu": {"id": "HIU_01", "name": "Partner Hospital"},
                "consentManager": {"id": "sbx"},
                "hiTypes": ["DiagnosticReport"],
                "permission": {
                    "accessMode": "VIEW",
                    "dateRange": {
                        "from": (now - timedelta(days=365)).isoformat(),
                        "to": now.isoformat(),
                    },
                    "dataEraseAt": erase_at,
                    "frequency": {"unit": "HOUR", "value": 1, "repeats": 0},
                },
            },
            "signature": "mock-abdm-signature",
        },
    }


@pytest.mark.asyncio
async def test_inbound_consent_notify_returns_202(client: AsyncClient):
    consent_id = str(uuid4())
    payload = _build_grant_payload(consent_id)

    response = await client.post("/v0.5/consents/hip/notify", json=payload)
    assert response.status_code == 202
    assert response.json()["status"] == "ACCEPTED"
    assert response.json()["requestId"] == payload["requestId"]


@pytest.mark.asyncio
async def test_consent_grant_and_active_validation(db_session: AsyncSession):
    consent_id = str(uuid4())
    abha = f"consent_{uuid4().hex[:6]}@sbx"
    raw_payload = _build_grant_payload(consent_id, abha)

    req = ConsentHipNotifyRequest.model_validate(raw_payload)
    on_notify = await ConsentService.process_consent_notify(db_session, req)

    assert on_notify.error is None
    assert on_notify.acknowledgement is not None
    assert on_notify.acknowledgement.status == "OK"
    assert on_notify.acknowledgement.consentId == consent_id

    record = (
        await db_session.execute(
            select(ConsentArtefactRecord).where(ConsentArtefactRecord.consent_id == consent_id)
        )
    ).scalar_one_or_none()
    assert record is not None
    assert record.status == "GRANTED"
    assert record.abha_address == abha

    active = await ConsentService.get_valid_consent(db_session, consent_id)
    assert active is not None


@pytest.mark.asyncio
async def test_consent_revocation_blocks_access(db_session: AsyncSession):
    consent_id = str(uuid4())
    grant_req = ConsentHipNotifyRequest.model_validate(_build_grant_payload(consent_id))
    await ConsentService.process_consent_notify(db_session, grant_req)

    revoke_payload = {
        "requestId": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "notification": {
            "status": "REVOKED",
            "consentId": consent_id,
        },
    }
    revoke_req = ConsentHipNotifyRequest.model_validate(revoke_payload)
    on_notify = await ConsentService.process_consent_notify(db_session, revoke_req)

    assert on_notify.error is None
    assert on_notify.acknowledgement is not None
    assert on_notify.acknowledgement.status == "OK"

    active = await ConsentService.get_valid_consent(db_session, consent_id)
    assert active is None


@pytest.mark.asyncio
async def test_revoke_unknown_consent_returns_1404(db_session: AsyncSession):
    revoke_payload = {
        "requestId": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "notification": {
            "status": "REVOKED",
            "consentId": "non-existent-consent-999",
        },
    }
    revoke_req = ConsentHipNotifyRequest.model_validate(revoke_payload)
    on_notify = await ConsentService.process_consent_notify(db_session, revoke_req)

    assert on_notify.acknowledgement is None
    assert on_notify.error is not None
    assert on_notify.error.code == 1404