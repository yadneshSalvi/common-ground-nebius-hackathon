from copy import deepcopy
import json
import uuid
import pytest
from icalendar import Calendar
from broker.engine import BrokerError
from shared.protocol import sign_message, digest
from tests.cluster import Cluster

@pytest.fixture
def cluster(tmp_path):
    return Cluster(tmp_path)

def test_complete_effects_idempotence_ics_and_proof(cluster):
    cluster.release_all()
    proposal = cluster.plan()
    cluster.approve(proposal)
    state = cluster.enact(proposal)
    assert state["state"] == "ACTIVE"
    assert len(state["actions"]) == 5 and all(a["status"] == "VERIFIED" for a in state["actions"])
    assert sum(len(app.state.owner.calendar.list()) for app in cluster.apps.values()) == 5
    assert cluster.enact(proposal)["state"] == "ACTIVE"
    assert sum(len(app.state.owner.calendar.list()) for app in cluster.apps.values()) == 5
    events = Calendar.from_ical(cluster.op("/api/agreement.ics").content).walk("VEVENT")
    assert len(events) == 5 and all(str(e["STATUS"]) == "CONFIRMED" for e in events)
    proof = cluster.op("/api/evidence").json()
    assert digest(proof["content"]) == proof["content_sha256"]
    serialized = json.dumps(proof)
    assert "CG_PRIVATE_" not in serialized
    for secret in [cluster.ingest, cluster.broker_token, *cluster.tokens.values()]:
        assert secret not in serialized
    assert len(proof["content"]["signed_messages"]) == 6

def test_lost_ack_exact_redelivery_and_altered_replay(cluster):
    cluster.drop_ack = True
    failed = cluster.op("/api/release", {"expected_revision": 1, "allow_inference": True}, "asha")
    assert failed.status_code == 503 and len(cluster.state()["offers"]) == 1
    recovered = cluster.op("/api/state", owner="asha")
    assert recovered.status_code == 200 and recovered.json()["coordinator_available"]
    assert len(cluster.engine.store.read()["protocol_messages"]) == 1
    grant = deepcopy(cluster.state()["offers"][0])
    grant["body"]["consent_revision"] += 1
    changed = sign_message(cluster.apps["asha"].state.owner.identity["private_key"], grant["body"])
    with pytest.raises(BrokerError, match="reused"):
        cluster.engine.ingest_release(changed)
    response = cluster.op("/api/withdraw", {"expected_revision": 1}, "asha")
    assert response.status_code == 200 and not cluster.state()["offers"]

def test_wrong_circle_audience_and_stale_new_consent(cluster):
    cluster.release_all()
    original = cluster.state()["offers"][0]
    for field, value, match in [("circle_id", "other-circle", "different circle"), ("audience", ["malicious-recipient"], "audience")]:
        body = deepcopy(original["body"])
        body.update(message_id=str(uuid.uuid4()), nonce=uuid.uuid4().hex)
        body[field] = value
        altered = sign_message(cluster.apps[body["issuer"]].state.owner.identity["private_key"], body)
        with pytest.raises(BrokerError, match=match):
            cluster.engine.ingest_release(altered)
    body = deepcopy(original["body"])
    body.update(message_id=str(uuid.uuid4()), nonce=uuid.uuid4().hex)
    body["payload"]["offer"]["revision"] += 1
    with pytest.raises(BrokerError, match="stale"):
        cluster.engine.ingest_release(sign_message(cluster.apps[body["issuer"]].state.owner.identity["private_key"], body))

def test_member_only_grant_blocks_provider_without_network(cluster):
    cluster.release_all(inference=False)
    response = cluster.op("/api/plan", {"mode": "live", "expected_revision": cluster.state()["revision"]})
    assert response.status_code == 403 and "separate named release" in response.text
    assert not cluster.state()["model_runs"]
    assert cluster.plan()["model_receipt_id"] is None

def test_scoped_authority_and_hostile_origin(cluster):
    broker = cluster.clients[4302]
    assert broker.get("/api/state").status_code == 403
    assert broker.get("/api/state", headers={"Authorization": "Bearer " + cluster.ingest}).status_code == 403
    assert broker.get("/api/state", headers={**cluster.headers(), "Origin": "http://hostile.example"}).status_code == 403
    assert broker.get("/v1/current", headers=cluster.headers()).status_code == 403
    for owner, config in cluster.configs.items():
        for cap in (cluster.broker_token, cluster.ingest, config["service_token"]):
            response = cluster.clients[config["port"]].get("/api/state", headers={"Authorization": "Bearer " + cap})
            assert response.status_code in (401, 403)

