# app/abdm/session.py
import asyncio
import time
import httpx
from typing import Optional
from app.core.config import settings
from app.core.exceptions import AbdmAuthFailedException, AbdmUnavailableException

class AbdmSessionManager:
    """
    Manages ABDM Gateway session tokens with in-memory caching,
    expiration buffers, and race-condition locking.
    """
    def __init__(self):
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_valid_token(self) -> str:
        """
        Returns a valid cached token, or fetches a fresh token if expired.
        """
        # 1. Fast path: token exists and has > 60 seconds of validity remaining
        now = time.time()
        if self._access_token and (self._expires_at - now > 60):
            return self._access_token

        # 2. Slow path: Acquire lock to prevent duplicate simultaneous token requests
        async with self._lock:
            # Double-check inside lock in case another task refreshed it while waiting
            now = time.time()
            if self._access_token and (self._expires_at - now > 60):
                return self._access_token

            # Fetch fresh token from ABDM
            token, expires_in = await self._fetch_new_token()
            self._access_token = token
            self._expires_at = time.time() + expires_in
            return self._access_token

    async def _fetch_new_token(self) -> tuple[str, int]:
        """
        Calls ABDM /sessions endpoint to exchange client credentials for a Bearer token.
        """
        if not settings.ABDM_CLIENT_ID or not settings.ABDM_CLIENT_SECRET:
            raise AbdmAuthFailedException("ABDM_CLIENT_ID or ABDM_CLIENT_SECRET is missing in configuration.")

        url = f"{settings.ABDM_BASE_URL}{settings.ABDM_SESSION_PATH}"
        payload = {
            "clientId": settings.ABDM_CLIENT_ID,
            "clientSecret": settings.ABDM_CLIENT_SECRET
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)

            if response.status_code == 200:
                data = response.json()
                access_token = data.get("accessToken")
                expires_in = data.get("expiresIn", 1800)  # Default 30 mins if not provided
                if not access_token:
                    raise AbdmAuthFailedException("ABDM session response did not contain an accessToken.")
                return access_token, expires_in

            elif response.status_code in (401, 403):
                raise AbdmAuthFailedException(f"ABDM rejected credentials: {response.text}")

            else:
                raise AbdmUnavailableException(f"ABDM Gateway returned status {response.status_code}: {response.text}")

        except httpx.RequestError as exc:
            raise AbdmUnavailableException(f"Network error connecting to ABDM Gateway: {str(exc)}")

    def clear_cache(self):
        """Forces next request to refresh the token."""
        self._access_token = None
        self._expires_at = 0.0

# Singleton instance for the gateway
session_manager = AbdmSessionManager()