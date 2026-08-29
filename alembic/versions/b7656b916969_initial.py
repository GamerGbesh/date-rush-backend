"""initial

Revision ID: b7656b916969
Revises: 
Create Date: 2026-08-28 21:55:17.532220

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b7656b916969'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

questiontarget_enum = postgresql.ENUM('ANY', 'MALE', 'FEMALE', name='questiontarget', create_type=False)
gender_enum = postgresql.ENUM('MALE', 'FEMALE', name='gender', create_type=False)
userstate_enum = postgresql.ENUM('WAITING', 'QUEUED', 'IN_GAME', 'MATCHED', name='userstate', create_type=False)
roomstate_enum = postgresql.ENUM('WAITING', 'READY', 'INTRO', 'QUESTIONING', 'VOTING', 'ELIMINATION', 'FINAL', 'MATCHED', 'COMPLETED', name='roomstate', create_type=False)
playerrole_enum = postgresql.ENUM('CHALLENGER', 'AUDIENCE', name='playerrole', create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    context = op.get_context()
    is_postgres = context.dialect.name == 'postgresql'
    bind = op.get_bind()

    if is_postgres:
        if bind is not None:
            postgresql.ENUM('ANY', 'MALE', 'FEMALE', name='questiontarget').create(bind, checkfirst=True)
            postgresql.ENUM('MALE', 'FEMALE', name='gender').create(bind, checkfirst=True)
            postgresql.ENUM('WAITING', 'QUEUED', 'IN_GAME', 'MATCHED', name='userstate').create(bind, checkfirst=True)
            postgresql.ENUM('WAITING', 'READY', 'INTRO', 'QUESTIONING', 'VOTING', 'ELIMINATION', 'FINAL', 'MATCHED', 'COMPLETED', name='roomstate').create(bind, checkfirst=True)
            postgresql.ENUM('CHALLENGER', 'AUDIENCE', name='playerrole').create(bind, checkfirst=True)
        else:
            op.execute("CREATE TYPE questiontarget AS ENUM ('ANY', 'MALE', 'FEMALE')")
            op.execute("CREATE TYPE gender AS ENUM ('MALE', 'FEMALE')")
            op.execute("CREATE TYPE userstate AS ENUM ('WAITING', 'QUEUED', 'IN_GAME', 'MATCHED')")
            op.execute("CREATE TYPE roomstate AS ENUM ('WAITING', 'READY', 'INTRO', 'QUESTIONING', 'VOTING', 'ELIMINATION', 'FINAL', 'MATCHED', 'COMPLETED')")
            op.execute("CREATE TYPE playerrole AS ENUM ('CHALLENGER', 'AUDIENCE')")

    target_gender_col = questiontarget_enum if is_postgres else sa.Enum('ANY', 'MALE', 'FEMALE', name='questiontarget')
    gender_col = gender_enum if is_postgres else sa.Enum('MALE', 'FEMALE', name='gender')
    userstate_col = userstate_enum if is_postgres else sa.Enum('WAITING', 'QUEUED', 'IN_GAME', 'MATCHED', name='userstate')
    roomstate_col = roomstate_enum if is_postgres else sa.Enum('WAITING', 'READY', 'INTRO', 'QUESTIONING', 'VOTING', 'ELIMINATION', 'FINAL', 'MATCHED', 'COMPLETED', name='roomstate')
    playerrole_col = playerrole_enum if is_postgres else sa.Enum('CHALLENGER', 'AUDIENCE', name='playerrole')

    op.create_table('questions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('text', sa.String(length=500), nullable=False),
    sa.Column('target_gender', target_gender_col, nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_questions_id'), ['id'], unique=False)

    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('gender', gender_col, nullable=False),
    sa.Column('state', userstate_col, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_id'), ['id'], unique=False)

    op.create_table('rooms',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('state', roomstate_col, nullable=False),
    sa.Column('challenger_id', sa.Integer(), nullable=True),
    sa.Column('challenger_gender', gender_col, nullable=True),
    sa.Column('current_question_id', sa.Integer(), nullable=True),
    sa.Column('current_round', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['challenger_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['current_question_id'], ['questions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('rooms', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rooms_id'), ['id'], unique=False)

    op.create_table('answers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('room_id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('answer', sa.String(length=1000), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['question_id'], ['questions.id'], ),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('answers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_answers_id'), ['id'], unique=False)

    op.create_table('matches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('room_id', sa.Integer(), nullable=False),
    sa.Column('challenger_id', sa.Integer(), nullable=False),
    sa.Column('audience_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['audience_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['challenger_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('matches', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_matches_id'), ['id'], unique=False)

    op.create_table('room_participants',
    sa.Column('room_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role', playerrole_col, nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('left_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('room_id', 'user_id')
    )
    op.create_table('votes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('room_id', sa.Integer(), nullable=False),
    sa.Column('round', sa.Integer(), nullable=False),
    sa.Column('voter_id', sa.Integer(), nullable=False),
    sa.Column('vote', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
    sa.ForeignKeyConstraint(['voter_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('room_id', 'round', 'voter_id', name='uq_vote_per_round')
    )
    with op.batch_alter_table('votes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_votes_id'), ['id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('votes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_votes_id'))

    op.drop_table('votes')
    op.drop_table('room_participants')
    with op.batch_alter_table('matches', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_matches_id'))

    op.drop_table('matches')
    with op.batch_alter_table('answers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_answers_id'))

    op.drop_table('answers')
    with op.batch_alter_table('rooms', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rooms_id'))

    op.drop_table('rooms')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_id'))

    op.drop_table('users')
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_questions_id'))

    op.drop_table('questions')

    context = op.get_context()
    if context.dialect.name == 'postgresql':
        bind = op.get_bind()
        if bind is not None:
            postgresql.ENUM(name='playerrole').drop(bind, checkfirst=True)
            postgresql.ENUM(name='roomstate').drop(bind, checkfirst=True)
            postgresql.ENUM(name='userstate').drop(bind, checkfirst=True)
            postgresql.ENUM(name='gender').drop(bind, checkfirst=True)
            postgresql.ENUM(name='questiontarget').drop(bind, checkfirst=True)
        else:
            op.execute("DROP TYPE IF EXISTS playerrole")
            op.execute("DROP TYPE IF EXISTS roomstate")
            op.execute("DROP TYPE IF EXISTS userstate")
            op.execute("DROP TYPE IF EXISTS gender")
            op.execute("DROP TYPE IF EXISTS questiontarget")
