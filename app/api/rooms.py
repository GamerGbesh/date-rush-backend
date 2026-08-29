from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.exceptions import (
    DuplicateAnswerError,
    DuplicateSessionAnswerError,
    DuplicateSessionQuestionError,
    DuplicateSessionVoteError,
    DuplicateVoteError,
    FinalSelectionUnauthorizedError,
    InvalidAnswerSubmissionError,
    InvalidFinalSelectionStateError,
    InvalidQuestionPayloadError,
    InvalidSessionStateError,
    InvalidVoterError,
    InvalidVotingStateError,
    MatchAlreadyExistsError,
    NotChallengerError,
    NotEligibleFinalistError,
    RoomNotFoundError,
    SessionNotFoundError,
    SessionUnauthorizedError,
)
from app.models.user import User
from app.schemas.answer import AnswerRead, AnswerSubmitRequest
from app.schemas.match import (
    FinalSelectionRequest,
    FinalSelectionStatusResponse,
    MatchRead,
)
from app.schemas.one_on_one import (
    OneOnOneRoomStatusResponse,
    OneOnOneSessionPublicSummary,
    OneOnOneSessionRead,
    PrivateAnswerSubmitRequest,
    PrivateQuestionSubmitRequest,
    PrivateVoteSubmitRequest,
)
from app.schemas.room import ParticipantDetail, RoomDetail, RoomRead
from app.schemas.vote import VoteRead, VoteSubmitRequest, VotingStatusResponse
from app.services.match_service import match_service
from app.services.one_on_one_service import one_on_one_service
from app.services.questioning_service import questioning_service
from app.services.room_manager import room_manager
from app.services.voting_service import voting_service

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.get("/{room_id}", response_model=RoomDetail)
def get_room(room_id: int, db: Session = Depends(get_db)) -> RoomDetail:
    """
    Retrieve a room and its currently active participants.

    Each participant entry includes the user's name and gender — useful
    for development inspection and eventual client rendering.
    """
    room = room_manager.get_room(db, room_id)
    active_participants = room_manager.get_active_participants(db, room)

    participant_details: list[ParticipantDetail] = []
    for p in active_participants:
        user = db.get(User, p.user_id)
        if user:
            participant_details.append(
                ParticipantDetail(
                    user_id=p.user_id,
                    name=user.name,
                    gender=user.gender,
                    role=p.role,
                    joined_at=p.joined_at,
                    left_at=p.left_at,
                )
            )

    return RoomDetail(
        room=RoomRead.model_validate(room),
        participants=participant_details,
    )


@router.post("/{room_id}/answers", response_model=AnswerRead, status_code=status.HTTP_201_CREATED)
async def submit_answer(
    room_id: int,
    payload: AnswerSubmitRequest,
    db: Session = Depends(get_db),
) -> AnswerRead:
    """
    Submit an answer from the challenger during public questioning.

    Validates that:
      - The room is in QUESTIONING state.
      - The user is the challenger for this room.
      - The active question for this round has not yet been answered.

    Persists the answer, broadcasts `answer_revealed`, and automatically advances
    to the next question or transitions the room to VOTING.
    """
    try:
        answer = await questioning_service.submit_answer(
            db=db,
            room_id=room_id,
            user_id=payload.user_id,
            answer_text=payload.answer,
        )
        return AnswerRead.model_validate(answer)
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except NotChallengerError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidAnswerSubmissionError, DuplicateAnswerError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/{room_id}/vote", response_model=VoteRead, status_code=status.HTTP_201_CREATED)
async def submit_vote(
    room_id: int,
    payload: VoteSubmitRequest,
    db: Session = Depends(get_db),
) -> VoteRead:
    """
    Submit an audience member's YES/NO vote on the challenger.

    Validates that:
      - The room is in VOTING state.
      - The user is an active AUDIENCE participant in this room.
      - The user has not already voted in this voting round.

    Persists the vote, broadcasts `vote_progress`, and automatically finalizes
    voting when all eligible audience votes have been received.
    """
    try:
        vote = await voting_service.submit_vote(
            db=db,
            room_id=room_id,
            voter_id=payload.user_id,
            vote_choice=payload.vote,
        )
        return VoteRead.model_validate(vote)
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidVoterError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidVotingStateError, DuplicateVoteError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/{room_id}/voting", response_model=VotingStatusResponse)
def get_voting_status(
    room_id: int,
    user_id: int | None = Query(None, description="Optional user ID to check if user has voted"),
    db: Session = Depends(get_db),
) -> VotingStatusResponse:
    """
    Retrieve aggregate voting progress for a room without revealing individual votes.
    """
    try:
        return voting_service.get_voting_status(db=db, room_id=room_id, user_id=user_id)
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# One-on-One session endpoints
# ---------------------------------------------------------------------------

