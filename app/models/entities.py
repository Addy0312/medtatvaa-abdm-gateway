# app/models/entities.py
import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Text, UniqueConstraint, ForeignKey, func
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
    operation_type = Column(String(32), nullable=False)
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
    care_context_reference = Column(String(128), nullable=False)
    display_name = Column(String(255), nullable=False)
    is_linked = Column(Integer, default=0, nullable=False)
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
    care_contexts = Column(Text, nullable=False)
    otp = Column(String(16), default="123456", nullable=False)
    is_confirmed = Column(Integer, default=0, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False
    )


class ConsentArtefactRecord(Base):
    """
    Persists ABDM consent artefacts granted, revoked, or expired for Medtatvaa HIP care contexts.
    """
    __tablename__ = "consent_artefacts"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    consent_id = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False)  # GRANTED, REVOKED, EXPIRED
    abha_address = Column(String(128), nullable=True, index=True)
    care_contexts = Column(Text, nullable=True)  # JSON list of {patientReference, careContextReference}
    hi_types = Column(Text, nullable=True)       # JSON list e.g. ["DiagnosticReport"]
    date_range_from = Column(DateTime(timezone=True), nullable=True)
    date_range_to = Column(DateTime(timezone=True), nullable=True)
    data_erase_at = Column(DateTime(timezone=True), nullable=True)
    raw_consent_detail = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class DiagnosticReportStore(Base):
    """
    Persists the full canonical diagnostic report JSON keyed by
    (abha_address, care_context_reference, local_report_id) and linked to
    a unique idempotency_key and non-null gateway_transaction_id.
    """
    __tablename__ = "diagnostic_reports"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    abha_address = Column(String(128), nullable=False, index=True)
    local_patient_id = Column(String(64), nullable=False, index=True)
    care_context_reference = Column(String(128), nullable=False, index=True)
    local_report_id = Column(String(64), nullable=False, index=True)
    idempotency_key = Column(String(128), unique=True, nullable=False, index=True)
    gateway_transaction_id = Column(
        String(36),
        ForeignKey("gateway_transactions.gateway_transaction_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    payload_json = Column(Text, nullable=False)
    payload_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "abha_address",
            "care_context_reference",
            "local_report_id",
            name="uq_diag_report_abha_care_context_report_id",
        ),
    )
