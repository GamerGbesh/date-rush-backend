# Date Rush — REST API Reference (OpenAPI Specification)

This document provides the complete HTTP API reference for the Date Rush backend. It is designed for frontend developers building client applications against the Date Rush platform.

---

## 1. General API Conventions

### Base URL
All REST endpoints are relative to the root server URL (e.g. `http://localhost:8000` or production host).

### Time Handling
All timestamps returned in request/response payloads follow **ISO 8601 UTC format**:
```text
2026-08-29T14:30:00Z
```

### Opaque Identifiers
All entity identifiers (`user_id`, `room_id`, `session_id`, `match_id`, `match_room_id`, `question_id`) must be treated as opaque identifiers by the client.

### Standard Error Response Envelope
When an error occurs, the API returns a structured JSON payload with stable machine-readable error codes:
```json
{
  "detail": "Descriptive error message"
}
```
Or structured validation errors (`422 Unprocessable Content`):
```json
{
  "detail": [
    {
      "loc": ["body", "whatsapp"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### Common Machine-Readable Error Codes & Scenarios
| HTTP Status | Condition / Scenario | Typical Detail Message |
| :--- | :--- | :--- |
| `400 Bad Request` | Malformed input | `"Invalid request payload"` |
| `403 Forbidden` | Non-participant, non-challenger, or unauthorized action | `"User {id} is not authorized..."` |
| `404 Not Found` | Entity does not exist | `"User {id} not found."`, `"Room {id} not found."`, `"Match {id} not found."` |
| `409 Conflict` | Invalid phase transition, duplicate submission, already voted, or completed user | `"User already completed event."`, `"Cannot submit vote: room is in state 'intro'..."` |
| `422 Unprocessable` | Input validation failed (e.g., whitespace-only contact) | `"At least one contact method (WhatsApp or Snapchat) must be provided."` |

---

## 2. Authentication & User Profile API

### `POST /users`
**Purpose:** Register a new user profile.  
**Who can call:** Anyone.  
**Request Body:**
```json
{
  "name": "Kofi",
  "gender": "male"
}
```
**Success Response:** `201 Created`
```json
{
  "id": 1,
  "name": "Kofi",
  "gender": "male",
  "state": "waiting",
  "created_at": "2026-08-29T12:00:00Z",
  "queued_at": null
}
```

---

### `GET /users/me`
**Purpose:** Retrieve the current user's profile, active game room, role, and match information. Used after app launch, login, refresh, or reconnect.  
**Query Parameters:**
- `user_id` (integer, required): Authenticated user ID.  
**Success Response:** `200 OK`
```json
{
  "id": 1,
  "name": "Kofi",
  "gender": "male",
  "state": "in_game",
  "queued_at": "2026-08-29T12:01:00Z",
  "room_id": 4,
  "role": "audience",
  "match_id": null,
  "match_room_id": null
}
```

---

### `GET /users/{user_id}`
**Purpose:** Retrieve public profile of a user.  
**Success Response:** `200 OK`
```json
{
  "id": 1,
  "name": "Kofi",
  "gender": "male",
  "state": "in_game",
  "created_at": "2026-08-29T12:00:00Z",
  "queued_at": "2026-08-29T12:01:00Z"
}
```

---

## 3. Queue & Event Participation API

### `POST /queue/join`
**Purpose:** Create a user profile and immediately enter them into the matchmaking queue. The backend automatically selects the correct queue based on gender.  
**Request Body:**
```json
{
  "name": "Ama",
  "gender": "female"
}
```
**Success Response:** `201 Created`
```json
{
  "user_id": 2,
  "name": "Ama",
  "gender": "female",
  "state": "queued",
  "queued_at": "2026-08-29T12:02:00Z",
  "message": "User registered and placed into queue"
}
```
**Possible Errors:**
- `409 Conflict`: User has already completed the event.

---

### `GET /queue/status`
**Purpose:** Retrieve current queue counts for monitoring.  
**Success Response:** `200 OK`
```json
{
  "male_queue_count": 4,
  "female_queue_count": 1,
  "active_rooms_count": 2
}
```

---

## 4. Game Room API

### `GET /rooms/{room_id}`
**Purpose:** Retrieve current public room details, state, and active participant list.  
**Success Response:** `200 OK`
```json
{
  "id": 4,
  "state": "questioning",
  "challenger_id": 2,
  "challenger_gender": "female",
  "current_round": 1,
  "created_at": "2026-08-29T12:05:00Z",
  "participants": [
    {
      "user_id": 2,
      "role": "challenger",
      "status": "active"
    },
    {
      "user_id": 1,
      "role": "audience",
      "status": "active"
    }
  ]
}
```

---

### `POST /rooms/{room_id}/answers`
**Purpose:** Challenger submits answer for the current public question round.  
**Who can call:** Challenger only.  
**When:** When room is in `QUESTIONING` state.  
**Request Body:**
```json
{
  "user_id": 2,
  "answer": "I enjoy hiking and playing basketball on weekends."
}
```
**Success Response:** `201 Created`
```json
{
  "id": 10,
  "room_id": 4,
  "question_id": 3,
  "user_id": 2,
  "answer": "I enjoy hiking and playing basketball on weekends.",
  "created_at": "2026-08-29T12:06:30Z"
}
```
**Side Effects & Progression:**
- Broadcasts `answer_revealed` to the room.
- If more questions remain, automatically advances round and broadcasts `question_started`.
- If 3 questions have been answered, automatically transitions room to `VOTING` and broadcasts `voting_started`.

---

### `GET /rooms/{room_id}/voting`
**Purpose:** Retrieve public voting status for recovery after page refresh.  
**Query Parameters:**
- `user_id` (integer, optional): Authenticated participant user ID to check if they have already voted.  
**Success Response:** `200 OK`
```json
{
  "state": "voting",
  "total_voters": 5,
  "votes_submitted": 3,
  "votes_remaining": 2,
  "has_voted": false
}
```

---

### `POST /rooms/{room_id}/vote`
**Purpose:** Audience member submits their public YES/NO vote.  
**Who can call:** Active audience members in the room.  
**When:** When room is in `VOTING` state.  
**Request Body:**
```json
{
  "user_id": 1,
  "vote": "yes"
}
```
**Success Response:** `201 Created`
```json
{
  "id": 15,
  "room_id": 4,
  "round": 1,
  "voter_id": 1,
  "target_id": 2,
  "vote": "yes",
  "created_at": "2026-08-29T12:08:00Z"
}
```
**Possible Errors:**
- `403 Forbidden`: Voter is not an active audience member in the room.
- `409 Conflict`: Room is not in `VOTING` state, or user has already voted.

---

## 5. One-on-One Phase API

### `GET /rooms/{room_id}/one-on-one`
**Purpose:** Retrieve summary list of all 1-on-1 sessions for the room.  
**Success Response:** `200 OK`
```json
[
  {
    "id": 1,
    "room_id": 4,
    "audience_id": 1,
    "challenger_id": 2,
    "sequence": 1,
    "state": "completed",
    "vote": "yes",
    "created_at": "2026-08-29T12:10:00Z"
  },
  {
    "id": 2,
    "room_id": 4,
    "audience_id": 3,
    "challenger_id": 2,
    "sequence": 2,
    "state": "active",
    "vote": null,
    "created_at": "2026-08-29T12:10:00Z"
  }
]
```

---

### `POST /rooms/{room_id}/one-on-one/{session_id}/question`
**Purpose:** Audience member submits their private question to the challenger.  
**Who can call:** The specific audience member assigned to `session_id`.  
**When:** When session is in `ACTIVE` state.  
**Request Body:**
```json
{
  "user_id": 3,
  "text": "What is your biggest life goal for the next 5 years?"
}
```
**Success Response:** `201 Created`
```json
{
  "id": 2,
  "room_id": 4,
  "audience_id": 3,
  "challenger_id": 2,
  "sequence": 2,
  "state": "answered",
  "question": "What is your biggest life goal for the next 5 years?",
  "answer": null,
  "vote": null
}
```

---

### `POST /rooms/{room_id}/one-on-one/{session_id}/answer`
**Purpose:** Challenger submits their private answer to the audience member.  
**Who can call:** Challenger only.  
**When:** When session is in `ANSWERED` (question submitted) state.  
**Request Body:**
```json
{
  "user_id": 2,
  "text": "I want to build my own business and travel across East Asia."
}
```
**Success Response:** `201 Created`
```json
{
  "id": 2,
  "room_id": 4,
  "audience_id": 3,
  "challenger_id": 2,
  "sequence": 2,
  "state": "voting",
  "question": "What is your biggest life goal for the next 5 years?",
  "answer": "I want to build my own business and travel across East Asia.",
  "vote": null
}
```

---

### `POST /rooms/{room_id}/one-on-one/{session_id}/vote`
**Purpose:** Audience member submits mandatory private YES/NO vote.  
**Who can call:** The specific audience member assigned to `session_id`.  
**When:** When session is in `VOTING` state.  
**Request Body:**
```json
{
  "user_id": 3,
  "vote": "yes"
}
```
**Success Response:** `201 Created`
```json
{
  "id": 2,
  "room_id": 4,
  "audience_id": 3,
  "challenger_id": 2,
  "sequence": 2,
  "state": "completed",
  "vote": "yes"
}
```
**Side Effects & Automatic Progression:**
- YES vote: Audience member marked `ParticipantStatus.FINALIST`.
- NO vote: Audience member eliminated and returned to `QUEUED`.
- Automatically activates next 1-on-1 session if any remain.
- When all sessions finish:
  - 0 survivors $\rightarrow$ Room completed.
  - 1 survivor $\rightarrow$ Auto match created.
  - >1 survivors $\rightarrow$ Room transitions to `FINAL_SELECTION`.

---

## 6. Final Selection API

### `GET /rooms/{room_id}/final-selection`
**Purpose:** Retrieve candidate finalists and selection status.  
**Query Parameters:**
- `user_id` (integer, required): Authenticated user ID.  
**Success Response:** `200 OK`
```json
{
  "state": "final_selection",
  "is_challenger": true,
  "candidates": [
    {
      "id": 1,
      "name": "Kofi",
      "gender": "male"
    },
    {
      "id": 3,
      "name": "Yaw",
      "gender": "male"
    }
  ],
  "selected": false,
  "match_id": null
}
```

---

### `POST /rooms/{room_id}/final-selection`
**Purpose:** Challenger selects their chosen partner from the finalists.  
**Who can call:** Challenger only.  
**When:** When room is in `FINAL_SELECTION` state.  
**Request Body:**
```json
{
  "user_id": 2,
  "candidate_id": 1
}
```
**Success Response:** `201 Created`
```json
{
  "id": 8,
  "room_id": 4,
  "challenger_id": 2,
  "audience_id": 1,
  "status": "created",
  "created_at": "2026-08-29T12:20:00Z"
}
```
**Side Effects:**
- Creates `Match` and `MatchRoom`.
- Transitions non-selected finalists back to `UserState.QUEUED` with fresh timestamps and triggers background room formation.
- Broadcasts `final_selection_completed` and `match_created`.

---

## 7. Matches API

### `GET /matches/{match_id}`
**Purpose:** Retrieve match summary and `match_room_id` for contact exchange.  
**Query Parameters:**
- `user_id` (integer, required): Authenticated participant user ID.  
**Success Response:** `200 OK`
```json
{
  "id": 8,
  "room_id": 4,
  "status": "created",
  "created_at": "2026-08-29T12:20:00Z",
  "partner": {
    "id": 1,
    "name": "Kofi",
    "gender": "male"
  },
  "match_room_id": 5
}
```
**Possible Errors:**
- `403 Forbidden`: User is not a participant of the match.
- `404 Not Found`: Match does not exist.

---

## 8. Match Room & Contact Exchange API

### `GET /match-rooms/{match_room_id}`
**Purpose:** Retrieve match room status and submission status.  
**Query Parameters:**
- `user_id` (integer, required): Authenticated participant user ID.  
**Success Response:** `200 OK`
```json
{
  "id": 5,
  "match_id": 8,
  "state": "waiting_for_contacts",
  "my_contact_submitted": true,
  "partner_contact_available": false,
  "created_at": "2026-08-29T12:20:00Z",
  "completed_at": null
}
```

---

### `POST /match-rooms/{match_room_id}/contacts`
**Purpose:** Submit WhatsApp and/or Snapchat handle.  
**Validation Rules:**
- At least one contact method required.
- Maximum 100 characters per field.
- Non-empty, non-whitespace.
- Single submission per user (subsequent submissions rejected with 409).  
**Request Body:**
```json
{
  "user_id": 2,
  "whatsapp": "+233201234567",
  "snapchat": "ama_gh"
}
```
**Success Response (First submitter):** `201 Created`
```json
{
  "state": "waiting_for_contacts",
  "submitted": true,
  "partner": null
}
```
**Success Response (Second submitter — Triggers Atomic Exchange):** `201 Created`
```json
{
  "state": "completed",
  "submitted": true,
  "partner": {
    "name": "Kofi",
    "whatsapp": "+233501234567",
    "snapchat": "kofi_snap"
  }
}
```

---

### `GET /match-rooms/{match_room_id}/contacts`
**Purpose:** Retrieve contact exchange state and partner contact information (only available after exchange).  
**Query Parameters:**
- `user_id` (integer, required): Authenticated participant user ID.  
**Success Response (Post-exchange):** `200 OK`
```json
{
  "state": "completed",
  "submitted": true,
  "partner": {
    "name": "Kofi",
    "whatsapp": "+233501234567",
    "snapchat": "kofi_snap"
  }
}
```
