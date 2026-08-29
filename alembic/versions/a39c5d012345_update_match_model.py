"""update matches table with status and unique room constraint

Revision ID: a39c5d012345
Revises: f28b4c901234
Create Date: 2026-08-28 23:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a39c5d012345'
down_revision: Union[str, Sequence[str], None] = 'f28b4c901234'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('matches', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'status',
                sa.Enum('CREATED', 'COMPLETED', 'CANCELLED', name='matchstatus'),
                nullable=False,
                server_default='CREATED',
            )
        )
        batch_op.create_unique_constraint('uq_match_room_id', ['room_id'])
        batch_op.create_index(batch_op.f('ix_matches_room_id'), ['room_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_matches_challenger_id'), ['challenger_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_matches_audience_id'), ['audience_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('matches', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_matches_audience_id'))
        batch_op.drop_index(batch_op.f('ix_matches_challenger_id'))
        batch_op.drop_index(batch_op.f('ix_matches_room_id'))
        batch_op.drop_constraint('uq_match_room_id', type_='unique')
        batch_op.drop_column('status')
