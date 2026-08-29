from enum import StrEnum


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"


class UserState(StrEnum):
    WAITING = "waiting"
    QUEUED = "queued"
    IN_GAME = "in_game"
    MATCHED = "matched"
    COMPLETED = "completed"


class PlayerRole(StrEnum):
    CHALLENGER = "challenger"
    AUDIENCE = "audience"


class RoomState(StrEnum):
    WAITING = "waiting"
    READY = "ready"
    INTRO = "intro"
    QUESTIONING = "questioning"
    VOTING = "voting"
    ELIMINATION = "elimination"
    ONE_ON_ONE = "one_on_one"
    FINAL_SELECTION = "final_selection"
    FINAL = "final"
    MATCHED = "matched"
    COMPLETED = "completed"


class QuestionTarget(StrEnum):
    ANY = "any"
    MALE = "male"
    FEMALE = "female"


class QuestionPhase(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class VoteChoice(StrEnum):
    YES = "yes"
    NO = "no"


class ParticipantStatus(StrEnum):
    ACTIVE = "active"
    ELIMINATED = "eliminated"
    FINALIST = "finalist"
    SELECTED = "selected"


class OneOnOneSessionState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ANSWERED = "answered"
    VOTING = "voting"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMPLETED = "completed"


class VotePhase(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class MatchStatus(StrEnum):
    CREATED = "created"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MatchRoomState(StrEnum):
    WAITING_FOR_CONTACTS = "waiting_for_contacts"
    CONTACTS_EXCHANGED = "contacts_exchanged"
    COMPLETED = "completed"





