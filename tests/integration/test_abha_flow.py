# tests/integration/test_abha_flow.py
import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

@pytest.mark.asyncio
async def test_complete_m1_verification_flow(async_client: AsyncClient):
    """Verifies end-to-end M1 ABHA flow: Initiate -> Receive OTP_REQUIRED -> Submit OTP -> Receive Verified Profile."""
    idempotency_key = f"m1-test-{uuid.uuid4().hex[:8]}"

    # 1. Initiate Verification
    init_res = await async_client.post(
        "/api/v1/abha/verify-or-link",
        json={"abha_address": "test-patient@sbx", "auth_mode": "MOBILE_OTP"},
        headers={"x-idempotency-key": idempotency_key}
    )
    assert init_res.status_code == 200
    init_data = init_res.json()
    assert init_data["status"] == "PENDING"
    assert init_data["action_required"] == "OTP_REQUIRED"
    tx_id = init_data["transaction_id"]

    # 2. Confirm OTP with valid test OTP
    confirm_res = await async_client.post(
        "/api/v1/abha/confirm-otp",
        json={"transaction_id": tx_id, "otp": "123456"}
    )
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()
    assert confirm_data["status"] == "COMPLETED"
    assert confirm_data["action_required"] is None
    assert confirm_data["profile"]["name"] == "Ramesh Kumar"
    assert confirm_data["profile"]["gender"] == "M"

@pytest.mark.asyncio
async def test_m1_invalid_otp_rejection(async_client: AsyncClient):
    """Verifies that submitting an incorrect OTP returns normalized ABHA_INVALID error."""
    idempotency_key = f"m1-bad-otp-{uuid.uuid4().hex[:8]}"

    init_res = await async_client.post(
        "/api/v1/abha/verify-or-link",
        json={"abha_address": "test-patient@sbx", "auth_mode": "MOBILE_OTP"},
        headers={"x-idempotency-key": idempotency_key}
    )
    tx_id = init_res.json()["transaction_id"]

    # Submit invalid OTP
    bad_res = await async_client.post(
        "/api/v1/abha/confirm-otp",
        json={"transaction_id": tx_id, "otp": "999999"}
    )
    assert bad_res.status_code == 404
    bad_data = bad_res.json()
    assert bad_data["error_code"] == "ABHA_INVALID"

@pytest.mark.asyncio
async def test_m1_invalid_abha_address_format(async_client: AsyncClient):
    """Verifies that an address missing domain is rejected."""
    bad_res = await async_client.post(
        "/api/v1/abha/verify-or-link",
        json={"abha_address": "invalid_address_without_at", "auth_mode": "MOBILE_OTP"},
        headers={"x-idempotency-key": "bad-address-key"}
    )
    assert bad_res.status_code == 404
    assert bad_res.json()["error_code"] == "ABHA_INVALID"