def test_timeout_reconcile_and_user_edit_safe_compensation(cluster):
    cluster.release_all()
    proposal = cluster.plan()
    cluster.approve(proposal)
    cluster.op("/api/fault", {"mode": "timeout_after_write"}, "ravi")
    partial = cluster.enact(proposal)
    assert partial["state"] == "RECOVERING"
    assert any(a["status"] == "AMBIGUOUS" for a in partial["actions"])
    cluster.op("/api/fault", {"mode": "none"}, "ravi")
    response = cluster.op("/api/reconcile", {"proposal_id": proposal["proposal_id"]})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "ACTIVE"
    assert sum(len(a.state.owner.calendar.list()) for a in cluster.apps.values()) == 5
    event = cluster.apps["asha"].state.owner.calendar.list()[0]
    cluster.op("/api/calendar/" + event["event_id"] + "/edit", {"summary": "CG_PRIVATE_EDITED_TITLE_REMAINS_LOCAL"}, "asha")
    response = cluster.op("/api/compensate", {"proposal_id": proposal["proposal_id"]})
    assert response.status_code == 200 and response.json()["state"] == "NEEDS_ATTENTION"
    assert "CG_PRIVATE_EDITED" not in response.text
    assert sum(len(a.state.owner.calendar.list()) for a in cluster.apps.values()) == 1
    proof = cluster.op("/api/evidence")
    assert proof.status_code == 200 and "CG_PRIVATE_EDITED" not in proof.text

def test_withdrawal_in_persisted_intent_gap(cluster):
    cluster.release_all()
    proposal = cluster.plan()
    cluster.approve(proposal)
    cluster.op("/api/fault", {"mode": "pause_before_send"}, "ravi")
    assert cluster.enact(proposal)["state"] == "RECOVERING"
    own_state = cluster.op("/api/state", owner="ravi").json()
    response = cluster.op("/api/withdraw", {"expected_revision": own_state["consent_revision"]}, "ravi")
    assert response.status_code == 200, response.text
    recovered = cluster.op("/api/reconcile", {"proposal_id": proposal["proposal_id"]})
    assert recovered.status_code == 200 and recovered.json()["state"] == "COMPENSATED"
    assert sum(len(a.state.owner.calendar.list()) for a in cluster.apps.values()) == 0

def test_changed_preference_replans_and_preserves_proof(cluster):
    cluster.release_all()
    first = cluster.plan()
    cluster.approve(first)
    cluster.enact(first)
    state = cluster.op("/api/state", owner="asha").json()
    preferences = state["preferences"]
    response = cluster.op("/api/preferences", {"expected_revision": state["constraint_revision"], "availability_start": preferences["availability_start"], "availability_end": 950, "task_ids": preferences["task_ids"], "ask_before_driving": preferences["ask_before_driving"]}, "asha")
    assert response.status_code == 200, response.text
    assert cluster.state()["state"] == "REPLAN_REQUIRED"
    assert all(a["status"] != "VERIFIED" for a in cluster.state()["actions"])
    renewed = cluster.op("/api/release", {"expected_revision": 2, "allow_inference": True}, "asha")
    assert renewed.status_code == 200, renewed.text
    result = cluster.op("/api/new-round", {"expected_revision": cluster.state()["revision"]})
    assert result.status_code == 200, result.text
    second = cluster.plan()
    assert next(a for a in second["assignments"] if a["task_id"] == "handoff")["owner_id"] == "leena"
    assert second["version"] == first["version"] + 1
    assert not cluster.state()["approvals"]
    proof = cluster.op("/api/evidence").json()["content"]
    assert len(proof["proposals"]) == 2 and proof["closed_rounds"] and proof["action_receipts"]
    assert len([m for m in proof["signed_messages"] if m["body"]["type"] == "Approval"]) == 3

def test_edit_between_dispatch_and_final_observation_never_active(cluster):
    cluster.release_all()
    proposal = cluster.plan()
    cluster.approve(proposal)
    original = cluster.engine.owner_call
    edited = False
    def intercept(owner, path, body=None):
        nonlocal edited
        if path.startswith("/coordination/events") and not edited:
            event = cluster.apps["asha"].state.owner.calendar.list()[0]
            cluster.apps["asha"].state.owner.calendar.edit(event["event_id"], "CG_PRIVATE_LATE_EDIT")
            edited = True
        return original(owner, path, body)
    cluster.engine.owner_call = intercept
    state = cluster.enact(proposal)
    assert state["state"] == "NEEDS_ATTENTION"
    assert "CG_PRIVATE_LATE_EDIT" not in json.dumps(state)

