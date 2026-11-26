# migrations/versions/734706997e4e_add_link_sessions_table.py
"""add link_sessions table

Revision ID: 734706997e4e
Revises: f5d1f786413e
Create Date: 2026-11-23 23:07:17.803132

Note: Databases that already applied a prior broken version of 734706997e4e
require manual backup and reconciliation rather than an automatic rewrite.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '734706997e4e'
down_revision: Union[str, None] = 'f5d1f786413e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'link_sessions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('link_ref_number', sa.String(length=64), nullable=False),
        sa.Column('transaction_id', sa.String(length=64), nullable=False),
        sa.Column('abha_address', sa.String(length=128), nullable=False),
        sa.Column('patient_reference', sa.String(length=64), nullable=False),
        sa.Column('care_contexts', sa.Text(), nullable=False),
        sa.Column('otp', sa.String(length=16), nullable=False),
        sa.Column('is_confirmed', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_link_sessions_link_ref_number'),
        'link_sessions',
        ['link_ref_number'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_link_sessions_link_ref_number'), table_name='link_sessions')
    op.drop_table('link_sessions')
