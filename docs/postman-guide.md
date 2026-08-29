# Date Rush — Postman Testing Guide (REST & WebSockets)

This guide provides step-by-step instructions to test the entire Date Rush backend system in **Postman**, covering both **HTTP REST APIs** and **Real-Time WebSocket channels**.

---

## 1. Quick Setup & Import

### A. Start the Backend Server
Make sure the Date Rush server is running on port 8000:
```bash
uv run uvicorn app.main:app --port 8000 --reload
```

### B. Import the Ready-to-Use Postman Collection
An importable Postman collection is located at:
📁 [`docs/date_rush.postman_collection.json`](./date_rush.postman_collection.json)

1. Open **Postman**.
2. Click **Import** (top left).
3. Drag and drop `docs/date_rush.postman_collection.json` or select the file.
4. The **Date Rush API & WebSockets** collection will appear in your sidebar.

---

## 2. Collection Variables

The collection includes the following pre-configured variables (accessible via `{{variable_name}}`):

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `base_url` | `http://127.0.0.1:8000` | HTTP Server Base URL |
| `ws_url` | `ws://127.0.0.1:8000` | WebSocket Base URL |
| `challenger_id` | `1` | ID of the Female Challenger |
| `aud1_id` | `2` | ID of Male Audience Member 1 |
| `aud2_id` | `3` | ID of Male Audience Member 2 |
| `aud3_id` | `4` | ID of Male Audience Member 3 |
| `aud4_id` | `5` | ID of Male Audience Member 4 |
| `aud5_id` | `6` | ID of Male Audience Member 5 |
| `room_id` | `1` | Current Game Room ID |
| `session_id` | `1` | Current 1-on-1 Session ID |
| `match_id` | `1` | Formed Match ID |
| `match_room_id` | `1` | Formed Match Room ID |

---

## 3. How to Test WebSockets in Postman

Postman includes native WebSocket support:
1. In Postman, click **New** (top left) $\rightarrow$ select **WebSocket Request**.
2. Set the URL (e.g. `ws://127.0.0.1:8000/ws/rooms/1/users/1`).
3. Click **Connect**.
4. Real-time events sent by the server will appear instantly in the **Messages** pane.

---

## 4. Complete End-to-End Manual Testing Workflow

Follow these steps in order in Postman to test the full user lifecycle:

### Step 1: Health & Queue Status
1. **Health Check**
   - **Method:** `GET` `{{base_url}}/health`
   - **Response:** `200 OK` `{"status": "ok"}`
2. **Get Initial Queue Status**
   - **Method:** `GET` `{{base_url}}/queue/status`
   - **Response:** `200 OK` `{"male": 0, "female": 0}`

---

### Step 2: Queue Registration & Automatic Room Formation
Register 1 female and 5 males. The 5th male will trigger automatic game room creation:

1. **Join Queue - Female (Challenger)**
   - **Method:** `POST` `{{base_url}}/queue/join`
   - **Body (JSON):**
     ```json
     {
       "name": "Ama",
       "gender": "female"
     }
     ```
   - **Response:** `201 Created` $\rightarrow$ Copy the returned `user_id` to your `challenger_id` collection variable.

2. **Join Queue - Male 1 to Male 5**
   - **Method:** `POST` `{{base_url}}/queue/join`
   - **Bodies:**
     - Male 1: `{"name": "Kofi", "gender": "male"}` $\rightarrow$ Set `aud1_id`
     - Male 2: `{"name": "Yaw", "gender": "male"}` $\rightarrow$ Set `aud2_id`
     - Male 3: `{"name": "Kwame", "gender": "male"}` $\rightarrow$ Set `aud3_id`
     - Male 4: `{"name": "Kojo", "gender": "male"}` $\rightarrow$ Set `aud4_id`
     - Male 5: `{"name": "Kwabena", "gender": "male"}` $\rightarrow$ Set `aud5_id`
   - *When Male 5 is submitted, the room is created automatically!*

3. **Verify Challenger Event Profile**
   - **Method:** `GET` `{{base_url}}/users/me?user_id={{challenger_id}}`
   - **Response:** `200 OK`
     ```json
     {
       "id": 1,
       "name": "Ama",
       "gender": "female",
       "state": "in_game",
       "room_id": 1,
       "role": "challenger"
     }
     ```
   - Copy `room_id` into your `room_id` collection variable.

---

### Step 3: Public Game Room (REST + WebSocket)

1. **Open Postman WebSocket for Challenger**:
   - Create a WebSocket request: `{{ws_url}}/ws/rooms/{{room_id}}/users/{{challenger_id}}`
   - Click **Connect**.
   - You will immediately receive:
     - `{"type": "room_state_changed", "state": "ready"}`

2. **Open Postman WebSocket for Audience Member 1**:
   - Create a second WebSocket tab: `{{ws_url}}/ws/rooms/{{room_id}}/users/{{aud1_id}}`
   - Click **Connect**.

