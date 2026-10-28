from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from owner_agent.app import create_app
from owner_agent.calendar import event_id_for
from shared.protocol import digest, expires_in, sign_message, utc_now
from shared.schema import TASKS, validate_payload


class World:
    def __init__(self, tmp_path):
        self.ingested = []
        self.proposals = {}
        self.current = None
        self.configs = {}
        self.apps = {}
        self.clients = {}
        self.tokens = {}
        self.transport = httpx.MockTransport(self.broker)
        for index, owner in enumerate(("asha", "ravi", "leena")):
            config = {"owner_id": owner, "port": 4311 + index, "broker_url": "http://127.0.0.1:4302", "broker_ingest_token": "broker-ingest-" + "b" * 32, "service_token": owner + "-service-" + "s" * 32, "pair_code": owner + "-pair-" + "p" * 32, "data_dir": str(tmp_path / owner), "broker_transport": self.transport}
            self.configs[owner] = config
            self.apps[owner] = create_app(config)
            self.clients[owner] = TestClient(self.apps[owner], base_url=f"http://127.0.0.1:{4311 + index}")
            self.tokens[owner] = self.clients[owner].post("/api/session", headers={"Origin": self.origin(owner)}, json={"pair_code": config["pair_code"]}).json()["token"]
            response = self.post(owner, "/api/release", {"expected_revision": 1, "allow_inference": True})
            assert response.status_code == 200, response.text
        self.make_proposal("proposal-test-0001")

    def broker(self, request):
        assert request.headers["authorization"] == "Bearer broker-ingest-" + "b" * 32
        if request.method == "POST":
            payload = json.loads(request.content)
            self.ingested.append((request.url.path, payload["message"]))
            validate_payload(payload["message"]["body"]["type"], payload["message"]["body"]["payload"])
            return httpx.Response(200, json={"accepted": True})
        proposal = self.current if request.url.path == "/v1/current" else self.proposals.get(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, json={"proposal": proposal, "proposal_digest": digest(proposal) if proposal else None, "manifest_digest": digest(proposal["actions"]) if proposal else None})

    def origin(self, owner):
        return f"http://127.0.0.1:{self.configs[owner]['port']}"

    def headers(self, owner):
        return {"Origin": self.origin(owner), "Authorization": "Bearer " + self.tokens[owner]}

    def service(self, owner):
        return {"Authorization": "Bearer " + self.configs[owner]["service_token"]}

    def post(self, owner, path, body):
        return self.clients[owner].post(path, headers=self.headers(owner), json=body)

    def coord(self, owner, path, body):
        return self.clients[owner].post("/coordination/" + path, headers=self.service(owner), json=body)

    def make_proposal(self, proposal_id):
        allocations = [("prepare", "asha", 740, 760), ("outbound", "ravi", 790, 830), ("accompany", "leena", 830, 920), ("return", "ravi", 920, 960), ("handoff", "asha", 960, 975)]
        assignments, actions, refs = [], [], []
        states = {o: a.state.owner.vault.read() for o, a in self.apps.items()}
        for owner, state in states.items():
            offer = state["release"]["body"]["payload"]["offer"]
            refs.append({"owner_id": owner, "offer_id": offer["offer_id"], "revision": offer["revision"], "constraint_revision": state["constraint_revision"], "consent_revision": state["consent_revision"]})
        for task_id, owner, start, end in allocations:
            offer = states[owner]["release"]["body"]["payload"]["offer"]
            assignments.append({"task_id": task_id, "owner_id": owner, "start": start, "end": end, "offer_id": offer["offer_id"], "offer_revision": offer["revision"]})
            action_id = f"{proposal_id}-{task_id}"
            actions.append({"action_id": action_id, "owner_id": owner, "task_id": task_id, "label": next(t["label"] for t in TASKS if t["task_id"] == task_id), "start": start, "end": end, "date": "2026-11-02", "timezone": "Asia/Kolkata", "adapter": "local-calendar", "event_id": event_id_for(action_id), "expected_absent": True})
        proposal = {"proposal_id": proposal_id, "version": 1, "goal_id": "dev-appointment", "goal_revision": 1, "date": "2026-11-02", "timezone": "Asia/Kolkata", "created_at": utc_now(), "expires_at": expires_in(7200), "tasks": deepcopy(TASKS), "assignments": assignments, "actions": actions, "offer_refs": refs, "solver": {"status": "OPTIMAL", "objectives": [], "settings": {}}, "checker": {"valid": True, "checks": [], "errors": []}, "model_receipt_id": None, "explanation": "Authored test proposal, independently checked by each owner."}
        self.proposals[proposal_id] = proposal
        self.current = proposal
        return proposal

    def approved(self, owner="asha", proposal=None):
        proposal = proposal or self.current
        response = self.post(owner, "/api/approve", {"proposal_id": proposal["proposal_id"], "expected_version": proposal["version"]})
        assert response.status_code == 200, response.text
        return response.json()["approval"]

    def prepared(self, owner="asha", proposal=None, approval=None):
        proposal = proposal or self.current
        response = self.coord(owner, "prepare", {"proposal": proposal, "approval": approval or self.approved(owner, proposal)})
        assert response.status_code == 200, response.text
        result = response.json()
        action = next(a for a in proposal["actions"] if a["owner_id"] == owner)
        return {"proposal_id": proposal["proposal_id"], "action_id": action["action_id"], "reservation_id": result["reservation_id"], "fence": result["fence"]}


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_session_origin_scopes_and_encrypted_private_canaries(world):
    client = world.clients["asha"]
    assert client.get("/api/state").status_code == 401
    assert client.get("/meta").status_code == 200
    assert client.post("/api/session", json={"pair_code": world.configs["asha"]["pair_code"]}).status_code == 403
    assert client.post("/api/session", headers={"Origin": world.origin("asha")}, json={"pair_code": "localhost"}).status_code == 401
    assert client.get("/api/state", headers=world.headers("ravi")).status_code == 403
    assert client.get("/api/state", headers=world.service("asha")).status_code == 401
    assert client.get("/api/state", headers={"Authorization": "Bearer " + world.tokens["ravi"]}).status_code == 401
    assert client.get("/coordination/status", headers=world.service("ravi")).status_code == 401
    assert client.get("/coordination/status", headers={**world.service("asha"), "Origin": world.origin("asha")}).status_code == 403
    state = client.get("/api/state", headers=world.headers("asha")).json()
    assert "CG_PRIVATE_ASHA" in json.dumps(state)
    assert "CG_PRIVATE_RAVI" not in json.dumps(state)
    assert "CG_PRIVATE_" not in json.dumps(world.ingested)
    public = client.get("/coordination/status", headers=world.service("asha")).text
    assert "CG_PRIVATE_" not in public
    vault = world.apps["asha"].state.owner.vault
    assert b"CG_PRIVATE_" not in vault.path.read_bytes()
    assert vault.path.stat().st_mode & 0o777 == 0o600
    assert vault.directory.stat().st_mode & 0o777 == 0o700
    assert "set-cookie" not in client.get("/api/state", headers=world.headers("asha")).headers


