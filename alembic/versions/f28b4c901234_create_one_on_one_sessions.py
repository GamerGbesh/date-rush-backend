"""create one_on_one_sessions table

Revision ID: f28b4c901234
Revises: e17a3f890123
Create Date: 2026-08-28 23:28:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f28b4c901234'
down_revision: Union[str, Sequence[str], None] = 'e17a3f890123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'one_on_one_sessions',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('room_id', sa.Integer(), nullable=False),
        sa.Column('audience_id', sa.Integer(), nullable=False),
        sa.Column('challenger_id', sa.Integer(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column(
            'state',
            sa.Enum(
                'PENDING',
                'ACTIVE',
                'ANSWERED',
                'VOTING',
                'ACCEPTED',
                'REJECTED',
                'COMPLETED',
                name='oneononesessionstate',
            ),
            nullable=False,
            server_default='PENDING',
        ),
        sa.Column('question', sa.String(length=500), nullable=True),
        sa.Column('answer', sa.String(length=1000), nullable=True),
        sa.Column(
            'vote',
            sa.Enum('YES', 'NO', name='votechoice'),
            nullable=True,
        ),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('voted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], name='fk_one_on_one_sessions_room_id'),
        sa.ForeignKeyConstraint(['audience_id'], ['users.id'], name='fk_one_on_one_sessions_audience_id'),
        sa.ForeignKeyConstraint(['challenger_id'], ['users.id'], name='fk_one_on_one_sessions_challenger_id'),
        sa.UniqueConstraint('room_id', 'sequence', name='uq_one_on_one_room_sequence'),
        sa.UniqueConstraint('room_id', 'audience_id', name='uq_one_on_one_room_audience'),
    )
    op.create_index(op.f('ix_one_on_one_sessions_id'), 'one_on_one_sessions', ['id'], unique=False)
    op.create_index(op.f('ix_one_on_one_sessions_room_id'), 'one_on_one_sessions', ['room_id'], unique=False)
    op.create_index(op.f('ix_one_on_one_sessions_audience_id'), 'one_on_one_sessions', ['audience_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_one_on_one_sessions_audience_id'), table_name='one_on_one_sessions')
    op.drop_index(op.f('ix_one_on_one_sessions_room_id'), table_name='one_on_one_sessions')
    op.drop_index(op.f('ix_one_on_one_sessions_id'), table_name='one_on_one_sessions')
    op.drop_table('one_on_one_sessions')
