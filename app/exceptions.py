class DateRushError(Exception):
    """Base domain exception."""


class InvalidRoomTransitionError(DateRushError):
    """Raised when an illegal room state transition is attempted."""

    def __init__(self, from_state: str, to_state: str, message: str | None = None) -> None:
        self.from_state = from_state
        self.to_state = to_state
        self.message = message or f"Invalid room transition: {from_state} → {to_state}"
        super().__init__(self.message)


# Alias as requested in prompt section 4
InvalidRoomTransition = InvalidRoomTransitionError


class RoomNotFoundError(DateRushError):
    """Raised when a requested room does not exist."""

    def __init__(self, room_id: int) -> None:
        self.room_id = room_id
        super().__init__(f"Room {room_id} not found.")


class UserNotFoundError(DateRushError):
    """Raised when a requested user does not exist."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(f"User {user_id} not found.")


class ParticipantNotFoundError(DateRushError):
    """Raised when a user is not a participant in a given room."""

    def __init__(self, room_id: int, user_id: int) -> None:
        self.room_id = room_id
        self.user_id = user_id
        super().__init__(f"User {user_id} is not an active participant in room {room_id}.")


class QuestionNotFoundError(DateRushError):
    """Raised when a requested question does not exist."""

    def __init__(self, question_id: int) -> None:
        self.question_id = question_id
        super().__init__(f"Question {question_id} not found.")


class InsufficientQuestionsError(DateRushError):
    """Raised when not enough eligible active questions exist to create a room."""

    def __init__(self, required: int, available: int, gender: str) -> None:
        self.required = required
        self.available = available
        self.gender = gender
        super().__init__(
            f"Insufficient active questions for gender '{gender}': required {required}, available {available}."
        )


class NotChallengerError(DateRushError):
    """Raised when a non-challenger user attempts to submit an answer."""

    def __init__(self, room_id: int, user_id: int) -> None:
        self.room_id = room_id
        self.user_id = user_id
        super().__init__(f"User {user_id} is not the challenger in room {room_id}.")


class InvalidAnswerSubmissionError(DateRushError):
    """Raised when an answer submission is invalid (e.g. wrong room state or no active question)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class DuplicateAnswerError(DateRushError):
    """Raised when an answer has already been submitted for the current question."""

    def __init__(self, room_id: int, question_id: int, user_id: int) -> None:
        self.room_id = room_id
        self.question_id = question_id
        self.user_id = user_id
        super().__init__(
            f"User {user_id} has already answered question {question_id} in room {room_id}."
        )


class InvalidVoterError(DateRushError):
    """Raised when a user is ineligible to vote (e.g. challenger, outsider, or eliminated)."""

    def __init__(self, room_id: int, user_id: int, reason: str) -> None:
        self.room_id = room_id
        self.user_id = user_id
        self.reason = reason
        super().__init__(f"User {user_id} cannot vote in room {room_id}: {reason}")


class InvalidVotingStateError(DateRushError):
    """Raised when a vote is submitted while the room is not in VOTING state."""

    def __init__(self, room_id: int, current_state: str) -> None:
        self.room_id = room_id
        self.current_state = current_state
        super().__init__(
            f"Cannot vote: room {room_id} is in state '{current_state}', not 'voting'."
        )


class DuplicateVoteError(DateRushError):
    """Raised when an audience member attempts to vote twice in the same round."""

    def __init__(self, room_id: int, round_number: int, user_id: int) -> None:
        self.room_id = room_id
        self.round_number = round_number
        self.user_id = user_id
        super().__init__(
            f"User {user_id} has already voted in round {round_number} for room {room_id}."
        )