3. **Admin Transition: Start Questioning**
   - **Method:** `POST` `{{base_url}}/admin/rooms/{{room_id}}/transition`
   - **Body (JSON):** `{"state": "intro"}`
   - Then: `POST` `{{base_url}}/admin/rooms/{{room_id}}/transition`
   - **Body (JSON):** `{"state": "questioning"}`
   - *Look at your WebSocket tabs:* Both tabs receive `room_state_changed` and `question_started` with the active question!

4. **Challenger Submits Answers (3 Rounds)**
   - **Round 1:**
     - **Method:** `POST` `{{base_url}}/rooms/{{room_id}}/answers`
     - **Body:** `{"user_id": {{challenger_id}}, "answer": "I love road trips and beaches."}`
     - *WebSockets receive:* `answer_revealed` and auto-advance to `question_started` (Round 2).
   - **Round 2:**
     - **Method:** `POST` `{{base_url}}/rooms/{{room_id}}/answers`
     - **Body:** `{"user_id": {{challenger_id}}, "answer": "Honesty and shared sense of humor."}`
   - **Round 3:**
     - **Method:** `POST` `{{base_url}}/rooms/{{room_id}}/answers`
     - **Body:** `{"user_id": {{challenger_id}}, "answer": "I value quality time together."}`
     - *WebSockets receive:* `voting_started` $\rightarrow$ Room auto-enters `VOTING`!

---

### Step 4: Public Voting & Elimination

1. **Audience Members Vote (3 YES, 2 NO)**
   - **Male 1 (YES):** `POST {{base_url}}/rooms/{{room_id}}/vote` `{"user_id": {{aud1_id}}, "vote": "yes"}`
   - **Male 2 (YES):** `POST {{base_url}}/rooms/{{room_id}}/vote` `{"user_id": {{aud2_id}}, "vote": "yes"}`
   - **Male 3 (YES):** `POST {{base_url}}/rooms/{{room_id}}/vote` `{"user_id": {{aud3_id}}, "vote": "yes"}`
   - **Male 4 (NO):** `POST {{base_url}}/rooms/{{room_id}}/vote` `{"user_id": {{aud4_id}}, "vote": "no"}`
   - **Male 5 (NO):** `POST {{base_url}}/rooms/{{room_id}}/vote` `{"user_id": {{aud5_id}}, "vote": "no"}`
2. *WebSockets receive:* `vote_progress`, `voting_completed`, `participants_eliminated` (2 eliminated, 3 survivors).
3. Room automatically transitions to `ONE_ON_ONE`!

---

### Step 5: Sequential 1-on-1 Sessions (Filtered GameRoom WebSocket)

1. **Check 1-on-1 Sessions List**
   - **Method:** `GET` `{{base_url}}/rooms/{{room_id}}/one-on-one`
   - **Response:** List of 3 sessions. Copy the first session ID into `{{session_id}}`.

2. **Check Current Active Session**
   - **Method:** `GET` `{{base_url}}/rooms/{{room_id}}/one-on-one/current?user_id={{aud1_id}}`