@router.get("/{room_id}/one-on-one", response_model=list[OneOnOneSessionPublicSummary])
def list_one_on_one_sessions(
    room_id: int,
    db: Session = Depends(get_db),
) -> list[OneOnOneSessionPublicSummary]:
    """
    Retrieve a public summary of one-on-one sessions for a room.
    Does not leak private questions, answers, or individual votes.
    """
    sessions = one_on_one_service.get_sessions_for_room(db, room_id)
    return [OneOnOneSessionPublicSummary.model_validate(s) for s in sessions]


@router.get("/{room_id}/one-on-one/current", response_model=OneOnOneRoomStatusResponse)
def get_current_one_on_one_session(
    room_id: int,
    db: Session = Depends(get_db),
) -> OneOnOneRoomStatusResponse:
    """
    Retrieve the status of the current active 1-on-1 session and progress counters.
    """
    sessions = one_on_one_service.get_sessions_for_room(db, room_id)
    active = one_on_one_service.get_active_session(db, room_id)
    completed = sum(1 for s in sessions if s.state.value == "completed")
    return OneOnOneRoomStatusResponse(
        room_id=room_id,
        total_sessions=len(sessions),
        completed_sessions=completed,
        active_session=OneOnOneSessionRead.model_validate(active) if active else None,
    )


@router.post(
    "/{room_id}/one-on-one/{session_id}/question",
    response_model=OneOnOneSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_private_question(
    room_id: int,
    session_id: int,
    payload: PrivateQuestionSubmitRequest,
    db: Session = Depends(get_db),
) -> OneOnOneSessionRead:
    """
    Submit a free-form question from the session's active audience member.
    """
    try:
        session = await one_on_one_service.submit_question(
            db=db,
            room_id=room_id,
            session_id=session_id,
            user_id=payload.user_id,
            text=payload.text,
        )
        return OneOnOneSessionRead.model_validate(session)
    except (RoomNotFoundError, SessionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SessionUnauthorizedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidSessionStateError, DuplicateSessionQuestionError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvalidQuestionPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post(
    "/{room_id}/one-on-one/{session_id}/answer",
    response_model=OneOnOneSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_private_answer(
    room_id: int,
    session_id: int,
    payload: PrivateAnswerSubmitRequest,
    db: Session = Depends(get_db),
) -> OneOnOneSessionRead:
    """
    Submit an answer from the challenger for the active session's question.
    """
    try:
        session = await one_on_one_service.submit_answer(
            db=db,
            room_id=room_id,
            session_id=session_id,
            user_id=payload.user_id,
            text=payload.text,
        )
        return OneOnOneSessionRead.model_validate(session)
    except (RoomNotFoundError, SessionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SessionUnauthorizedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidSessionStateError, DuplicateSessionAnswerError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvalidQuestionPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post(
    "/{room_id}/one-on-one/{session_id}/vote",
    response_model=OneOnOneSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_private_vote(
    room_id: int,
    session_id: int,
    payload: PrivateVoteSubmitRequest,
    db: Session = Depends(get_db),
) -> OneOnOneSessionRead:
    """
    Submit mandatory private YES/NO vote from the audience member.
    """
    try:
        session = await one_on_one_service.submit_vote(
            db=db,
            room_id=room_id,
            session_id=session_id,
            user_id=payload.user_id,
            vote_choice=payload.vote,
        )
        return OneOnOneSessionRead.model_validate(session)
    except (RoomNotFoundError, SessionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SessionUnauthorizedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidSessionStateError, DuplicateSessionVoteError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ---------------------------------------------------------------------------
# Final selection & Match endpoints
# ---------------------------------------------------------------------------

@router.get("/{room_id}/final-selection", response_model=FinalSelectionStatusResponse)
def get_final_selection_status(
    room_id: int,
    user_id: int | None = Query(None, description="Optional user ID to check challenger view"),
    db: Session = Depends(get_db),
) -> FinalSelectionStatusResponse:
    """
    Retrieve final selection status and eligible candidates (candidates shown only to challenger).
    """
    try:
        return match_service.get_final_selection_status(db=db, room_id=room_id, user_id=user_id)
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/{room_id}/final-selection",
    response_model=MatchRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_final_selection(
    room_id: int,
    payload: FinalSelectionRequest,
    db: Session = Depends(get_db),
) -> MatchRead:
    """
    Challenger final selection: picks one surviving finalist candidate to create a Match.
    """
    try:
        match = await match_service.create_match(
            db=db,
            room_id=room_id,
            challenger_id=payload.user_id,
            candidate_id=payload.candidate_id,
        )
        return MatchRead.model_validate(match)
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except FinalSelectionUnauthorizedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidFinalSelectionStateError, NotEligibleFinalistError, MatchAlreadyExistsError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
