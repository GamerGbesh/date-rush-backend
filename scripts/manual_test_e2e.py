"""
Manual end-to-end testing script for Date Rush live server.
Runs against http://127.0.0.1:8000.
"""

import sys
import time
import httpx

BASE_URL = "http://127.0.0.1:8000"


def log(section: str, msg: str):
    print(f"\n[\033[1;34m{section}\033[0m] {msg}")


def success(msg: str):
    print(f"  \033[1;32m✓\033[0m {msg}")


def error(msg: str):
    print(f"  \033[1;31m✗\033[0m {msg}")
    sys.exit(1)


def run_manual_tests():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        # --- Step 1: Health Check ---
        log("STEP 1", "Checking server health...")
        resp = client.get("/health")
        if resp.status_code != 200 or resp.json() != {"status": "ok"}:
            error(f"Health check failed: {resp.status_code} {resp.text}")
        success("Server is healthy and responding.")

        # --- Step 2: Queue Initial Status ---
        log("STEP 2", "Querying initial queue status...")
        resp = client.get("/queue/status")
        if resp.status_code != 200:
            error(f"Failed to get queue status: {resp.status_code} {resp.text}")
        success(f"Queue status: {resp.json()}")

        # --- Step 3: Register 1 Female + 5 Males ---
        log("STEP 3", "Registering users and joining matchmaking queues...")
        # 1 Female
        resp_f = client.post("/queue/join", json={"name": "Ama (Challenger)", "gender": "female"})
        if resp_f.status_code != 201:
            error(f"Failed to queue female user: {resp_f.text}")
        female_id = resp_f.json()["user_id"]
        success(f"Queued Female: ID={female_id}, Name='Ama'")

        # 5 Males
        male_names = ["Kofi", "Yaw", "Kwame", "Kojo", "Kwabena"]
        male_ids = []
        for name in male_names:
            resp_m = client.post("/queue/join", json={"name": name, "gender": "male"})
            if resp_m.status_code != 201:
                error(f"Failed to queue male user '{name}': {resp_m.text}")
            m_id = resp_m.json()["user_id"]
            male_ids.append(m_id)
            success(f"Queued Male: ID={m_id}, Name='{name}'")

        # --- Step 4: Verify Room Formation ---
        log("STEP 4", "Verifying automatic room creation...")
        resp_me = client.get(f"/users/me?user_id={female_id}")
        if resp_me.status_code != 200:
            error(f"Failed to fetch profile: {resp_me.text}")
        f_profile = resp_me.json()
        if f_profile["state"] != "in_game" or not f_profile["room_id"]:
            error(f"Room was not created automatically! Profile: {f_profile}")
        room_id = f_profile["room_id"]
        success(f"Game Room #{room_id} created automatically! Challenger: {female_id} (Role: {f_profile['role']})")

        # Check room details
        resp_room = client.get(f"/rooms/{room_id}")
        room_data = resp_room.json()
        success(f"Room #{room_id} has {len(room_data['participants'])} active participants in state '{room_data['room']['state']}'.")

        # --- Step 5: Advance Room to QUESTIONING ---
        log("STEP 5", "Transitioning room READY -> INTRO -> QUESTIONING...")
        resp_admin1 = client.post(f"/admin/rooms/{room_id}/transition", json={"state": "intro"})
        if resp_admin1.status_code != 200:
            error(f"Failed transition to intro: {resp_admin1.text}")
        resp_admin2 = client.post(f"/admin/rooms/{room_id}/transition", json={"state": "questioning"})
        if resp_admin2.status_code != 200:
            error(f"Failed transition to questioning: {resp_admin2.text}")
        success("Room is now in QUESTIONING state.")

        # --- Step 6: Public Questioning (3 Rounds) ---
        log("STEP 6", "Challenger submitting answers to 3 public questions...")
        answers = [
            "I love visiting nature reserves and trying authentic local dishes.",
            "Honesty, kindness, and a great sense of humor.",
            "I prioritize open communication and actively listening to each other.",
        ]
        for round_num, ans in enumerate(answers, start=1):
            resp_ans = client.post(
                f"/rooms/{room_id}/answers",
                json={"user_id": female_id, "answer": ans},
            )
            if resp_ans.status_code != 201:
                error(f"Failed to submit answer for round {round_num}: {resp_ans.text}")
            success(f"Round {round_num} Answer submitted: '{ans[:40]}...'")

        # Check that room automatically transitioned to VOTING
        resp_room = client.get(f"/rooms/{room_id}")
        if resp_room.json()["room"]["state"] != "voting":
            error(f"Room state expected 'voting', got '{resp_room.json()['room']['state']}'")
        success("All 3 public questions answered! Room automatically entered 'VOTING' phase.")

        # --- Step 7: Public Voting & Elimination ---
        log("STEP 7", "Audience members casting public votes (3 YES, 2 NO)...")
        # 3 Vote YES (Kofi, Yaw, Kwame)
        for idx in range(3):
            m_id = male_ids[idx]
            resp_v = client.post(f"/rooms/{room_id}/vote", json={"user_id": m_id, "vote": "yes"})
            if resp_v.status_code != 201:
                error(f"Failed to vote YES for user {m_id}: {resp_v.text}")
            success(f"Audience #{m_id} ({male_names[idx]}) voted YES.")

        # 2 Vote NO (Kojo, Kwabena)
        for idx in range(3, 5):
            m_id = male_ids[idx]
            resp_v = client.post(f"/rooms/{room_id}/vote", json={"user_id": m_id, "vote": "no"})
            if resp_v.status_code != 201:
                error(f"Failed to vote NO for user {m_id}: {resp_v.text}")
            success(f"Audience #{m_id} ({male_names[idx]}) voted NO.")

        # Room automatically enters ONE_ON_ONE with 3 survivors!
        resp_room = client.get(f"/rooms/{room_id}")
        if resp_room.json()["room"]["state"] != "one_on_one":
            error(f"Room state expected 'one_on_one', got '{resp_room.json()['room']['state']}'")
        success("Voting finalized! 2 NO voters eliminated to queue; Room entered 'ONE_ON_ONE' with 3 survivors.")

        # --- Step 8: Sequential One-on-One Sessions ---
        log("STEP 8", "Executing sequential 1-on-1 private sessions...")
        resp_ooo = client.get(f"/rooms/{room_id}/one-on-one")
        sessions = resp_ooo.json()
        success(f"Found {len(sessions)} sequential 1-on-1 sessions.")

        # Session 1: Kofi (Audience 0) -> Asks Q -> Challenger Answers -> Kofi votes YES (Finalist)
        s1 = sessions[0]
        client.post(f"/rooms/{room_id}/one-on-one/{s1['id']}/question", json={"user_id": male_ids[0], "text": "What makes you laugh the most?"})
        client.post(f"/rooms/{room_id}/one-on-one/{s1['id']}/answer", json={"user_id": female_id, "text": "Witty dry humor and silly situational jokes!"})
        client.post(f"/rooms/{room_id}/one-on-one/{s1['id']}/vote", json={"user_id": male_ids[0], "vote": "yes"})
        success(f"Session 1 ({male_names[0]}): Question, Answer, and YES vote submitted -> Marked FINALIST.")

        # Session 2: Yaw (Audience 1) -> Asks Q -> Challenger Answers -> Yaw votes NO (Eliminated)
        s2 = sessions[1]
        client.post(f"/rooms/{room_id}/one-on-one/{s2['id']}/question", json={"user_id": male_ids[1], "text": "Are you an early bird or night owl?"})
        client.post(f"/rooms/{room_id}/one-on-one/{s2['id']}/answer", json={"user_id": female_id, "text": "Definitely a night owl."})
        client.post(f"/rooms/{room_id}/one-on-one/{s2['id']}/vote", json={"user_id": male_ids[1], "vote": "no"})
        success(f"Session 2 ({male_names[1]}): Question, Answer, and NO vote submitted -> Eliminated to queue.")

        # Session 3: Kwame (Audience 2) -> Asks Q -> Challenger Answers -> Kwame votes YES (Finalist)
        s3 = sessions[2]
        client.post(f"/rooms/{room_id}/one-on-one/{s3['id']}/question", json={"user_id": male_ids[2], "text": "What is your dream vacation?"})
        client.post(f"/rooms/{room_id}/one-on-one/{s3['id']}/answer", json={"user_id": female_id, "text": "A road trip across the Mediterranean coast."})
        client.post(f"/rooms/{room_id}/one-on-one/{s3['id']}/vote", json={"user_id": male_ids[2], "vote": "yes"})
        success(f"Session 3 ({male_names[2]}): Question, Answer, and YES vote submitted -> Marked FINALIST.")

        # Room automatically transitions to FINAL_SELECTION
        resp_room = client.get(f"/rooms/{room_id}")
        if resp_room.json()["room"]["state"] != "final_selection":
            error(f"Room state expected 'final_selection', got '{resp_room.json()['room']['state']}'")
        success("All 1-on-1 sessions completed! 2 finalists survived -> Room entered 'FINAL_SELECTION'.")

        # --- Step 9: Final Selection ---
        log("STEP 9", "Challenger viewing finalists and selecting a match...")
        resp_fs = client.get(f"/rooms/{room_id}/final-selection?user_id={female_id}")
        candidates = resp_fs.json()["candidates"]
        success(f"Candidates available to Challenger: {[c['name'] for c in candidates]}")

        # Challenger selects Kwame (Audience 2)
        chosen_id = male_ids[2]
        resp_select = client.post(
            f"/rooms/{room_id}/final-selection",
            json={"user_id": female_id, "candidate_id": chosen_id},
        )
        if resp_select.status_code != 201:
            error(f"Failed to submit final selection: {resp_select.text}")
        match_info = resp_select.json()
        match_id = match_info["id"]
        success(f"Challenger selected Kwame! Match #{match_id} created.")

        # --- Step 10: Match & Match Room Details ---
        log("STEP 10", "Fetching Match details and MatchRoom status...")
        resp_m_detail = client.get(f"/matches/{match_id}?user_id={female_id}")
        match_data = resp_m_detail.json()
        match_room_id = match_data["match_room_id"]
        success(f"Match #{match_id} linked to Private Match Room #{match_room_id}.")

        resp_mr = client.get(f"/match-rooms/{match_room_id}?user_id={female_id}")
        success(f"MatchRoom #{match_room_id} initial state: '{resp_mr.json()['state']}' (my_submitted={resp_mr.json()['my_contact_submitted']})")

        # --- Step 11: Contact Submission & Atomic Exchange ---
        log("STEP 11", "Submitting contact information and triggering atomic exchange...")
        # Challenger submits WhatsApp
        resp_sub_f = client.post(
            f"/match-rooms/{match_room_id}/contacts",
            json={"user_id": female_id, "whatsapp": "+233201234567", "snapchat": None},
        )
        success(f"Challenger submitted WhatsApp: {resp_sub_f.json()['state']}, partner={resp_sub_f.json()['partner']}")

        # Candidate submits Snapchat -> triggers exchange!
        resp_sub_m = client.post(
            f"/match-rooms/{match_room_id}/contacts",
            json={"user_id": chosen_id, "whatsapp": None, "snapchat": "kwame_snap"},
        )
        success(f"Kwame submitted Snapchat! Response: state={resp_sub_m.json()['state']}")
        success(f"Kwame received partner details: {resp_sub_m.json()['partner']}")

        # Challenger checks contacts -> receives Kwame's Snapchat!
        resp_f_contacts = client.get(f"/match-rooms/{match_room_id}/contacts?user_id={female_id}")
        success(f"Challenger retrieved partner details: {resp_f_contacts.json()['partner']}")

        # --- Step 12: Completed User Status & Queue Protection ---
        log("STEP 12", "Verifying final user completion state and queue protection...")
        resp_final_f = client.get(f"/users/me?user_id={female_id}")
        resp_final_m = client.get(f"/users/me?user_id={chosen_id}")
        success(f"Challenger final state: '{resp_final_f.json()['state']}'")
        success(f"Kwame final state: '{resp_final_m.json()['state']}'")

        print("\n\033[1;32m========================================================\033[0m")
        print("\033[1;32m  ALL MANUAL END-TO-END FLOW TESTS PASSED SUCCESSFULLY! \033[0m")
        print("\033[1;32m========================================================\033[0m\n")


if __name__ == "__main__":
    run_manual_tests()