def test_exact_disclosure_and_private_persistent_correction(world):
    client = world.clients["ravi"]
    before = client.get("/api/release-preview?allow_inference=0", headers=world.headers("ravi")).json()
    assert before["recipients"]["inference"] == []
    assert before["offer"]["preference_cost"] == 1
    assert before["fields"] == ["owner_id", "capabilities", "task_ids", "start", "end", "capacity", "preference_cost", "constraint_revision"]
    payload = {"expected_revision": 1, "availability_start": 780, "availability_end": 835, "task_ids": ["outbound"], "ask_before_driving": True, "private_note": "CG_PRIVATE_CORRECTION_48"}
    changed = world.post("ravi", "/api/preferences", payload)
    assert changed.status_code == 200, changed.text
    assert changed.json()["constraint_revision"] == 2
    assert world.post("ravi", "/api/preferences", payload).status_code == 409
    restored = create_app(world.configs["ravi"])
    state = restored.state.owner.vault.read()
    assert state["preferences"]["private_note"] == "CG_PRIVATE_CORRECTION_48"
    assert state["preferences"]["task_ids"] == ["outbound"]
    assert state["corrections"][-1]["to_revision"] == 2
    assert state["skills"][0]["required_approvals"]
    assert state["release"] is None and not state["approvals"]
    assert "CG_PRIVATE_CORRECTION_48" not in json.dumps(world.ingested)
    assert world.ingested[-1][0] == "/v1/withdrawals"


def test_exact_approval_manifest_and_owner_veto(world):
    approved = world.approved()
    payload = approved["body"]["payload"]
    assert payload["proposal_digest"] == digest(world.current)
    assert payload["manifest_digest"] == digest(world.current["actions"])
    assert payload["compensation_policy"] == "delete-only-unchanged-created-events"
    tampered = deepcopy(world.current)
    tampered["actions"][0]["label"] += " changed"
    assert world.coord("asha", "prepare", {"proposal": tampered, "approval": approved}).status_code == 409
    tampered = deepcopy(world.current)
    tampered["assignments"][0]["end"] += 1
    assert world.coord("asha", "prepare", {"proposal": tampered, "approval": approved}).status_code == 409
    # A valid, newly signed but never owner-approved message cannot obtain authority.
    forged = deepcopy(approved)
    forged["body"]["nonce"] = "new-nonce-" + "n" * 30
    forged = sign_message(world.apps["asha"].state.owner.identity["private_key"], forged["body"])
    assert world.coord("asha", "prepare", {"proposal": world.current, "approval": forged}).status_code == 409
    engine = world.apps["asha"].state.owner
    with engine.vault.transaction() as db:
        state = engine.vault.read(db)
        state["private_calendar"].append({"source_id": "late-conflict", "title": "CG_PRIVATE_LATE", "start": 740, "end": 760, "date": "2026-11-02", "timezone": "Asia/Kolkata"})
        engine.vault.write(db, state)
    assert world.coord("asha", "prepare", {"proposal": world.current, "approval": approved}).status_code == 409


