"""update votes table and add status to room_participants

Revision ID: e17a3f890123
Revises: d94b2a8e3123
Create Date: 2026-08-28 23:14:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e17a3f890123'
down_revision: Union[str, Sequence[str], None] = 'd94b2a8e3123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

participantstatus_enum = postgresql.ENUM(
    'ACTIVE', 'ELIMINATED', 'FINALIST', 'SELECTED', name='participantstatus', create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    context = op.get_context()
    is_postgres = context.dialect.name == 'postgresql'
    bind = op.get_bind()

    if is_postgres:
        if bind is not None:
            postgresql.ENUM('ACTIVE', 'ELIMINATED', 'FINALIST', 'SELECTED', name='participantstatus').create(bind, checkfirst=True)
        else:
            op.execute("CREATE TYPE participantstatus AS ENUM ('ACTIVE', 'ELIMINATED', 'FINALIST', 'SELECTED')")

    status_col = participantstatus_enum if is_postgres else sa.Enum(
        'ACTIVE', 'ELIMINATED', 'FINALIST', 'SELECTED', name='participantstatus'
    )

    # 1. Add status column to room_participants
    with op.batch_alter_table('room_participants', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'status',
                status_col,
                nullable=False,
                server_default='ACTIVE',
            )
        )

    # 2. Add target_id column to votes and update vote column type if needed
    with op.batch_alter_table('votes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('target_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_votes_target_id', 'users', ['target_id'], ['id'])
        batch_op.create_index(batch_op.f('ix_votes_room_id'), ['room_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_votes_voter_id'), ['voter_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('votes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_votes_voter_id'))
        batch_op.drop_index(batch_op.f('ix_votes_room_id'))
        batch_op.drop_constraint('fk_votes_target_id', type_='foreignkey')
        batch_op.drop_column('target_id')

    with op.batch_alter_table('room_participants', schema=None) as batch_op:
        batch_op.drop_column('status')

    context = op.get_context()
    if context.dialect.name == 'postgresql':
        bind = op.get_bind()
        if bind is not None:
            postgresql.ENUM(name='participantstatus').drop(bind, checkfirst=True)
        else:
            op.execute("DROP TYPE IF EXISTS participantstatus")
