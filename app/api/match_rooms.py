from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import MatchRoomState
from app.exceptions import (
    DuplicateContactSubmissionError,
    InvalidContactPayloadError,
    InvalidMatchRoomStateError,
    MatchRoomNotFoundError,
    MatchRoomUnauthorizedError,
)
from app.models.match_contact import MatchContact
from app.schemas.match_room import (
    ContactSubmitRequest,
    MatchRoomContactsResponse,
    MatchRoomDetailResponse,
)
from app.services.match_room_service import match_room_service

router = APIRouter(prefix="/match-rooms", tags=["match-rooms"])


@router.get("/{match_room_id}", response_model=MatchRoomDetailResponse)
def get_match_room(
    match_room_id: int,
    user_id: int = Query(..., description="Authenticated participant user ID"),
    db: Session = Depends(get_db),
) -> MatchRoomDetailResponse:
    """
    Retrieve match room status for an authorized matched participant.
    """
    try:
        match_room = match_room_service.get_match_room_for_user(
            db=db, match_room_id=match_room_id, user_id=user_id
        )
        my_contact = db.execute(
            select(MatchContact).where(
                MatchContact.match_room_id == match_room_id,
                MatchContact.user_id == user_id,
            )
        ).scalar_one_or_none()

        partner_available = match_room.state in (
            MatchRoomState.CONTACTS_EXCHANGED,
            MatchRoomState.COMPLETED,
        )

        return MatchRoomDetailResponse(
            id=match_room.id,
            match_id=match_room.match_id,
            state=match_room.state,
            my_contact_submitted=my_contact is not None,
            partner_contact_available=partner_available,
            created_at=match_room.created_at,
            completed_at=match_room.completed_at,
        )
    except MatchRoomNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except MatchRoomUnauthorizedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))



@router.get("/{match_room_id}/contacts", response_model=MatchRoomContactsResponse)
def get_contacts_status(
    match_room_id: int,
    user_id: int = Query(..., description="Authenticated participant user ID"),
    db: Session = Depends(get_db),
) -> MatchRoomContactsResponse:
    """
    Retrieve contact exchange status for a participant in a private match room.
    Partner contact details are only revealed after both participants have submitted.
    """
    try:
        return match_room_service.get_contacts_status(
            db=db, match_room_id=match_room_id, user_id=user_id
        )
    except MatchRoomNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except MatchRoomUnauthorizedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/{match_room_id}/contacts",
    response_model=MatchRoomContactsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_contact(
    match_room_id: int,
    payload: ContactSubmitRequest,
    db: Session = Depends(get_db),
) -> MatchRoomContactsResponse:
    """
    Submit contact information (WhatsApp, Snapchat, or both) for a matched participant.
    Once both participants submit, contact details are automatically exchanged and users completed.
    """
    try:
        await match_room_service.submit_contact(
            db=db,
            match_room_id=match_room_id,
            user_id=payload.user_id,
            whatsapp=payload.whatsapp,
            snapchat=payload.snapchat,
        )
        return match_room_service.get_contacts_status(
            db=db, match_room_id=match_room_id, user_id=payload.user_id
        )
    except MatchRoomNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except MatchRoomUnauthorizedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (InvalidMatchRoomStateError, DuplicateContactSubmissionError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvalidContactPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        )
