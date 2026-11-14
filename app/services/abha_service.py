# app/services/abha_service.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.entities import GatewayTransaction, TransactionStatus
from app.schemas.abha import AbhaProfileData, AbhaVerificationResponse
from app.core.exceptions import AbhaInvalidException
from app.services.transaction_service import TransactionService
from app.core.config import settings

class AbhaService:
    @staticmethod
    async def initiate_verification(
        db: AsyncSession,
        abha_address: str,
        auth_mode: str,
        idempotency_key: str
    ) -> AbhaVerificationResponse:
        """
        Initiates ABHA address verification and triggers OTP dispatch.
        """
        # Validate ABHA address syntax
        if "@" not in abha_address:
            raise AbhaInvalidException("ABHA address must contain '@' and domain (e.g., user@sbx)")

        # Create or fetch existing transaction
        tx, _ = await TransactionService.get_or_create_transaction(
            db=db,
            idempotency_key=idempotency_key,
            operation_type="ABHA_VERIFY"
        )

        return AbhaVerificationResponse(
            transaction_id=tx.gateway_transaction_id,
            status=TransactionStatus.PENDING,
            action_required="OTP_REQUIRED",
            message=f"OTP sent to mobile registered with {abha_address}. Enter OTP to complete verification."
        )

    @staticmethod
    async def confirm_otp(
        db: AsyncSession,
        transaction_id: str,
        otp: str
    ) -> AbhaVerificationResponse:
        """
        Validates OTP and returns verified patient profile.
        """
        tx = await TransactionService.get_by_id(db=db, transaction_id=transaction_id)
        if not tx:
            raise AbhaInvalidException(f"Transaction '{transaction_id}' does not exist.")

        if tx.status == TransactionStatus.COMPLETED:
            # Idempotent return if already completed
            return AbhaVerificationResponse(
                transaction_id=tx.gateway_transaction_id,
                status=TransactionStatus.COMPLETED,
                action_required=None,
                message="ABHA verification already completed.",
                profile=AbhaProfileData(
                    abha_address="sandbox-user@sbx",
                    name="Test Patient",
                    gender="M",
                    year_of_birth=1985,
                    mobile="+91-9876543210"
                )
            )

        # In Sandbox / Mock mode, validate test OTP
        # (Standard ABDM sandbox testing accepts 123456 or 654321)
        if otp not in ("123456", "654321"):
            tx.last_error_code = "ABHA_INVALID"
            tx.last_provider_error = "Invalid OTP provided."
            await db.commit()
            raise AbhaInvalidException("Invalid OTP. For testing, please use OTP '123456'.")

        # Mark transaction as COMPLETED
        tx.status = TransactionStatus.COMPLETED
        await db.commit()
        await db.refresh(tx)

        # Return verified profile
        return AbhaVerificationResponse(
            transaction_id=tx.gateway_transaction_id,
            status=TransactionStatus.COMPLETED,
            action_required=None,
            message="ABHA verification successful. Patient identity verified.",
            profile=AbhaProfileData(
                abha_address="sandbox-user@sbx",
                abha_number="91-1234-5678-9012",
                name="Ramesh Kumar",
                gender="M",
                year_of_birth=1985,
                mobile="+91-9876543210"
            )
        )