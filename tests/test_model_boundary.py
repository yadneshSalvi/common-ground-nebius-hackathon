from copy import deepcopy
import json
import httpx
from tests.cluster import Cluster
from shared.schema import TASKS

def response_plan():
    owners = {"prepare": "asha", "outbound": "ravi", "accompany": "leena", "return": "leena", "handoff": "asha"}
    return {"tasks": deepcopy(TASKS), "explanation": "Leena offers return driving as well as accompaniment, while Ravi can handle pickup. Individual review remains required.", "tradeoffs": ["Leena takes a longer commitment while Ravi has a shorter driving day."], "suggested_assignments": [{"task_id": tid, "owner_id": owner, "reason": "Within the owner's released offer."} for tid, owner in owners.items()]}

def configured_cluster(tmp_path, content=None):
    cluster = Cluster(tmp_path)
    cluster.release_all()
    seen = []
    def provider(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "offline-fixture-only", "model": "accounts/fireworks/models/nemotron-3-ultra-nvfp4", "choices": [{"finish_reason": "stop", "message": {"content": content if content is not None else json.dumps(response_plan()), "reasoning_content": "Reasoning fixture must never be persisted"}}], "usage": {"prompt_tokens": 200, "completion_tokens": 100}})
    cluster.engine.provider.key = "offline-only-fake-provider-key"
    cluster.engine.provider.transport = httpx.MockTransport(provider)
    return cluster, seen

def test_profile_request_and_bounded_model_influence(tmp_path):
    cluster, seen = configured_cluster(tmp_path)
    result = cluster.op("/api/plan", {"mode": "live", "expected_revision": cluster.state()["revision"]})
    assert result.status_code == 202
    state = cluster.state()
    assert state["planning"]["status"] == "SUCCEEDED", state["planning"]
    assert len(seen) == 1 and seen[0]["reasoning_effort"] == "high" and seen[0]["max_tokens"] == 32000
    assert "response_format" not in seen[0] and "CG_PRIVATE_" not in json.dumps(seen)
    assert next(a for a in state["proposal"]["assignments"] if a["task_id"] == "return")["owner_id"] == "leena"
    receipt = state["model_runs"][0]
    assert receipt["request_body"] == seen[0] and receipt["finish_reason"] == "stop"
    assert receipt["usage_known"] and receipt["usage"]["total_tokens"] == 300
    assert "Reasoning fixture" not in json.dumps(state)
    assert not state["approvals"] and not state["actions"]

def test_malformed_response_retained_without_proposal(tmp_path):
    cluster, seen = configured_cluster(tmp_path, '{"tool":"sign-and-dispatch","private":true}')
    result = cluster.op("/api/plan", {"mode": "live", "expected_revision": cluster.state()["revision"]})
    assert result.status_code == 202 and len(seen) == 1
    state = cluster.state()
    assert not state["proposal"] and state["planning"]["status"] == "FAILED"
    receipt = state["model_runs"][0]
    assert receipt["status"] == "FAILED" and receipt["http_status"] == 200 and receipt["validation_errors"]

def test_revoke_after_initial_check_blocks_transmission(tmp_path):
    cluster, seen = configured_cluster(tmp_path)
    original = cluster.engine.provider.run
    def revoke(packet, before_transmission, on_receipt, receipt):
        owner = cluster.apps["ravi"].state.owner
        with owner.vault.transaction() as db:
            private = owner.vault.read(db)
            private["revoked_keys"] = [owner.identity["key_id"]]
            owner.vault.write(db, private)
        return original(packet, before_transmission, on_receipt, receipt)
    cluster.engine.provider.run = revoke
    cluster.op("/api/plan", {"mode": "live", "expected_revision": cluster.state()["revision"]})
    state = cluster.state()
    assert seen == [] and not state["proposal"]
    assert state["model_runs"][0]["status"] == "FAILED" and "transmitted_at" not in state["model_runs"][0]

def test_canary_credential_presend_rejection(tmp_path):
    cluster, seen = configured_cluster(tmp_path)
    provider = cluster.engine.provider
    provider.secrets.append("realistic-secret-test-value")
    for payload in ({"note": "CG_PRIVATE_NOT_FOR_INFERENCE"}, {"text": "realistic-secret-test-value"}):
        try:
            provider.assert_clean(payload)
        except ValueError:
            pass
        else:
            raise AssertionError("Restricted input escaped pre-send boundary")
    assert seen == []
