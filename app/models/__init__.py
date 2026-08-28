"""
Models package — import all models here so that Base.metadata is fully
populated when database.init_db() calls Base.metadata.create_all().
"""

from app.models.answer import Answer
from app.models.match import Match
from app.models.question import Question
from app.models.room import Room, RoomParticipant
from app.models.room_question import RoomQuestion
from app.models.room_state_history import RoomStateHistory
from app.models.user import User
from app.models.vote import Vote

__all__ = [
    "Answer",
    "Match",
    "Question",
    "Room",
    "RoomParticipant",
    "RoomQuestion",
    "RoomStateHistory",
    "User",
    "Vote",
]
