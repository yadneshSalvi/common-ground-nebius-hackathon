"""Authored v2 whole-protocol regressions; no external inference or humans."""
from copy import deepcopy
import json
import pytest
from tests.cluster import Cluster
from shared.living import agreement_digest


def living_cluster(tmp_path):
    cluster=Cluster(tmp_path)
    cluster.broker_config["fictional_sample"]=True
    for config in cluster.configs.values():
        config["fictional_sample"]=True
    return cluster


def state(cluster):
    response=cluster.op("/api/v2/state")
    assert response.status_code==200,response.text
    return response.json()


def sample(cluster,provider="none"):
    response=cluster.op("/api/v2/sample",{"provider":provider,"enable_policy":True})
    assert response.status_code==200,response.text
    value=response.json()
    assert value["status"]=="ACTIVE",value["planning"]
    return value


def owner_state(cluster,owner):
    response=cluster.op("/api/v2/state",owner=owner)
    assert response.status_code==200,response.text
    return response.json()


def release(cluster,owner,provider="none"):
    goal=state(cluster)["goal"]
    preview=cluster.op(f"/api/v2/offer-preview?goal_id={goal['goal_id']}&provider={provider}",owner=owner)
    assert preview.status_code==200,preview.text
    response=cluster.op("/api/v2/release",{"goal_id":goal["goal_id"],"provider":provider,"preview_digest":preview.json()["preview_digest"],"expected_revision":owner_state(cluster,owner)["revision"]},owner)
    assert response.status_code==200,response.text
    return response.json()


def withdraw_return(cluster):
    s=state(cluster); a=s["agreement"]
    cid=next(c["commitment_id"] for c in a["commitments"] if c["task_id"]=="return")
    response=cluster.op("/api/v2/withdraw",{"agreement_id":a["agreement_id"],"base_revision":a["revision"],"commitment_ids":[cid],"expected_revision":owner_state(cluster,"ravi")["revision"]},"ravi")
    assert response.status_code==200,response.text
    assert state(cluster)["status"]=="NEEDS_HELP"
    return cid


def plan(cluster,provider="local"):
    response=cluster.op("/api/v2/plan",{"provider":provider,"expected_revision":state(cluster)["revision"]})
    assert response.status_code==202,response.text
    return state(cluster)


def approve(cluster,owner,pending):
    response=cluster.op("/api/v2/approve",{"agreement_id":pending["agreement_id"],"revision":pending["revision"],"agreement_digest":agreement_digest(pending)},owner)
    assert response.status_code==200,response.text


def proposed_repair(cluster):
    original=sample(cluster)
    withdraw_return(cluster)
    question=plan(cluster)
    assert question["status"]=="NEEDS_HELP",question["planning"]
    assert any(q["owner_id"]=="leena" and q["task_id"]=="return" for q in question["questions"])
    assert not any(q["owner_id"]=="asha" and q["task_id"]=="return" for q in question["questions"])
    release(cluster,"leena")
    repaired=plan(cluster)
    assert repaired["pending"],repaired["planning"]
    return original,repaired


