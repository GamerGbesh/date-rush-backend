from enum import StrEnum


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"


class UserState(StrEnum):
    WAITING = "waiting"
    QUEUED = "queued"
    IN_GAME = "in_game"
    MATCHED = "matched"


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


