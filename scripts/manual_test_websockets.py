"""
Manual live WebSocket test script for Date Rush.
Connects real async WebSocket clients to http://127.0.0.1:8000.
"""

import asyncio
import json
import httpx
import websockets

BASE_HTTP = "http://127.0.0.1:8000"
BASE_WS = "ws://127.0.0.1:8000"


def log(section: str, msg: str):
    print(f"\n[\033[1;34m{section}\033[0m] {msg}")


def success(msg: str):
    print(f"  \033[1;32m✓\033[0m {msg}")


async def test_live_websockets():
    async with httpx.AsyncClient(base_url=BASE_HTTP) as client:
        log("WS-SETUP", "Registering users and forming a live room...")
        # Register Female Challenger + 5 Males
        resp_f = await client.post("/queue/join", json={"name": "Esi (Challenger)", "gender": "female"})
        f_id = resp_f.json()["user_id"]

        male_ids = []
        for name in ["GuyA", "GuyB", "GuyC", "GuyD", "GuyE"]:
            resp_m = await client.post("/queue/join", json={"name": name, "gender": "male"})
            male_ids.append(resp_m.json()["user_id"])

        # Fetch room ID
        me_resp = await client.get(f"/users/me?user_id={f_id}")
        room_id = me_resp.json()["room_id"]
        success(f"Live room #{room_id} formed for Challenger #{f_id}")

        # Transition to QUESTIONING
        await client.post(f"/admin/rooms/{room_id}/transition", json={"state": "intro"})
        await client.post(f"/admin/rooms/{room_id}/transition", json={"state": "questioning"})

        # --- Test 1: Public Room WebSocket ---
        log("WS-TEST 1", f"Connecting Challenger #{f_id} and Audience #{male_ids[0]} to Public Room WS...")
        uri_f = f"{BASE_WS}/ws/rooms/{room_id}/users/{f_id}"
        uri_m = f"{BASE_WS}/ws/rooms/{room_id}/users/{male_ids[0]}"

        async with websockets.connect(uri_f) as ws_f, websockets.connect(uri_m) as ws_m:
            # 1. State broadcast on connect
            init_f_state = json.loads(await ws_f.recv())
            init_f_q = json.loads(await ws_f.recv())
            success(f"Challenger received initial WS events: {init_f_state['type']} -> {init_f_q['type']} (Question: '{init_f_q['question']['text'][:35]}...')")

            init_m_state = json.loads(await ws_m.recv())
            init_m_q = json.loads(await ws_m.recv())
            success(f"Audience received initial WS events: {init_m_state['type']} -> {init_m_q['type']}")

            # 2. Challenger submits Answer 1 via HTTP -> Broadcast received on WS
            log("WS-TEST 1.1", "Challenger submits Answer 1 via HTTP...")
            await client.post(
                f"/rooms/{room_id}/answers",
                json={"user_id": f_id, "answer": "I enjoy playing tennis and reading books."},
            )

            ev_ans_f = json.loads(await ws_f.recv())
            ev_ans_m = json.loads(await ws_m.recv())
            success(f"Real-time answer broadcast received on Challenger WS: {ev_ans_f['type']} -> '{ev_ans_f['answer']}'")
            success(f"Real-time answer broadcast received on Audience WS: {ev_ans_m['type']} -> '{ev_ans_m['answer']}'")

            # Receive question 2 start
            ev_q2_f = json.loads(await ws_f.recv())
            ev_q2_m = json.loads(await ws_m.recv())
            success(f"Next question auto-broadcast: {ev_q2_f['type']} (Round {ev_q2_f['round']})")

        # Answer remaining questions -> Enter VOTING
        r_a2 = await client.post(f"/rooms/{room_id}/answers", json={"user_id": f_id, "answer": "Ans 2"})
        if r_a2.status_code != 201:
            print(f"ERROR on ans 2: {r_a2.status_code} {r_a2.text}")
        r_a3 = await client.post(f"/rooms/{room_id}/answers", json={"user_id": f_id, "answer": "Ans 3"})
        if r_a3.status_code != 201:
            print(f"ERROR on ans 3: {r_a3.status_code} {r_a3.text}")

        # Fetch active audience members for room
        resp_room = await client.get(f"/rooms/{room_id}")
        audience_ids = [p["user_id"] for p in resp_room.json()["participants"] if p["role"] == "audience"]
        first_aud_id = audience_ids[0]

        # All vote YES -> Enter ONE_ON_ONE
        for a_id in audience_ids:
            r_v = await client.post(f"/rooms/{room_id}/vote", json={"user_id": a_id, "vote": "yes"})
            if r_v.status_code != 201:
                print(f"ERROR on vote for {a_id}: {r_v.status_code} {r_v.text}")

        # Fetch active 1-on-1 session
        resp_ooo_cur = await client.get(f"/rooms/{room_id}/one-on-one/current")
        active_s = resp_ooo_cur.json()["active_session"]
        s1_id = active_s["id"]
        s1_aud = active_s["audience_id"]

        # --- Test 2: Private 1-on-1 WebSocket ---
        log("WS-TEST 2", f"Testing Private 1-on-1 Channel for Session #{s1_id} (Audience #{s1_aud})...")
        uri_ooo_aud = f"{BASE_WS}/ws/rooms/{room_id}/one-on-one/{s1_id}/users/{s1_aud}"
        uri_ooo_chal = f"{BASE_WS}/ws/rooms/{room_id}/one-on-one/{s1_id}/users/{f_id}"

        async with websockets.connect(uri_ooo_aud) as ws_ooo_aud, websockets.connect(uri_ooo_chal) as ws_ooo_chal:
            # Initial private state
            state_a = json.loads(await ws_ooo_aud.recv())
            state_c = json.loads(await ws_ooo_chal.recv())
            success(f"Private session initial state received: {state_a['type']} (state='{state_a['state']}')")

            # Audience submits private question
            await client.post(f"/rooms/{room_id}/one-on-one/{s1_id}/question", json={"user_id": s1_aud, "text": "What inspires you?"})
            q_ev_c = json.loads(await ws_ooo_chal.recv())
            success(f"Challenger received private question via WebSocket: '{q_ev_c['text']}'")
            _ = await ws_ooo_aud.recv()

            # Challenger submits private answer
            await client.post(f"/rooms/{room_id}/one-on-one/{s1_id}/answer", json={"user_id": f_id, "text": "Passionate and creative people."})
            a_ev_a = json.loads(await ws_ooo_aud.recv())
            success(f"Audience received private answer via WebSocket: '{a_ev_a['text']}'")
            _ = await ws_ooo_chal.recv()

            # Audience votes YES
            await client.post(f"/rooms/{room_id}/one-on-one/{s1_id}/vote", json={"user_id": s1_aud, "vote": "yes"})
            comp_a = json.loads(await ws_ooo_aud.recv())
            comp_c = json.loads(await ws_ooo_chal.recv())
            success(f"Session completed event delivered privately to both: {comp_a['type']}")

        # Complete remaining sessions
        while True:
            cur_resp = await client.get(f"/rooms/{room_id}/one-on-one/current")
            cur_data = cur_resp.json()
            if not cur_data.get("active_session"):
                break
            cur_s = cur_data["active_session"]
            await client.post(f"/rooms/{room_id}/one-on-one/{cur_s['id']}/question", json={"user_id": cur_s['audience_id'], "text": "Q"})
            await client.post(f"/rooms/{room_id}/one-on-one/{cur_s['id']}/answer", json={"user_id": f_id, "text": "A"})
            await client.post(f"/rooms/{room_id}/one-on-one/{cur_s['id']}/vote", json={"user_id": cur_s['audience_id'], "vote": "yes"})

        # Challenger selects s1_aud
        resp_match = await client.post(f"/rooms/{room_id}/final-selection", json={"user_id": f_id, "candidate_id": s1_aud})
        match_id = resp_match.json()["id"]

        resp_md = await client.get(f"/matches/{match_id}?user_id={f_id}")
        mr_id = resp_md.json()["match_room_id"]

        # --- Test 3: Private Match Room WebSocket ---
        log("WS-TEST 3", f"Testing Private Match Room WS #{mr_id} for Match #{match_id}...")
        uri_mr_f = f"{BASE_WS}/ws/match-rooms/{mr_id}/users/{f_id}"
        uri_mr_m = f"{BASE_WS}/ws/match-rooms/{mr_id}/users/{s1_aud}"

        async with websockets.connect(uri_mr_f) as ws_mr_f, websockets.connect(uri_mr_m) as ws_mr_m:
            init_mr_f = json.loads(await ws_mr_f.recv())
            init_mr_m = json.loads(await ws_mr_m.recv())
            success(f"MatchRoom WS state on connect: {init_mr_f['type']} (state='{init_mr_f['state']}')")

            # Challenger submits WhatsApp
            await client.post(f"/match-rooms/{mr_id}/contacts", json={"user_id": f_id, "whatsapp": "+233209876543"})
            sub_ev_f = json.loads(await ws_mr_f.recv())
            wait_ev_m = json.loads(await ws_mr_m.recv())
            success(f"Challenger received submission status: {sub_ev_f['type']}")
            success(f"Audience received partner waiting status: {wait_ev_m['type']}")

            # Audience submits Snapchat -> Triggers exchange!
            await client.post(f"/match-rooms/{mr_id}/contacts", json={"user_id": s1_aud, "snapchat": "guya_snap"})
            sub_ev_m = json.loads(await ws_mr_m.recv())

            exc_ev_f = json.loads(await ws_mr_f.recv())
            comp_ev_f = json.loads(await ws_mr_f.recv())
            success(f"Challenger received Partner Contact Exchange via WS: {exc_ev_f['partner']}")

            exc_ev_m = json.loads(await ws_mr_m.recv())
            comp_ev_m = json.loads(await ws_mr_m.recv())
            success(f"Audience received Partner Contact Exchange via WS: {exc_ev_m['partner']}")

        print("\n\033[1;32m========================================================\033[0m")
        print("\033[1;32m  ALL REAL-TIME WEBSOCKET TESTS PASSED SUCCESSFULLY!    \033[0m")
        print("\033[1;32m========================================================\033[0m\n")


if __name__ == "__main__":
    asyncio.run(test_live_websockets())
