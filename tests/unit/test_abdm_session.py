# tests/unit/test_abdm_session.py
import pytest
import time
from unittest.mock import patch, AsyncMock
import httpx
from app.abdm.session import AbdmSessionManager
from app.core.exceptions import AbdmAuthFailedException

@pytest.mark.asyncio
async def test_session_manager_caches_token():
    """Verifies that subsequent calls return the cached token without making another HTTP request."""
    mgr = AbdmSessionManager()

    mock_response = httpx.Response(
        status_code=200,
        json={"accessToken": "mock_token_abc_123", "expiresIn": 1800},
        request=httpx.Request("POST", "https://dev.abdm.gov.in")
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        # 1. First call - should trigger HTTP request
        token1 = await mgr.get_valid_token()
        assert token1 == "mock_token_abc_123"
        assert mock_post.call_count == 1

        # 2. Second call - should use in-memory cache
        token2 = await mgr.get_valid_token()
        assert token2 == "mock_token_abc_123"
        assert mock_post.call_count == 1  # Still 1! No second request

@pytest.mark.asyncio
async def test_session_manager_refreshes_expired_token():
    """Verifies that an expired token triggers a fresh HTTP request."""
    mgr = AbdmSessionManager()

    # Pre-populate with an expired token
    mgr._access_token = "old_expired_token"
    mgr._expires_at = time.time() - 100  # Expired in past

    mock_response = httpx.Response(
        status_code=200,
        json={"accessToken": "fresh_token_xyz_789", "expiresIn": 1800},
        request=httpx.Request("POST", "https://dev.abdm.gov.in")
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        fresh_token = await mgr.get_valid_token()
        assert fresh_token == "fresh_token_xyz_789"
        assert mock_post.call_count == 1

@pytest.mark.asyncio
async def test_session_manager_handles_auth_failure():
    """Verifies that rejected credentials throw AbdmAuthFailedException."""
    mgr = AbdmSessionManager()

    mock_response = httpx.Response(
        status_code=401,
        text="Invalid client credentials",
        request=httpx.Request("POST", "https://dev.abdm.gov.in")
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        with pytest.raises(AbdmAuthFailedException):
            await mgr.get_valid_token()