# app/abdm/client.py
import uuid
import httpx
from datetime import datetime, timezone
from typing import Any, Optional
from app.core.config import settings
from app.core.exceptions import AbdmAuthFailedException, AbdmUnavailableException
from app.abdm.session import session_manager, AbdmSessionManager

class AbdmClient:
    """
    HTTP client for all outbound ABDM Gateway communication.
    Automatically handles bearer token injection and standard ABDM headers.
    """
    def __init__(self, session_mgr: Optional[AbdmSessionManager] = None):
        self.session_manager = session_mgr or session_manager
        self.base_url = settings.ABDM_BASE_URL

    def _generate_standard_headers(self, token: str, request_id: Optional[str] = None) -> dict[str, str]:
        """Generates standard mandatory ABDM headers."""
        return {
            "Authorization": f"Bearer {token}",
            "X-CM-ID": settings.ABDM_CM_ID,
            "Content-Type": "application/json",
            "REQUEST-ID": request_id or str(uuid.uuid4()),
            "TIMESTAMP": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        }

    async def post(self, endpoint: str, payload: dict[str, Any], request_id: Optional[str] = None) -> httpx.Response:
        """
        Executes an authenticated POST request against the ABDM Gateway.
        """
        token = await self.session_manager.get_valid_token()
        headers = self._generate_standard_headers(token=token, request_id=request_id)
        url = f"{self.base_url}{endpoint}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=payload, headers=headers)

            # If token expired on server side, clear cache and retry once
            if response.status_code == 401:
                self.session_manager.clear_cache()
                fresh_token = await self.session_manager.get_valid_token()
                headers = self._generate_standard_headers(token=fresh_token, request_id=request_id)
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(url, json=payload, headers=headers)

            return response

        except httpx.RequestError as exc:
            raise AbdmUnavailableException(f"Network error communicating with ABDM Gateway: {str(exc)}")

# Global client singleton
abdm_client = AbdmClient()