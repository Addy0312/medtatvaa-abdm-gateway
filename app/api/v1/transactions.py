from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.transaction import TransactionStatusResponse
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/transactions", tags=["Transactions"])

@router.get("/{transaction_id}", response_model=TransactionStatusResponse)
async def get_transaction_status(
    transaction_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns normalized status and diagnostics for a gateway transaction.
    """
    tx = await TransactionService.get_by_id(db=db, transaction_id=transaction_id)
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "transaction_id": transaction_id,
                "status": "FAILED_FINAL",
                "error_code": "TRANSACTION_NOT_FOUND",
                "message": f"Transaction '{transaction_id}' was not found."
            }
        )

    return TransactionStatusResponse(
        transaction_id=tx.gateway_transaction_id,
        operation_type=tx.operation_type,
        status=tx.status,
        abdm_request_id=tx.abdm_request_id,
        abdm_transaction_id=tx.abdm_transaction_id,
        retry_count=tx.retry_count,
        last_error_code=tx.last_error_code,
        created_at=tx.created_at,
        updated_at=tx.updated_at
    )