def test_real_calendar_write_duplicate_restart_reconcile_and_ics(world):
    request = world.prepared()
    first = world.coord("asha", "dispatch", request)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "VERIFIED"
    event = world.apps["asha"].state.owner.calendar.get(first.json()["event_id"])
    assert event and event["summary"] == TASKS[0]["label"]
    for _ in range(3):
        assert world.coord("asha", "dispatch", request).json()["status"] == "VERIFIED"
    assert len(world.apps["asha"].state.owner.calendar.list()) == 1
    world.apps["asha"] = create_app(world.configs["asha"])
    world.clients["asha"] = TestClient(world.apps["asha"], base_url=world.origin("asha"))
    assert world.coord("asha", "reconcile", request).json()["status"] == "VERIFIED"
    exported = world.clients["asha"].get("/api/calendar.ics", headers=world.headers("asha"))
    assert exported.status_code == 200
    assert "BEGIN:VEVENT" in exported.text and event["event_id"] in exported.text
    assert "CG_PRIVATE_" not in exported.text
    assert world.coord("asha", "compensate", {"action_id": request["action_id"]}).json()["status"] == "CANCELLED"
    assert not world.apps["asha"].state.owner.calendar.list()


@pytest.mark.parametrize("mode,expected", [("fail_before_write", "FAILED"), ("timeout_after_write", "AMBIGUOUS"), ("conflict_before_write", "NEEDS_ATTENTION")])
def test_actual_fault_recovery(world, mode, expected):
    request = world.prepared()
    assert world.post("asha", "/api/fault", {"mode": mode}).status_code == 200
    result = world.coord("asha", "dispatch", request)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == expected
    count = len(world.apps["asha"].state.owner.calendar.list())
    assert count == (0 if mode == "fail_before_write" else 1)
    world.post("asha", "/api/fault", {"mode": "none"})
    recovered = world.coord("asha", "reconcile", request).json()
    assert recovered["status"] == ("NEEDS_ATTENTION" if mode == "conflict_before_write" else "VERIFIED")
    assert len(world.apps["asha"].state.owner.calendar.list()) == 1


def test_user_edit_survives_compensation_and_is_not_disclosed(world):
    request = world.prepared()
    done = world.coord("asha", "dispatch", request).json()
    changed = world.post("asha", f"/api/calendar/{done['event_id']}/edit", {"summary": "CG_PRIVATE_USER_EDIT"})
    assert changed.status_code == 200
    assert changed.json()["etag"] != done["etag"]
    result = world.coord("asha", "compensate", {"action_id": request["action_id"]})
    assert result.json()["status"] == "NEEDS_ATTENTION"
    assert result.json()["remaining_effect"]["user_edited"] is True
    assert "etag" not in result.json()["remaining_effect"]
    assert result.json()["etag"] == done["etag"]
    assert changed.json()["etag"] not in result.text
    private_event = world.apps["asha"].state.owner.calendar.get(done["event_id"])
    assert private_event["etag"] == changed.json()["etag"]
    private_state = world.clients["asha"].get("/api/state", headers=world.headers("asha")).json()
    assert private_state["calendar_events"][0]["etag"] == changed.json()["etag"]
    assert "CG_PRIVATE_" not in result.text
    assert world.apps["asha"].state.owner.calendar.get(done["event_id"])["summary"] == "CG_PRIVATE_USER_EDIT"


def test_withdrawal_in_intent_transmission_gap_cancels_durably(world):
    request = world.prepared()
    world.post("asha", "/api/fault", {"mode": "pause_before_send"})
    result = world.coord("asha", "dispatch", request)
    assert result.json()["status"] == "PAUSED"
    assert result.json()["intent"]["authorized_at"]
    assert result.json()["intent"]["transmitted_at"] is None
    withdrawal = world.post("asha", "/api/withdraw", {"expected_revision": 1})
    assert withdrawal.status_code == 200, withdrawal.text
    world.apps["asha"] = create_app(world.configs["asha"])
    world.clients["asha"] = TestClient(world.apps["asha"], base_url=world.origin("asha"))
    world.post("asha", "/api/fault", {"mode": "none"})
    assert world.coord("asha", "dispatch", request).json()["status"] == "CANCELLED"
    assert not world.apps["asha"].state.owner.calendar.list()
    assert world.coord("asha", "dispatch", {**request, "fence": request["fence"] + 1}).status_code == 409


def test_withdrawal_after_timeout_reconciles_and_removes_actual_effect(world):
    request = world.prepared()
    world.post("asha", "/api/fault", {"mode": "timeout_after_write"})
    assert world.coord("asha", "dispatch", request).json()["status"] == "AMBIGUOUS"
    result = world.post("asha", "/api/withdraw", {"expected_revision": 1})
    assert result.status_code == 200
    assert result.json()["effects"][0]["status"] == "CANCELLED"
    assert not world.apps["asha"].state.owner.calendar.list()


