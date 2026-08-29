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


class SessionNotFoundError(DateRushError):
    """Raised when a one-on-one session is not found."""

    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(f"One-on-one session {session_id} not found.")


class SessionUnauthorizedError(DateRushError):
    """Raised when an unauthorized user attempts to access or act on a private session."""

    def __init__(self, session_id: int, user_id: int, reason: str = "Unauthorized") -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.reason = reason
        super().__init__(f"User {user_id} unauthorized for session {session_id}: {reason}")


class InvalidSessionStateError(DateRushError):
    """Raised when an action is attempted on a session in an invalid state."""

    def __init__(self, session_id: int, current_state: str, action: str) -> None:
        self.session_id = session_id
        self.current_state = current_state
        self.action = action
        super().__init__(
            f"Cannot perform '{action}' on session {session_id} in state '{current_state}'."
        )


class DuplicateSessionQuestionError(DateRushError):
    """Raised when a question is submitted more than once in a session."""

    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(f"Question has already been submitted for session {session_id}.")


class DuplicateSessionAnswerError(DateRushError):
    """Raised when an answer is submitted more than once in a session."""

    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(f"Answer has already been submitted for session {session_id}.")


class DuplicateSessionVoteError(DateRushError):
    """Raised when a vote is submitted more than once in a session."""

    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(f"Vote has already been submitted for session {session_id}.")


class InvalidQuestionPayloadError(DateRushError):
    """Raised when a private question payload fails validation (e.g. empty or too long)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Invalid private question: {reason}")


class NotEligibleFinalistError(DateRushError):
    """Raised when a selected candidate is not an eligible FINALIST in the room."""

    def __init__(self, room_id: int, candidate_id: int, reason: str) -> None:
        self.room_id = room_id
        self.candidate_id = candidate_id
        self.reason = reason
        super().__init__(
            f"Candidate {candidate_id} is not an eligible finalist in room {room_id}: {reason}"
        )


class FinalSelectionUnauthorizedError(DateRushError):
    """Raised when a non-challenger user attempts to submit the final selection."""

    def __init__(self, room_id: int, user_id: int) -> None:
        self.room_id = room_id
        self.user_id = user_id
        super().__init__(
            f"User {user_id} is not authorized to make final selection for room {room_id} (not challenger)."
        )


class InvalidFinalSelectionStateError(DateRushError):
    """Raised when final selection is submitted while the room is not in FINAL_SELECTION state."""

    def __init__(self, room_id: int, current_state: str) -> None:
        self.room_id = room_id
        self.current_state = current_state
        super().__init__(
            f"Cannot make final selection: room {room_id} is in state '{current_state}', not 'final_selection'."
        )


class MatchAlreadyExistsError(DateRushError):
    """Raised when a match already exists for a room."""

    def __init__(self, room_id: int) -> None:
        self.room_id = room_id
        super().__init__(f"A match already exists for room {room_id}.")


class MatchRoomNotFoundError(DateRushError):
    """Raised when a requested match room is not found."""

    def __init__(self, match_room_id: int) -> None:
        self.match_room_id = match_room_id
        super().__init__(f"Match room {match_room_id} not found.")


class MatchRoomUnauthorizedError(DateRushError):
    """Raised when a user is not an authorized participant in the match room."""

    def __init__(self, match_room_id: int, user_id: int) -> None:
        self.match_room_id = match_room_id
        self.user_id = user_id
        super().__init__(
            f"User {user_id} is not authorized to access match room {match_room_id}."
        )


class InvalidMatchRoomStateError(DateRushError):
    """Raised when contact submission is attempted on a non-waiting match room."""

    def __init__(self, match_room_id: int, current_state: str) -> None:
        self.match_room_id = match_room_id
        self.current_state = current_state
        super().__init__(
            f"Cannot submit contact details: match room {match_room_id} is in state '{current_state}', not 'waiting_for_contacts'."
        )


class DuplicateContactSubmissionError(DateRushError):
    """Raised when a user attempts to submit contact details more than once."""

    def __init__(self, match_room_id: int, user_id: int) -> None:
        self.match_room_id = match_room_id
        self.user_id = user_id
        super().__init__(
            f"User {user_id} has already submitted contact details for match room {match_room_id}."
        )


class InvalidContactPayloadError(DateRushError):
    """Raised when contact details validation fails (both empty or invalid)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Invalid contact submission: {reason}")


class UserAlreadyCompletedEventError(DateRushError):
    """Raised when a completed user attempts to join a queue for the event."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(
            f"User {user_id} has already completed the event and cannot re-enter the queue."
        )





