"""add optimistic locking and session revocation

Revision ID: b058b1c0c7ad
Revises: 1c75097876de
Create Date: 2026-07-29 02:43:00.139086
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b058b1c0c7ad'
down_revision = '1c75097876de'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('revoked_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('jti', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('revoked_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_revoked_tokens_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_revoked_tokens_jti'), ['jti'], unique=True)
        batch_op.create_index(batch_op.f('ix_revoked_tokens_user_id'), ['user_id'], unique=False)

    # orders.version: 楽観ロック用。既存行にも値が必要なので server_default を付ける。
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('version', sa.Integer(), nullable=False, server_default='1')
        )

    # users.session_version: セッション一括失効用。既存行は 0 から開始する。
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('session_version', sa.Integer(), nullable=False, server_default='0')
        )



def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('session_version')

    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('version')

    with op.batch_alter_table('revoked_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_revoked_tokens_user_id'))
        batch_op.drop_index(batch_op.f('ix_revoked_tokens_jti'))
        batch_op.drop_index(batch_op.f('ix_revoked_tokens_expires_at'))

    op.drop_table('revoked_tokens')
