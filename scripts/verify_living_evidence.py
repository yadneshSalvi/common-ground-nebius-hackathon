#!/usr/bin/env python3
"""Standalone offline v2 verifier. Copy this file and a proof anywhere.

Requires only rfc8785 and cryptography; no project imports, keys, database,
network, model or solver. It verifies owner-key evidence, not owner identity or
physical attendance. All current successful readbacks must be owner-signed.
"""
import argparse
import base64
from datetime import datetime,date
import hashlib
import json
from pathlib import Path

import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def digest(value):
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def need(condition,message):
    if not condition:
        raise ValueError(message)


def decode(value):
    return base64.urlsafe_b64decode(value+"="*((-len(value))%4))


def instant(value):
    need(isinstance(value,str) and value.endswith("Z"),"Invalid UTC timestamp")
    return datetime.fromisoformat(value[:-1]+"+00:00")


def commitment_digest(c):
    return digest({k:v for k,v in c.items() if k not in ("offer_id","offer_revision")})


def check_goal(goal,owners):
    need(goal["schema_version"]==2 and 2<=len(goal["participants"])<=6 and set(goal["participants"])<=set(owners),"Unregistered goal participants")
    need(len(set(goal["participants"]))==len(goal["participants"]),"Duplicate participant")
    tasks={t["task_id"]:t for t in goal["tasks"]}
    need(2<=len(tasks)<=12 and len(tasks)==len(goal["tasks"]),"Invalid task count/identity")
    routes={(r["from_location"],r["to_location"]):r["duration"] for r in goal["routes"]}
    need(len(routes)==len(goal["routes"]),"Conflicting route facts")
    for t in goal["tasks"]:
        date.fromisoformat(t["date"])
        need(type(t["duration"]) is int and t["duration"]>0 and 0<=t["earliest"]<t["latest"]<=1440 and t["earliest"]+t["duration"]<=t["latest"],"Invalid reviewed task interval")
        need(t["source_quote"] and t["source_quote"] in goal["source_text"],"Unsupported reviewed task provenance")
        need(set(t["predecessors"])<=set(tasks),"Unknown dependency")
        if t["start_location"]!=t["end_location"]:
            need(t["capability"]=="driving" and routes.get((t["start_location"],t["end_location"]))==t["duration"],"Unconfirmed journey duration")
    for r in goal["routes"]:
        need(r["source_quote"] in goal["source_text"] and type(r["duration"]) is int and r["duration"]>0,"Unconfirmed route provenance")
    visiting=set(); visited=set()
    def visit(tid):
        need(tid not in visiting,"Cyclic responsibility graph")
        if tid in visited:
            return
        visiting.add(tid)
        for pid in tasks[tid]["predecessors"]:
            visit(pid)
        visiting.remove(tid); visited.add(tid)
    for tid in tasks:
        visit(tid)
    return tasks,routes