3. **GameRoom WebSocket Remains Active**
   - Keep the existing GameRoom WebSocket tab open: `{{ws_url}}/ws/rooms/{{room_id}/users/{{aud1_id}}` (and challenger's socket `{{ws_url}}/ws/rooms/{{room_id}/users/{{challenger_id}}`).
   - Receives: `{"type": "one_on_one_started", "session_id": 1, ...}`.

4. **Audience Submits Private Question**
   - **Method:** `POST` `{{base_url}}/rooms/{{room_id}}/one-on-one/{{session_id}}/question`
   - **Body:** `{"user_id": {{aud1_id}}, "text": "What is your biggest life goal?"}`
   - *Active participants receive via GameRoom WS:* `{"type": "one_on_one_question", "question": "..."}`

5. **Challenger Submits Private Answer**
   - **Method:** `POST` `{{base_url}}/rooms/{{room_id}}/one-on-one/{{session_id}}/answer`
   - **Body:** `{"user_id": {{challenger_id}}, "text": "To build a great tech startup."}`
   - *Active participants receive via GameRoom WS:* `{"type": "one_on_one_answer", "answer": "..."}`

6. **Audience Casts Private Vote (YES)**
   - **Method:** `POST` `{{base_url}}/rooms/{{room_id}}/one-on-one/{{session_id}}/vote`
   - **Body:** `{"user_id": {{aud1_id}}, "vote": "yes"}`
   - *Active participants receive via GameRoom WS:* `one_on_one_completed` $\rightarrow$ Audience 1 marked `FINALIST`.
   - *Room receives:* `one_on_one_progress`.

7. **Execute Remaining 2 Sessions:**
   - For Session 2: Submit Q $\rightarrow$ A $\rightarrow$ Vote `no` (Audience 2 eliminated to queue).
   - For Session 3: Submit Q $\rightarrow$ A $\rightarrow$ Vote `yes` (Audience 3 marked `FINALIST`).
   - *Result:* 2 finalists survive $\rightarrow$ Room automatically enters `FINAL_SELECTION`!

---

### Step 6: Final Selection & Match Creation

1. **Challenger Checks Finalist Candidates**
   - **Method:** `GET` `{{base_url}}/rooms/{{room_id}}/final-selection?user_id={{challenger_id}}`
   - **Response:**
     ```json
     {
       "state": "final_selection",
       "is_challenger": true,
       "candidates": [
         {"id": 2, "name": "Kofi", "gender": "male"},
         {"id": 4, "name": "Kwame", "gender": "male"}
       ]
     }
     ```

2. **Challenger Submits Final Choice**
   - **Method:** `POST` `{{base_url}}/rooms/{{room_id}}/final-selection`
   - **Body:** `{"user_id": {{challenger_id}}, "candidate_id": {{aud1_id}}}`
   - **Response:** `201 Created` with Match details!
   - Copy `id` to `{{match_id}}`.

3. **Get Match Details**
   - **Method:** `GET` `{{base_url}}/matches/{{match_id}}?user_id={{challenger_id}}`
   - **Response:** Returns `match_room_id`. Copy to `{{match_room_id}}`.

---

### Step 7: Private Match Room & Contact Exchange (REST + WebSocket)

1. **Open Private Match Room WebSocket in Postman**:
   - Tab 1 (Challenger): `{{ws_url}}/ws/match-rooms/{{match_room_id}}/users/{{challenger_id}}`
   - Tab 2 (Candidate): `{{ws_url}}/ws/match-rooms/{{match_room_id}}/users/{{aud1_id}}`
   - Both connect and receive: `{"type": "match_room_state", "state": "waiting_for_contacts"}`.

2. **Challenger Submits WhatsApp**
   - **Method:** `POST` `{{base_url}}/match-rooms/{{match_room_id}}/contacts`
   - **Body:**
     ```json
     {
       "user_id": {{challenger_id}},
       "whatsapp": "+233201234567",
       "snapchat": null
     }
     ```
   - *WebSockets:*
     - Challenger receives: `{"type": "contact_submission_status", "submitted": true}`
     - Candidate receives: `{"type": "waiting_for_partner"}`

3. **Candidate Submits Snapchat (Triggers Atomic Exchange!)**
   - **Method:** `POST` `{{base_url}}/match-rooms/{{match_room_id}}/contacts`
   - **Body:**
     ```json
     {
       "user_id": {{aud1_id}},
       "whatsapp": null,
       "snapchat": "kofi_snap"
     }
     ```
   - *WebSockets:*
     - Challenger receives: `{"type": "contacts_exchanged", "partner": {"name": "Kofi", "whatsapp": null, "snapchat": "kofi_snap"}}` followed by `match_completed`.
     - Candidate receives: `{"type": "contacts_exchanged", "partner": {"name": "Ama", "whatsapp": "+233201234567", "snapchat": null}}` followed by `match_completed`.

4. **Verify Final Completed Profile**
   - **Method:** `GET` `{{base_url}}/users/me?user_id={{challenger_id}}`
   - **Response:** `200 OK` `{"state": "completed", "match_id": 1, "match_room_id": 1}`.

---

## 5. Admin Question Management in Postman

You can create, inspect, update, and delete questions in the question pool:

### 1. Create a Question (Target: ANY)
- **Method:** `POST` `{{base_url}}/admin/questions`
- **Headers:** `Content-Type: application/json`
- **Body (JSON):**
  ```json
  {
    "text": "What is your favorite weekend activity?",
    "target_gender": "any",
    "active": true
  }
  ```
- **Response:** `201 Created`
  ```json
  {
    "id": 13,
    "text": "What is your favorite weekend activity?",
    "target_gender": "any",
    "active": true,
    "created_at": "2026-08-29T00:45:00Z",
    "updated_at": null
  }
  ```

---

### 2. Create a Question (Target: FEMALE Challenger)
- **Method:** `POST` `{{base_url}}/admin/questions`
- **Body (JSON):**
  ```json
  {
    "text": "What makes you feel most appreciated in a relationship?",
    "target_gender": "female",
    "active": true
  }
  ```
- **Response:** `201 Created`

---

### 3. Create a Question (Target: MALE Challenger)
- **Method:** `POST` `{{base_url}}/admin/questions`
- **Body (JSON):**
  ```json
  {
    "text": "How do you communicate when you are stressed?",
    "target_gender": "male",
    "active": true
  }
  ```
- **Response:** `201 Created`

---

### 4. List All Questions
- **Method:** `GET` `{{base_url}}/admin/questions`
- **Response:** `200 OK` (Array of all question objects)

### 5. List Only Active Questions
- **Method:** `GET` `{{base_url}}/admin/questions?active=true`
- **Response:** `200 OK`

---

### 6. Get Question by ID
- **Method:** `GET` `{{base_url}}/admin/questions/{question_id}`
- **Response:** `200 OK`

---

### 7. Update Question (Text, Target, or Active Status)
- **Method:** `PATCH` `{{base_url}}/admin/questions/{question_id}`
- **Body (JSON):**
  ```json
  {
    "text": "What is your ideal first date?",
    "active": true
  }
  ```
- **Response:** `200 OK`

---

### 8. Delete a Question
- **Method:** `DELETE` `{{base_url}}/admin/questions/{question_id}`
- **Response:** `204 No Content`

