import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.match import Match
from app.models.user import User
from app.schemas.match import MatchDetailResponse, PartnerInfo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("/{match_id}", response_model=MatchDetailResponse)
def get_match(
    match_id: int,
    user_id: int = Query(..., description="Authenticated participant user ID"),
    db: Session = Depends(get_db),
) -> MatchDetailResponse:
    """
    Retrieve match details for an authorized matched participant.
    Provides partner summary information and match_room_id for contact exchange.
    """
    logger.debug("Match detail requested: match_id=%d, user_id=%d", match_id, user_id)
    match = db.get(Match, match_id)
    if not match:
        logger.warning("Match %d not found", match_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Match {match_id} not found.",
        )

    if user_id not in (match.challenger_id, match.audience_id):
        logger.warning("Unauthorized match access attempt: user %d for match %d", user_id, match_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User {user_id} is not authorized to view match {match_id}.",
        )

    partner_id = (
        match.audience_id if user_id == match.challenger_id else match.challenger_id
    )
    partner_user = db.get(User, partner_id)

    match_room_id = match.match_room.id if match.match_room else None

    logger.debug("Match %d retrieved: partner_id=%d, match_room_id=%s", match.id, partner_id, match_room_id)
    return MatchDetailResponse(
        id=match.id,
        room_id=match.room_id,
        status=match.status,
        created_at=match.created_at,
        partner=PartnerInfo(
            id=partner_user.id if partner_user else partner_id,
            name=partner_user.name if partner_user else "",
            gender=partner_user.gender if partner_user else "male",
        ),
        match_room_id=match_room_id,
    )

