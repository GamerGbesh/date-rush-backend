from app.enums import Gender, PlayerRole, QuestionTarget, RoomState, UserState


class TestGender:
    def test_values(self):
        assert Gender.MALE == "male"
        assert Gender.FEMALE == "female"

    def test_is_str(self):
        assert isinstance(Gender.MALE, str)


class TestUserState:
    def test_all_states_present(self):
        expected = {"waiting", "queued", "in_game", "matched", "completed"}
        assert {s.value for s in UserState} == expected

    def test_in_game_value(self):
        assert UserState.IN_GAME == "in_game"


class TestMatchRoomState:
    def test_values(self):
        from app.enums import MatchRoomState
        assert MatchRoomState.WAITING_FOR_CONTACTS == "waiting_for_contacts"
        assert MatchRoomState.CONTACTS_EXCHANGED == "contacts_exchanged"
        assert MatchRoomState.COMPLETED == "completed"



class TestPlayerRole:
    def test_values(self):
        assert PlayerRole.CHALLENGER == "challenger"
        assert PlayerRole.AUDIENCE == "audience"


class TestRoomState:
    def test_all_states_present(self):
        expected = {
            "waiting", "ready", "intro", "questioning",
            "voting", "elimination", "one_on_one", "final_selection", "final", "matched", "completed",
        }
        assert {s.value for s in RoomState} == expected


class TestQuestionTarget:
    def test_values(self):
        assert QuestionTarget.ANY == "any"
        assert QuestionTarget.MALE == "male"
        assert QuestionTarget.FEMALE == "female"


class TestVoteChoice:
    def test_values(self):
        from app.enums import VoteChoice
        assert VoteChoice.YES == "yes"
        assert VoteChoice.NO == "no"


class TestParticipantStatus:
    def test_values(self):
        from app.enums import ParticipantStatus
        assert ParticipantStatus.ACTIVE == "active"
        assert ParticipantStatus.ELIMINATED == "eliminated"
        assert ParticipantStatus.FINALIST == "finalist"
        assert ParticipantStatus.SELECTED == "selected"

