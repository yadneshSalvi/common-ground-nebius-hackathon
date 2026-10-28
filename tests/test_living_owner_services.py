"""Offline owner-boundary tests; all decisions and calendars are authored locally."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from owner_agent.app import create_app
from shared.living import (action_id, agreement_digest, calendar_event_id,
                           commitment_digest, commitment_id, dependency_entries,
                           goal_digest, validate_agreement)
from shared.protocol import digest, expires_in, utc_now, verify_message


def reviewed_goal(goal_id="transport", day="2026-11-02"):
    source = "Reviewed authored sample: preparation at home, outbound journey forty minutes, appointment at clinic, return journey forty minutes, handoff at home by 16:15."
    facts = [("prepare", "preparation", 20, 740, 760, "Home", "Home", []),
             ("outbound", "driving", 40, 790, 830, "Home", "Clinic", ["prepare"]),
             ("accompany", "accompaniment", 90, 830, 920, "Clinic", "Clinic", ["outbound"]),
             ("return", "driving", 40, 920, 960, "Clinic", "Home", ["accompany"]),
             ("handoff", "handoff", 15, 960, 975, "Home", "Home", ["return"])]
    return {"schema_version": 2, "goal_id": goal_id, "revision": 1, "title": "Authored transport", "description": source,
            "timezone": "Asia/Kolkata", "participants": ["asha", "ravi", "leena"], "subject": "Dev", "source_text": source,
            "tasks": [{"task_id": tid, "label": tid.title(), "capability": capability, "date": day, "duration": duration,
                       "earliest": start, "latest": end, "start_location": start_at, "end_location": end_at,
                       "predecessors": predecessors, "required": True, "subject": "Dev", "source_quote": source}
                      for tid, capability, duration, start, end, start_at, end_at, predecessors in facts],
            "routes": [{"from_location": a, "to_location": b, "duration": 40, "source_quote": source} for a, b in [("Home", "Clinic"), ("Clinic", "Home")]],
            "confirmed_at": utc_now(), "confirmed_by": "Explicit fictional coordinator review"}


class OwnerWorld:
    def __init__(self, directory, fictional=True):
        self.messages, self.apps, self.clients, self.configs, self.tokens = [], {}, {}, {}, {}
        self.goal, self.current, self.pending = None, None, None
        for index, owner in enumerate(("asha", "ravi", "leena")):
            config = {"owner_id": owner, "port": 4311 + index, "broker_url": "http://127.0.0.1:4302",
                      "broker_ingest_token": "ingest-" + "i" * 32, "service_token": owner + "-service-" + "s" * 32,
                      "pair_code": owner + "-pair-" + "p" * 32, "data_dir": str(directory / owner),
                      "broker_transport": httpx.MockTransport(self.broker), "fictional_sample": fictional}
            self.configs[owner] = config
            self.restart(owner)
            response = self.clients[owner].post("/api/session", headers={"Origin": self.origin(owner)}, json={"pair_code": config["pair_code"]})
            self.tokens[owner] = response.json()["token"]

    def restart(self, owner):
        self.apps[owner] = create_app(self.configs[owner])
        self.clients[owner] = TestClient(self.apps[owner], base_url=self.origin(owner))

    def broker(self, request):
        assert request.headers["authorization"] == "Bearer " + self.configs["asha"]["broker_ingest_token"]
        assert "Origin" not in request.headers
        if request.method == "POST":
            message = json.loads(request.content)["message"]
            self.messages.append((request.url.path, message))
            return httpx.Response(200, json={"accepted": True})
        if request.url.path == "/v2/current":
            return httpx.Response(200, json={"goal": self.goal, "agreement": self.current, "pending": self.pending})
        candidates = [a for a in (self.pending, self.current) if a]
        agreement = next((a for a in candidates if request.url.path.endswith(f"/{a['agreement_id']}/{a['revision']}")), None)
        return httpx.Response(200, json={"agreement": agreement})

    def origin(self, owner):
        return f"http://127.0.0.1:{self.configs[owner]['port']}"

    def engine(self, owner):
        return self.apps[owner].state.owner

    def local(self, owner):
        return self.engine(owner).living

    def headers(self, owner):
        return {"Origin": self.origin(owner), "Authorization": "Bearer " + self.tokens[owner]}

    def private(self, owner, route, body=None):
        return self.clients[owner].request("GET" if body is None else "POST", "/api/v2/" + route, headers=self.headers(owner), json=body)

    def service(self, owner, route, body=None):
        return self.clients[owner].request("GET" if body is None else "POST", "/coordination/v2/" + route,
                                           headers={"Authorization": "Bearer " + self.configs[owner]["service_token"]}, json=body)

    def setup(self, goal=None, provider="none", enable_policy=True):
        from broker.living_sample import sample_goal
        authored = sample_goal()
        self.goal = goal or authored
        for owner in self.apps:
            if goal is None or not self.local(owner).read()["sample_setups"]:
                result = self.service(owner, "sample/setup", {"goal": authored, "provider": provider, "enable_policy": enable_policy})
                assert result.status_code == 200, result.text
            if goal is not None:
                assert self.service(owner, "goal", {"goal": goal}).status_code == 200
                # Custom goal tests author private choices explicitly, rather
                # than granting a service bootstrap exception to custom sources.
                with self.engine(owner).vault.transaction() as db:
                    state = self.local(owner).read(db)
                    capabilities = {"asha": {"preparation", "handoff"}, "ravi": {"driving"}, "leena": {"accompaniment"}}[owner]
                    state["task_choices"][goal["goal_id"]] = [t["task_id"] for t in goal["tasks"] if t["capability"] in capabilities]
                    self.local(owner).write(db, state)
                self.release(owner, provider)

    def preview(self, owner, provider="none"):
        result = self.private(owner, f"offer-preview?goal_id={self.goal['goal_id']}&provider={provider}")
        assert result.status_code == 200, result.text
        return result.json()

    def release(self, owner, provider="none"):
        preview = self.preview(owner, provider)
        result = self.private(owner, "release", {"goal_id": self.goal["goal_id"], "provider": provider,
                                                "preview_digest": preview["preview_digest"], "expected_revision": self.local(owner).read()["revision"]})
        assert result.status_code == 200, result.text
        return result.json()["release"]

    def build(self, previous=None, return_owner="ravi", timing=None, agreement_id=None, overrides=None):
        revision = previous["revision"] + 1 if previous else 1
        agreement_id = previous["agreement_id"] if previous else agreement_id or "agreement-owner-tests"
        ownership = {"prepare": "asha", "outbound": "ravi", "accompany": "leena", "return": return_owner, "handoff": "asha"}
        ownership.update(overrides or {})
        commits = []
        for task in self.goal["tasks"]:
            owner = ownership[task["task_id"]]
            offer = self.local(owner).status(self.goal["goal_id"])["release"]["body"]["payload"]
            cid = commitment_id(agreement_id, task["task_id"], owner)
            start = (timing or {}).get(task["task_id"], task["earliest"])
            commits.append({"commitment_id": cid, "task_id": task["task_id"], "owner_id": owner,
                            "date": task["date"], "timezone": self.goal["timezone"], "start": start, "end": start + task["duration"],
                            **{k: task[k] for k in ("start_location", "end_location", "capability", "label", "subject")},
                            "dependencies": [], "conditions": [c for c in offer["conditions"] if c["task_id"] == task["task_id"]],
                            "offer_id": offer["offer_id"], "offer_revision": offer["offer_revision"]})
        for commitment in commits:
            commitment["dependencies"] = dependency_entries(self.goal, commits, commitment["task_id"])
        old = {c["commitment_id"]: c for c in previous["commitments"]} if previous else {}
        old_intents = {i["commitment_id"]: i for i in previous["intents"]} if previous else {}
        intents, mutations, retained, changed, new = [], [], [], [], []
        created_at = utc_now()
        for commitment in commits:
            cid = commitment["commitment_id"]
            aid = action_id(cid)
            creation = old_intents[cid]["creation"] if cid in old_intents else {"agreement_id": agreement_id, "revision": revision, "created_at": created_at}
            intent = {"schema_version": 2, "action_id": aid, "commitment_id": cid, "owner_id": commitment["owner_id"],
                      "task_id": commitment["task_id"], "event_id": calendar_event_id(aid), "label": commitment["label"],
                      "date": commitment["date"], "timezone": commitment["timezone"], "start": commitment["start"], "end": commitment["end"],
                      "location": {"start": commitment["start_location"], "end": commitment["end_location"]}, "creation": creation}
            intents.append(intent)
            (new if cid not in old else retained if commitment_digest(old[cid]) == commitment_digest(commitment) else changed).append(cid)
            if cid not in old or old_intents[cid] != intent:
                mutations.append({"mutation_id": f"mutation-{revision}-{commitment['task_id']}", "kind": "insert" if cid not in old else "update",
                                  "owner_id": commitment["owner_id"], "commitment_id": cid, "action_id": aid, "event_id": intent["event_id"],
                                  "intent": intent, "expected_etag": self.local(commitment["owner_id"]).known_effect(intent["event_id"])["etag"] if cid in old else None})
        withdrawn = sorted(set(old) - {c["commitment_id"] for c in commits})
        for cid in withdrawn:
            prior = old[cid]
            intent = old_intents[cid]
            mutations.append({"mutation_id": f"mutation-{revision}-delete-{prior['task_id']}", "kind": "delete", "owner_id": prior["owner_id"],
                              "commitment_id": cid, "action_id": intent["action_id"], "event_id": intent["event_id"], "intent": None,
                              "expected_etag": self.local(prior["owner_id"]).known_effect(intent["event_id"])["etag"]})
        agreement = {"schema_version": 2, "agreement_id": agreement_id, "revision": revision, "base_revision": revision - 1,
                     "goal": self.goal, "goal_digest": goal_digest(self.goal), "commitments": commits, "intents": intents,
                     "delta": {"retained": retained, "changed": changed, "new": new, "withdrawn": withdrawn,
                               "affected_owners": list(self.apps), "approval_required": list(self.apps), "calendar_mutations": mutations},
                     "created_at": created_at, "expires_at": expires_in(7200), "checker": {"valid": True}, "model_receipt_id": None, "explanation": "Authored offline test"}
        self.pending = validate_agreement(agreement)
        return self.pending

    def approve(self, owner, agreement):
        result = self.private(owner, "approve", {"agreement_id": agreement["agreement_id"], "revision": agreement["revision"], "agreement_digest": agreement_digest(agreement)})
        assert result.status_code == 200, result.text
        return result.json()["consent"]

    def prepare(self, owner, agreement, consent=None):
        result = self.service(owner, "prepare", {"agreement": agreement, "consent": consent or self.approve(owner, agreement)})
        assert result.status_code == 200, result.text
        return result.json()

    def request(self, owner, agreement, mutation, reservation):
        return {"agreement_id": agreement["agreement_id"], "revision": agreement["revision"], "mutation_id": mutation["mutation_id"], **{k: reservation[k] for k in ("reservation_id", "fence")}}

    def enact(self, agreement):
        for owner in self.apps:
            reservation = self.prepare(owner, agreement)
            for mutation in self.local(owner).own_mutations(agreement):
                result = self.service(owner, "dispatch", self.request(owner, agreement, mutation, reservation))
                assert result.status_code == 200, result.text
                assert result.json()["status"] in {"VERIFIED", "CANCELLED"}, result.text
        self.current, self.pending = agreement, None

    def question(self, owner="leena", request_id="return-question", task_id="return", disruption="withdraw-return", invitation=False):
        capability = next(t["capability"] for t in self.goal["tasks"] if t["task_id"] == task_id)
        body = {"request_id": request_id, "goal_id": self.goal["goal_id"], "task_id": task_id, "category": capability, "disruption_id": disruption, "invitation": invitation}
        result = self.service(owner, "question", {"request": body})
        assert result.status_code == 200, result.text
        return result.json()


@pytest.fixture
def world(tmp_path):
    return OwnerWorld(tmp_path)


def test_sample_session_is_fictional_exact_origin_and_owner_local(tmp_path):
    world = OwnerWorld(tmp_path)
    client = world.clients["asha"]
    assert client.post("/sample/session").status_code == 403
    assert client.post("/sample/session", headers={"Origin": world.origin("ravi")}).status_code == 403
    session = client.post("/sample/session", headers={"Origin": world.origin("asha")})
    assert session.status_code == 200 and session.json()["authority"] == "fictional-sample-only"
    token = session.json()["token"]
    assert world.clients["ravi"].get("/api/v2/state", headers={"Authorization": "Bearer " + token}).status_code == 401
    real = OwnerWorld(tmp_path / "real", fictional=False)
    assert real.clients["asha"].post("/sample/session", headers={"Origin": real.origin("asha")}).status_code == 404
    assert real.service("asha", "sample/setup", {"goal": reviewed_goal()}).status_code == 404
    assert real.local("asha").read()["policy"]["enabled"] is False


def test_sample_policy_choice_is_immutable_and_later_changes_require_private_review(world):
    world.setup(enable_policy=False)
    assert all(world.local(owner).read()["policy"]["enabled"] is False for owner in world.apps)
    goal = world.goal
    result = world.service("ravi", "sample/setup", {"goal": goal, "provider": "none", "enable_policy": True})
    assert result.status_code == 409
    assert world.local("ravi").read()["policy"]["enabled"] is False
    result = world.private("ravi", "policy", {"expected_revision": world.local("ravi").read()["revision"], "enabled": True, "expires_at": expires_in(3600)})
    assert result.status_code == 200
    policy = world.local("ravi").read()["policy"]
    assert policy["enabled"] is True and "owner-reviewed" in policy["provenance"]
    result = world.service("ravi", "sample/setup", {"goal": goal, "provider": "none"})
    assert result.status_code == 200
    assert world.local("ravi").read()["policy"] == policy


def test_repeated_authored_setup_cannot_resurrect_owner_revoked_policy(world):
    world.setup(enable_policy=True)
    first = world.local("ravi").read()["sample_setups"][0]["setup_release"]
    result = world.private("ravi", "policy", {"expected_revision": world.local("ravi").read()["revision"], "enabled": False})
    assert result.status_code == 200
    revoked = deepcopy(world.local("ravi").read()["policy"])
    result = world.service("ravi", "sample/setup", {"goal": world.goal, "provider": "none", "enable_policy": True})
    assert result.status_code == 200 and result.json()["release"] == first
    assert world.local("ravi").read()["policy"] == revoked
    changed_provider = world.service("ravi", "sample/setup", {"goal": world.goal, "provider": "fireworks", "enable_policy": True})
    assert changed_provider.status_code == 409
    from broker.living_sample import sample_goal
    new_goal = sample_goal(2)
    result = world.service("ravi", "sample/setup", {"goal": new_goal, "provider": "none", "enable_policy": True})
    assert result.status_code == 200
    assert world.local("ravi").read()["policy"] == revoked


def test_service_sample_exception_cannot_sign_amendments_or_arbitrary_sources(world):
    world.setup()
    initial = world.build()
    first = world.service("asha", "sample/approve", {"agreement": initial})
    assert first.status_code == 200, first.text
    retry = world.service("asha", "sample/approve", {"agreement": initial})
    assert retry.status_code == 200 and retry.json()["consent"] == first.json()["consent"]
    changed = deepcopy(initial)
    changed["explanation"] = "A different initial document is not an idempotent retry"
    assert world.service("asha", "sample/approve", {"agreement": changed}).status_code == 409
    world.enact(initial)
    amendment = world.build(initial)
    before = deepcopy(world.local("asha").read()["approvals"])
    response = world.service("asha", "sample/approve", {"agreement": amendment})
    assert response.status_code == 409 and "amendments" in response.json()["detail"]
    assert world.local("asha").read()["approvals"] == before
    arbitrary = reviewed_goal("arbitrary-reviewed-source", "2026-11-04")
    arbitrary["confirmed_by"] = "authored-fictional-sample"
    state_before = deepcopy(world.local("asha").read())
    assert world.service("asha", "sample/setup", {"goal": arbitrary}).status_code == 409
    assert world.local("asha").read() == state_before
    world.setup(arbitrary)
    candidate = world.build(agreement_id="arbitrary-source-agreement")
    assert world.service("asha", "sample/approve", {"agreement": candidate}).status_code == 409


def test_memory_survives_restart_distinct_goal_and_delete_removes_content(world):
    world.setup()
    memory = next(m for m in world.local("asha").read()["memories"] if m["type"] == "excluded_capability")
    world.restart("asha")
    another = reviewed_goal("distinct-reviewed-goal", "2026-11-03")
    assert world.service("asha", "goal", {"goal": another}).status_code == 200
    preview = world.local("asha").preview(another["goal_id"])
    assert not set(preview["release"]["task_ids"]) & {"outbound", "return"}
    result = world.private("asha", f"memory/{memory['memory_id']}/delete", {"expected_revision": world.local("asha").read()["revision"]})
    assert result.status_code == 200
    saved = world.local("asha").read()
    assert all(m["memory_id"] != memory["memory_id"] for m in saved["memories"])
    assert set(saved["deletions"][-1]) == {"memory_id", "deleted_at", "revision"}
    assert {"outbound", "return"} <= set(world.local("asha").preview(another["goal_id"])["release"]["task_ids"])
    public = world.service("asha", f"status?goal_id={another['goal_id']}")
    assert memory["memory_id"] not in public.text and "provenance" not in public.text


def test_conditional_counteroffer_needs_exact_release_and_provider_grants_do_not_carry(world):
    world.setup(provider="fireworks")
    assert world.preview("leena", "fireworks")["release"]["task_ids"] == ["accompany"]
    assert world.question()["accepted"] is True
    preview = world.preview("leena", "nebius")
    assert preview["release"]["conditions"] == [{"task_id": "return", "receiver_id": "asha", "receiver_task_id": "handoff", "by": 975}]
    assert world.local("leena").status(world.goal["goal_id"])["release"]["body"]["payload"]["task_ids"] == ["accompany"]
    response = world.private("leena", "release", {"goal_id": world.goal["goal_id"], "provider": "nebius", "preview_digest": "0" * 64, "expected_revision": world.local("leena").read()["revision"]})
    assert response.status_code == 409
    message = world.release("leena", "nebius")
    payload = verify_message(message, world.engine("leena").identity["public_key"], BROKER := "common-ground-broker", "LivingRelease")["payload"]
    assert payload["recipients"]["inference"] == ["nebius"]
    assert set(world.local("leena").read()["offers"][world.goal["goal_id"]]) == {"fireworks", "nebius"}
    assert not any(m["memory_id"] in json.dumps(message) for m in world.local("leena").read()["memories"])


def test_refusal_closes_scope_until_private_explicit_reinvitation(world):
    world.setup()
    assert world.question()["accepted"]
    response = world.private("leena", "refuse", {"request_id": "return-question", "expected_revision": world.local("leena").read()["revision"]})
    assert response.status_code == 200
    assert set(response.json()["refusal"]["body"]["payload"]) == {"goal_id", "request_id", "owner_id", "task_id", "consent_revision"}
    assert world.question(request_id="again", disruption="another-run")["accepted"] is False
    assert "return" not in world.preview("leena")["release"]["task_ids"]
    assert world.question(request_id="invite", disruption="new-invitation", invitation=True)["accepted"] is False
    accepted = world.private("leena", "requests/invite/accept-invitation", {"expected_revision": world.local("leena").read()["revision"]})
    assert accepted.status_code == 200
    assert "return" in world.preview("leena")["release"]["task_ids"]
    assert world.question(owner="asha", request_id="asha-driving")["accepted"] is False


def test_question_budget_never_exceeds_three(world):
    world.setup()
    for index in range(3):
        assert world.question(request_id=f"question-{index}", task_id=world.goal["tasks"][index]["task_id"])["accepted"]
    assert world.question(request_id="question-3")["accepted"] is False


def test_prepare_authenticates_local_consent_before_private_conflict_lookup(world):
    world.setup()
    agreement = world.build()
    original = world.service("asha", "prepare", {"agreement": agreement, "consent": {}})
    with world.engine("asha").vault.transaction() as db:
        state = world.engine("asha").vault.read(db)
        state["private_calendar"].append({"date": "2026-11-02", "start": 740, "end": 760, "title": "PRIVATE_PROBE"})
        world.engine("asha").vault.write(db, state)
    changed = world.service("asha", "prepare", {"agreement": agreement, "consent": {}})
    assert original.status_code == changed.status_code == 409
    assert original.json() == changed.json() == {"detail": "Invalid or expired owner consent."}


def test_scoped_withdrawal_cancels_paused_return_and_preserves_pickup_authority(world):
    world.setup()
    agreement = world.build()
    reservation = world.prepare("ravi", agreement)
    pickup, returning = world.local("ravi").own_mutations(agreement)
    world.engine("ravi").set_fault("pause_before_send")
    request = world.request("ravi", agreement, returning, reservation)
    assert world.service("ravi", "dispatch", request).json()["status"] == "PAUSED"
    result = world.private("ravi", "withdraw", {"agreement_id": agreement["agreement_id"], "base_revision": 1,
                                               "commitment_ids": [returning["commitment_id"]], "expected_revision": world.local("ravi").read()["revision"]})
    assert result.status_code == 200, result.text
    world.restart("ravi")
    world.engine("ravi").set_fault("none")
    assert world.service("ravi", "dispatch", request).json()["status"] == "CANCELLED"
    sent = world.service("ravi", "dispatch", world.request("ravi", agreement, pickup, reservation))
    assert sent.status_code == 200 and sent.json()["status"] == "VERIFIED", sent.text
    assert [event["task_id"] for event in world.local("ravi").calendar.list()] == ["outbound"]
    assert world.preview("ravi")["release"]["task_ids"] == ["outbound"]


def test_lost_ack_restart_reads_once_without_duplicate_or_reauthorization(world):
    world.setup()
    agreement = world.build()
    reservation = world.prepare("asha", agreement)
    mutation = world.local("asha").own_mutations(agreement)[0]
    request = world.request("asha", agreement, mutation, reservation)
    world.engine("asha").set_fault("timeout_after_write")
    assert world.service("asha", "dispatch", request).json()["status"] == "AMBIGUOUS"
    world.restart("asha")
    assert world.service("asha", "reconcile", request).json()["status"] == "VERIFIED"
    assert len(world.local("asha").calendar.list()) == 1
    assert world.service("asha", "dispatch", request).json()["status"] == "VERIFIED"
    assert len(world.local("asha").calendar.list()) == 1


def test_handoff_counterpart_needs_fresh_asha_review_and_scoped_ravi_policy_attestation(world):
    world.setup()
    original = world.build()
    world.enact(original)
    return_commitment = next(c for c in original["commitments"] if c["task_id"] == "return")
    result = world.private("ravi", "withdraw", {"agreement_id": original["agreement_id"], "base_revision": 1,
                                               "commitment_ids": [return_commitment["commitment_id"]], "expected_revision": world.local("ravi").read()["revision"]})
    assert result.status_code == 200
    assert len(world.local("ravi").calendar.list()) == 2
    observed = world.service("ravi", f"events?agreement_id={original['agreement_id']}").json()["observation"]["body"]["payload"]
    assert observed["authorities"] == [{"revision": 1, "agreement_digest": agreement_digest(original),
                                        "consent_message_id": world.local("ravi").read()["approvals"][world.local("ravi").agreement_key(original)]["body"]["message_id"],
                                        "authority_current": False, "withdrawn_commitment_ids": [return_commitment["commitment_id"]]}]
    assert world.question()["accepted"]
    world.release("leena")
    amendment = world.build(original, "leena")
    assert world.service("asha", "attest", {"agreement": amendment}).json() == {"status": "needs_review"}
    assert world.service("leena", "attest", {"agreement": amendment}).json() == {"status": "needs_review"}
    ravi = world.service("ravi", "attest", {"agreement": amendment})
    assert ravi.status_code == 200 and ravi.json()["status"] == "attested", ravi.text
    consent = ravi.json()["consent"]
    assert consent["body"]["payload"]["basis"] == "standing-policy"
    reservation = world.prepare("ravi", amendment, consent)
    deletion = world.local("ravi").own_mutations(amendment)[0]
    result = world.service("ravi", "dispatch", world.request("ravi", amendment, deletion, reservation))
    assert result.json()["status"] == "CANCELLED", result.text
    assert [event["task_id"] for event in world.local("ravi").calendar.list()] == ["outbound"]
    authorities = world.service("ravi", f"events?agreement_id={original['agreement_id']}").json()["observation"]["body"]["payload"]["authorities"]
    current = next(a for a in authorities if a["revision"] == 2)
    assert current == {"revision": 2, "agreement_digest": agreement_digest(amendment), "consent_message_id": consent["body"]["message_id"],
                       "authority_current": True, "withdrawn_commitment_ids": []}
    world.approve("asha", amendment)
    world.approve("leena", amendment)
    assert "PRIVATE" not in json.dumps(world.messages)


def test_user_edit_is_preserved_during_scoped_delete_and_public_observation(world):
    world.setup()
    original = world.build()
    world.enact(original)
    returning = next(c for c in original["commitments"] if c["task_id"] == "return")
    result = world.private("ravi", "withdraw", {"agreement_id": original["agreement_id"], "base_revision": 1,
                                               "commitment_ids": [returning["commitment_id"]], "expected_revision": world.local("ravi").read()["revision"]})
    assert result.status_code == 200
    world.question()
    world.release("leena")
    amendment = world.build(original, "leena")
    consent = world.service("ravi", "attest", {"agreement": amendment}).json()["consent"]
    reservation = world.prepare("ravi", amendment, consent)
    deletion = world.local("ravi").own_mutations(amendment)[0]
    world.local("ravi").calendar.edit(deletion["event_id"], "PRIVATE_USER_EDIT_REMAINS")
    sent = world.service("ravi", "dispatch", world.request("ravi", amendment, deletion, reservation))
    assert sent.json()["status"] == "NEEDS_ATTENTION", sent.text
    assert "PRIVATE_USER_EDIT_REMAINS" not in sent.text
    assert world.local("ravi").calendar.get(deletion["event_id"])["label"] == "PRIVATE_USER_EDIT_REMAINS"
    events = world.service("ravi", f"events?agreement_id={original['agreement_id']}")
    assert "PRIVATE_USER_EDIT_REMAINS" not in events.text


def test_memory_correction_fences_paused_work_and_changes_next_offer(world):
    world.setup()
    agreement = world.build()
    reservation = world.prepare("asha", agreement)
    mutation = world.local("asha").own_mutations(agreement)[0]
    request = world.request("asha", agreement, mutation, reservation)
    world.engine("asha").set_fault("pause_before_send")
    assert world.service("asha", "dispatch", request).json()["status"] == "PAUSED"
    memory = {"type": "excluded_capability", "value": {"capability": "preparation"}, "scope": {"goal_id": world.goal["goal_id"]},
              "provenance": "Explicit owner correction", "owner_confirmed": True, "private_note": "PRIVATE_CORRECTION"}
    result = world.private("asha", "memory", {"expected_revision": world.local("asha").read()["revision"], "memory": memory})
    assert result.status_code == 200
    world.restart("asha")
    world.engine("asha").set_fault("none")
    assert world.service("asha", "dispatch", request).json()["status"] == "CANCELLED"
    assert world.local("asha").calendar.list() == []
    assert "prepare" not in world.preview("asha")["release"]["task_ids"]
    assert b"PRIVATE_CORRECTION" not in world.engine("asha").vault.path.read_bytes()


def test_offer_revision_increases_after_memory_add_correct_delete_and_restart(world):
    world.setup()
    first = world.local("asha").status(world.goal["goal_id"])["release"]
    releases = [first]
    memory = {"type": "excluded_capability", "value": {"capability": "preparation"}, "scope": {"goal_id": world.goal["goal_id"]},
              "provenance": "Explicit owner rule", "owner_confirmed": True}
    saved = world.private("asha", "memory", {"expected_revision": world.local("asha").read()["revision"], "memory": memory})
    assert saved.status_code == 200
    assert world.local("asha").status(world.goal["goal_id"])["releases"] == []
    world.restart("asha")
    releases.append(world.release("asha"))
    assert releases[-1]["body"]["payload"]["task_ids"] == ["handoff"]
    corrected = {**memory, "memory_id": saved.json()["memory"]["memory_id"], "value": {"capability": "handoff"}}
    result = world.private("asha", "memory", {"expected_revision": world.local("asha").read()["revision"], "memory": corrected})
    assert result.status_code == 200
    world.restart("asha")
    releases.append(world.release("asha"))
    assert releases[-1]["body"]["payload"]["task_ids"] == ["prepare"]
    result = world.private("asha", f"memory/{corrected['memory_id']}/delete", {"expected_revision": world.local("asha").read()["revision"]})
    assert result.status_code == 200
    world.restart("asha")
    releases.append(world.release("asha"))
    assert releases[-1]["body"]["payload"]["task_ids"] == ["prepare", "handoff"]
    assert [m["body"]["payload"]["offer_revision"] for m in releases] == [1, 2, 3, 4]
    assert len({m["body"]["payload"]["offer_id"] for m in releases}) == 4
    assert world.local("asha").status(world.goal["goal_id"])["releases"] == [releases[-1]]


def test_expired_reservation_renews_fence_without_reusing_stale_worker(world):
    world.setup()
    agreement = world.build()
    consent = world.approve("asha", agreement)
    reservation = world.prepare("asha", agreement, consent)
    mutation = world.local("asha").own_mutations(agreement)[0]
    request = world.request("asha", agreement, mutation, reservation)
    world.engine("asha").set_fault("pause_before_send")
    assert world.service("asha", "dispatch", request).json()["status"] == "PAUSED"
    with world.engine("asha").vault.transaction() as db:
        db.execute("UPDATE living_reservations SET lease_expires_at='2020-01-01T00:00:00Z'")
    fresh = world.prepare("asha", agreement, consent)
    assert fresh["fence"] > reservation["fence"]
    world.engine("asha").set_fault("none")
    assert world.service("asha", "dispatch", request).status_code == 409
    result = world.service("asha", "dispatch", world.request("asha", agreement, mutation, fresh))
    assert result.status_code == 200 and result.json()["status"] == "VERIFIED", result.text
    assert len(world.local("asha").calendar.list()) == 1


@pytest.mark.parametrize("edited", [False, True])
def test_exact_update_preserves_creation_and_refuses_concurrent_user_edit(world, edited):
    goal = reviewed_goal()
    goal["tasks"][0]["latest"] = 780
    world.setup(goal)
    original = world.build()
    world.enact(original)
    amendment = world.build(original, timing={"prepare": 760})
    consent = world.approve("asha", amendment)
    reservation = world.prepare("asha", amendment, consent)
    mutation = world.local("asha").own_mutations(amendment)[0]
    assert mutation["kind"] == "update"
    before = world.local("asha").calendar.get(mutation["event_id"])
    if edited:
        world.local("asha").calendar.edit(mutation["event_id"], "PRIVATE_CONCURRENT_UPDATE")
    result = world.service("asha", "dispatch", world.request("asha", amendment, mutation, reservation))
    assert result.status_code == 200, result.text
    after = world.local("asha").calendar.get(mutation["event_id"])
    assert after["creation"] == before["creation"] and after["event_id"] == before["event_id"]
    if edited:
        assert result.json()["status"] == "NEEDS_ATTENTION"
        assert after["label"] == "PRIVATE_CONCURRENT_UPDATE" and after["start"] == 740
        assert "PRIVATE_CONCURRENT_UPDATE" not in result.text
    else:
        assert result.json()["status"] == "VERIFIED"
        assert after["start"] == 760 and after["etag"] != before["etag"]


def test_unavailable_calendar_readback_is_unconfirmed_and_private_state_marks_unavailable(world, monkeypatch):
    world.setup()
    agreement = world.build()
    reservation = world.prepare("asha", agreement)
    mutation = world.local("asha").own_mutations(agreement)[0]
    request = world.request("asha", agreement, mutation, reservation)
    assert world.service("asha", "dispatch", request).json()["status"] == "VERIFIED"
    def unavailable(*args):
        raise ConnectionError("PRIVATE_PROVIDER_ERROR")
    monkeypatch.setattr(world.local("asha").calendar, "get", unavailable)
    monkeypatch.setattr(world.local("asha").calendar, "list", unavailable)
    observed = world.service("asha", "reconcile", request)
    assert observed.status_code == 200 and observed.json()["status"] == "UNCONFIRMED"
    assert "PRIVATE_PROVIDER_ERROR" not in observed.text
    private = world.private("asha", "state")
    assert private.json()["calendar_available"] is False
    assert private.json()["receipts"][0]["status"] == "UNCONFIRMED"


def test_signed_observation_binds_actual_public_receipts_and_never_caller_data(world):
    from shared.living import validate_payload
    world.setup()
    agreement = world.build()
    world.enact(agreement)
    route = f"events?agreement_id={agreement['agreement_id']}"
    response = world.service("asha", route)
    assert response.status_code == 200, response.text
    observation = response.json()["observation"]
    body = verify_message(observation, world.engine("asha").identity["public_key"], "common-ground-broker", "LivingObservation")
    payload = validate_payload("LivingObservation", body["payload"])
    assert body["schema_version"] == 2 and payload["agreement_id"] == agreement["agreement_id"]
    assert payload["receipts"] == response.json()["receipts"]
    authority = payload["authorities"][0]
    assert authority["revision"] == agreement["revision"] and authority["agreement_digest"] == agreement_digest(agreement)
    assert authority["authority_current"] is True and authority["withdrawn_commitment_ids"] == []
    tampered = deepcopy(observation)
    tampered["body"]["payload"]["receipts"][0]["etag"] = '"tampered-event-version"'
    with pytest.raises(ValueError, match="signature"):
        verify_message(tampered, world.engine("asha").identity["public_key"], "common-ground-broker", "LivingObservation")
    event = world.local("asha").calendar.list()[0]
    world.local("asha").calendar.edit(event["event_id"], "PRIVATE_OBSERVATION_EDIT")
    forged = [{"event_id": "caller-controlled", "status": "VERIFIED"}]
    response = world.clients["asha"].request("GET", "/coordination/v2/" + route,
                                             headers={"Authorization": "Bearer " + world.configs["asha"]["service_token"]}, json={"receipts": forged})
    assert response.status_code == 200 and "PRIVATE_OBSERVATION_EDIT" not in response.text
    actual = response.json()["observation"]["body"]["payload"]["receipts"]
    assert actual != forged and any(r["status"] == "NEEDS_ATTENTION" for r in actual)
    assert world.service("asha", "events?agreement_id=unapproved-caller-scope").status_code == 404


def test_signed_observation_never_discloses_manually_changed_interval_or_location(world, monkeypatch):
    world.setup()
    agreement = world.build()
    world.enact(agreement)
    calendar = world.local("asha").calendar
    original_get = calendar.get
    changed_id = calendar.list()[0]["event_id"]
    def moved_by_owner(event_id):
        observed = original_get(event_id)
        if observed and event_id == changed_id:
            return {**observed, "date": "2035-02-19", "start": 13, "end": 27,
                    "location": {"start": "PRIVATE_MOVED_LOCATION", "end": "PRIVATE_MOVED_LOCATION"}, "user_edited": True}
        return observed
    monkeypatch.setattr(calendar, "get", moved_by_owner)
    response = world.service("asha", f"events?agreement_id={agreement['agreement_id']}")
    assert response.status_code == 200
    assert "PRIVATE_MOVED_LOCATION" not in response.text and "2035-02-19" not in response.text
    receipt = next(r for r in response.json()["receipts"] if r["event_id"] == changed_id)
    assert receipt["status"] == "NEEDS_ATTENTION"
    assert set(receipt["remaining_effect"]) == {"event_id", "action_id", "commitment_id"}
    assert response.json()["observation"]["body"]["payload"]["receipts"] == response.json()["receipts"]


def test_observation_revokes_current_authority_after_memory_change_with_calendar_still_verified(world):
    world.setup()
    agreement = world.build()
    world.enact(agreement)
    memory = {"type": "excluded_capability", "value": {"capability": "preparation"}, "scope": {"goal_id": world.goal["goal_id"]},
              "provenance": "PRIVATE_NEW_CONSTRAINT_PROVENANCE", "private_note": "PRIVATE_NEW_CONSTRAINT_NOTE", "owner_confirmed": True}
    result = world.private("asha", "memory", {"expected_revision": world.local("asha").read()["revision"], "memory": memory})
    assert result.status_code == 200
    response = world.service("asha", f"events?agreement_id={agreement['agreement_id']}")
    assert response.status_code == 200
    payload = response.json()["observation"]["body"]["payload"]
    assert all(r["status"] == "VERIFIED" for r in payload["receipts"])
    assert payload["authorities"] == [{"revision": 1, "agreement_digest": agreement_digest(agreement), "consent_message_id": None,
                                        "authority_current": False, "withdrawn_commitment_ids": []}]
    assert "PRIVATE_NEW_CONSTRAINT" not in response.text


def test_paused_update_does_not_become_an_applied_baseline_for_later_attestation(world):
    goal = reviewed_goal()
    goal["tasks"][0]["latest"] = 780
    world.setup(goal)
    original = world.build()
    world.enact(original)
    amendment = world.build(original, timing={"prepare": 760})
    consent = world.approve("asha", amendment)
    reservation = world.prepare("asha", amendment, consent)
    mutation = world.local("asha").own_mutations(amendment)[0]
    world.engine("asha").set_fault("pause_before_send")
    response = world.service("asha", "dispatch", world.request("asha", amendment, mutation, reservation))
    assert response.json()["status"] == "PAUSED"
    assert world.local("asha").known_effect(mutation["event_id"])["intent"]["start"] == 740
    later = world.build(amendment, timing={"prepare": 760})
    assert world.local("asha").own_mutations(later) == []
    response = world.service("asha", "attest", {"agreement": later})
    assert response.status_code == 200 and response.json() == {"status": "needs_review"}
    assert world.local("asha").calendar.get(mutation["event_id"])["start"] == 740


def test_policy_revocation_cannot_race_standing_eligibility_into_a_disabled_policy_signature(world, monkeypatch):
    world.setup()
    original = world.build()
    world.enact(original)
    amendment = world.build(original)
    owner = world.local("asha")
    policy_revision = owner.read()["policy"]["revision"]
    entering, attempted, revoked = threading.Event(), threading.Event(), threading.Event()
    approve = owner._approve
    def delayed_approve(*args, **kwargs):
        entering.set()
        assert attempted.wait(2)
        revoked.wait(0.1)
        return approve(*args, **kwargs)
    monkeypatch.setattr(owner, "_approve", delayed_approve)
    def revoke():
        assert entering.wait(2)
        attempted.set()
        with owner.lock:
            result = owner.set_policy(owner.read()["revision"], False, None)
        revoked.set()
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        attested = pool.submit(world.service, "asha", "attest", {"agreement": amendment})
        withdrawal = pool.submit(revoke)
        response, policy = attested.result(timeout=5), withdrawal.result(timeout=5)
    assert response.status_code == 200 and response.json()["status"] == "attested", response.text
    consent = response.json()["consent"]
    assert consent["body"]["payload"]["policy_revision"] == policy_revision
    assert consent["body"]["issued_at"] <= policy["policy"]["updated_at"]
    authority = owner.signed_observation(original["agreement_id"])["observation"]["body"]["payload"]["authorities"][-1]
    assert authority["revision"] == 2 and authority["authority_current"] is False and authority["consent_message_id"] is None


def test_scoped_memory_change_does_not_cancel_another_goals_authority(world):
    world.setup()
    agreement = world.build()
    reservation = world.prepare("asha", agreement)
    mutation = world.local("asha").own_mutations(agreement)[0]
    request = world.request("asha", agreement, mutation, reservation)
    another = reviewed_goal("another-goal", "2026-11-05")
    assert world.service("asha", "goal", {"goal": another}).status_code == 200
    result = world.private("asha", "memory", {"expected_revision": world.local("asha").read()["revision"],
                                              "memory": {"type": "excluded_capability", "value": {"capability": "preparation"},
                                                         "scope": {"goal_id": another["goal_id"]}, "provenance": "Owner correction for another goal", "owner_confirmed": True}})
    assert result.status_code == 200
    dispatched = world.service("asha", "dispatch", request)
    assert dispatched.status_code == 200 and dispatched.json()["status"] == "VERIFIED", dispatched.text


def test_distinct_goal_reservations_cannot_double_book_owner(world):
    world.setup()
    first = world.build()
    first_reservation = world.prepare("asha", first)
    world.setup(reviewed_goal("second-same-time-goal"))
    second = world.build(agreement_id="distinct-agreement")
    consent = world.approve("asha", second)
    response = world.service("asha", "prepare", {"agreement": second, "consent": consent})
    assert response.status_code == 409 and "already reserves" in response.json()["detail"]
    with world.engine("asha").vault.connect() as db:
        row = db.execute("SELECT status FROM living_reservations WHERE reservation_id=?", (first_reservation["reservation_id"],)).fetchone()
    assert row["status"] == "ACTIVE"


def test_distinct_goal_cannot_ignore_existing_calendar_effects(world):
    world.setup()
    world.enact(world.build())
    before = world.local("asha").calendar.list()
    world.setup(reviewed_goal("second-calendar-goal"))
    second = world.build(agreement_id="distinct-calendar-agreement")
    response = world.private("asha", "approve", {"agreement_id": second["agreement_id"], "revision": 1, "agreement_digest": agreement_digest(second)})
    assert response.status_code == 409 and "calendar effect conflicts" in response.json()["detail"]
    assert world.local("asha").calendar.list() == before


def test_question_cannot_disguise_driving_as_an_allowed_category(world):
    world.setup()
    response = world.service("asha", "question", {"request": {"request_id": "disguised-driving", "goal_id": world.goal["goal_id"],
                                                               "task_id": "return", "category": "meal", "disruption_id": "malicious-disruption"}})
    assert response.status_code == 200 and response.json() == {"request_id": "disguised-driving", "accepted": False, "status": "declined"}
    assert "return" not in world.preview("asha")["release"]["task_ids"]


@pytest.mark.parametrize("scoped", [False, True])
def test_weekly_capacity_includes_another_active_goal_without_doublecounting_amendment(world, scoped):
    world.setup()
    first = world.build()
    world.enact(first)
    second_goal = reviewed_goal("capacity-second-goal", "2026-11-03")
    memory = {"type": "weekly_capacity", "value": {"minutes": 60}, "scope": {"goal_id": second_goal["goal_id"]} if scoped else {},
              "provenance": "Explicit owner capacity rule", "owner_confirmed": True}
    result = world.private("asha", "memory", {"expected_revision": world.local("asha").read()["revision"], "memory": memory})
    assert result.status_code == 200
    world.setup(second_goal)
    second = world.build(agreement_id="capacity-second-agreement")
    result = world.private("asha", "approve", {"agreement_id": second["agreement_id"], "revision": 1, "agreement_digest": agreement_digest(second)})
    assert result.status_code == (200 if scoped else 409), result.text
    if not scoped:
        assert "weekly capacity" in result.json()["detail"]


@pytest.mark.parametrize("calendar_change", ["shrink", "delete"])
@pytest.mark.parametrize("capacity,expected", [(60, 409), (80, 200)])
def test_capacity_keeps_responsibilities_after_calendar_edits_and_deduplicates_pending_revisions(world, monkeypatch, calendar_change, capacity, expected):
    world.setup()
    original = world.build()
    world.enact(original)
    # A proposed removal has an exact private review, but has not executed its
    # conditional delete or replaced the enacted agreement.
    assert world.question(task_id="prepare")["accepted"]
    world.release("leena")
    pending = world.build(original, overrides={"prepare": "leena"})
    world.approve("asha", pending)
    calendar = world.local("asha").calendar
    events = calendar.list()
    if calendar_change == "delete":
        for event in events:
            assert calendar.delete_if_unchanged(event["event_id"], event["etag"])[0]
    else:
        observed = calendar.list
        monkeypatch.setattr(calendar, "list", lambda: [{**event, "end": event["start"] + 1, "user_edited": True} for event in observed()])
    memory = {"type": "weekly_capacity", "value": {"minutes": capacity}, "scope": {},
              "provenance": "Explicit global weekly capacity", "owner_confirmed": True}
    result = world.private("asha", "memory", {"expected_revision": world.local("asha").read()["revision"], "memory": memory})
    assert result.status_code == 200
    world.setup(reviewed_goal("capacity-after-manual-change", "2026-11-03"))
    candidate = world.build(agreement_id="capacity-new-agreement")
    response = world.private("asha", "approve", {"agreement_id": candidate["agreement_id"], "revision": 1, "agreement_digest": agreement_digest(candidate)})
    assert response.status_code == expected, response.text
    if expected == 409:
        assert "weekly capacity" in response.json()["detail"]


@pytest.mark.parametrize("count", [2, 6])
def test_generic_owner_accepts_registered_two_to_six_member_goals(tmp_path, count):
    owners = [f"member-{index}" for index in range(count)]
    config = {"owner_id": owners[0], "owner_profile": {"name": "Registered Owner", "capabilities": ["preparation", "handoff"]},
              "registered_owners": owners, "port": 4390, "origin": "http://127.0.0.1:4390",
              "broker_url": "http://127.0.0.1:4302", "broker_ingest_token": "generic-ingest-" + "i" * 32,
              "service_token": "generic-service-" + "s" * 32, "pair_code": "generic-pair-" + "p" * 32,
              "data_dir": str(tmp_path / str(count)), "broker_transport": httpx.MockTransport(lambda req: httpx.Response(200, json={"accepted": True}))}
    app = create_app(config)
    engine = app.state.owner
    goal = reviewed_goal("generic-goal")
    goal["participants"] = owners
    engine.living.remember_goal(goal)
    preview = engine.living.preview(goal["goal_id"])
    assert set(preview["release"]["recipients"]["humans"]) == set(owners)
    assert preview["release"]["task_ids"] == ["prepare", "handoff"]
    assert preview["release"]["request_categories"] == ["handoff", "preparation"]
    assert engine.meta()["name"] == "Registered Owner"
    assert engine.owner()["owner_id"] == owners[0]
    assert engine.living.read()["memories"] == []
    assert engine.living.read()["policy"]["enabled"] is False
    released = engine.living.release(goal["goal_id"], "none", preview["preview_digest"], engine.living.read()["revision"])
    body = verify_message(released["release"], engine.identity["public_key"], "common-ground-broker", "LivingRelease")
    assert body["issuer"] == owners[0]


def test_lost_delete_ack_restart_verifies_absence_without_touching_pickup(world):
    world.setup()
    original = world.build()
    world.enact(original)
    returning = next(c for c in original["commitments"] if c["task_id"] == "return")
    world.private("ravi", "withdraw", {"agreement_id": original["agreement_id"], "base_revision": 1,
                                       "commitment_ids": [returning["commitment_id"]], "expected_revision": world.local("ravi").read()["revision"]})
    world.question()
    world.release("leena")
    amendment = world.build(original, "leena")
    consent = world.service("ravi", "attest", {"agreement": amendment}).json()["consent"]
    reservation = world.prepare("ravi", amendment, consent)
    deletion = world.local("ravi").own_mutations(amendment)[0]
    request = world.request("ravi", amendment, deletion, reservation)
    world.engine("ravi").set_fault("timeout_after_write")
    result = world.service("ravi", "dispatch", request)
    assert result.json()["status"] == "AMBIGUOUS", result.text
    world.restart("ravi")
    result = world.service("ravi", "reconcile", request)
    assert result.json()["status"] == "CANCELLED", result.text
    assert [e["task_id"] for e in world.local("ravi").calendar.list()] == ["outbound"]


def test_withdrawal_and_dispatch_linearize_before_transmission(tmp_path):
    for index in range(8):
        world = OwnerWorld(tmp_path / str(index))
        world.setup()
        agreement = world.build()
        reservation = world.prepare("ravi", agreement)
        returning = next(m for m in world.local("ravi").own_mutations(agreement) if m["intent"]["task_id"] == "return")
        request = world.request("ravi", agreement, returning, reservation)
        expected = world.local("ravi").read()["revision"]
        barrier = threading.Barrier(2)
        def send():
            barrier.wait()
            return world.service("ravi", "dispatch", request)
        def revoke():
            barrier.wait()
            return world.private("ravi", "withdraw", {"agreement_id": agreement["agreement_id"], "base_revision": 1,
                                                       "commitment_ids": [returning["commitment_id"]], "expected_revision": expected})
        with ThreadPoolExecutor(max_workers=2) as pool:
            sent, withdrawn = pool.submit(send), pool.submit(revoke)
            sent, withdrawn = sent.result(), withdrawn.result()
        assert withdrawn.status_code == 200, withdrawn.text
        assert sent.status_code in {200, 409}, sent.text
        with world.engine("ravi").vault.connect() as db:
            row = db.execute("SELECT * FROM living_mutations WHERE mutation_id=?", (returning["mutation_id"],)).fetchone()
        if world.local("ravi").calendar.get(returning["event_id"]):
            # A send which won the lock is an already-existing effect awaiting its
            # later scoped amendment delete. No send can begin after withdrawal.
            assert row["transmitted_at"] <= withdrawn.json()["withdrawal"]["body"]["issued_at"]
        assert returning["commitment_id"] in world.local("ravi").read()["withdrawn"][agreement["agreement_id"]]
