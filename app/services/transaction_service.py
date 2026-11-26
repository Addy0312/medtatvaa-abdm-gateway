# app/services/transaction_service.py
import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.entities import GatewayTransaction, TransactionStatus


class TransactionConflictError(Exception):
    """Raised when transaction creation or idempotency lookup encounters a conflict."""

    def __init__(
        self,
        message: str,
        code: str = "TRANSACTION_CONFLICT",
        details: Optional[object] = None,
        transaction_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details
        self.transaction_id = transaction_id


class TransactionService:
    @staticmethod
    async def get_or_create_transaction(
        db: AsyncSession,
        idempotency_key: str,
        operation_type: str,
        abdm_request_id: Optional[str] = None,
        commit: bool = True,
    ) -> tuple[GatewayTransaction, bool]:
        """
        Retrieves existing transaction by idempotency_key or creates a new one.
        Validates operation_type match when an existing transaction is returned.
        Returns: (transaction_instance, is_created_bool)
        """
        query = select(GatewayTransaction).where(GatewayTransaction.idempotency_key == idempotency_key)
        result = await db.execute(query)
        existing_tx = result.scalar_one_or_none()

        if existing_tx:
            if existing_tx.operation_type != operation_type:
                raise TransactionConflictError(
                    message="Idempotency key already exists for a different operation type.",
                    code="IDEMPOTENCY_OPERATION_CONFLICT",
                    details={
                        "idempotency_key": idempotency_key,
                        "expected_operation_type": operation_type,
                        "actual_operation_type": existing_tx.operation_type,
                    },
                    transaction_id=existing_tx.gateway_transaction_id,
                )
            return existing_tx, False

        new_tx = GatewayTransaction(
            gateway_transaction_id=f"gw_{uuid.uuid4().hex[:16]}",
            idempotency_key=idempotency_key,
            abdm_request_id=abdm_request_id or str(uuid.uuid4()),
            operation_type=operation_type,
            status=TransactionStatus.PENDING,
            retry_count=0,
        )
        db.add(new_tx)
        try:
            await db.flush()
            if commit:
                await db.commit()
                await db.refresh(new_tx)
        except IntegrityError as exc:
            if commit:
                await db.rollback()
            raise TransactionConflictError(
                message="Idempotency key already exists concurrently.",
                code="IDEMPOTENCY_CONFLICT",
                details={"idempotency_key": idempotency_key},
            ) from exc
        return new_tx, True

    @staticmethod
    async def get_by_id(db: AsyncSession, transaction_id: str) -> Optional[GatewayTransaction]:
        query = select(GatewayTransaction).where(GatewayTransaction.gateway_transaction_id == transaction_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_idempotency_key(db: AsyncSession, idempotency_key: str) -> Optional[GatewayTransaction]:
        query = select(GatewayTransaction).where(GatewayTransaction.idempotency_key == idempotency_key)
        result = await db.execute(query)
        return result.scalar_one_or_none()
