import logging

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
from app.schemas.timer import TimerStatusResponse
from app.schemas.vote import VoteRead, VoteSubmitRequest, VotingStatusResponse
from app.services.match_service import match_service
from app.services.one_on_one_service import one_on_one_service
from app.services.questioning_service import questioning_service
from app.services.room_manager import room_manager
from app.services.timer_service import timer_service
from app.services.voting_service import voting_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.get("/{room_id}", response_model=RoomDetail)
def get_room(room_id: int, db: Session = Depends(get_db)) -> RoomDetail:
    """
    Retrieve a room and its currently active participants.

    Each participant entry includes the user's name and gender — useful
    for development inspection and eventual client rendering.
    """
    logger.debug("Fetching room detail for room_id=%d", room_id)
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


@router.get("/{room_id}/timer", response_model=TimerStatusResponse)
def get_room_timer(room_id: int, db: Session = Depends(get_db)) -> TimerStatusResponse:
    """
    Retrieve the current countdown timer status for a room.
    Used by frontend clients on page load or refresh to initialize and run a local countdown clock.
    """
    logger.debug("Fetching countdown timer status for room_id=%d", room_id)
    room = room_manager.get_room(db, room_id)
    timer_info = timer_service.get_timer_info(room.id)
    return TimerStatusResponse(**timer_info)


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
    logger.info("Challenger submitting answer: room_id=%d, user_id=%d", room_id, payload.user_id)
    try:
        answer = await questioning_service.submit_answer(
            db=db,
            room_id=room_id,
            user_id=payload.user_id,
            answer_text=payload.answer,
        )
        logger.info("Answer submitted successfully: room_id=%d, answer_id=%d", room_id, answer.id)
        return AnswerRead.model_validate(answer)
    except RoomNotFoundError as exc:
        logger.warning("Answer submission failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except NotChallengerError as exc:
        logger.warning("Answer submission rejected: %s", exc)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidAnswerSubmissionError, DuplicateAnswerError) as exc:
        logger.warning("Answer submission conflict: %s", exc)
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
    logger.info("Audience vote submission: room_id=%d, voter_id=%d, choice=%s", room_id, payload.user_id, payload.vote.value)
    try:
        vote = await voting_service.submit_vote(
            db=db,
            room_id=room_id,
            voter_id=payload.user_id,
            vote_choice=payload.vote,
        )
        logger.info("Vote accepted: room_id=%d, vote_id=%d", room_id, vote.id)
        return VoteRead.model_validate(vote)
    except RoomNotFoundError as exc:
        logger.warning("Vote submission failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidVoterError as exc:
        logger.warning("Vote submission rejected: %s", exc)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidVotingStateError, DuplicateVoteError) as exc:
        logger.warning("Vote submission conflict: %s", exc)
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
    logger.debug("Voting status requested: room_id=%d, user_id=%s", room_id, user_id)
    try:
        return voting_service.get_voting_status(db=db, room_id=room_id, user_id=user_id)
    except RoomNotFoundError as exc:
        logger.warning("Get voting status failed: %s", exc)
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
    logger.debug("Listing 1-on-1 sessions for room_id=%d", room_id)
    sessions = one_on_one_service.get_sessions_for_room(db, room_id)
    return [OneOnOneSessionPublicSummary.model_validate(s) for s in sessions]


