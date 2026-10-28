import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import threading
import time

import httpx
import pytest

from tests.test_living_integration import living_cluster,sample,state,plan,owner_state,release,withdraw_return
from broker.living_models import ROUTES


def response(body,output):
    return httpx.Response(200,json={"id":"authored-offline-response","model":body["model"],"choices":[{"finish_reason":"stop","message":{"content":json.dumps(output),"reasoning_content":"Excluded reasoning fixture"}}],"usage":{"prompt_tokens":101,"completion_tokens":67}})


def structured_repair(request):
    body=json.loads(request.content); packet=json.loads(body["messages"][1]["content"])
    chosen=[]
    for task in packet["goal"]["tasks"]:
        offer=next((o for o in packet["released_offers"] if task["task_id"] in o["task_ids"]),None)
        chosen.append({"task_id":task["task_id"],"owner_id":offer["owner_id"] if offer else None})
    return response(body,{"suggested_assignments":chosen,"questions":[],"outcome":"candidate","explanation":None})


def test_actual_request_boundary_exact_route_profile_and_optional_prose(tmp_path):
    cluster=living_cluster(tmp_path); sample(cluster,"fireworks")
    living=cluster.app.state.living
    living.provider.keys["fireworks"]="offline-fixture-key"
    seen=[]
    def provider(request):
        seen.append(json.loads(request.content)); return structured_repair(request)
    living.provider.transport=httpx.MockTransport(provider)
    result=plan(cluster,"fireworks")
    assert result["pending"],result["planning"]
    assert seen[0]["reasoning_effort"]=="high" and seen[0]["max_tokens"]==32000
    assert "response_format" not in seen[0]
    receipt=result["model_runs"][-1]
    assert receipt["status"]=="SUCCEEDED" and receipt["usage_known"]
    assert receipt["request_body"]==seen[0] and receipt["validated_output"]["explanation"]==""
    assert "Excluded reasoning fixture" not in json.dumps(result)
    assert receipt["endpoint"]==ROUTES["fireworks"]["endpoint"]


def test_fireworks_disclosure_does_not_authorize_nebius(tmp_path):
    cluster=living_cluster(tmp_path); sample(cluster,"fireworks")
    living=cluster.app.state.living; seen=[]
    living.provider.transport=httpx.MockTransport(lambda request:seen.append(request))
    response=cluster.op("/api/v2/plan",{"provider":"nebius","expected_revision":state(cluster)["revision"]})
    assert response.status_code==403 and not seen and not state(cluster)["model_runs"]


def test_fresh_named_nebius_grants_use_qualified_profile_without_fallback(tmp_path):
    cluster=living_cluster(tmp_path); sample(cluster,"fireworks")
    for owner in ("asha","ravi","leena"):
        release(cluster,owner,"nebius")
    living=cluster.app.state.living; living.provider.keys["nebius"]="offline-fixture-key"
    seen=[]
    def provider(request):
        seen.append(request); return structured_repair(request)
    living.provider.transport=httpx.MockTransport(provider)
    result=plan(cluster,"nebius"); assert result["pending"],result["planning"]
    body=json.loads(seen[0].content)
    assert str(seen[0].url).startswith(ROUTES["nebius"]["endpoint"])
    assert body["temperature"]==1.0 and body["top_p"]==0.95
    assert body["chat_template_kwargs"]=={"enable_thinking":True,"force_nonempty_content":True}
    assert "reasoning_effort" not in body and "response_format" not in body
    assert result["model_runs"][-1]["provider_id"]=="nebius"


def test_cancellation_closes_transport_and_discards_late_result(tmp_path):
    cluster=living_cluster(tmp_path); sample(cluster,"fireworks")
    living=cluster.app.state.living; living.provider.keys["fireworks"]="offline-fixture-key"
    entered=threading.Event(); closed=threading.Event()
    class Slow(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):
            entered.set()
            try:
                await asyncio.sleep(30)
                return structured_repair(request)
            finally:
                closed.set()
    living.provider.transport=Slow()
    living.begin("repair","fireworks",state(cluster)["revision"])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(living.run)
        assert entered.wait(5)
        living.cancel(living.store.read()["revision"])
        future.result(timeout=5)
    final=state(cluster)
    assert closed.is_set() and final["pending"] is None
    assert final["planning"]["status"]=="CANCELLED"
    receipt=final["model_runs"][-1]
    assert receipt["status"]=="CANCELLED" and receipt["transmitted_at"] and not receipt["usage_known"]


def test_private_plain_language_note_and_hash_never_reach_broker_or_provider(tmp_path):
    from shared.protocol import digest
    cluster=living_cluster(tmp_path); sample(cluster,"fireworks")
    secret="My sister visits the quiet blue greenhouse every Thursday."
    owner=cluster.apps["asha"].state.owner.living
    with owner.lock,owner.vault.transaction() as db:
        private=owner.read(db)
        private["memories"][0]["private_note"]=secret
        owner.write(db,private)
    living=cluster.app.state.living; living.provider.keys["fireworks"]="offline-fixture-key"
    living.provider.transport=httpx.MockTransport(structured_repair)
    result=plan(cluster,"fireworks")
    public=json.dumps({"state":result,"proof":living.evidence()},ensure_ascii=False)
    assert secret not in public and digest(secret) not in public
    assert "private_note" not in public and "CG_PRIVATE_" not in public


def test_invalid_output_is_retained_without_signing_or_writes(tmp_path):
    cluster=living_cluster(tmp_path); original=sample(cluster,"fireworks")
    living=cluster.app.state.living; living.provider.keys["fireworks"]="offline-fixture-key"
    living.provider.transport=httpx.MockTransport(lambda request:response(json.loads(request.content),{"tool":"approve-and-dispatch"}))
    result=plan(cluster,"fireworks")
    assert result["pending"] is None and result["planning"]["status"]=="FAILED"
    receipt=result["model_runs"][-1]
    assert receipt["http_status"]==200 and receipt["usage_known"] and receipt["validation_errors"]
    assert result["counts"]["calendar_mutations"]==original["counts"]["calendar_mutations"]


def test_withdrawn_history_is_explicitly_ineligible_and_cannot_restore_authority(tmp_path):
    cluster=living_cluster(tmp_path); original=sample(cluster,"fireworks")
    withdraw_return(cluster)
    living=cluster.app.state.living; living.provider.keys["fireworks"]="offline-fixture-key"
    def provider(request):
        body=json.loads(request.content); packet=json.loads(body["messages"][1]["content"])
        assert next(t for t in packet["eligible_assignments"] if t["task_id"]=="return")["eligible_owner_ids"]==[]
        assert any(t["task_id"]=="return" and t["owner_id"]=="ravi" for t in packet["withdrawn_assignments"])
        return response(body,{"suggested_assignments":[{"task_id":"return","owner_id":"ravi"}],"questions":[],"outcome":"candidate","explanation":""})
    living.provider.transport=httpx.MockTransport(provider)
    result=plan(cluster,"fireworks")
    assert result["pending"] is None and result["planning"]["status"]=="FAILED"
    assert result["model_runs"][-1]["error"]=="Suggestion exceeded currently released task scope."
    assert result["counts"]["calendar_mutations"]==original["counts"]["calendar_mutations"]