def verify(proof):
    try:
        need(proof.get("format")=="common-ground.living-proof/v2","Unknown proof format")
        need(proof.get("digest")==digest({k:v for k,v in proof.items() if k!="digest"}),"Outer canonical digest mismatch")
        owners={o["id"]:o for o in proof["owners"]}
        need(len(owners)==len(proof["owners"]),"Duplicate signing identity")
        goals={g["goal_id"]:g for g in proof["goals"]}
        need(len(goals)==len(proof["goals"]),"Duplicate reviewed goal identity")
        for goal in goals.values():
            check_goal(goal,owners)
        releases={}; consents={}; consent_messages={}; message_ids=set(); nonces=set(); observation_heads={}; latest_observation_times={}; withdrawals=[]
        def signed(message,unique=True):
            need(set(message)=={"body","signature"},"Unexpected signed-message fields")
            body=message["body"]
            need(set(body)=={"type","schema_version","message_id","issuer","audience","circle_id","issued_at","expires_at","nonce","key_id","consent_revision","payload"},"Unexpected envelope fields")
            owner=owners.get(body["issuer"])
            need(owner and body["key_id"]==owner["key_id"] and body["schema_version"]==2 and "common-ground-broker" in body["audience"],"Unknown key, version or audience")
            need(instant(body["expires_at"])>instant(body["issued_at"]),"Invalid historical signature lifetime")
            need(instant(body["issued_at"])<=instant(proof["generated_at"]),"Signature was issued after this export")
            try:
                Ed25519PublicKey.from_public_bytes(decode(owner["public_key"])).verify(decode(message["signature"]),rfc8785.dumps(body))
            except Exception as exc:
                raise ValueError("Invalid owner signature") from exc
            if unique:
                need(body["message_id"] not in message_ids and (body["issuer"],body["nonce"]) not in nonces,"Replayed protocol identity")
                message_ids.add(body["message_id"]); nonces.add((body["issuer"],body["nonce"]))
            need(body["payload"]["owner_id"]==body["issuer"],"Payload identity mismatch")
            return body,body["payload"]
        for message in proof["messages"]:
            body,p=signed(message)
            need(body["type"] in ("LivingRelease","LivingConsent","LivingWithdrawal","LivingRefusal"),"Wrong protocol purpose")
            if body["type"]=="LivingRelease":
                need(set(body["audience"])==set(p["recipients"]["humans"]+p["recipients"]["inference"]+["common-ground-broker"]),"Release audience mismatch")
                goal=goals.get(p["goal_id"])
                need(goal and goal["revision"]==p["goal_revision"] and digest(goal)==p["goal_digest"],"Exported goal differs from the exact signed release")
                releases[p["offer_id"]]=p
            elif body["type"]=="LivingConsent":
                need(p["consent_revision"]==body["consent_revision"],"Consent revision mismatch")
                consents.setdefault((p["agreement_id"],p["revision"]),[]).append(p)
                consent_messages[body["message_id"]]=p
            elif body["type"]=="LivingWithdrawal":
                withdrawals.append(p)
        for message in proof.get("observation_history",[])+proof.get("observations",[]):
            body,p=signed(message,unique=False)
            need(body["type"]=="LivingObservation","Wrong observation purpose")
            need(instant(p["observed_at"])<=instant(body["issued_at"]),"Observation timestamp follows its signature")
            key=(body["issuer"],p["agreement_id"])
            latest_observation_times[key]=max(latest_observation_times.get(key,p["observed_at"]),p["observed_at"])
        for message in proof.get("observations",[]):
            body,p=signed(message,unique=False)
            key=(body["issuer"],p["agreement_id"])
            need(key not in observation_heads,"Duplicate current observation head")
            need(p["observed_at"]==latest_observation_times[key],"A newer signed observation supersedes this exported head")
            observation_heads[key]=p
        agreements={}; intent_creations={}; mutations={}
        for agreement in sorted(proof["agreements"],key=lambda a:(a["agreement_id"],a["revision"])):
            key=(agreement["agreement_id"],agreement["revision"])
            need(key not in agreements and agreement["revision"]==agreement["base_revision"]+1,"Duplicate or inconsistent agreement revision")
            agreements[key]=agreement
            goal=agreement["goal"]; tasks,routes=check_goal(goal,owners)
            need(goals.get(goal["goal_id"])==goal,"Agreement differs from exported reviewed goal")
            need(agreement["goal_digest"]==digest(goal),"Goal digest mismatch")
            cs={c["task_id"]:c for c in agreement["commitments"]}; by_id={c["commitment_id"]:c for c in agreement["commitments"]}
            need(len(cs)==len(agreement["commitments"])==len(by_id) and set(cs)<=set(tasks),"Duplicate or unknown commitment")
            need(all(t["task_id"] in cs for t in tasks.values() if t["required"]),"Incomplete required coverage")
            for c in cs.values():
                t=tasks[c["task_id"]]; release=releases.get(c["offer_id"])
                need(release and release["goal_digest"]==digest(goal) and release["owner_id"]==c["owner_id"] and release["offer_revision"]==c["offer_revision"] and c["task_id"] in release["task_ids"],"Commitment exceeds exact signed release")
                need(c["owner_id"] in goal["participants"] and c["commitment_id"]=="commitment-"+digest([agreement["agreement_id"],c["task_id"],c["owner_id"]])[:32],"Unstable commitment identity")
                for field in ("date","start_location","end_location","capability","label","subject"):
                    need(c[field]==t[field],"Commitment changes reviewed task fact")
                need(c["timezone"]==goal["timezone"] and c["end"]-c["start"]==t["duration"] and t["earliest"]<=c["start"]<c["end"]<=t["latest"],"Commitment interval mismatch")
                need(any(w["date"]==c["date"] and w["start"]<=c["start"] and c["end"]<=w["end"] for w in release["windows"]),"Commitment exceeds released availability")
                related=set(t["predecessors"])|{x["task_id"] for x in tasks.values() if t["task_id"] in x["predecessors"]}
                fields=("task_id","commitment_id","owner_id","date","start","end","start_location","end_location")
                expected=[{f:x[f] for f in fields} for x in sorted(cs.values(),key=lambda x:x["task_id"]) if x["task_id"] in related]
                need(c["dependencies"]==expected,"Changed or omitted handoff dependency/counterpart")
                for pid in t["predecessors"]:
                    need(pid in cs and (cs[pid]["date"],cs[pid]["end"])<=(c["date"],c["start"]),"Dependency timing violation")
                conditions=[v for v in release["conditions"] if v["task_id"]==c["task_id"]]
                need(c["conditions"]==conditions,"Altered conditional offer")
                for condition in conditions:
                    receiver=cs.get(condition["receiver_task_id"])
                    need(receiver and receiver["owner_id"]==condition["receiver_id"] and receiver["date"]==c["date"] and c["end"]<=receiver["start"] and receiver["end"]<=condition["by"],"Conditional handoff violation")
            for owner in goal["participants"]:
                own=sorted([c for c in cs.values() if c["owner_id"]==owner],key=lambda c:(c["date"],c["start"]))
                for left,right in zip(own,own[1:]):
                    travel=0 if left["end_location"]==right["start_location"] else routes.get((left["end_location"],right["start_location"]))
                    gap=(date.fromisoformat(right["date"])-date.fromisoformat(left["date"])).days*1440+right["start"]-left["end"]
                    need(travel is not None and gap>=travel,"Owner overlap or unknown travel")
            for subject_day in {(c["subject"],c["date"]) for c in cs.values()}:
                ordered=sorted([c for c in cs.values() if (c["subject"],c["date"])==subject_day],key=lambda c:c["start"])
                for left,right in zip(ordered,ordered[1:]):
                    need(left["end"]<=right["start"] and left["end_location"]==right["start_location"],"Recipient overlap or missing journey")
            need(len(agreement["intents"])==len(cs),"Wrong calendar intent coverage")
            for intent in agreement["intents"]:
                c=by_id[intent["commitment_id"]]
                need(intent["action_id"]=="action-"+digest(c["commitment_id"])[:32] and intent["event_id"]=="cg2"+hashlib.sha256(intent["action_id"].encode()).hexdigest()[:40],"Unstable calendar identity")
                for field in ("owner_id","task_id","label","date","timezone","start","end"):
                    need(intent[field]==c[field],"Calendar intent differs from commitment")
                need(intent["location"]=={"start":c["start_location"],"end":c["end_location"]},"Calendar location mismatch")
                need(intent["creation"]["agreement_id"]==agreement["agreement_id"] and intent["creation"]["revision"]<=agreement["revision"],"Invalid calendar creation provenance")
                need(intent["event_id"] not in intent_creations or intent_creations[intent["event_id"]]==intent["creation"],"Calendar creation provenance changed")
                intent_creations[intent["event_id"]]=intent["creation"]
            prior=agreements.get((agreement["agreement_id"],agreement["base_revision"]))
            need(agreement["base_revision"]==0 or prior is not None,"Missing amendment base revision")
            old={c["commitment_id"]:c for c in prior["commitments"]} if prior else {}
            old_intents={i["commitment_id"]:i for i in prior["intents"]} if prior else {}
            new_intents={i["commitment_id"]:i for i in agreement["intents"]}
            d=agreement["delta"]
            expected={"new":set(by_id)-set(old),"withdrawn":set(old)-set(by_id),"retained":{cid for cid in set(old)&set(by_id) if commitment_digest(old[cid])==commitment_digest(by_id[cid])},"changed":{cid for cid in set(old)&set(by_id) if commitment_digest(old[cid])!=commitment_digest(by_id[cid])}}
            for kind,ids in expected.items():
                need(set(d[kind])==ids and len(d[kind])==len(ids),"Incorrect amendment delta: "+kind)
            expected_mutations={("insert",cid) for cid in set(new_intents)-set(old_intents)}|{("delete",cid) for cid in set(old_intents)-set(new_intents)}|{("update",cid) for cid in set(old_intents)&set(new_intents) if old_intents[cid]!=new_intents[cid]}
            need({(m["kind"],m["commitment_id"]) for m in d["calendar_mutations"]}==expected_mutations and len(d["calendar_mutations"])==len(expected_mutations),"Calendar delta omits, duplicates or adds a mutation")
            for m in d["calendar_mutations"]:
                need(m["mutation_id"] not in mutations,"Duplicate mutation identity")
                need(m["kind"] in ("insert","update","delete"),"Unknown mutation kind")
                need((m["kind"]=="delete")== (m["intent"] is None),"Invalid mutation content")
                need((m["kind"]=="insert")== (m["expected_etag"] is None),"Missing conditional ETag")
                intent=(old_intents if m["kind"]=="delete" else new_intents)[m["commitment_id"]]
                need(all(m[f]==intent[f] for f in ("owner_id","commitment_id","action_id","event_id")),"Calendar mutation substitutes an identity")
                need(m["intent"]==(None if m["kind"]=="delete" else intent),"Calendar mutation changes exact intent")
                need(m["mutation_id"]=="mutation-"+digest([key[0],key[1],m["action_id"],m["kind"]])[:32],"Unstable calendar mutation identity")
                mutations[m["mutation_id"]]=(key,m)
            for consent in consents.get(key,[]):
                own={cid:c for cid,c in by_id.items() if c["owner_id"]==consent["owner_id"]}
                need(consent["agreement_digest"]==digest(agreement) and consent["goal_digest"]==digest(goal) and consent["base_revision"]==agreement["base_revision"],"Consent binds another agreement/base")
                need(consent["commitment_digests"]=={cid:commitment_digest(c) for cid,c in own.items()},"Consent commitment scope mismatch")
                need(consent["dependency_digests"]=={cid:digest({"dependencies":c["dependencies"],"conditions":c["conditions"]}) for cid,c in own.items()},"Consent dependency scope mismatch")
                need(consent["mutation_ids"]==[m["mutation_id"] for m in d["calendar_mutations"] if m["owner_id"]==consent["owner_id"]],"Consent mutation scope mismatch")
        for receipt in proof["receipts"]:
            if receipt["status"] in ("VERIFIED","CANCELLED","NEEDS_ATTENTION"):
                entry=mutations.get(receipt.get("mutation_id"))
                need(entry is not None,"Current receipt has no authorized mutation identity")
                key,mutation=entry
                head=observation_heads.get((mutation["owner_id"],key[0]))
                need(head is not None,"Current receipt has no observation by its owning signer/agreement")
                current=next((r for r in reversed(head["receipts"]) if r["event_id"]==receipt["event_id"]),None)
                fields=("mutation_id","commitment_id","action_id","event_id","status","etag")
                need(current is not None and all(current.get(f)==receipt.get(f) for f in fields),"Current receipt differs from the owning agreement’s latest signed observation")
        for item in proof.get("receipt_history",[]):
            if item["source"]!="owner-dispatch":
                continue
            r=item["receipt"]; entry=mutations.get(r["mutation_id"])
            need(entry is not None,"Receipt names unknown mutation")
            key,m=entry
            need(m["event_id"]==r["event_id"] and any(c["owner_id"]==m["owner_id"] and m["mutation_id"] in c["mutation_ids"] for c in consents.get(key,[])),"Receipt has no exact signed dispatch authority")
        for r in proof["model_runs"]:
            need(digest(r["permitted_input"])==r["input_digest"],"Provider input digest mismatch")
            if r.get("request_body"):
                need(digest(r["request_body"])==r["request_digest"] and r["request_body"]["model"]==r["model"],"Provider request/model mismatch")
            if r["purpose"]=="repair":
                packet=r["permitted_input"]
                if "eligible_assignments" in packet:
                    expected=[{"task_id":t["task_id"],"eligible_owner_ids":sorted({o["owner_id"] for o in packet["released_offers"] if t["task_id"] in o["task_ids"]})} for t in packet["goal"]["tasks"]]
                    need(packet["eligible_assignments"]==expected,"Provider eligibility table broadens released authority")
                for effective in r["permitted_input"]["released_offers"]:
                    release=releases.get(effective["offer_id"])
                    need(release and r["provider_id"] in release["recipients"]["inference"],"Provider lacks a named signed release")
                    need(set(effective["task_ids"])<=set(release["task_ids"]),"Provider input broadened released tasks")
                    for field in set(effective)-{"task_ids","conditions"}:
                        need(effective[field]==release[field],"Provider input altered a released fact")
        def resolve(ref):
            if ref is None:
                return None
            agreement=agreements.get((ref["agreement_id"],ref["revision"]))
            need(agreement is not None and ref["digest"]==digest(agreement),"Invalid current/pending agreement reference")
            return agreement
        current=resolve(proof.get("current_agreement")); pending=resolve(proof.get("pending_agreement"))
        if proof["current_status"]=="ACTIVE":
            need(current is not None and pending is None and not proof.get("pending_invalidated") and not proof.get("withdrawn_commitment_ids"),"ACTIVE conflicts with pending or withdrawn authority")
            key=(current["agreement_id"],current["revision"])
            need(instant(current["expires_at"])>instant(proof["generated_at"]),"Expired agreement cannot be currently ACTIVE")
            need(not any(w["agreement_id"]==key[0] and w["base_revision"]==key[1] for w in withdrawals),"A signed current withdrawal prevents ACTIVE")
            required={c["owner_id"] for c in current["commitments"]}|{m["owner_id"] for m in current["delta"]["calendar_mutations"]}
            need(required<={c["owner_id"] for c in consents.get(key,[])},"ACTIVE lacks exact signed consent for every required owner")
            heads=[]
            for owner in required:
                head=observation_heads.get((owner,key[0]))
                need(head is not None and instant(head["observed_at"])>=instant(current["created_at"]),"ACTIVE lacks a fresh owner observation for this revision")
                authority=next((a for a in head.get("authorities",[]) if a["revision"]==key[1] and a["agreement_digest"]==digest(current)),None)
                need(authority and authority["authority_current"] and not authority["withdrawn_commitment_ids"],"ACTIVE lacks current signed authority for this exact revision")
                consent=consent_messages.get(authority["consent_message_id"])
                need(consent and consent["owner_id"]==owner and (consent["agreement_id"],consent["revision"])==key and consent["agreement_digest"]==digest(current),"Current observation names another owner's or revision's consent")
                need(instant(consent["execution_not_after"])>instant(proof["generated_at"]),"ACTIVE authority expired before this export")
                heads.append(head)
            for intent in current["intents"]:
                head=observation_heads[(intent["owner_id"],key[0])]
                receipt=next((r for r in reversed(head["receipts"]) if r["event_id"]==intent["event_id"]),None)
                need(receipt and receipt["status"]=="VERIFIED","ACTIVE has an unverified current calendar intent")
            for mutation in current["delta"]["calendar_mutations"]:
                if mutation["kind"]=="delete":
                    head=observation_heads[(mutation["owner_id"],key[0])]
                    receipt=next((r for r in reversed(head["receipts"]) if r["event_id"]==mutation["event_id"]),None)
                    need(receipt and receipt["status"]=="CANCELLED","ACTIVE has an unresolved withdrawn event")
            need(proof.get("observed_at")==min(h["observed_at"] for h in heads),"Current observation time is not the signed observation floor")
        return {"valid":True,"agreements":len(agreements),"signed_messages":len(proof["messages"]),"signed_observations":len(proof.get("observations",[])),"model_attempts":len(proof["model_runs"]),"limits":["Historical integrity and owner-key evidence at the exported observation time; verify owner identity independently","A copied snapshot cannot prove that no later event was omitted, or authorize present execution","No evidence of attendance, independently administered households, Google OAuth or human benefit"]}
    except Exception as exc:
        return {"valid":False,"errors":[str(exc) or type(exc).__name__]}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("path",type=Path); args=parser.parse_args()
    result=verify(json.loads(args.path.read_text())); print(json.dumps(result,indent=2))
    if not result["valid"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