def test_simultaneous_reservations_are_serialized(world):
    p1 = world.current
    a1 = world.approved(proposal=p1)
    p2 = world.make_proposal("proposal-test-0002")
    a2 = world.approved(proposal=p2)
    def prepare(pair):
        proposal, approval = pair
        return world.coord("asha", "prepare", {"proposal": proposal, "approval": approval})
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(prepare, [(p1, a1), (p2, a2)]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    chosen = next(r for r in responses if r.status_code == 200).json()
    assert chosen["fence"] == 1


def test_lease_expiry_and_revoked_signing_key_block_fresh_transport(world):
    request = world.prepared()
    engine = world.apps["asha"].state.owner
    engine.config["revoked_keys"] = [engine.identity["key_id"]]
    assert world.coord("asha", "dispatch", request).status_code == 409
    assert not engine.calendar.list()
    engine.config["revoked_keys"] = []
    with engine.vault.transaction() as db:
        db.execute("UPDATE reservations SET lease_expires_at=?", ("2020-01-01T00:00:00Z",))
    assert world.coord("asha", "dispatch", request).status_code == 409
    assert not engine.calendar.list()


def test_new_fence_after_expired_reservation_blocks_stale_worker(world):
    request = world.prepared()
    engine = world.apps["asha"].state.owner
    with engine.vault.transaction() as db:
        db.execute("UPDATE reservations SET lease_expires_at=?", ("2020-01-01T00:00:00Z",))
    renewed = world.prepared()
    assert renewed["fence"] > request["fence"]
    assert world.coord("asha", "dispatch", request).status_code == 409
    assert world.coord("asha", "dispatch", renewed).json()["status"] == "VERIFIED"


@contextmanager
def serve(app, sock):
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


def test_real_http_three_separate_owner_apps_deny_other_capabilities(tmp_path):
    from contextlib import ExitStack
    with ExitStack() as stack:
        configs, clients = {}, {}
        for owner in ("asha", "ravi", "leena"):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sock.listen(128)
            port = sock.getsockname()[1]
            config = {"owner_id": owner, "port": port, "broker_url": "http://127.0.0.1:1", "broker_ingest_token": "b" * 32, "service_token": owner + "-" + "s" * 32, "pair_code": owner + "-" + "p" * 32, "data_dir": str(tmp_path / owner)}
            configs[owner] = config
            app = create_app(config)
            stack.enter_context(serve(app, sock))
            clients[owner] = stack.enter_context(httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False))
        tokens = {}
        for owner, client in clients.items():
            response = client.post("/api/session", headers={"Origin": str(client.base_url).rstrip("/")}, json={"pair_code": configs[owner]["pair_code"]})
            assert response.status_code == 200
            tokens[owner] = response.json()["token"]
            assert "set-cookie" not in response.headers
        for owner, client in clients.items():
            for other in configs:
                if owner == other:
                    continue
                assert client.get("/api/state", headers={"Authorization": "Bearer " + tokens[other]}).status_code == 401
                assert client.get("/coordination/status", headers={"Authorization": "Bearer " + configs[other]["service_token"]}).status_code == 401
            broker = {"Authorization": "Bearer " + "b" * 32}
            assert client.get("/api/state", headers=broker).status_code == 401
            assert client.post("/api/approve", headers={**broker, "Origin": str(client.base_url).rstrip("/")}, json={"proposal_id": "proposal-test", "expected_version": 1}).status_code == 401
            remove_path = "/api/calendar/cg-auth-boundary/remove"
            remove_body = {"expected_etag": '"reviewed-etag"', "confirmation": "remove-this-local-event"}
            assert client.post(remove_path, headers={**broker, "Origin": str(client.base_url).rstrip("/")}, json=remove_body).status_code == 401
            for other in configs:
                if owner != other:
                    assert client.post(remove_path, headers={"Authorization": "Bearer " + tokens[other], "Origin": str(client.base_url).rstrip("/")}, json=remove_body).status_code == 401


def test_calendar_ics_unicode_folding_escaping_and_round_trip(world):
    from icalendar import Calendar
    request = world.prepared()
    done = world.coord("asha", "dispatch", request).json()
    summary = "आशा; family, notes\\backslash\r\nA real new line " + "é🙂" * 70
    assert world.post("asha", f"/api/calendar/{done['event_id']}/edit", {"summary": summary}).status_code == 200
    response = world.clients["asha"].get("/api/calendar.ics", headers=world.headers("asha"))
    assert response.status_code == 200
    payload = response.content
    assert b"\r\n" in payload
    assert all(len(line) <= 75 for line in payload.split(b"\r\n"))
    parsed = Calendar.from_ical(payload)
    event = parsed.walk("VEVENT")[0]
    assert str(event["summary"]).replace("\r\n", "\n") == summary.replace("\r\n", "\n")
    assert b"\\;" in payload and b"\\," in payload and b"\\\\" in payload and b"\\n" in payload
    assert event.decoded("dtend") > event.decoded("dtstart")


