"""add room_questions table, updated_at to questions, and answer constraints

Revision ID: d94b2a8e3123
Revises: c83a1b7e4112
Create Date: 2026-08-28 22:48:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd94b2a8e3123'
down_revision: Union[str, Sequence[str], None] = 'c83a1b7e4112'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

questionphase_enum = postgresql.ENUM('PUBLIC', 'PRIVATE', name='questionphase', create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    context = op.get_context()
    is_postgres = context.dialect.name == 'postgresql'
    bind = op.get_bind()

    if is_postgres:
        if bind is not None:
            postgresql.ENUM('PUBLIC', 'PRIVATE', name='questionphase').create(bind, checkfirst=True)
        else:
            op.execute("CREATE TYPE questionphase AS ENUM ('PUBLIC', 'PRIVATE')")

    phase_col = questionphase_enum if is_postgres else sa.Enum('PUBLIC', 'PRIVATE', name='questionphase')

    # 1. Create room_questions table
    op.create_table(
        'room_questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('room_id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('phase', phase_col, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['question_id'], ['questions.id']),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('room_id', 'position', name='uq_room_question_position'),
        sa.UniqueConstraint('room_id', 'question_id', name='uq_room_question_unique'),
    )
    op.create_index(op.f('ix_room_questions_id'), 'room_questions', ['id'], unique=False)
    op.create_index(op.f('ix_room_questions_room_id'), 'room_questions', ['room_id'], unique=False)

    # 2. Add updated_at column to questions table
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

    # 3. Add unique constraint to answers table
    with op.batch_alter_table('answers', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_answer_per_room_question', ['room_id', 'question_id', 'user_id']
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('answers', schema=None) as batch_op:
        batch_op.drop_constraint('uq_answer_per_room_question', type_='unique')

    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.drop_column('updated_at')

    op.drop_index(op.f('ix_room_questions_room_id'), table_name='room_questions')
    op.drop_index(op.f('ix_room_questions_id'), table_name='room_questions')
    op.drop_table('room_questions')

    context = op.get_context()
    if context.dialect.name == 'postgresql':
        bind = op.get_bind()
        if bind is not None:
            postgresql.ENUM(name='questionphase').drop(bind, checkfirst=True)
        else:
            op.execute("DROP TYPE IF EXISTS questionphase")
