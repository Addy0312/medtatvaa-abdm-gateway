# migrations/versions/20261124_0015_add_diagnostic_reports.py
"""Add diagnostic_reports table for canonical diagnostic report storage.

Revision ID: 20261124_0015
Revises: 734706997e4e
Create Date: 2026-11-24 00:15:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "20261124_0015"
down_revision: Union[str, None] = "734706997e4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("abha_address", sa.String(length=128), nullable=False),
        sa.Column("local_patient_id", sa.String(length=64), nullable=False),
        sa.Column("care_context_reference", sa.String(length=128), nullable=False),
        sa.Column("local_report_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("gateway_transaction_id", sa.String(length=36), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["gateway_transaction_id"],
            ["gateway_transactions.gateway_transaction_id"],
            name="fk_diagnostic_reports_gateway_transaction_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "abha_address",
            "care_context_reference",
            "local_report_id",
            name="uq_diag_report_abha_care_context_report_id",
        ),
    )
    op.create_index(
        "ix_diagnostic_reports_abha_address",
        "diagnostic_reports",
        ["abha_address"],
        unique=False,
    )
    op.create_index(
        "ix_diagnostic_reports_local_patient_id",
        "diagnostic_reports",
        ["local_patient_id"],
        unique=False,
    )
    op.create_index(
        "ix_diagnostic_reports_care_context_reference",
        "diagnostic_reports",
        ["care_context_reference"],
        unique=False,
    )
    op.create_index(
        "ix_diagnostic_reports_local_report_id",
        "diagnostic_reports",
        ["local_report_id"],
        unique=False,
    )
    op.create_index(
        "ix_diagnostic_reports_idempotency_key",
        "diagnostic_reports",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_diagnostic_reports_gateway_transaction_id",
        "diagnostic_reports",
        ["gateway_transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_diagnostic_reports_gateway_transaction_id", table_name="diagnostic_reports")
    op.drop_index("ix_diagnostic_reports_idempotency_key", table_name="diagnostic_reports")
    op.drop_index("ix_diagnostic_reports_local_report_id", table_name="diagnostic_reports")
    op.drop_index("ix_diagnostic_reports_care_context_reference", table_name="diagnostic_reports")
    op.drop_index("ix_diagnostic_reports_local_patient_id", table_name="diagnostic_reports")
    op.drop_index("ix_diagnostic_reports_abha_address", table_name="diagnostic_reports")
    op.drop_table("diagnostic_reports")