def test_cancel_releases_prepared_reservation_and_never_reuses_approval(world):
    request = world.prepared()
    cancelled = world.coord("asha", "cancel", {"proposal_id": request["proposal_id"]})
    assert cancelled.status_code == 200
    assert cancelled.json() == {"actions": [], "reservation_cancelled": True}
    assert world.coord("asha", "dispatch", request).status_code == 409
    replacement = world.make_proposal("proposal-replacement-1")
    renewed = world.prepared(proposal=replacement)
    assert renewed["fence"] > request["fence"]
    assert world.coord("asha", "dispatch", renewed).json()["status"] == "VERIFIED"


def test_cancel_applied_proposal_preserves_only_user_edited_effect(world):
    request = world.prepared()
    result = world.coord("asha", "dispatch", request).json()
    world.post("asha", f"/api/calendar/{result['event_id']}/edit", {"summary": "CG_PRIVATE_CANCELLATION_EDIT"})
    cancelled = world.coord("asha", "cancel", {"proposal_id": request["proposal_id"]})
    assert cancelled.status_code == 200
    assert cancelled.json()["actions"][0]["status"] == "NEEDS_ATTENTION"
    assert "CG_PRIVATE_" not in cancelled.text
    assert world.apps["asha"].state.owner.calendar.get(result["event_id"])
    assert world.coord("asha", "cancel", {"proposal_id": "unknown-proposal"}).status_code == 404


def test_exact_release_preview_digest_and_idempotent_retry(world):
    client = world.clients["asha"]
    before = world.apps["asha"].state.owner.vault.read()
    same = client.get("/api/release-preview?allow_inference=1", headers=world.headers("asha")).json()
    assert same == before["release"]["body"]["payload"]
    released = world.post("asha", "/api/release", {"expected_revision": 1, "allow_inference": True, "preview_digest": digest(same)})
    assert released.status_code == 200
    assert released.json()["release"] == before["release"]
    changed = client.get("/api/release-preview?allow_inference=0", headers=world.headers("asha")).json()
    assert changed["recipients"]["inference"] == []
    assert world.post("asha", "/api/release", {"expected_revision": 1, "allow_inference": False, "preview_digest": digest(same)}).status_code == 409
    assert world.post("asha", "/api/release", {"expected_revision": 1, "allow_inference": False, "preview_digest": digest(changed)}).status_code == 200


@pytest.mark.parametrize("expired", ["grant", "approval", "proposal"])
def test_each_authority_expiry_rechecked_after_pause_and_restart(world, expired):
    request = world.prepared()
    world.post("asha", "/api/fault", {"mode": "pause_before_send"})
    assert world.coord("asha", "dispatch", request).json()["status"] == "PAUSED"
    engine = world.apps["asha"].state.owner
    with engine.vault.transaction() as db:
        state = engine.vault.read(db)
        if expired == "grant":
            body = deepcopy(state["release"]["body"])
            body.update(issued_at="2020-01-01T00:00:00Z", expires_at="2020-01-02T00:00:00Z")
            state["release"] = sign_message(engine.identity["private_key"], body)
        else:
            row = db.execute("SELECT payload FROM reservations WHERE reservation_id=?", (request["reservation_id"],)).fetchone()
            saved = json.loads(row["payload"])
            if expired == "approval":
                body = deepcopy(saved["approval"]["body"])
                body.update(issued_at="2020-01-01T00:00:00Z", expires_at="2020-01-02T00:00:00Z")
                saved["approval"] = sign_message(engine.identity["private_key"], body)
                state["approvals"] = [saved["approval"]]
            else:
                saved["proposal"]["expires_at"] = "2020-01-02T00:00:00Z"
            db.execute("UPDATE reservations SET payload=? WHERE reservation_id=?", (json.dumps(saved), request["reservation_id"]))
        engine.vault.write(db, state)
    world.apps["asha"] = create_app(world.configs["asha"])
    world.clients["asha"] = TestClient(world.apps["asha"], base_url=world.origin("asha"))
    world.post("asha", "/api/fault", {"mode": "none"})
    assert world.coord("asha", "dispatch", request).status_code == 409
    assert not world.apps["asha"].state.owner.calendar.list()


def test_concurrent_withdrawal_dispatch_has_no_remaining_unauthorized_effect(tmp_path):
    for iteration in range(12):
        world = World(tmp_path / str(iteration))
        request = world.prepared()
        barrier = threading.Barrier(2)
        def dispatch():
            barrier.wait()
            return world.coord("asha", "dispatch", request)
        def withdraw():
            barrier.wait()
            return world.post("asha", "/api/withdraw", {"expected_revision": 1})
        with ThreadPoolExecutor(max_workers=2) as executor:
            send = executor.submit(dispatch)
            revoke = executor.submit(withdraw)
            result, withdrawn = send.result(), revoke.result()
        assert withdrawn.status_code == 200
        assert result.status_code in (200, 409)
        assert not world.apps["asha"].state.owner.calendar.list()
        assert all(event["status"] == "CANCELLED" for event in world.apps["asha"].state.owner.events())


