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


def error(msg: str):
    print(f"  \033[1;31m✗\033[0m {msg}")
    raise RuntimeError(msg)


async def test_live_websockets():
    async with httpx.AsyncClient(base_url=BASE_HTTP, timeout=120.0) as client:
        log("WS-SETUP", "Registering users and forming a live room...")
        # Register Female Challenger + 5 Males
        resp_f = await client.post("/queue/join", json={"name": "Esi (Challenger)", "gender": "female"})
        if resp_f.status_code != 201:
            error(f"Failed to join queue for female: {resp_f.text}")
        f_id = resp_f.json()["user_id"]

        male_ids = []
        for name in ["GuyA", "GuyB", "GuyC", "GuyD", "GuyE"]:
            resp_m = await client.post("/queue/join", json={"name": name, "gender": "male"})
            if resp_m.status_code != 201:
                error(f"Failed to join queue for {name}: {resp_m.text}")
            male_ids.append(resp_m.json()["user_id"])

        # Fetch room ID and participants
        me_resp = await client.get(f"/users/me?user_id={f_id}")
        room_id = me_resp.json()["room_id"]

        room_resp = await client.get(f"/rooms/{room_id}")
        room_data = room_resp.json()
        audience_ids = [p["user_id"] for p in room_data["participants"] if p["role"] == "audience"]
        first_aud_id = audience_ids[0]

        success(f"Live room #{room_id} formed for Challenger #{f_id} and audience: {audience_ids}")

        # Transition to QUESTIONING
        await client.post(f"/admin/rooms/{room_id}/transition", json={"state": "intro"})
        await client.post(f"/admin/rooms/{room_id}/transition", json={"state": "questioning"})

        # --- Test 1: Public Room WebSocket ---
        log("WS-TEST 1", f"Connecting Challenger #{f_id} and Audience #{first_aud_id} to Public Room WS...")
        uri_f = f"{BASE_WS}/ws/rooms/{room_id}/users/{f_id}"
        uri_m = f"{BASE_WS}/ws/rooms/{room_id}/users/{first_aud_id}"

        # Keep public room WS connections open throughout questioning and voting
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
                error(f"ERROR on ans 2: {r_a2.status_code} {r_a2.text}")
            _ = json.loads(await ws_f.recv()) # ans 2
            _ = json.loads(await ws_m.recv())
            _ = json.loads(await ws_f.recv()) # q3
            _ = json.loads(await ws_m.recv())

            r_a3 = await client.post(f"/rooms/{room_id}/answers", json={"user_id": f_id, "answer": "Ans 3"})
            if r_a3.status_code != 201:
                error(f"ERROR on ans 3: {r_a3.status_code} {r_a3.text}")
            _ = json.loads(await ws_f.recv()) # ans 3
            _ = json.loads(await ws_m.recv())

            # Receive room_state_changed -> voting_started on public WS
            st_vote_f = json.loads(await ws_f.recv())
            st_vote_m = json.loads(await ws_m.recv())
            success(f"Room state changed to '{st_vote_f['state']}' received on WS")

            v_start_f = json.loads(await ws_f.recv())
            v_start_m = json.loads(await ws_m.recv())
            success(f"Voting started broadcast received: {v_start_f['type']}, total voters={v_start_f['total_voters']}")

            # Fetch active audience members for room
            resp_room = await client.get(f"/rooms/{room_id}")
            audience_ids = [p["user_id"] for p in resp_room.json()["participants"] if p["role"] == "audience"]
            first_aud_id = audience_ids[0]

            # All vote YES -> Enter ONE_ON_ONE
            log("WS-TEST 1.2", "Audience members casting votes while WS is active...")
            for idx, a_id in enumerate(audience_ids, start=1):
                r_v = await client.post(f"/rooms/{room_id}/vote", json={"user_id": a_id, "vote": "yes"})
                if r_v.status_code != 201:
                    error(f"ERROR on vote for {a_id}: {r_v.status_code} {r_v.text}")
                # Consume vote progress events on WS
                _ = json.loads(await ws_f.recv())
                _ = json.loads(await ws_m.recv())

            # On 5th vote, finalization triggers:
            # 1. voting_completed
            ev_vc_f = json.loads(await ws_f.recv())
            ev_vc_m = json.loads(await ws_m.recv())
            success(f"Voting completed event received on WS: {ev_vc_f['type']}")

            # 2. room_state_changed (elimination)
            ev_elim_st_f = json.loads(await ws_f.recv())
            ev_elim_st_m = json.loads(await ws_m.recv())

            # 3. participants_eliminated
            ev_elim_f = json.loads(await ws_f.recv())
            ev_elim_m = json.loads(await ws_m.recv())

            # 4. room_state_changed (one_on_one)
            s_ooo_f = json.loads(await ws_f.recv())
            s_ooo_m = json.loads(await ws_m.recv())
            success(f"Room transitioned to ONE_ON_ONE via WS broadcast: {s_ooo_f['state']}")

            # Fetch active 1-on-1 session
            resp_ooo_cur = await client.get(f"/rooms/{room_id}/one-on-one/current")
            active_s = resp_ooo_cur.json()["active_session"]
            s1_id = active_s["id"]
            s1_aud = active_s["audience_id"]

            # --- Test 2: Filtered GameRoom 1-on-1 Messages ---
            log("WS-TEST 2", f"Testing Filtered 1-on-1 Channel for Session #{s1_id} (Audience #{s1_aud})...")
            # Consume one_on_one_started / one_on_one_progress on existing GameRoom sockets
            start_f = json.loads(await ws_f.recv())
            success(f"Challenger received one_on_one_started on GameRoom WS: session={start_f.get('session_id')}")
            _ = json.loads(await ws_f.recv())  # one_on_one_progress
            start_m = json.loads(await ws_m.recv())
            _ = json.loads(await ws_m.recv())  # one_on_one_progress

            # Audience submits private question
            await client.post(f"/rooms/{room_id}/one-on-one/{s1_id}/question", json={"user_id": s1_aud, "text": "What inspires you?"})
            q_ev_c = json.loads(await ws_f.recv())
            success(f"Challenger received private question via GameRoom WebSocket: '{q_ev_c.get('question') or q_ev_c.get('text')}'")
            _ = json.loads(await ws_m.recv())

            # Challenger submits private answer
            await client.post(f"/rooms/{room_id}/one-on-one/{s1_id}/answer", json={"user_id": f_id, "text": "Passionate and creative people."})
            a_ev_a = json.loads(await ws_m.recv())
            success(f"Audience received private answer via GameRoom WebSocket: '{a_ev_a.get('answer') or a_ev_a.get('text')}'")
            _ = json.loads(await ws_f.recv())

            # Audience votes YES
            await client.post(f"/rooms/{room_id}/one-on-one/{s1_id}/vote", json={"user_id": s1_aud, "vote": "yes"})
            comp_c = json.loads(await ws_f.recv())
            comp_a = json.loads(await ws_m.recv())
            success(f"Session completed event delivered privately to both via GameRoom WS: {comp_a['type']}")
            _ = json.loads(await ws_f.recv())  # one_on_one_progress
            _ = json.loads(await ws_m.recv())  # one_on_one_progress

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
            log("WS-TEST 2.1", "Challenger performs final selection...")
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
