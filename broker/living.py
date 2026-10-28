"""Living agreement coordinator. Owner services keep every signing/write power."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import threading
import uuid
from pathlib import Path

from broker.engine import BrokerError
from broker.living_store import LivingStore
from broker.living_models import LivingProvider,Cancelled,ProviderError
from broker.living_solver import solve
from broker.living_checker import check
from shared.living import (validate_goal,validate_agreement,validate_payload,goal_digest,agreement_digest,
                           commitment_digest,commitment_id,dependency_entries,action_id,calendar_event_id,consent_payload)
from shared.protocol import digest,utc_now,expires_in,parse_time,verify_message


class LivingEngine:
    def __init__(self,engine):
        self.engine=engine; self.config=engine.config
        self.store=LivingStore(Path(self.config["data_dir"])/"living.sqlite3")
        self.provider=LivingProvider(self.config)
        self.cancel_event=threading.Event()
        self.plan_lock=threading.Lock(); self.execute_lock=threading.Lock()
        with self.store.transaction() as (s,db):
            s.setdefault("receipt_history",[])
            s.setdefault("pending_invalidated",False)
            s.setdefault("observation_started",0)
            s.setdefault("observation_applied",0)
            s.setdefault("observations",{})
            s.setdefault("observation_history",[])
            if s["planning"]["status"]=="RUNNING":
                s["planning"].update(status="INTERRUPTED",error="Process restarted. The provider outcome may be unknown; no late result can publish.")
                for r in s["model_runs"]:
                    if r["status"]=="RUNNING":
                        r.update(status="INTERRUPTED",finished_at=utc_now(),error="Process stopped during this attempt; unknown usage is retained.")

    def owners(self):
        return self.engine.store.read()["owners"]

    def call(self,owner,path,body=None):
        return self.engine.owner_call(owner,path,body)

    def revision(self,s,expected):
        if expected!=s["revision"]:
            raise BrokerError("The arrangement changed. Refresh and review its current version.")

    def verify(self,message,kind):
        try:
            body=message["body"]
            owner=next(o for o in self.owners() if o["id"]==body["issuer"])
            if body["schema_version"]!=2 or body["circle_id"]!=self.config.get("circle_id","dev-circle") or body["key_id"]!=owner["key_id"]:
                raise ValueError("Unknown v2 circle/key")
            body=verify_message(message,owner["public_key"],"common-ground-broker",kind)
            payload=validate_payload(kind,body["payload"])
            if payload["owner_id"]!=owner["id"]:
                raise ValueError("Payload owner mismatch")
            self.provider.assert_clean(payload)
            if kind=="LivingRelease":
                if set(body["audience"])!=set(payload["recipients"]["humans"]+payload["recipients"]["inference"]+["common-ground-broker"]):
                    raise ValueError("Exact recipient mismatch")
            return body,payload
        except (ValueError,KeyError,TypeError,StopIteration) as exc:
            raise BrokerError("The signed v2 message failed identity, purpose, expiry or strict schema verification.",403) from exc

    def delivery(self,db,message):
        b=message["body"]
        old=db.execute("SELECT * FROM living_deliveries WHERE message_id=? OR (issuer=? AND nonce=?)",(b["message_id"],b["issuer"],b["nonce"])).fetchone()
        if old:
            if old["message_id"]!=b["message_id"] or old["message_digest"]!=digest(message):
                raise BrokerError("A message ID or nonce was reused with different signed content.")
            return json.loads(old["result"])
        return None

    def accepted(self,s,db,message,result=None):
        b=message["body"]; result=result or {"accepted":True}
        db.execute("INSERT INTO living_deliveries VALUES(?,?,?,?,?)",(b["message_id"],b["issuer"],b["nonce"],digest(message),json.dumps(result)))
        s["protocol_messages"].append(message)

    @staticmethod
    def invalidate_pending(s):
        # Never discard a durable outbox after transmission began. Its exact
        # revision and observations are still needed for safe reconciliation.
        attempted=any(o.get("attempts",0)>0 for o in s["outbox"].values())
        if s["pending"] and attempted:
            s["pending_invalidated"]=True
            s["status"]="RECOVERING"
            return True
        s["pending"]=None; s["consents"]={}; s["reservations"]={}; s["outbox"]={}
        s["pending_invalidated"]=False
        return False

    def ingest(self,message,kind):
        body,payload=self.verify(message,kind)
        with self.store.transaction() as (s,db):
            old=self.delivery(db,message)
            if old is not None:
                return old
            owner=body["issuer"]
            goal=s["goal"]
            if kind=="LivingRelease":
                if not goal or payload["goal_id"]!=goal["goal_id"] or payload["goal_digest"]!=goal_digest(goal) or payload["goal_revision"]!=goal["revision"] or set(payload["recipients"]["humans"])!=set(goal["participants"]):
                    raise BrokerError("Release does not match the current reviewed goal and recipients.")
                if set(payload["task_ids"])-{t["task_id"] for t in goal["tasks"]}:
                    raise BrokerError("Release contains an unknown task.")
                provider=",".join(sorted(payload["recipients"]["inference"])) or "none"
                prior=s["offers"].setdefault(owner,{}).get(provider)
                if prior and (payload["offer_revision"]<=prior["body"]["payload"]["offer_revision"] or body["consent_revision"]<=prior["body"]["consent_revision"]):
                    raise BrokerError("Release revision is stale.")
                s["offers"][owner][provider]=message
                recovering=self.invalidate_pending(s) if s["pending"] else False
                if not recovering:
                    s["status"]="COLLECTING" if not s["withdrawn"] else "NEEDS_HELP"
                self.store.event(s,"RELEASE",self.name(owner)+" released an exact offer.",{"owner_id":owner,"recipients":payload["recipients"],"offer_id":payload["offer_id"]})
            elif kind=="LivingConsent":
                pending=s["pending"]
                if not pending or payload["agreement_digest"]!=agreement_digest(pending):
                    raise BrokerError("Consent does not bind the current proposed revision.")
                expected=consent_payload(pending,owner,payload["consent_revision"],payload["constraint_revision"],payload["basis"],payload["policy_revision"])
                if expected!=payload or payload["consent_revision"]!=body["consent_revision"]:
                    raise BrokerError("Consent omits exact commitments, dependencies or calendar changes.")
                s["consents"][owner]=message
                required=self.required_owners(pending)
                s["status"]="READY" if required<=set(s["consents"]) else "AWAITING_CONSENT"
                self.store.event(s,"CONSENT",self.name(owner)+(" reviewed the exact changes." if payload["basis"]=="exact-review" else "’s agent freshly attested unchanged commitments under the reviewed policy."),{"owner_id":owner,"basis":payload["basis"],"agreement_digest":payload["agreement_digest"]})
            elif kind=="LivingWithdrawal":
                current=s["agreement"]
                if not current or payload["agreement_id"]!=current["agreement_id"] or payload["base_revision"]!=current["revision"] or payload["goal_id"]!=current["goal"]["goal_id"]:
                    raise BrokerError("Withdrawal references a stale agreement.")
                own={c["commitment_id"] for c in current["commitments"] if c["owner_id"]==owner}
                if not set(payload["commitment_ids"])<=own or payload["consent_revision"]!=body["consent_revision"]:
                    raise BrokerError("Withdrawal exceeds the signer’s exact commitment scope.")
                s["withdrawn"]=sorted(set(s["withdrawn"])|set(payload["commitment_ids"]))
                s["withdrawals"].append(message)
                recovering=self.invalidate_pending(s)
                if not recovering:
                    s["status"]="NEEDS_HELP"
                s["disruption_id"]="disruption-"+uuid.uuid4().hex
                self.cancel_event.set()
                self.store.event(s,"WITHDRAWAL",self.name(owner)+" withdrew only the selected responsibility. Retained commitments stay in place.",{"commitment_ids":payload["commitment_ids"],"owner_id":owner})
            else:
                request=next((q for q in s["questions"] if q["request_id"]==payload["request_id"] and q["owner_id"]==owner and q["task_id"]==payload["task_id"]),None)
                if not request or payload["goal_id"]!=goal["goal_id"]:
                    raise BrokerError("Refusal references an unknown bounded request.")
                request["status"]="declined"; s["refusals"].append(message)
                if not self.invalidate_pending(s):
                    s["status"]="NEEDS_HELP"
                self.store.event(s,"REFUSAL",self.name(owner)+" declined the bounded request. No reason was shared.",{"owner_id":owner,"task_id":payload["task_id"]})
            self.accepted(s,db,message)
        return {"accepted":True}

    def name(self,owner):
        return next((o["name"] for o in self.owners() if o["id"]==owner),owner)

    def confirm_goal(self,raw,expected_revision):
        try:
            goal=validate_goal(raw)
            self.provider.assert_clean(goal)
        except ValueError as exc:
            raise BrokerError("The reviewed goal is incomplete or inconsistent: "+str(exc)[:500],422) from exc
        if set(goal["participants"])-{o["id"] for o in self.owners()}:
            raise BrokerError("Every participant must be a registered owner.",422)
        with self.store.transaction() as (s,db):
            self.revision(s,expected_revision)
            if s["planning"]["status"]=="RUNNING" or s["status"] in ("APPLYING","RECOVERING"):
                raise BrokerError("Finish or cancel current work before reviewing a new goal.")
            if goal["goal_id"] in s["goals"] and s["goals"][goal["goal_id"]]!=goal:
                raise BrokerError("A confirmed goal identity is immutable; create a new reviewed goal.")
            s["goal"]=goal; s["goals"][goal["goal_id"]]=goal; s["offers"]={}
            s["agreement"]=None; s["pending"]=None; s["consents"]={}; s["withdrawn"]=[]; s["reservations"]={}; s["outbox"]={}
            s["pending_invalidated"]=False
            s["status"]="COLLECTING"; s["draft"]=None; s["disruption_id"]="disruption-"+uuid.uuid4().hex
            self.store.event(s,"GOAL_CONFIRMED","The complete dates, responsibilities, dependencies and travel facts were explicitly reviewed.",{"goal_id":goal["goal_id"],"goal_digest":goal_digest(goal),"confirmed_by":goal["confirmed_by"]})
        for owner in goal["participants"]:
            self.call(owner,"/coordination/v2/goal",{"goal":goal})
        return self.public_state(refresh=False)

    def current(self,agreement_id=None,revision=None):
        s=self.store.read()
        if agreement_id is None:
            return {"goal":s["goal"],"agreement":s["agreement"],"pending":s["pending"],"disruption_id":s["disruption_id"]}
        agreement=s["archive"].get(f"{agreement_id}:{revision}")
        if agreement is None:
            raise BrokerError("That exact immutable agreement revision is unavailable.",404)
        return {"agreement":agreement,"agreement_digest":agreement_digest(agreement)}

    def grants(self,s,provider="local",fresh=False):
        if not s["goal"]:
            raise BrokerError("Confirm a complete reviewed goal first.")
        result=[]
        for owner,by_provider in s["offers"].items():
            valid=[]
            for message in by_provider.values():
                try:
                    body,payload=self.verify(message,"LivingRelease")
                    if payload["goal_digest"]!=goal_digest(s["goal"]) or parse_time(payload["expires_at"])<=parse_time(utc_now()):
                        continue
                    if provider!="local" and provider not in payload["recipients"]["inference"]:
                        continue
                    valid.append(message)
                except BrokerError:
                    continue
            if not valid:
                if provider!="local":
                    raise BrokerError(self.name(owner)+" needs a fresh named "+provider+" disclosure; another provider’s grant cannot be reused.",403)
                continue
            message=max(valid,key=lambda m:m["body"]["payload"]["offer_revision"])
            if fresh:
                status=self.call(owner,"/coordination/v2/status?goal_id="+s["goal"]["goal_id"])
                if message not in status.get("releases",[]) or message["body"]["key_id"] in status.get("revoked_keys",[]) or message["body"]["payload"]["constraint_revision"]!=status["constraint_revision"]:
                    raise BrokerError("An owner’s release, private constraints or key changed. Review the fresh offer.")
            result.append(message)
        if not result:
            raise BrokerError("Owners must review and release offers for this goal first.")
        return result

    def permitted_questions(self,s,grants):
        tasks=s["goal"]["tasks"]
        offers=self.effective_offers(s,grants)
        covered={tid for o in offers for tid in o["task_ids"]}
        withdrawn_tasks={c["task_id"] for c in (s["agreement"] or {}).get("commitments",[]) if c["commitment_id"] in s["withdrawn"]}
        used={(q["owner_id"],q["task_id"]) for q in s["questions"] if q["goal_id"]==s["goal"]["goal_id"]}
        candidates=[]
        for task in tasks:
            if not task["required"] or (task["task_id"] in covered and task["task_id"] not in withdrawn_tasks):
                continue
            for offer in offers:
                if task["capability"] in offer["request_categories"] and task["task_id"] not in offer["task_ids"] and (offer["owner_id"],task["task_id"]) not in used:
                    if any(c["task_id"]==task["task_id"] and c["owner_id"]==offer["owner_id"] and c["commitment_id"] in s["withdrawn"] for c in (s["agreement"] or {}).get("commitments",[])):
                        continue
                    candidates.append({"owner_id":offer["owner_id"],"task_id":task["task_id"],"category":task["capability"],"label":task["label"]})
        remaining=max(0,3-sum(q["disruption_id"]==s["disruption_id"] for q in s["questions"]))
        return candidates[:remaining]

    @staticmethod
    def effective_offers(s,grants):
        # A signed scoped withdrawal narrows the surviving release. It does not
        # invalidate the pickup grant or authorize replacement facts.
        blocked={}
        for c in (s["agreement"] or {}).get("commitments",[]):
            if c["commitment_id"] in s["withdrawn"]:
                blocked.setdefault(c["owner_id"],set()).add(c["task_id"])
        offers=[]
        for message in grants:
            offer=deepcopy(message["body"]["payload"])
            forbidden=blocked.get(offer["owner_id"],set())
            offer["task_ids"]=[t for t in offer["task_ids"] if t not in forbidden]
            offer["conditions"]=[c for c in offer["conditions"] if c["task_id"] not in forbidden]
            offers.append(offer)
        return offers

    def ask(self,requests,snapshot):
        allowed={(q["owner_id"],q["task_id"]):q for q in self.permitted_questions(snapshot,self.grants(snapshot))}
        for choice in requests[:3]:
            key=(choice["owner_id"],choice["task_id"])
            if key not in allowed:
                raise BrokerError("A question exceeded current permission or refusal scope.")
            public=allowed[key]
            request={"request_id":"question-"+uuid.uuid4().hex,"goal_id":snapshot["goal"]["goal_id"],"task_id":choice["task_id"],"category":public["category"],"disruption_id":snapshot["disruption_id"],"label":public["label"]}
            response=self.call(choice["owner_id"],"/coordination/v2/question",{"request":request})
            with self.store.transaction() as (s,db):
                if s["goal"]["goal_id"]!=snapshot["goal"]["goal_id"] or s["disruption_id"]!=snapshot["disruption_id"]:
                    raise BrokerError("The question’s disruption changed.")
                s["questions"].append({**request,"owner_id":choice["owner_id"],"text":choice.get("text") or "Could you review an offer for "+public["label"].lower()+"?","status":response.get("status","offered"),"created_at":utc_now()})
                self.store.event(s,"QUESTION","A bounded question was sent to "+self.name(choice["owner_id"])+"’s agent.",{"owner_id":choice["owner_id"],"task_id":choice["task_id"]})

    def record(self,receipt):
        with self.store.transaction() as (s,db):
            index=next((i for i,r in enumerate(s["model_runs"]) if r["receipt_id"]==receipt["receipt_id"]),None)
            if index is None:
                s["model_runs"].append(deepcopy(receipt))
            else:
                s["model_runs"][index]=deepcopy(receipt)

    def admission(self,provider):
        if provider!="nebius":
            return
        receipts=[r for r in self.store.read()["model_runs"] if r.get("provider_id")=="nebius"]
        if any(r.get("transmitted_at") and not r.get("usage_known") for r in receipts):
            raise BrokerError("A previous Nebius attempt has unknown usage. Resolve its recorded outcome before another qualification call.")
        spent=sum(r.get("estimated_cost_usd",0) for r in receipts)
        if spent+0.25>self.config.get("living_nebius_cap_usd",2.0):
            raise BrokerError("The local Nebius qualification safeguard has been reached; all receipts remain available.")

    def begin(self,purpose,provider,expected_revision=None,source_text=None,allow_inference=False):
        if provider not in ("local","fireworks","nebius"):
            raise BrokerError("Choose an explicit provider.",422)
        if purpose=="goal" and (not source_text or len(source_text)>16000):
            raise BrokerError("Provide a bounded shared goal request.",422)
        if purpose=="goal" and provider!="local" and not allow_inference:
            raise BrokerError("Explicitly release this shared request to the selected provider first.",403)
        self.provider.assert_clean(source_text or {})
        with self.store.transaction() as (s,db):
            if expected_revision is not None:
                self.revision(s,expected_revision)
            if s["planning"]["status"]=="RUNNING" or s["status"] in ("APPLYING","RECOVERING"):
                raise BrokerError("A planning or calendar operation is already in progress.")
            if purpose=="repair" and s["pending"]:
                raise BrokerError("Review the current proposed amendment before requesting another.")
            if purpose=="repair":
                self.grants(s,provider)
            self.admission(provider)
            self.cancel_event=threading.Event()
            request_id="planning-"+uuid.uuid4().hex
            s["planning"]={"status":"RUNNING","purpose":purpose,"provider":provider,"request_id":request_id,"started_at":utc_now(),"error":None}
            if purpose=="goal":
                s["draft"]={"draft_id":"draft-"+uuid.uuid4().hex,"source_text":source_text,"goal":None,"questions":[],"status":"RUNNING","provider":provider,"receipt_id":None}
            self.store.event(s,"PLANNING_STARTED","Preparing a reviewed goal draft." if purpose=="goal" else "Checking current released offers for the next arrangement.",{"provider":provider})
        return {"accepted":True,"request_id":request_id}

    def cancel(self,expected_revision):
        with self.store.transaction() as (s,db):
            self.revision(s,expected_revision)
            if s["planning"]["status"]!="RUNNING":
                raise BrokerError("There is no running planning request.")
            self.cancel_event.set(); s["planning"].update(status="CANCELLED",finished_at=utc_now(),error="Cancelled explicitly; late results cannot publish.")
            if s["draft"] and s["draft"]["status"]=="RUNNING":
                s["draft"]["status"]="CANCELLED"
            self.store.event(s,"PLANNING_CANCELLED","Planning was cancelled. All attempted transmissions and known usage remain recorded.")
        return self.public_state(refresh=False)

    def run(self):
        with self.plan_lock:
            snapshot=self.store.read(); job=snapshot["planning"].copy()
            cancel_token=self.cancel_event
            purpose,provider=job["purpose"],job["provider"]
            if job["status"]!="RUNNING":
                return
            grants=[]
            fingerprint=digest(snapshot["offers"])
            def fresh():
                s=self.store.read()
                if cancel_token.is_set() or s["planning"]["request_id"]!=job["request_id"] or s["planning"]["status"]!="RUNNING":
                    raise Cancelled("The planning request was cancelled or superseded.")
                if purpose=="repair":
                    if digest(s["offers"])!=fingerprint or s["withdrawn"]!=snapshot["withdrawn"]:
                        raise BrokerError("Released authority changed during planning; no stale amendment can publish.")
                    self.grants(s,provider,fresh=True)
            try:
                grants=self.grants(snapshot,provider,fresh=True) if purpose=="repair" else []
                fresh()
                if purpose=="goal":
                    source=snapshot["draft"]["source_text"]
                    if provider=="local":
                        output={"title":"New reviewed care arrangement","subject":"","timezone":"Asia/Kolkata","participants":[o["id"] for o in self.owners()],"tasks":[],"routes":[],"questions":["Enter the exact dates, task durations, locations, confirmed travel times and dependency chain in the structured review."],"explanation":"Structured review; no model was called."}; receipt_id=None
                    else:
                        packet={"source_text":source,"registered_owners":[{"id":o["id"],"name":o["name"]} for o in self.owners()]}
                        output,receipt_id=self.provider.run("goal",provider,packet,fresh,self.record,cancel_token)
                    fresh()
                    draft_goal={"schema_version":2,"goal_id":"goal-"+uuid.uuid4().hex,"revision":1,"title":output["title"],"description":source,"timezone":output["timezone"],"participants":output["participants"],"subject":output["subject"],"source_text":source,"tasks":output["tasks"],"routes":output["routes"],"confirmed_at":utc_now(),"confirmed_by":"coordinator-reviewed-form"}
                    with self.store.transaction() as (s,db):
                        fresh()
                        s["draft"].update(goal=draft_goal,questions=output["questions"],status="REVIEW_REQUIRED",receipt_id=receipt_id)
                        s["status"]="REVIEW_GOAL"
                        s["planning"].update(status="SUCCEEDED",finished_at=utc_now())
                        self.store.event(s,"GOAL_DRAFTED","A source-linked goal draft is ready. No offer or calendar action is authorized until review.",{"receipt_id":receipt_id})
                    return
                offers=self.effective_offers(snapshot,grants)
                permitted=self.permitted_questions(snapshot,grants)
                output={"suggested_assignments":[],"questions":permitted,"outcome":"candidate","explanation":"The complete reviewed goal and current public offers were solved locally. No model was called."}; receipt_id=None
                if provider!="local":
                    packet={"goal":snapshot["goal"],"released_offers":offers,"previous_commitments":(snapshot["agreement"] or {}).get("commitments",[]),"withdrawn_commitment_ids":snapshot["withdrawn"],"permitted_questions":permitted,"owners":[{"id":o["id"],"name":o["name"]} for o in self.owners()]}
                    # Keep history for explaining the change, but make current
                    # released authority explicit. A prior assignment is never
                    # an offer after its commitment has been withdrawn.
                    packet["withdrawn_assignments"]=[{"commitment_id":c["commitment_id"],"task_id":c["task_id"],"owner_id":c["owner_id"]} for c in packet["previous_commitments"] if c["commitment_id"] in snapshot["withdrawn"]]
                    packet["eligible_assignments"]=[{"task_id":t["task_id"],"eligible_owner_ids":sorted({o["owner_id"] for o in offers if t["task_id"] in o["task_ids"]})} for t in snapshot["goal"]["tasks"]]
                    output,receipt_id=self.provider.run("repair",provider,packet,fresh,self.record,cancel_token)
                fresh()
                result=solve(snapshot["goal"],offers,previous=(snapshot["agreement"] or {}).get("commitments",[]),suggestions=output["suggested_assignments"])
                if result["status"] not in ("OPTIMAL","FEASIBLE"):
                    if output["questions"]:
                        self.ask(output["questions"],snapshot)
                    with self.store.transaction() as (s,db):
                        s["status"]="NEEDS_HELP"; s["planning"].update(status="NEEDS_HELP",finished_at=utc_now(),error=result["reason"],solver=result)
                        self.store.event(s,"HELP_NEEDED",result["reason"],{"questions":len(output["questions"]),"solver_status":result["status"]})
                    return
                checked=check(snapshot["goal"],offers,result["assignments"])
                if not checked["valid"]:
                    raise BrokerError("Independent schedule verification rejected the candidate.")
                # Refresh current ETags before freezing a conditional delta.
                self.observe(snapshot["agreement"])
                fresh()
                current=self.store.read()
                agreement=self.build_agreement(current,result["assignments"],offers,checked,receipt_id,output.get("explanation", ""))
                with self.store.transaction() as (s,db):
                    fresh()
                    s["pending"]=agreement; s["archive"][f"{agreement['agreement_id']}:{agreement['revision']}"]=agreement
                    s["consents"]={}; s["reservations"]={}; s["outbox"]={}; s["status"]="AWAITING_CONSENT"
                    s["pending_invalidated"]=False
                    s["planning"].update(status="SUCCEEDED",finished_at=utc_now(),solver=result)
                    self.store.event(s,"AMENDMENT_PROPOSED","The full arrangement passed independent checks. Exact owner decisions are still required.",{"agreement_id":agreement["agreement_id"],"revision":agreement["revision"],"calendar_mutations":len(agreement["delta"]["calendar_mutations"])})
                for owner in self.required_owners(agreement):
                    self.call(owner,"/coordination/v2/attest",{"agreement":agreement})
            except Exception as exc:
                with self.store.transaction() as (s,db):
                    if s["planning"].get("request_id")==job["request_id"] and s["planning"]["status"]=="RUNNING":
                        message=str(exc)[:500] if isinstance(exc,(BrokerError,ProviderError)) else "Planning failed its validation boundary; no amendment was published."
                        s["planning"].update(status="CANCELLED" if isinstance(exc,Cancelled) else "FAILED",finished_at=utc_now(),error=message)
                        if s["draft"] and s["draft"]["status"]=="RUNNING":
                            s["draft"]["status"]=s["planning"]["status"]
                        self.store.event(s,"PLANNING_STOPPED",message)

    def build_agreement(self,s,assignments,offers,checked,receipt_id,explanation):
        prior=s["agreement"]; aid=prior["agreement_id"] if prior else "agreement-"+uuid.uuid4().hex
        revision=prior["revision"]+1 if prior else 1; now=utc_now()
        tasks={t["task_id"]:t for t in s["goal"]["tasks"]}; by_offer={o["offer_id"]:o for o in offers}
        commitments=[]
        for a in assignments:
            t=tasks[a["task_id"]]; offer=by_offer[a["offer_id"]]
            c={"commitment_id":commitment_id(aid,t["task_id"],a["owner_id"]),"task_id":t["task_id"],"owner_id":a["owner_id"],"date":t["date"],"timezone":s["goal"]["timezone"],"start":a["start"],"end":a["end"],"start_location":t["start_location"],"end_location":t["end_location"],"capability":t["capability"],"label":t["label"],"subject":t["subject"],"dependencies":[],"conditions":[x for x in offer["conditions"] if x["task_id"]==t["task_id"]],"offer_id":offer["offer_id"],"offer_revision":offer["offer_revision"]}
            commitments.append(c)
        for c in commitments:
            c["dependencies"]=dependency_entries(s["goal"],commitments,c["task_id"])
        old={c["commitment_id"]:c for c in (prior or {}).get("commitments",[])}
        old_intents={i["commitment_id"]:i for i in (prior or {}).get("intents",[])}
        intents=[]; mutations=[]; retained=[]; changed=[]; new=[]
        def mutation(kind,intent,previous=None):
            event=intent or previous
            receipt=s["receipts"].get(event["event_id"],{})
            etag=receipt.get("etag")
            if kind!="insert" and not etag:
                raise BrokerError("An affected event has no observed version. Reconcile its owner calendar before proposing a mutation.")
            return {"mutation_id":"mutation-"+digest([aid,revision,event["action_id"],kind])[:32],"kind":kind,"owner_id":event["owner_id"],"commitment_id":event["commitment_id"],"action_id":event["action_id"],"event_id":event["event_id"],"intent":intent,"expected_etag":None if kind=="insert" else etag}
        for c in commitments:
            cid=c["commitment_id"]; old_intent=old_intents.get(cid); action=action_id(cid)
            intent={"schema_version":2,"action_id":action,"commitment_id":cid,"owner_id":c["owner_id"],"task_id":c["task_id"],"event_id":calendar_event_id(action),"label":c["label"],"date":c["date"],"timezone":c["timezone"],"start":c["start"],"end":c["end"],"location":{"start":c["start_location"],"end":c["end_location"]},"creation":old_intent["creation"] if old_intent else {"agreement_id":aid,"revision":revision,"created_at":now}}
            intents.append(intent)
            if cid not in old:
                new.append(cid); mutations.append(mutation("insert",intent))
            elif commitment_digest(c)!=commitment_digest(old[cid]):
                changed.append(cid)
            else:
                retained.append(cid)
            if old_intent is not None and intent!=old_intent:
                mutations.append(mutation("update",intent))
        withdrawn=sorted(set(old)-{c["commitment_id"] for c in commitments})
        for cid in withdrawn:
            mutations.append(mutation("delete",None,old_intents[cid]))
        affected={c["owner_id"] for c in commitments if c["commitment_id"] in set(changed+new)}|{old[cid]["owner_id"] for cid in withdrawn}
        agreement={"schema_version":2,"agreement_id":aid,"revision":revision,"base_revision":revision-1,"goal":s["goal"],"goal_digest":goal_digest(s["goal"]),"commitments":commitments,"intents":intents,"delta":{"retained":retained,"changed":changed,"new":new,"withdrawn":withdrawn,"affected_owners":sorted(affected),"approval_required":sorted(affected),"calendar_mutations":mutations},"created_at":now,"expires_at":min([expires_in(14400)]+[o["expires_at"] for o in offers]),"checker":checked,"model_receipt_id":receipt_id,"explanation":explanation}
        return validate_agreement(agreement)

    @staticmethod
    def required_owners(agreement):
        return {c["owner_id"] for c in agreement["commitments"]}|{m["owner_id"] for m in agreement["delta"]["calendar_mutations"]}

    def observed_authority_current(self,s,agreement):
        for owner in self.required_owners(agreement):
            message=s["observations"].get(owner+":"+agreement["agreement_id"])
            if not message:
                return False
            payload=message["body"]["payload"]
            if parse_time(payload["observed_at"])<parse_time(agreement["created_at"]):
                return False
            authority=next((a for a in payload.get("authorities",[]) if a["revision"]==agreement["revision"] and a["agreement_digest"]==agreement_digest(agreement)),None)
            if not authority or not authority["authority_current"] or authority["withdrawn_commitment_ids"]:
                return False
        return True

    def observe(self,agreement=None):
        explicit=agreement is not None
        with self.store.transaction() as (snapshot,db):
            if not explicit and snapshot["pending"] and snapshot["status"] in ("APPLYING","RECOVERING"):
                return
            agreement=agreement or snapshot["agreement"]
            if not agreement:
                return
            generation=snapshot["revision"]
            target=agreement_digest(agreement)
            snapshot["observation_started"]+=1
            observation=snapshot["observation_started"]
        observed={}; signed_observations=[]
        for owner in self.required_owners(agreement):
            try:
                response=self.call(owner,"/coordination/v2/events?agreement_id="+agreement["agreement_id"])
                signed=response.get("observation")
                if signed is None:
                    raise BrokerError("Owner readback has no signed observation.")
                _,payload=self.verify(signed,"LivingObservation")
                if payload["owner_id"]!=owner or payload["agreement_id"]!=agreement["agreement_id"] or payload["receipts"]!=response.get("receipts",[]):
                    raise BrokerError("Owner observation does not bind this exact readback.")
                signed_observations.append(signed)
                for receipt in response.get("receipts",[]):
                    observed[receipt["event_id"]]=receipt
            except BrokerError:
                for intent in agreement["intents"]:
                    if intent["owner_id"]==owner:
                        observed[intent["event_id"]]={"event_id":intent["event_id"],"action_id":intent["action_id"],"commitment_id":intent["commitment_id"],"status":"UNCONFIRMED","verified_at":None,"error":"Owner calendar is unavailable; prior verification is historical."}
        with self.store.transaction() as (s,db):
            # A slow old read cannot overwrite a newer agreement, mutation or
            # observation. Explicit pre-promotion reads may target pending only.
            live_target=(s["pending"] if explicit and s["pending"] and agreement_digest(s["pending"])==target else s["agreement"])
            if s["revision"]!=generation or not live_target or agreement_digest(live_target)!=target or observation<=s["observation_applied"]:
                return
            s["observation_applied"]=observation
            for signed in signed_observations:
                payload=signed["body"]["payload"]
                key=payload["owner_id"]+":"+payload["agreement_id"]
                old=s["observations"].get(key)
                def material(message):
                    value=message["body"]["payload"]
                    return {"receipts":[{k:r.get(k) for k in ("mutation_id","event_id","status","etag","error")} for r in value["receipts"]],"authorities":value.get("authorities",[])}
                if old is None or material(old)!=material(signed):
                    s["observation_history"].append(signed)
                s["observations"][key]=signed
            for eid,r in observed.items():
                if r.get("etag") is None and s["receipts"].get(eid,{}).get("etag"):
                    r={**r,"etag":s["receipts"][eid]["etag"]}
                prior=s["receipts"].get(eid)
                if prior is None or any(prior.get(k)!=r.get(k) for k in ("status","etag","error","mutation_id")):
                    s["receipt_history"].append({"agreement_id":agreement["agreement_id"],"revision":agreement["revision"],"source":"owner-calendar-observation","observed_at":utc_now(),"receipt":deepcopy(r)})
                s["receipts"][eid]=r
            complete=self.observed_authority_current(s,agreement) and all(s["receipts"].get(i["event_id"],{}).get("status")=="VERIFIED" for i in agreement["intents"] if i["commitment_id"] not in s["withdrawn"])
            s["observed_at"]=min((m["body"]["payload"]["observed_at"] for m in signed_observations),default=None) if complete else None
            if s["status"]=="ACTIVE" and (not complete or parse_time(agreement["expires_at"])<=parse_time(utc_now())):
                s["status"]="HISTORICAL" if parse_time(agreement["expires_at"])<=parse_time(utc_now()) else "RECOVERING"
            elif complete and s["status"]=="RECOVERING" and s["pending"] is None and not s["withdrawn"] and parse_time(agreement["expires_at"])>parse_time(utc_now()):
                s["status"]="ACTIVE"

    def execute(self,aid,revision,reconcile=False):
        if not self.execute_lock.acquire(blocking=False):
            raise BrokerError("An amendment is already being applied or reconciled.")
        try:
            s=self.store.read(); agreement=s["pending"]
            if agreement and s.get("pending_invalidated"):
                if not reconcile:
                    raise BrokerError("Authority changed after calendar work began. Reconcile the preserved exact mutation records; no new writes are authorized.")
                self.observe(agreement)
                return self.public_state(refresh=False)
            if not agreement or agreement["agreement_id"]!=aid or agreement["revision"]!=revision:
                if s["agreement"] and s["agreement"]["agreement_id"]==aid and s["agreement"]["revision"]==revision:
                    self.observe(s["agreement"]); return self.public_state(refresh=False)
                raise BrokerError("Review the exact current proposed amendment first.")
            self.ready(s,agreement)
            for owner in self.required_owners(agreement):
                reservation=s["reservations"].get(owner)
                if not reservation or parse_time(reservation["lease_expires_at"])<=parse_time(utc_now()):
                    reservation=self.call(owner,"/coordination/v2/prepare",{"agreement":agreement,"consent":s["consents"][owner]})
                    with self.store.transaction() as (current,db):
                        current["reservations"][owner]=reservation
            with self.store.transaction() as (current,db):
                self.ready(current,agreement)
                current["status"]="APPLYING"
                for m in agreement["delta"]["calendar_mutations"]:
                    current["outbox"].setdefault(m["mutation_id"],{"status":"PENDING","attempts":0,"owner_id":m["owner_id"]})
                self.store.event(current,"MUTATIONS_AUTHORIZED","All affected owners reserved exact authority; selective calendar work is durable.",{"mutation_count":len(agreement["delta"]["calendar_mutations"])})
            for m in sorted(agreement["delta"]["calendar_mutations"],key=lambda m:m["kind"]!="delete"):
                current=self.store.read(); self.ready(current,agreement)
                outbox=current["outbox"][m["mutation_id"]]
                expected="CANCELLED" if m["kind"]=="delete" else "VERIFIED"
                if outbox["status"]==expected and not reconcile:
                    continue
                reservation=current["reservations"][m["owner_id"]]
                request={"agreement_id":aid,"revision":revision,"mutation_id":m["mutation_id"],"reservation_id":reservation["reservation_id"],"fence":reservation["fence"]}
                with self.store.transaction() as (current,db):
                    current["outbox"][m["mutation_id"]].update(status="SENDING",attempts=outbox["attempts"]+1)
                try:
                    receipt=self.call(m["owner_id"],"/coordination/v2/reconcile" if reconcile or outbox["attempts"] else "/coordination/v2/dispatch",request)
                except BrokerError as exc:
                    receipt={"mutation_id":m["mutation_id"],"event_id":m["event_id"],"action_id":m["action_id"],"commitment_id":m["commitment_id"],"status":"AMBIGUOUS" if exc.status>=500 else "FAILED","error":str(exc)}
                with self.store.transaction() as (current,db):
                    current["outbox"][m["mutation_id"]]["status"]=receipt["status"]
                    current["receipts"][m["event_id"]]=receipt
                    current["receipt_history"].append({"agreement_id":aid,"revision":revision,"source":"owner-dispatch","observed_at":utc_now(),"receipt":deepcopy(receipt)})
                    self.store.event(current,"CALENDAR_"+receipt["status"],"Observed "+m["kind"]+" result: "+receipt["status"].lower().replace("_"," ")+".",{"mutation_id":m["mutation_id"],"kind":m["kind"],"event_id":m["event_id"]})
                    if receipt["status"]!=expected:
                        current["status"]="RECOVERING"
                if receipt["status"]!=expected:
                    return self.public_state(refresh=False)
            self.observe(agreement)
            with self.store.transaction() as (current,db):
                self.ready(current,agreement)
                complete=self.observed_authority_current(current,agreement) and all(current["receipts"].get(i["event_id"],{}).get("status")=="VERIFIED" for i in agreement["intents"]) and all(current["receipts"].get(m["event_id"],{}).get("status")=="CANCELLED" for m in agreement["delta"]["calendar_mutations"] if m["kind"]=="delete")
                if complete:
                    current["agreement"]=agreement; current["pending"]=None; current["withdrawn"]=[]; current["status"]="ACTIVE"
                    self.store.event(current,"AGREEMENT_ACTIVE","The revised arrangement is agreed and its current calendar effects were read back. No attendance is implied.",{"agreement_id":aid,"revision":revision,"retained_events":len(agreement["intents"])-sum(m["kind"] in ("insert","update") for m in agreement["delta"]["calendar_mutations"]),"calendar_mutations":len(agreement["delta"]["calendar_mutations"])})
                else:
                    current["status"]="RECOVERING"
            return self.public_state(refresh=False)
        finally:
            self.execute_lock.release()

    def ready(self,s,agreement):
        if s.get("pending_invalidated"):
            raise BrokerError("This amendment was invalidated; preserved effects require reconciliation without further dispatch.")
        if not s["pending"] or agreement_digest(s["pending"])!=agreement_digest(agreement) or (s["agreement"]["revision"] if s["agreement"] else 0)!=agreement["base_revision"]:
            raise BrokerError("The amendment base or pending revision changed.")
        if parse_time(agreement["expires_at"])<=parse_time(utc_now()) or s["planning"]["status"]=="RUNNING":
            raise BrokerError("The exact amendment expired or planning is still running.")
        for owner in self.required_owners(agreement):
            message=s["consents"].get(owner)
            if not message:
                raise BrokerError("Every affected owner needs exact review or a fresh valid policy attestation.")
            _,payload=self.verify(message,"LivingConsent")
            if payload!=consent_payload(agreement,owner,payload["consent_revision"],payload["constraint_revision"],payload["basis"],payload["policy_revision"]):
                raise BrokerError("Consent no longer matches the exact amendment.")

    def sample(self,provider="none",enable_policy=False):
        if self.config.get("fictional_sample") is not True:
            raise BrokerError("Fictional setup is not enabled for this installation.",404)
        from broker.living_sample import sample_goal
        s=self.store.read(); goal=sample_goal(s["sample_count"])
        self.confirm_goal(goal,s["revision"])
        for owner in goal["participants"]:
            self.call(owner,"/coordination/v2/sample/setup",{"goal":goal,"provider":provider,"enable_policy":enable_policy})
        self.begin("repair","local",self.store.read()["revision"]); self.run()
        pending=self.store.read()["pending"]
        if not pending:
            raise BrokerError("The fictional starting arrangement did not pass the ordinary planner/checker.")
        for owner in self.required_owners(pending):
            self.call(owner,"/coordination/v2/sample/approve",{"agreement":pending})
        result=self.execute(pending["agreement_id"],pending["revision"])
        with self.store.transaction() as (current,db):
            current["sample_count"]+=1
            self.store.event(current,"FICTIONAL_SETUP","Initial owner decisions were authored fictional sample decisions, applied through the normal consent and calendar path.",{"authored":True,"goal_id":goal["goal_id"]})
        return self.public_state(refresh=False)

    def public_state(self,refresh=True):
        if refresh:
            self.observe()
        s=self.store.read(); target=s["pending"] or s["agreement"]
        rows=[]
        for c in (s["agreement"] or {}).get("commitments",[]):
            intent=next(i for i in s["agreement"]["intents"] if i["commitment_id"]==c["commitment_id"])
            receipt=s["receipts"].get(intent["event_id"],{})
            rows.append({**c,"status":"withdrawn" if c["commitment_id"] in s["withdrawn"] else "committed","calendar_status":receipt.get("status","UNCONFIRMED"),"event_id":intent["event_id"],"etag":receipt.get("etag"),"verified_at":receipt.get("verified_at")})
        approvals=[]
        if s["pending"]:
            for owner in sorted(self.required_owners(s["pending"])):
                consent=s["consents"].get(owner)
                approvals.append({"owner_id":owner,"status":"approved" if consent else "needs_review","basis":consent["body"]["payload"]["basis"] if consent else None,"reason":"Exact signed authority is recorded." if consent else "Review the exact commitment and any changed handoff counterpart in your private workspace."})
        public={k:deepcopy(s[k]) for k in ("schema_version","revision","goal","draft","agreement","pending","questions","history","model_runs","planning","status","observed_at","disruption_id")}
        public.update(sample=self.config.get("fictional_sample") is True,owners=self.owners(),offers=[m for values in s["offers"].values() for m in values.values()],consents=list(s["consents"].values()),approval_status=approvals,commitments=rows,receipts=list(s["receipts"].values()),pending_invalidated=s.get("pending_invalidated",False),provider=self.provider.public_config(),limits={"human_participants":0,"calendar":"Actual local SQLite effects; Google adapter tests do not qualify OAuth/accounts","ownership":"Local runtime isolation does not establish independent household administrators","question_budget":3},counts={"owner_reviews":sum(e["type"]=="CONSENT" and e["data"].get("basis")=="exact-review" for e in s["history"]),"calendar_mutations":len({e["data"]["mutation_id"] for e in s["history"] if e["type"] in ("CALENDAR_VERIFIED","CALENDAR_CANCELLED")}),"questions":len(s["questions"])})
        self.provider.assert_clean(public)
        return public

    def evidence(self):
        self.observe(); s=self.store.read()
        proof={"format":"common-ground.living-proof/v2","generated_at":utc_now(),"kind":"Authored local validation; no independent humans or external account qualification","owners":self.owners(),"goals":list(s["goals"].values()),"agreements":list(s["archive"].values()),"messages":s["protocol_messages"],"model_runs":s["model_runs"],"receipts":list(s["receipts"].values()),"receipt_history":s["receipt_history"],"observations":list(s["observations"].values()),"observation_history":s["observation_history"],"history":s["history"],"current_status":s["status"],"observed_at":s["observed_at"]}
        def reference(agreement):
            return {"agreement_id":agreement["agreement_id"],"revision":agreement["revision"],"digest":agreement_digest(agreement)} if agreement else None
        proof.update(current_agreement=reference(s["agreement"]),pending_agreement=reference(s["pending"]),withdrawn_commitment_ids=s["withdrawn"],pending_invalidated=s.get("pending_invalidated",False))
        root=Path(__file__).resolve().parents[1]
        sources=sorted({p for pattern in ("broker/*.py","shared/*.py","owner_agent/*.py","owner_agent/connectors/*.py","scripts/verify_living_evidence.py") for p in root.glob(pattern) if p.is_file()})
        proof["source_hashes"]={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        proof["source_hash_basis"]="Files available at export time; historical process bytes are not attested. Each model attempt retains its exact request and prompt revision."
        self.provider.assert_clean(proof)
        return {**proof,"digest":digest(proof)}
