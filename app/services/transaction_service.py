import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.entities import GatewayTransaction, TransactionStatus

class TransactionService:
    @staticmethod
    async def get_or_create_transaction(
        db: AsyncSession,
        idempotency_key: str,
        operation_type: str,
        abdm_request_id: Optional[str] = None
    ) -> tuple[GatewayTransaction, bool]:
        """
        Retrieves existing transaction by idempotency_key or creates a new one.
        Returns: (transaction_instance, is_created_bool)
        """
        # 1. Check if idempotency key already exists
        query = select(GatewayTransaction).where(GatewayTransaction.idempotency_key == idempotency_key)
        result = await db.execute(query)
        existing_tx = result.scalar_one_or_none()

        if existing_tx:
            return existing_tx, False

        # 2. Create fresh transaction in CREATED/PENDING state
        new_tx = GatewayTransaction(
            gateway_transaction_id=f"gw_{uuid.uuid4().hex[:16]}",
            idempotency_key=idempotency_key,
            abdm_request_id=abdm_request_id or str(uuid.uuid4()),
            operation_type=operation_type,
            status=TransactionStatus.PENDING,
            retry_count=0
        )
        db.add(new_tx)
        await db.commit()
        await db.refresh(new_tx)
        return new_tx, True

    @staticmethod
    async def get_by_id(db: AsyncSession, transaction_id: str) -> Optional[GatewayTransaction]:
        query = select(GatewayTransaction).where(GatewayTransaction.gateway_transaction_id == transaction_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()