"""add room_state_history table

Revision ID: c83a1b7e4112
Revises: 0d90af715a91
Create Date: 2026-08-28 22:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c83a1b7e4112'
down_revision: Union[str, Sequence[str], None] = '0d90af715a91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

roomstate_enum = postgresql.ENUM(
    'WAITING', 'READY', 'INTRO', 'QUESTIONING', 'VOTING', 'ELIMINATION', 'FINAL', 'MATCHED', 'COMPLETED',
    name='roomstate',
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    context = op.get_context()
    is_postgres = context.dialect.name == 'postgresql'
    bind = op.get_bind()

    roomstate_col = roomstate_enum if is_postgres else sa.Enum(
        'WAITING', 'READY', 'INTRO', 'QUESTIONING', 'VOTING', 'ELIMINATION', 'FINAL', 'MATCHED', 'COMPLETED',
        name='roomstate',
    )

    op.create_table(
        'room_state_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('room_id', sa.Integer(), nullable=False),
        sa.Column('from_state', roomstate_col, nullable=False),
        sa.Column('to_state', roomstate_col, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_room_state_history_id'), 'room_state_history', ['id'], unique=False)
    op.create_index(op.f('ix_room_state_history_room_id'), 'room_state_history', ['room_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_room_state_history_room_id'), table_name='room_state_history')
    op.drop_index(op.f('ix_room_state_history_id'), table_name='room_state_history')
    op.drop_table('room_state_history')