def test_broker_restart_recovers_outbox_without_duplicate_effect(cluster):
    from broker.engine import Engine
    from broker.execution import execute
    cluster.release_all()
    proposal = cluster.plan()
    cluster.approve(proposal)
    cluster.op("/api/fault", {"mode": "timeout_after_write"}, "ravi")
    assert cluster.enact(proposal)["state"] == "RECOVERING"
    cluster.op("/api/fault", {"mode": "none"}, "ravi")
    restarted = Engine(cluster.broker_config)
    restarted.bootstrap_members()
    state = execute(restarted, proposal["proposal_id"], reconcile=True)
    assert state["state"] == "ACTIVE"
    assert sum(len(a.state.owner.calendar.list()) for a in cluster.apps.values()) == 5

def test_replanning_cannot_replace_a_signed_execution_round(cluster):
    cluster.release_all()
    proposal = cluster.plan()
    cluster.approve(proposal)
    result = cluster.op("/api/plan", {"mode": "local", "expected_revision": cluster.state()["revision"]})
    assert result.status_code == 409 and "Close the current" in result.text
    assert cluster.state()["proposal"]["proposal_id"] == proposal["proposal_id"]
    assert len(cluster.state()["approvals"]) == 3
    assert cluster.enact(proposal)["state"] == "ACTIVE"

def test_proof_verifier_rejects_tampering_even_with_recomputed_outer_hash(cluster):
    from scripts.verify_evidence import verify
    cluster.release_all()
    proposal = cluster.plan()
    cluster.approve(proposal)
    proof = cluster.op("/api/evidence").json()
    assert verify(proof)["valid"]
    corrupted = deepcopy(proof)
    corrupted["content"]["proposals"][0]["actions"][0]["start"] += 1
    corrupted["content_sha256"] = digest(corrupted["content"])
    with pytest.raises(ValueError):
        verify(corrupted)
    corrupted = deepcopy(proof)
    corrupted["content"]["signed_messages"][0]["body"]["consent_revision"] += 1
    corrupted["content_sha256"] = digest(corrupted["content"])
    with pytest.raises(ValueError, match="signature"):
        verify(corrupted)


def test_active_view_and_exports_observe_later_private_edit(cluster):
    cluster.release_all()
    proposal = cluster.plan()
    cluster.approve(proposal)
    assert cluster.enact(proposal)['state'] == 'ACTIVE'
    event = cluster.apps['asha'].state.owner.calendar.list()[0]
    edited = cluster.apps['asha'].state.owner.calendar.edit(event['event_id'], 'CG_PRIVATE_AFTER_ACTIVE_EDIT')
    state = cluster.state()
    assert state['state'] == 'NEEDS_ATTENTION'
    action = next(a for a in state['actions'] if a['event_id'] == event['event_id'])
    assert action['status'] == 'NEEDS_ATTENTION' and 'etag' not in action['remaining_effect']
    assert edited['etag'] not in json.dumps(state) and 'CG_PRIVATE_AFTER_ACTIVE_EDIT' not in json.dumps(state)
    proof = cluster.op('/api/evidence').json()
    assert proof['content']['current_state'] == 'NEEDS_ATTENTION'
    events = Calendar.from_ical(cluster.op('/api/agreement.ics').content).walk('VEVENT')
    changed = next(e for e in events if str(e['UID']) == event['event_id'] + '@common-ground.local')
    assert str(changed['STATUS']) == 'TENTATIVE'


def test_changed_offers_clear_obsolete_refusal_but_not_running_attempt(cluster):
    cluster.op('/api/release', {'expected_revision': 1, 'allow_inference': False}, 'asha')
    cluster.op('/api/plan', {'mode': 'local', 'expected_revision': cluster.state()['revision']})
    assert cluster.state()['planning']['status'] == 'NO_PLAN'
    cluster.op('/api/release', {'expected_revision': 1, 'allow_inference': False}, 'ravi')
    state = cluster.state()
    assert state['planning']['status'] == 'IDLE' and state['planning']['error'] is None
    assert any(e['type'] == 'SOLVER_INFEASIBLE' for e in state['history'])
    with cluster.engine.store.transaction() as (current, db):
        current['planning'] = {'status': 'RUNNING', 'phase': 'test pending attempt', 'error': None}
    cluster.op('/api/release', {'expected_revision': 1, 'allow_inference': False}, 'leena')
    assert cluster.state()['planning']['status'] == 'RUNNING'