def test_living_sample_real_effects_and_scoped_conditional_repair(tmp_path):
    cluster=living_cluster(tmp_path)
    original,repaired=proposed_repair(cluster)
    pending=repaired["pending"]
    assert next(c for c in pending["commitments"] if c["task_id"]=="return")["owner_id"]=="leena"
    assert next(c for c in pending["commitments"] if c["task_id"]=="return")["conditions"][0]["by"]==975
    statuses={a["owner_id"]:a for a in repaired["approval_status"]}
    assert statuses["asha"]["status"]=="needs_review"
    assert statuses["leena"]["status"]=="needs_review"
    assert statuses["ravi"]["basis"]=="standing-policy"
    assert sorted(m["kind"] for m in pending["delta"]["calendar_mutations"])==["delete","insert"]
    old_pickup=next(c for c in original["commitments"] if c["task_id"]=="outbound")
    approve(cluster,"leena",pending)
    denied=cluster.op("/api/v2/execute",{"agreement_id":pending["agreement_id"],"revision":pending["revision"]})
    assert denied.status_code==409
    approve(cluster,"asha",pending)
    response=cluster.op("/api/v2/execute",{"agreement_id":pending["agreement_id"],"revision":pending["revision"]})
    assert response.status_code==200,response.text
    final=response.json(); assert final["status"]=="ACTIVE",final
    pickup=next(c for c in final["commitments"] if c["task_id"]=="outbound")
    assert (pickup["event_id"],pickup["etag"])==(old_pickup["event_id"],old_pickup["etag"])
    old_return=next(c for c in original["commitments"] if c["task_id"]=="return")
    assert cluster.apps["ravi"].state.owner.living.calendar.get(old_return["event_id"]) is None
    assert len(cluster.apps["leena"].state.owner.living.calendar.list())==2
    again=cluster.op("/api/v2/execute",{"agreement_id":pending["agreement_id"],"revision":pending["revision"]})
    assert again.status_code==200 and len(cluster.apps["leena"].state.owner.living.calendar.list())==2
    proof=cluster.op("/api/v2/evidence").json()
    assert "CG_PRIVATE_" not in json.dumps(proof)
    from scripts.verify_living_evidence import verify
    assert verify(proof)["valid"],verify(proof)
    from shared.protocol import digest
    for target in ("goal","exported-goal","dependency","receipt","signed-observation","historical-receipt","wrong-owner-head","observed-at"):
        altered=deepcopy(proof)
        if target=="goal":
            altered["agreements"][-1]["goal"]["tasks"][0]["duration"]+=1
        elif target=="exported-goal":
            altered["goals"][0]["title"]="Tampered but well-formed reviewed goal"
        elif target=="dependency":
            handoff=next(c for c in altered["agreements"][-1]["commitments"] if c["task_id"]=="handoff")
            handoff["dependencies"][0]["owner_id"]="ravi"
        elif target=="receipt":
            altered["receipts"][0]["etag"]='"tampered"'
        elif target=="signed-observation":
            altered["observations"][0]["body"]["payload"]["receipts"][0]["etag"]='"tampered"'
        elif target=="historical-receipt":
            old=next(r for m in altered["observation_history"] for r in m["body"]["payload"]["receipts"] if r["event_id"]==old_return["event_id"] and r["status"]=="VERIFIED")
            altered["receipts"]=[deepcopy(old) if r["event_id"]==old_return["event_id"] else r for r in altered["receipts"]]
        elif target=="wrong-owner-head":
            altered["observations"]=[m for m in altered["observations"] if m["body"]["issuer"]!="ravi"]
        else:
            altered["observed_at"]=altered["generated_at"]
        altered["digest"]=digest({k:v for k,v in altered.items() if k!="digest"})
        assert not verify(altered)["valid"],target


def test_withdrawal_cannot_be_relabelled_active_in_portable_proof(tmp_path):
    from scripts.verify_living_evidence import verify
    from shared.protocol import digest
    cluster=living_cluster(tmp_path); sample(cluster); withdraw_return(cluster)
    proof=cluster.op("/api/v2/evidence").json()
    assert proof["current_status"]=="NEEDS_HELP" and verify(proof)["valid"],verify(proof)
    altered=deepcopy(proof)
    altered.update(current_status="ACTIVE",withdrawn_commitment_ids=[],pending_agreement=None,pending_invalidated=False)
    altered["digest"]=digest({k:v for k,v in altered.items() if k!="digest"})
    result=verify(altered)
    assert not result["valid"] and "withdrawal" in result["errors"][0]


def test_current_calendar_does_not_prove_current_owner_authority(tmp_path):
    from scripts.verify_living_evidence import verify
    from shared.protocol import digest
    cluster=living_cluster(tmp_path); sample(cluster)
    old=cluster.op("/api/v2/evidence").json()
    memory={"type":"excluded_capability","value":{"capability":"preparation"},"scope":{"goal_id":state(cluster)["goal"]["goal_id"]},"provenance":"Owner-reviewed correction","expires_at":None,"private_note":"A private reason that is not released.","owner_confirmed":True}
    response=cluster.op("/api/v2/memory",{"expected_revision":owner_state(cluster,"asha")["revision"],"memory":memory},"asha")
    assert response.status_code==200,response.text
    proof=cluster.op("/api/v2/evidence").json()
    assert proof["current_status"]!="ACTIVE" and verify(proof)["valid"],verify(proof)
    assert all(r["status"]=="VERIFIED" for r in proof["receipts"])
    forged=deepcopy(proof); forged.update(current_status="ACTIVE",withdrawn_commitment_ids=[],pending_agreement=None,pending_invalidated=False)
    forged["digest"]=digest({k:v for k,v in forged.items() if k!="digest"})
    assert not verify(forged)["valid"]
    old_head=next(m for m in old["observations"] if m["body"]["issuer"]=="asha")
    forged["observations"]=[deepcopy(old_head) if m["body"]["issuer"]=="asha" else m for m in forged["observations"]]
    forged["digest"]=digest({k:v for k,v in forged.items() if k!="digest"})
    result=verify(forged)
    assert not result["valid"] and "supersedes" in result["errors"][0]


