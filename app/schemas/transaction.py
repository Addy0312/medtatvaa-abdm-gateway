from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from app.models.entities import TransactionStatus

class TransactionResponse(BaseModel):
    transaction_id: str = Field(..., description="Medtatvaa unique tracking UUID", example="gw_01J8K9...")
    status: TransactionStatus = Field(default=TransactionStatus.PENDING, example=TransactionStatus.PENDING)
    abdm_request_id: Optional[str] = Field(None, description="Correlated ABDM Request ID", example="c1a2b3...")
    message: Optional[str] = Field(None, example="Request accepted for processing")

class TransactionStatusResponse(BaseModel):
    transaction_id: str = Field(..., example="gw_01J8K9...")
    operation_type: str = Field(..., example="REPORT_SHARE")
    status: TransactionStatus = Field(..., example=TransactionStatus.COMPLETED)
    abdm_request_id: Optional[str] = None
    abdm_transaction_id: Optional[str] = None
    retry_count: int = 0
    last_error_code: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

class ErrorResponse(BaseModel):
    transaction_id: Optional[str] = None
    status: str = "FAILED_FINAL"
    error_code: str = Field(..., example="ABHA_INVALID")
    message: str = Field(..., example="The provided ABHA address does not exist.")
    details: Optional[Any] = None