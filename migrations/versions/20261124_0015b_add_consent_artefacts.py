# migrations/versions/20261124_0015b_add_consent_artefacts.py
"""add consent_artefacts table

Revision ID: 20261124_0015b
Revises: 20261124_0015
Create Date: 2026-11-24 08:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20261124_0015b'
down_revision: Union[str, None] = '20261124_0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'consent_artefacts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('consent_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('abha_address', sa.String(length=128), nullable=True),
        sa.Column('care_contexts', sa.Text(), nullable=True),
        sa.Column('hi_types', sa.Text(), nullable=True),
        sa.Column('date_range_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('date_range_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('data_erase_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('raw_consent_detail', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_consent_artefacts_consent_id'), 'consent_artefacts', ['consent_id'], unique=True)
    op.create_index(op.f('ix_consent_artefacts_abha_address'), 'consent_artefacts', ['abha_address'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_consent_artefacts_abha_address'), table_name='consent_artefacts')
    op.drop_index(op.f('ix_consent_artefacts_consent_id'), table_name='consent_artefacts')
    op.drop_table('consent_artefacts')