def test_memory_correction_can_release_fresh_scope_and_repair_the_active_goal(tmp_path):
    cluster=living_cluster(tmp_path); original=sample(cluster)
    first=next(m["body"]["payload"] for m in original["offers"] if m["body"]["issuer"]=="asha")
    memory={"type":"excluded_capability","value":{"capability":"preparation"},"scope":{"goal_id":original["goal"]["goal_id"]},"provenance":"Authored owner correction","owner_confirmed":True}
    response=cluster.op("/api/v2/memory",{"expected_revision":owner_state(cluster,"asha")["revision"],"memory":memory},"asha")
    assert response.status_code==200,response.text
    fresh=release(cluster,"asha")["release"]["body"]["payload"]
    assert fresh["offer_revision"]>first["offer_revision"] and "prepare" not in fresh["task_ids"]
    assert fresh["constraint_revision"]>first["constraint_revision"]
    missing=plan(cluster)
    assert missing["status"]=="NEEDS_HELP" and missing["planning"]["status"]=="NEEDS_HELP",missing["planning"]
    assert any(q["owner_id"]=="leena" and q["task_id"]=="prepare" for q in missing["questions"])
    release(cluster,"leena")
    proposed=plan(cluster); pending=proposed["pending"]
    assert pending,proposed["planning"]
    assert next(c for c in pending["commitments"] if c["task_id"]=="prepare")["owner_id"]!="asha"
    for row in proposed["approval_status"]:
        if row["status"]!="approved":
            approve(cluster,row["owner_id"],pending)
    response=cluster.op("/api/v2/execute",{"agreement_id":pending["agreement_id"],"revision":pending["revision"]})
    assert response.status_code==200 and response.json()["status"]=="ACTIVE",response.text
    assert sorted(m["kind"] for m in pending["delta"]["calendar_mutations"])==["delete","insert"]


def test_negative_refusal_never_volunteers_asha_or_repeats_question(tmp_path):
    cluster=living_cluster(tmp_path); sample(cluster); withdraw_return(cluster)
    first=plan(cluster)
    request=next(q for q in first["questions"] if q["owner_id"]=="leena" and q["task_id"]=="return")
    response=cluster.op("/api/v2/refuse",{"request_id":request["request_id"],"expected_revision":owner_state(cluster,"leena")["revision"]},"leena")
    assert response.status_code==200,response.text
    second=plan(cluster)
    assert second["status"]=="NEEDS_HELP" and second["pending"] is None
    assert len(second["questions"])==len(first["questions"])
    assert all(q["owner_id"]!="asha" or q["task_id"]!="return" for q in second["questions"])


def test_circle_only_release_cannot_reach_fireworks_or_nebius(tmp_path):
    cluster=living_cluster(tmp_path); sample(cluster)
    for provider in ("fireworks","nebius"):
        response=cluster.op("/api/v2/plan",{"provider":provider,"expected_revision":state(cluster)["revision"]})
        assert response.status_code==403
    assert not state(cluster)["model_runs"]


def test_sample_sessions_and_v2_ingestion_are_explicitly_scoped(tmp_path):
    cluster=Cluster(tmp_path)
    response=cluster.clients[4302].post("/sample/session",headers={"Origin":"http://127.0.0.1:4301"})
    assert response.status_code==404
    response=cluster.clients[4302].get("/v2/current")
    assert response.status_code==403
    cluster.broker_config["fictional_sample"]=True
    response=cluster.clients[4302].post("/sample/session",headers={"Origin":"https://evil.example"})
    assert response.status_code==403
    response=cluster.clients[4302].post("/sample/session",headers={"Origin":"http://127.0.0.1:4301"})
    assert response.status_code==200 and "owner" not in response.json()


def test_slow_old_observation_cannot_overwrite_successful_amendment(tmp_path):
    import threading
    cluster=living_cluster(tmp_path)
    _,repaired=proposed_repair(cluster)
    pending=repaired["pending"]
    approve(cluster,"asha",pending); approve(cluster,"leena",pending)
    living=cluster.app.state.living; original=living.call
    blocked=threading.Event(); resume=threading.Event()
    def intercept(owner,path,body=None):
        result=original(owner,path,body)
        if threading.current_thread().name=="stale-observer" and path.startswith("/coordination/v2/events") and not blocked.is_set():
            blocked.set(); assert resume.wait(10)
        return result
    living.call=intercept
    observer=threading.Thread(target=living.observe,name="stale-observer")
    observer.start(); assert blocked.wait(5)
    response=cluster.op("/api/v2/execute",{"agreement_id":pending["agreement_id"],"revision":pending["revision"]})
    assert response.status_code==200 and response.json()["status"]=="ACTIVE",response.text
    exact=deepcopy(living.store.read())
    resume.set(); observer.join(10); assert not observer.is_alive()
    after=living.store.read()
    assert after["status"]=="ACTIVE" and after["agreement"]["revision"]==2
    assert after["receipts"]==exact["receipts"] and after["observed_at"]==exact["observed_at"]
