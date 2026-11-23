# app/models/entities.py
import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Text, UniqueConstraint, func
from app.core.database import Base


class TransactionStatus(str, enum.Enum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    LINKED = "LINKED"
    SHARED = "SHARED"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"


class GatewayTransaction(Base):
    __tablename__ = "gateway_transactions"

    gateway_transaction_id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    idempotency_key = Column(String(128), unique=True, nullable=False, index=True)
    abdm_request_id = Column(String(36), unique=True, nullable=True, index=True)
    abdm_transaction_id = Column(String(64), nullable=True, index=True)
    operation_type = Column(String(32), nullable=False)  # e.g., "CARE_CONTEXT_LINK", "REPORT_SHARE"
    status = Column(String(20), default=TransactionStatus.CREATED, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    last_error_code = Column(String(64), nullable=True)
    last_provider_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CareContextRecord(Base):
    __tablename__ = "care_contexts"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    local_patient_id = Column(String(64), nullable=False, index=True)
    abha_address = Column(String(128), nullable=False, index=True)
    care_context_reference = Column(String(128), nullable=False)  # Local study ID / Accession No.
    display_name = Column(String(255), nullable=False)            # e.g., "Ultrasound Abdomen - 31 Oct 2026"
    is_linked = Column(Integer, default=0, nullable=False)        # 0 = False, 1 = True
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('abha_address', 'care_context_reference', name='uq_patient_care_context'),
    )


class LinkSession(Base):
    __tablename__ = "link_sessions"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    link_ref_number = Column(String(64), unique=True, nullable=False, index=True)
    transaction_id = Column(String(64), nullable=False)
    abha_address = Column(String(128), nullable=False)
    patient_reference = Column(String(64), nullable=False)
    care_contexts = Column(Text, nullable=False)  # JSON-encoded list of context references
    otp = Column(String(16), default="123456", nullable=False)
    is_confirmed = Column(Integer, default=0, nullable=False)  # 0 = False, 1 = True
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False
    )