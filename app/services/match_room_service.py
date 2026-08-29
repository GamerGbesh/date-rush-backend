"""
MatchRoomService — manages private post-match contact collection, validation,
automatic contact exchange, user event completion, and WebSocket privacy.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import MatchRoomState, MatchStatus, UserState
from app.exceptions import (
    DuplicateContactSubmissionError,
    InvalidContactPayloadError,
    InvalidMatchRoomStateError,
    MatchRoomNotFoundError,
    MatchRoomUnauthorizedError,
)
from app.models.match import Match
from app.models.match_contact import MatchContact
from app.models.match_room import MatchRoom
from app.models.user import User
from app.schemas.match_room import MatchRoomContactsResponse, PartnerContactRead
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

_match_room_locks: dict[int, asyncio.Lock] = {}


def _get_match_room_lock(match_room_id: int) -> asyncio.Lock:
    if match_room_id not in _match_room_locks:
        _match_room_locks[match_room_id] = asyncio.Lock()
    return _match_room_locks[match_room_id]


class MatchRoomService:
    """Service managing post-match contact exchange lifecycle."""

    def create_match_room(self, db: Session, match_id: int) -> MatchRoom:
        """Create a new MatchRoom in WAITING_FOR_CONTACTS state."""
        match_room = MatchRoom(
            match_id=match_id,
            state=MatchRoomState.WAITING_FOR_CONTACTS,
            created_at=datetime.now(timezone.utc),
        )
        db.add(match_room)
        db.commit()
        db.refresh(match_room)
        logger.info("Created MatchRoom %d for match %d", match_room.id, match_id)
        return match_room

    def get_match_room(self, db: Session, match_room_id: int) -> MatchRoom:
        """Retrieve match room or raise MatchRoomNotFoundError."""
        match_room = db.get(MatchRoom, match_room_id)
        if not match_room:
            raise MatchRoomNotFoundError(match_room_id)
        return match_room

    def get_match_room_for_user(
        self, db: Session, match_room_id: int, user_id: int
    ) -> MatchRoom:
        """Retrieve match room and verify user is one of the two matched participants."""
        match_room = self.get_match_room(db, match_room_id)
        match = match_room.match
        if not match or (user_id != match.challenger_id and user_id != match.audience_id):
            raise MatchRoomUnauthorizedError(match_room_id, user_id)
        return match_room

    def get_contacts_status(
        self, db: Session, match_room_id: int, user_id: int
    ) -> MatchRoomContactsResponse:
        """
        Retrieve contact exchange status for a participant.
        Partner contact info is returned ONLY if state is CONTACTS_EXCHANGED or COMPLETED.
        """
        match_room = self.get_match_room_for_user(db, match_room_id, user_id)
        match = match_room.match

        my_contact = db.execute(
            select(MatchContact).where(
                MatchContact.match_room_id == match_room_id,
                MatchContact.user_id == user_id,
            )
        ).scalar_one_or_none()

        partner_id = (
            match.audience_id if user_id == match.challenger_id else match.challenger_id
        )

        partner_info: PartnerContactRead | None = None
        if match_room.state in (
            MatchRoomState.CONTACTS_EXCHANGED,
            MatchRoomState.COMPLETED,
        ):
            partner_contact = db.execute(
                select(MatchContact).where(
                    MatchContact.match_room_id == match_room_id,
                    MatchContact.user_id == partner_id,
                )
            ).scalar_one_or_none()

            partner_user = db.get(User, partner_id)
            if partner_user and partner_contact:
                partner_info = PartnerContactRead(
                    name=partner_user.name,
                    whatsapp=partner_contact.whatsapp,
                    snapchat=partner_contact.snapchat,
                )

        return MatchRoomContactsResponse(
            state=match_room.state,
            submitted=my_contact is not None,
            partner=partner_info,
        )

    async def submit_contact(
        self,
        db: Session,
        match_room_id: int,
        user_id: int,
        whatsapp: str | None,
        snapchat: str | None,
    ) -> MatchContact:
        """
        Submit WhatsApp and/or Snapchat for a participant.
        Atomically triggers contact exchange if both participants have submitted.
        """
        lock = _get_match_room_lock(match_room_id)
        async with lock:
            match_room = self.get_match_room_for_user(db, match_room_id, user_id)
            match = match_room.match

            # 1. State check
            if match_room.state != MatchRoomState.WAITING_FOR_CONTACTS:
                raise InvalidMatchRoomStateError(
                    match_room_id=match_room_id,
                    current_state=match_room.state.value,
                )

            # 2. Validation & normalization
            w_clean = whatsapp.strip() if whatsapp and whatsapp.strip() else None
            s_clean = snapchat.strip() if snapchat and snapchat.strip() else None

            if not w_clean and not s_clean:
                raise InvalidContactPayloadError(
                    "At least one contact method (WhatsApp or Snapchat) must be provided."
                )

            max_len = settings.CONTACT_MAX_LENGTH
            if w_clean and len(w_clean) > max_len:
                raise InvalidContactPayloadError(
                    f"WhatsApp handle exceeds maximum length of {max_len} characters."
                )
            if s_clean and len(s_clean) > max_len:
                raise InvalidContactPayloadError(
                    f"Snapchat handle exceeds maximum length of {max_len} characters."
                )

            # 3. Duplicate check
            existing = db.execute(
                select(MatchContact).where(
                    MatchContact.match_room_id == match_room_id,
                    MatchContact.user_id == user_id,
                )
            ).scalar_one_or_none()

            if existing:
                raise DuplicateContactSubmissionError(match_room_id, user_id)

            # 4. Save contact
            now = datetime.now(timezone.utc)
            contact = MatchContact(
                match_room_id=match_room_id,
                user_id=user_id,
                whatsapp=w_clean,
                snapchat=s_clean,
                submitted_at=now,
            )
            db.add(contact)
            db.commit()
            db.refresh(contact)
            logger.info(
                "Contact submitted for match room %d by user %d (has_whatsapp=%s, has_snapchat=%s)",
                match_room_id,
                user_id,
                bool(w_clean),
                bool(s_clean),
            )

            partner_id = (
                match.audience_id
                if user_id == match.challenger_id
                else match.challenger_id
            )

            # 5. Check if both participants have submitted
            all_contacts = list(
                db.execute(
                    select(MatchContact).where(
                        MatchContact.match_room_id == match_room_id
                    )
                ).scalars()
            )

            # Notify submitter
            await ws_manager.send_to_match_room_user(
                match_room_id,
                user_id,
                {"type": "contact_submission_status", "submitted": True},
            )

            if len(all_contacts) == 1:
                # First submission: notify partner that we are waiting for them
                await ws_manager.send_to_match_room_user(
                    match_room_id,
                    partner_id,
                    {"type": "waiting_for_partner"},
                )
            elif len(all_contacts) == 2:
                logger.info(
                    "Both participants submitted contacts for match room %d — executing exchange.",
                    match_room_id,
                )
                # Finalize exchange & completion
                match_room.state = MatchRoomState.COMPLETED
                match_room.completed_at = now
                match.status = MatchStatus.COMPLETED

                user_a = db.get(User, match.challenger_id)
                user_b = db.get(User, match.audience_id)
                if user_a:
                    user_a.state = UserState.COMPLETED
                if user_b:
                    user_b.state = UserState.COMPLETED

                db.commit()

                contact_a = next(c for c in all_contacts if c.user_id == user_a.id)
                contact_b = next(c for c in all_contacts if c.user_id == user_b.id)

                # Send User A User B's info
                await ws_manager.send_to_match_room_user(
                    match_room_id,
                    user_a.id,
                    {
                        "type": "contacts_exchanged",
                        "partner": {
                            "name": user_b.name,
                            "whatsapp": contact_b.whatsapp,
                            "snapchat": contact_b.snapchat,
                        },
                    },
                )

                # Send User B User A's info
                await ws_manager.send_to_match_room_user(
                    match_room_id,
                    user_b.id,
                    {
                        "type": "contacts_exchanged",
                        "partner": {
                            "name": user_a.name,
                            "whatsapp": contact_a.whatsapp,
                            "snapchat": contact_a.snapchat,
                        },
                    },
                )

                # Broadcast match_completed to match room
                await ws_manager.broadcast_match_room(
                    match_room_id,
                    {"type": "match_completed"},
                )

            return contact


match_room_service = MatchRoomService()
