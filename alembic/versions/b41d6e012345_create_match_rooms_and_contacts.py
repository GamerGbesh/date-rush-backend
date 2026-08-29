"""create match_rooms and match_contacts tables

Revision ID: b41d6e012345
Revises: a39c5d012345
Create Date: 2026-08-28 23:59:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b41d6e012345'
down_revision: Union[str, Sequence[str], None] = 'a39c5d012345'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'match_rooms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=False),
        sa.Column(
            'state',
            sa.Enum('WAITING_FOR_CONTACTS', 'CONTACTS_EXCHANGED', 'COMPLETED', name='matchroomstate'),
            nullable=False,
            server_default='WAITING_FOR_CONTACTS',
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('match_id', name='uq_match_room_match_id'),
    )
    with op.batch_alter_table('match_rooms', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_match_rooms_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_match_rooms_match_id'), ['match_id'], unique=True)

    op.create_table(
        'match_contacts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_room_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('whatsapp', sa.String(length=100), nullable=True),
        sa.Column('snapchat', sa.String(length=100), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['match_room_id'], ['match_rooms.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('match_room_id', 'user_id', name='uq_match_room_user_contact'),
    )
    with op.batch_alter_table('match_contacts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_match_contacts_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_match_contacts_match_room_id'), ['match_room_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_match_contacts_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('match_contacts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_match_contacts_user_id'))
        batch_op.drop_index(batch_op.f('ix_match_contacts_match_room_id'))
        batch_op.drop_index(batch_op.f('ix_match_contacts_id'))
    op.drop_table('match_contacts')

    with op.batch_alter_table('match_rooms', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_match_rooms_match_id'))
        batch_op.drop_index(batch_op.f('ix_match_rooms_id'))
    op.drop_table('match_rooms')