def test_independent_owner_travel_check_ignores_forged_checker_flag(world, monkeypatch):
    # A different confirmed timing fixture exposes travel; the standard appointment
    # happens to satisfy this rule exactly at its fixed forty-minute gap.
    import owner_agent.engine as module
    confirmed = deepcopy(TASKS)
    confirmed[2].update(duration=110, latest=940)
    confirmed[3].update(duration=20, earliest=940)
    monkeypatch.setattr(module, "TASKS", confirmed)
    proposal = world.current
    proposal["tasks"] = confirmed
    for assignment in proposal["assignments"]:
        if assignment["task_id"] == "accompany":
            assignment["end"] = 940
        if assignment["task_id"] == "return":
            assignment["start"] = 940
        if assignment["task_id"] == "handoff":
            state = world.apps["leena"].state.owner.vault.read()
            offer = state["release"]["body"]["payload"]["offer"]
            assignment.update(owner_id="leena", offer_id=offer["offer_id"], offer_revision=offer["revision"])
    for action in proposal["actions"]:
        if action["task_id"] == "accompany":
            action["end"] = 940
        if action["task_id"] == "return":
            action["start"] = 940
        if action["task_id"] == "handoff":
            action["owner_id"] = "leena"
    proposal["checker"]["valid"] = True
    result = world.post("leena", "/api/approve", {"proposal_id": proposal["proposal_id"], "expected_version": 1})
    assert result.status_code == 409
    assert "Travel time" in result.json()["detail"]


def test_durable_outbox_recovers_lost_ack_by_exact_message_redelivery(world):
    engine = world.apps["asha"].state.owner
    commits, attempts = {}, []
    def flaky_broker(request):
        if request.method == "GET":
            return world.broker(request)
        message = json.loads(request.content)["message"]
        key = message["body"]["message_id"]
        attempts.append(message)
        if key not in commits:
            commits[key] = message
            raise httpx.ReadTimeout("Injected acknowledgement lost after remote commit", request=request)
        assert commits[key] == message
        return httpx.Response(200, json={"accepted": True})
    engine.config["broker_transport"] = httpx.MockTransport(flaky_broker)
    result = world.post("asha", "/api/release", {"expected_revision": 1, "allow_inference": False})
    assert result.status_code == 503
    saved = engine.vault.read()
    assert saved["release"]["body"]["payload"]["recipients"]["inference"] == []
    with engine.vault.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM outbox WHERE delivered=0").fetchone()[0] == 1
    state = world.clients["asha"].get("/api/state", headers=world.headers("asha"))
    assert state.status_code == 200
    assert state.json()["coordinator_available"] is True
    assert state.json()["coordination_pending"] == 0
    assert len(attempts) == 2 and attempts[0] == attempts[1]


def test_events_endpoint_independently_reads_calendar_without_resending(world):
    request = world.prepared()
    result = world.coord("asha", "dispatch", request).json()
    client = world.clients["asha"]
    endpoint = "/coordination/events?proposal_id=" + request["proposal_id"]
    events = client.get(endpoint, headers=world.service("asha")).json()["events"]
    assert events[0]["status"] == "VERIFIED"
    world.post("asha", f"/api/calendar/{result['event_id']}/edit", {"summary": "CG_PRIVATE_OBSERVATIONAL_EDIT"})
    events = client.get(endpoint, headers=world.service("asha"))
    assert events.json()["events"][0]["status"] == "NEEDS_ATTENTION"
    assert "CG_PRIVATE_" not in events.text
    event = world.apps["asha"].state.owner.calendar.get(result["event_id"])
    assert event["summary"] == "CG_PRIVATE_OBSERVATIONAL_EDIT"
    assert len(world.apps["asha"].state.owner.calendar.list()) == 1


def test_events_missing_verified_calendar_effect_never_claims_done_or_rewrites(world):
    request = world.prepared()
    result = world.coord("asha", "dispatch", request).json()
    engine = world.apps["asha"].state.owner
    assert engine.calendar.delete_if_unchanged(result["event_id"], result["etag"])[0]
    response = world.clients["asha"].get("/coordination/events", headers=world.service("asha"))
    assert response.json()["events"][0]["status"] == "NEEDS_ATTENTION"
    assert not engine.calendar.list()


