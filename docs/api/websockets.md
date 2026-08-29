# Date Rush — WebSocket Protocol & Event Catalog

This document defines the WebSocket communication architecture, connection lifecycles, and event catalog for real-time frontend integration.

---

## 1. Overview & Channels

The Date Rush backend exposes three dedicated WebSocket channels:

1. **Public Game Room Channel:**
   ```text
   WS /ws/rooms/{room_id}/users/{user_id}
   ```
   Live public game room events (questions, challenger answers, voting progress, eliminations, 1-on-1 announcements, final selection, and match creation).

2. **Private One-on-One Session Channel:**
   ```text
   WS /ws/rooms/{room_id}/one-on-one/{session_id}/users/{user_id}
   ```
   Private, isolated channel restricted strictly to the challenger and the active audience member in that specific session.

3. **Private Match Room Channel:**
   ```text
   WS /ws/match-rooms/{match_room_id}/users/{user_id}
   ```
   Private post-match contact exchange channel strictly restricted to the two matched participants.

---

## 2. Protocol Standards & Security

### Authorization & Rejection
- All WebSocket connections require a valid `user_id` in the URL path.
- The server checks whether the user is an active, authorized member of the requested room or session before accepting the connection.
- If unauthorized, the socket is immediately closed with:
  ```text
  WS Close Code: 1008 (Policy Violation)
  ```

### Reconnection & State Synchronization
When a frontend client connects (or reconnects after a network drop or page refresh), the server **immediately pushes the current phase state**. The frontend does not need to wait for a future broadcast event to reconstruct the screen.

---

## 3. Public Game Room Events Catalog (`/ws/rooms/{room_id}/users/{user_id}`)

### 1. `room_state_changed`
Sent immediately on connection and whenever the room changes state.
```json
{
  "type": "room_state_changed",
  "room_id": 4,
  "previous_state": "intro",
  "state": "questioning"
}
```

### 2. `question_started`
Sent when a public question begins.
```json
{
  "type": "question_started",
  "room_id": 4,
  "round": 1,
  "question": {
    "id": 3,
    "text": "What is your biggest fear in a relationship?"
  }
}
```

### 3. `answer_revealed`
Broadcast when the challenger submits their answer.
```json
{
  "type": "answer_revealed",
  "room_id": 4,
  "round": 1,
  "question_id": 3,
  "answer": "Fear of poor communication."
}
```

### 4. `voting_started`
Broadcast when public voting begins after all public questions.
```json
{
  "type": "voting_started",
  "room_id": 4,
  "round": 1,
  "total_voters": 5
}
```

### 5. `vote_progress`
Broadcast whenever an audience member casts a vote (does not reveal individual choices).
```json
{
  "type": "vote_progress",
  "room_id": 4,
  "submitted": 3,
  "total": 5
}
```

### 6. `voting_completed`
Broadcast when all audience votes have been cast.
```json
{
  "type": "voting_completed",
  "room_id": 4,
  "round": 1
}
```

### 7. `participants_eliminated`
Broadcast to surviving participants summarizing elimination results.
```json
{
  "type": "participants_eliminated",
  "room_id": 4,
  "eliminated_count": 2,
  "remaining_count": 3
}
```

### 8. `eliminated`
Sent privately to eliminated audience members notifying them of queue re-entry.
```json
{
  "type": "eliminated",
  "room_id": 4,
  "reason": "Voted NO or was eliminated."
}
```

### 9. `one_on_one_started`
Broadcast when the room enters the 1-on-1 phase.
```json
{
  "type": "one_on_one_started",
  "room_id": 4,
  "total_sessions": 3
}
```

### 10. `final_selection_started`
Broadcast when multiple finalists survive and the challenger must choose.
```json
{
  "type": "final_selection_started",
  "room_id": 4,
  "candidates": [
    {"id": 1, "name": "Kofi", "gender": "male"},
    {"id": 3, "name": "Yaw", "gender": "male"}
  ]
}
```

### 11. `final_selection_completed`
Broadcast when the challenger submits their final choice.
```json
{
  "type": "final_selection_completed",
  "room_id": 4,
  "selected_candidate_id": 1
}
```

### 12. `match_created`
Broadcast when a match is formed (either via selection or single-survivor shortcut).
```json
{
  "type": "match_created",
  "match_id": 8,
  "match_room_id": 5,
  "room_id": 4,
  "challenger_id": 2,
  "candidate_id": 1
}
```

### 13. `room_completed`
Broadcast when the room lifecycle ends.
```json
{
  "type": "room_completed",
  "room_id": 4
}
```

---

## 4. Private 1-on-1 Session Events (`/ws/rooms/{room_id}/one-on-one/{session_id}/users/{user_id}`)

### 1. `private_session_state`
Sent immediately on connection to restore session state.
```json
{
  "type": "private_session_state",
  "session_id": 2,
  "state": "active",
  "sequence": 2,
  "audience_id": 3,
  "challenger_id": 2,
  "question": null,
  "answer": null,
  "vote": null
}
```

### 2. `private_question`
Delivered to both participants when the audience member submits their question.
```json
{
  "type": "private_question",
  "session_id": 2,
  "text": "What is your favorite weekend activity?"
}
```

### 3. `private_answer`
Delivered to both participants when the challenger answers.
```json
{
  "type": "private_answer",
  "session_id": 2,
  "text": "Cooking dinner and watching movies."
}
```

### 4. `session_completed`
Delivered to both participants when the private vote is processed.
```json
{
  "type": "session_completed",
  "session_id": 2,
  "result": "accepted"
}
```

---

## 5. Private Match Room Events (`/ws/match-rooms/{match_room_id}/users/{user_id}`)

### 1. `match_room_state`
Sent immediately upon connection to report current contact submission status.
```json
{
  "type": "match_room_state",
  "state": "waiting_for_contacts",
  "my_contact_submitted": true,
  "partner_contact_available": false
}
```

### 2. `contact_submission_status`
Sent to the submitter confirming their submission has been recorded.
```json
{
  "type": "contact_submission_status",
  "submitted": true
}
```

### 3. `waiting_for_partner`
Sent to the partner informing them that the other participant has submitted.
```json
{
  "type": "waiting_for_partner"
}
```

### 4. `contacts_exchanged`
Sent privately to each participant once both have submitted contact details.
```json
{
  "type": "contacts_exchanged",
  "partner": {
    "name": "Ama",
    "whatsapp": "+233201234567",
    "snapchat": "ama_gh"
  }
}
```

### 5. `match_completed`
Sent to both participants indicating that the matchmaking experience is complete.
```json
{
  "type": "match_completed"
}
```