@router.get("/{room_id}/one-on-one/current", response_model=OneOnOneRoomStatusResponse)
def get_current_one_on_one_session(
    room_id: int,
    user_id: int | None = None,
    db: Session = Depends(get_db),
) -> OneOnOneRoomStatusResponse:
    """
    Retrieve the status of the current active 1-on-1 session and progress counters.
    If user_id is provided, only participants of the active session see private details.
    """
    logger.debug("Fetching current 1-on-1 session: room_id=%d, user_id=%s", room_id, user_id)
    sessions = one_on_one_service.get_sessions_for_room(db, room_id)
    active = one_on_one_service.get_active_session(db, room_id)
    completed = sum(1 for s in sessions if s.state.value == "completed")

    active_read = None
    if active:
        if user_id is not None and user_id not in (active.challenger_id, active.audience_id):
            active_read = OneOnOneSessionRead(
                id=active.id,
                room_id=active.room_id,
                audience_id=active.audience_id,
                challenger_id=active.challenger_id,
                sequence=active.sequence,
                state=active.state,
                question=None,
                answer=None,
                vote=None,
                started_at=active.started_at,
                answered_at=active.answered_at,
                voted_at=active.voted_at,
                completed_at=active.completed_at,
                created_at=active.created_at,
            )
        else:
            active_read = OneOnOneSessionRead.model_validate(active)

    return OneOnOneRoomStatusResponse(
        room_id=room_id,
        total_sessions=len(sessions),
        completed_sessions=completed,
        active_session=active_read,
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
    logger.info("Submitting 1-on-1 private question: room_id=%d, session_id=%d, user_id=%d", room_id, session_id, payload.user_id)
    try:
        session = await one_on_one_service.submit_question(
            db=db,
            room_id=room_id,
            session_id=session_id,
            user_id=payload.user_id,
            text=payload.text,
        )
        logger.info("1-on-1 private question saved: session_id=%d", session.id)
        return OneOnOneSessionRead.model_validate(session)
    except (RoomNotFoundError, SessionNotFoundError) as exc:
        logger.warning("1-on-1 question failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SessionUnauthorizedError as exc:
        logger.warning("1-on-1 question unauthorized: %s", exc)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidSessionStateError, DuplicateSessionQuestionError) as exc:
        logger.warning("1-on-1 question state conflict: %s", exc)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvalidQuestionPayloadError as exc:
        logger.warning("1-on-1 question payload invalid: %s", exc)
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
    logger.info("Submitting 1-on-1 private answer: room_id=%d, session_id=%d, user_id=%d", room_id, session_id, payload.user_id)
    try:
        session = await one_on_one_service.submit_answer(
            db=db,
            room_id=room_id,
            session_id=session_id,
            user_id=payload.user_id,
            text=payload.text,
        )
        logger.info("1-on-1 private answer saved: session_id=%d", session.id)
        return OneOnOneSessionRead.model_validate(session)
    except (RoomNotFoundError, SessionNotFoundError) as exc:
        logger.warning("1-on-1 answer failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SessionUnauthorizedError as exc:
        logger.warning("1-on-1 answer unauthorized: %s", exc)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidSessionStateError, DuplicateSessionAnswerError) as exc:
        logger.warning("1-on-1 answer state conflict: %s", exc)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvalidQuestionPayloadError as exc:
        logger.warning("1-on-1 answer payload invalid: %s", exc)
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
    logger.info("Submitting 1-on-1 private vote: room_id=%d, session_id=%d, user_id=%d, choice=%s", room_id, session_id, payload.user_id, payload.vote.value)
    try:
        session = await one_on_one_service.submit_vote(
            db=db,
            room_id=room_id,
            session_id=session_id,
            user_id=payload.user_id,
            vote_choice=payload.vote,
        )
        logger.info("1-on-1 private vote saved: session_id=%d, state=%s", session.id, session.state.value)
        return OneOnOneSessionRead.model_validate(session)
    except (RoomNotFoundError, SessionNotFoundError) as exc:
        logger.warning("1-on-1 vote failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SessionUnauthorizedError as exc:
        logger.warning("1-on-1 vote unauthorized: %s", exc)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidSessionStateError, DuplicateSessionVoteError) as exc:
        logger.warning("1-on-1 vote state conflict: %s", exc)
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
    logger.debug("Final selection status requested: room_id=%d, user_id=%s", room_id, user_id)
    try:
        return match_service.get_final_selection_status(db=db, room_id=room_id, user_id=user_id)
    except RoomNotFoundError as exc:
        logger.warning("Get final selection status failed: %s", exc)
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
    logger.info("Challenger final selection submitted: room_id=%d, challenger_id=%d, candidate_id=%d", room_id, payload.user_id, payload.candidate_id)
    try:
        match = await match_service.create_match(
            db=db,
            room_id=room_id,
            challenger_id=payload.user_id,
            candidate_id=payload.candidate_id,
        )
        logger.info("Match created successfully via final selection: match_id=%d", match.id)
        return MatchRead.model_validate(match)
    except RoomNotFoundError as exc:
        logger.warning("Final selection failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except FinalSelectionUnauthorizedError as exc:
        logger.warning("Final selection unauthorized: %s", exc)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidFinalSelectionStateError, NotEligibleFinalistError, MatchAlreadyExistsError) as exc:
        logger.warning("Final selection conflict: %s", exc)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