def test_leena_broader_released_alternatives_are_actually_approvable(world):
    proposal = world.current
    state = world.apps["leena"].state.owner.vault.read()
    offer = state["release"]["body"]["payload"]["offer"]
    assert set(offer["task_ids"]) == {"accompany", "return", "handoff"}
    assert {"accompaniment", "driving", "handoff"} == set(offer["capabilities"])
    for assignment in proposal["assignments"]:
        if assignment["task_id"] in ("return", "handoff"):
            assignment.update(owner_id="leena", offer_id=offer["offer_id"], offer_revision=offer["revision"])
    for action in proposal["actions"]:
        if action["task_id"] in ("return", "handoff"):
            action["owner_id"] = "leena"
    approval = world.approved("leena")
    prepared = world.prepared("leena", approval=approval)
    result = world.coord("leena", "dispatch", prepared)
    assert result.status_code == 200 and result.json()["status"] == "VERIFIED"
    assert len(approval["body"]["payload"]["action_ids"]) == 3


def test_service_without_exact_owner_approval_cannot_probe_private_conflicts(world):
    proposal = deepcopy(world.current)
    original = world.coord("asha", "prepare", {"proposal": proposal, "approval": {}})
    assert original.status_code == 409
    engine = world.apps["asha"].state.owner
    with engine.vault.transaction() as db:
        state = engine.vault.read(db)
        state["private_calendar"].append({"title": "CG_PRIVATE_PROBE", "start": 740, "end": 780, "date": "2026-11-02", "timezone": "Asia/Kolkata"})
        engine.vault.write(db, state)
    conflicted = world.coord("asha", "prepare", {"proposal": proposal, "approval": {}})
    assert conflicted.status_code == original.status_code
    assert conflicted.json() == original.json() == {"detail": "Invalid or expired owner approval."}


def test_explicit_owner_removal_is_scoped_current_etag_and_privately_audited(world):
    request = world.prepared()
    done = world.coord("asha", "dispatch", request).json()
    edited = world.post("asha", f"/api/calendar/{done['event_id']}/edit", {"summary": "CG_PRIVATE_OWNER_REMOVAL_TITLE"}).json()
    assert world.coord("asha", "compensate", {"action_id": request["action_id"]}).json()["status"] == "NEEDS_ATTENTION"
    endpoint = f"/api/calendar/{done['event_id']}/remove"
    body = {"expected_etag": edited["etag"], "confirmation": "remove-this-local-event"}
    client = world.clients["asha"]
    for token in (world.configs["asha"]["service_token"], world.configs["asha"]["broker_ingest_token"], world.tokens["ravi"]):
        response = client.post(endpoint, headers={"Origin": world.origin("asha"), "Authorization": "Bearer " + token}, json=body)
        assert response.status_code == 401
    assert client.post(endpoint, headers={**world.headers("asha"), "Origin": world.origin("ravi")}, json=body).status_code == 403
    assert world.post("asha", endpoint, {"expected_etag": edited["etag"]}).status_code == 422
    assert world.post("asha", endpoint, {**body, "confirmation": "yes"}).status_code == 422
    stale = world.post("asha", endpoint, {**body, "expected_etag": done["etag"]})
    assert stale.status_code == 409
    engine = world.apps["asha"].state.owner
    assert engine.calendar.get(done["event_id"])["summary"] == "CG_PRIVATE_OWNER_REMOVAL_TITLE"
    response = world.post("asha", endpoint, body)
    assert response.status_code == 200
    assert response.json()["status"] == "REMOVED" and response.json()["removed"] is True
    assert engine.calendar.get(done["event_id"]) is None
    audit = client.get("/api/state", headers=world.headers("asha")).json()["calendar_resolutions"][-1]
    assert audit["resolution_id"] == response.json()["resolution_id"]
    assert audit["decision"] == "remove-this-local-event" and audit["status"] == "REMOVED"
    assert audit["expected_etag"] == edited["etag"] and audit["verified_absent_at"]
    assert "CG_PRIVATE_" not in json.dumps(audit)
    assert b"remove-this-local-event" not in engine.vault.path.read_bytes()
    public = client.get("/coordination/events", headers=world.service("asha"))
    assert public.json()["events"][0]["status"] == "CANCELLED"
    assert public.json()["events"][0]["resolution"]["kind"] == "owner-confirmed-removal"
    assert "CG_PRIVATE_" not in public.text
    assert world.coord("asha", "reconcile", request).json()["status"] == "CANCELLED"
    assert world.post("asha", endpoint, body).status_code == 404


def test_owner_removal_condition_rechecks_etag_at_calendar_write(world, monkeypatch):
    request = world.prepared()
    done = world.coord("asha", "dispatch", request).json()
    engine = world.apps["asha"].state.owner
    remove = engine.calendar.remove_by_owner
    def user_changes_between_review_and_delete(event_id, expected_etag):
        engine.calendar.edit(event_id, "CG_PRIVATE_EDIT_DURING_REMOVE")
        return remove(event_id, expected_etag)
    monkeypatch.setattr(engine.calendar, "remove_by_owner", user_changes_between_review_and_delete)
    result = world.post("asha", f"/api/calendar/{done['event_id']}/remove", {"expected_etag": done["etag"], "confirmation": "remove-this-local-event"})
    assert result.status_code == 409
    assert engine.calendar.get(done["event_id"])["summary"] == "CG_PRIVATE_EDIT_DURING_REMOVE"
    assert engine.vault.read()["calendar_resolutions"][-1]["status"] == "REFUSED_CHANGED_OR_MISSING"


