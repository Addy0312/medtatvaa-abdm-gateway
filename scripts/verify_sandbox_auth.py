import sys
import os

# Ensure project root is in Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
from app.core.config import settings
from app.abdm.session import session_manager
from app.core.exceptions import AbdmAuthFailedException, AbdmUnavailableException

async def verify_abdm_credentials():
    print("=" * 65)
    print("  MEDTATVAA ABDM SANDBOX CREDENTIALS & CONNECTIVITY VERIFIER")
    print("=" * 65)

    print(f"\n[1] Inspecting Current Environment Configuration:")
    print(f"    - Environment:          {settings.ENV}")
    print(f"    - ABDM Base URL:        {settings.ABDM_BASE_URL}")
    print(f"    - Session Endpoint:     {settings.ABDM_SESSION_PATH}")
    print(f"    - Consent Manager ID:   {settings.ABDM_CM_ID}")
    print(f"    - Configured Client ID: {settings.ABDM_CLIENT_ID}")

    # Check if using placeholder credentials
    if settings.ABDM_CLIENT_ID in (None, "", "mock_client_id"):
        print("\n🟡 STATUS: RUNNING IN LOCAL MOCK MODE")
        print("    - Current ABDM_CLIENT_ID is set to placeholder ('mock_client_id').")
        print("    - All M1 and Gateway workflows use the high-fidelity mock engine.")
        print("    - When your manager provides live credentials, update:")
        print("        ABDM_CLIENT_ID=\"...\"")
        print("        ABDM_CLIENT_SECRET=\"...\"")
        print("      in your .env file, and re-run this script to test live connectivity.")
        print("\n" + "=" * 65)
        return

    print(f"\n[2] Attempting Live Handshake with ABDM Sandbox Servers...")
    try:
        token = await session_manager.get_valid_token()
        print("✅ Live Token Handshake SUCCESSFUL!")
        print(f"    - Access Token Received: {token[:20]}...{token[-10:]}")
        print("    - Token Caching: Active (in-memory with 60s buffer)")
        print("\n🟢 STATUS: READY FOR LIVE SANDBOX M1/M2 TESTING")
    except AbdmAuthFailedException as exc:
        print(f"❌ AUTHENTICATION FAILED: {exc.message}")
        print("    - Please verify ABDM_CLIENT_ID and ABDM_CLIENT_SECRET in .env.")
    except AbdmUnavailableException as exc:
        print(f"⚠️  ABDM GATEWAY UNAVAILABLE: {exc.message}")
        print("    - The government sandbox server may be undergoing maintenance.")

    print("\n" + "=" * 65)

if __name__ == "__main__":
    asyncio.run(verify_abdm_credentials())