def test_owner_removal_crash_after_calendar_delete_has_durable_decision(world, monkeypatch):
    request = world.prepared()
    done = world.coord("asha", "dispatch", request).json()
    engine = world.apps["asha"].state.owner
    remove = engine.calendar.remove_by_owner
    def crash_after_effect(event_id, expected_etag):
        remove(event_id, expected_etag)
        raise RuntimeError("Injected crash after independent calendar delete before vault acknowledgment")
    monkeypatch.setattr(engine.calendar, "remove_by_owner", crash_after_effect)
    with pytest.raises(RuntimeError, match="Injected crash"):
        engine.remove_calendar_event(done["event_id"], done["etag"])
    assert engine.vault.read()["calendar_resolutions"][-1]["status"] == "AUTHORIZED"
    restarted = create_app(world.configs["asha"])
    client = TestClient(restarted, base_url=world.origin("asha"))
    observed = client.get("/coordination/events", headers=world.service("asha"))
    assert observed.json()["events"][0]["status"] == "CANCELLED"
    assert not restarted.state.owner.calendar.list()
    assert restarted.state.owner.vault.read()["calendar_resolutions"][-1]["status"] == "ABSENCE_CONFIRMED"


def test_owner_explicit_removal_closes_broker_recovery_and_allows_new_round(tmp_path):
    from tests.cluster import Cluster
    cluster = Cluster(tmp_path)
    cluster.release_all()
    proposal = cluster.plan()
    cluster.approve(proposal)
    assert cluster.enact(proposal)["state"] == "ACTIVE"
    event = cluster.apps["asha"].state.owner.calendar.list()[0]
    changed = cluster.op(f"/api/calendar/{event['event_id']}/edit", {"summary": "CG_PRIVATE_FINAL_OWNER_DECISION"}, "asha").json()
    partial = cluster.op("/api/compensate", {"proposal_id": proposal["proposal_id"]})
    assert partial.status_code == 200 and partial.json()["state"] == "NEEDS_ATTENTION"
    assert len(cluster.apps["asha"].state.owner.calendar.list()) == 1
    removed = cluster.op(f"/api/calendar/{event['event_id']}/remove", {"expected_etag": changed["etag"], "confirmation": "remove-this-local-event"}, "asha")
    assert removed.status_code == 200
    reconciled = cluster.op("/api/reconcile", {"proposal_id": proposal["proposal_id"]})
    assert reconciled.status_code == 200 and reconciled.json()["state"] == "COMPENSATED"
    assert all(not app.state.owner.calendar.list() for app in cluster.apps.values())
    assert "CG_PRIVATE_" not in reconciled.text
    reopened = cluster.op("/api/new-round", {"expected_revision": cluster.state()["revision"]})
    assert reopened.status_code == 200 and reopened.json()["state"] == "COLLECTING"


def test_calendar_versions_are_opaque_random_not_private_content_hashes(tmp_path, monkeypatch):
    from owner_agent import calendar as module
    from shared.protocol import canonical
    versions = iter(("a" * 48, "b" * 48, "c" * 48))
    requested_entropy = []
    def opaque_version(byte_count):
        requested_entropy.append(byte_count)
        return next(versions)
    monkeypatch.setattr(module.secrets, "token_hex", opaque_version)
    store = module.CalendarStore(tmp_path / "independent.sqlite3")
    action_id = "opaque-version-test"
    action = {"action_id": action_id, "event_id": event_id_for(action_id), "label": "Public approved calendar action", "start": 740, "end": 760, "date": "2026-11-02", "timezone": "Asia/Kolkata"}
    created = store.insert(action, "proposal-opaque-versions")
    assert created["etag"] == '"' + "a" * 48 + '"'
    assert created["etag"] != '"' + hashlib.sha256(canonical(store.intended(action, "proposal-opaque-versions"))).hexdigest() + '"'
    # Duplicate delivery and a fresh adapter instance preserve the persisted tag.
    assert store.insert(action, "proposal-opaque-versions")["etag"] == created["etag"]
    assert module.CalendarStore(store.path).get(action["event_id"])["etag"] == created["etag"]
    private_summary = "CG_PRIVATE_SAME_EDITED_SUMMARY"
    first = store.edit(action["event_id"], private_summary)
    second = store.edit(action["event_id"], private_summary)
    assert first["etag"] == '"' + "b" * 48 + '"'
    assert second["etag"] == '"' + "c" * 48 + '"'
    assert first["etag"] != second["etag"]
    assert requested_entropy == [24, 24, 24]
    assert store.delete_if_unchanged(action["event_id"], created["etag"])[0] is False
    with pytest.raises(ValueError):
        store.remove_by_owner(action["event_id"], first["etag"])
    assert store.get(action["event_id"])["summary"] == private_summary
    assert store.remove_by_owner(action["event_id"], second["etag"])["summary"] == private_summary
