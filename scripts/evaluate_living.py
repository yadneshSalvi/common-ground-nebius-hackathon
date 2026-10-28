"""Frozen authored scheduling validation and a strong no-model baseline.

60 development + 120 authored validation cases share one deterministic generator.
They are NOT independently authored, sealed held-out cases, or a human study.
No provider calls, private runtime reads or service/calendar mutations occur.
"""
import argparse
from collections import Counter
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from broker.living_checker import check
from broker.living_solver import solve
from shared.living import validate_goal, goal_digest
from shared.protocol import digest, utc_now


def minute(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def generate_case(index):
    family = ("appointment", "two-day-meal", "parallel-subjects", "visit-chain")[index % 4]
    day = (date(2026, 11, 10) + timedelta(days=index)).isoformat()
    tomorrow = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    owners = [f"owner{n}" for n in range(2 + index % 5)]
    tasks = []
    def task(tid, cap, start, end, subject="Dev", at="home", to=None, prior=(), on=day, required=True):
        quote = f"On {on}, {tid} is a {cap} responsibility for {subject} from {minute(start)} to {minute(end)} ({end-start} minutes), from {at} to {to or at}."
        tasks.append({"task_id":tid,"label":tid,"capability":cap,"date":on,"duration":end-start,"earliest":start,"latest":end,"start_location":at,"end_location":to or at,"predecessors":list(prior),"required":required,"subject":subject,"source_quote":quote})
    if family == "appointment":
        task("prepare","preparation",740,760)
        task("outbound","driving",790,830,to="clinic",prior=["prepare"])
        task("accompany","accompaniment",830,920,at="clinic",prior=["outbound"])
        task("return","driving",920,960,at="clinic",to="home",prior=["accompany"])
        task("handoff","handoff",960,975,prior=["return"])
    elif family == "two-day-meal":
        task("company","accompaniment",600,630)
        task("meal-prep","meal",660,680,subject="Meal",on=tomorrow)
        task("meal-handoff","handoff",680,690,subject="Meal",on=tomorrow,prior=["meal-prep"])
    elif family == "parallel-subjects":
        for subject in ("Dev", "Meal"):
            for step in range(3):
                task(subject.lower()+str(step),"visit" if subject=="Dev" else "meal",600+20*step,620+20*step,subject=subject,prior=[subject.lower()+str(step-1)] if step else [])
    else:
        for step in range(2 + (index // 4) % 11):
            task("visit"+str(step),"visit",480+15*step,495+15*step,prior=["visit"+str(step-1)] if step else [],required=not (step and step==1+(index//4)%11 and index%3==0))
    routes=[]
    if family=="appointment":
        for a,b in (("home","clinic"),("clinic","home")):
            routes.append({"from_location":a,"to_location":b,"duration":40,"source_quote":f"The confirmed journey from {a} to {b} takes exactly 40 minutes."})
    source=" ".join([t["source_quote"] for t in tasks]+[r["source_quote"] for r in routes])
    goal=validate_goal({"schema_version":2,"goal_id":f"authored-{index:03d}","revision":1,"title":family,"description":"Authored fixed-time schedule validation","timezone":"Asia/Kolkata","participants":owners,"subject":"Authored care","source_text":source,"tasks":tasks,"routes":routes,"confirmed_at":"2026-10-28T15:00:00.000000Z","confirmed_by":"authored-evaluation-fixture"})
    full=[]
    for owner_index,owner in enumerate(owners):
        tids=[t["task_id"] for j,t in enumerate(tasks) if owner_index in {j % len(owners),(j+1) % len(owners)}]
        full.append({"goal_id":goal["goal_id"],"goal_revision":1,"goal_digest":goal_digest(goal),"offer_id":f"offer-{index}-{owner}","offer_revision":1,"owner_id":owner,"constraint_revision":1,"task_ids":tids,"windows":[{"date":d,"start":0,"end":1440} for d in sorted({t["date"] for t in tasks})],"conditions":[],"recipients":{"humans":owners,"broker":"common-ground-broker","inference":[]},"request_categories":[],"expires_at":"2099-01-01T00:00:00.000000Z"})
    # Some same-day parallel duties genuinely exceed one available owner.
    if family=="parallel-subjects" and index%3==2:
        for offer in full:
            offer["task_ids"]=[t["task_id"] for t in tasks] if offer["owner_id"]==owners[0] else []
    if family=="appointment":
        receiver=next(o["owner_id"] for o in full if "handoff" in o["task_ids"])
        for offer in full:
            if "return" in offer["task_ids"]:
                offer["conditions"]=[{"task_id":"return","receiver_task_id":"handoff","receiver_id":receiver,"by":974 if index%20==0 else 975}]
    released=json.loads(json.dumps(full))
    withheld=None
    if index%6==1:
        withheld=next(t["task_id"] for t in reversed(tasks) if t["required"])
        for offer in released:
            offer["task_ids"]=[t for t in offer["task_ids"] if t!=withheld]
            offer["conditions"]=[c for c in offer["conditions"] if c["task_id"]!=withheld]
    return {"id":goal["goal_id"],"partition":"development" if index<60 else "authored-validation","family":family,"goal":goal,"oracle_full_offers":full,"released_offers":released,"withheld_task":withheld,"additional_question_permission":False}


def oracle(goal,offers):
    """Independent exhaustive fixed-time feasibility oracle; no solver/checker."""
    tasks=goal["tasks"]; routes={(r["from_location"],r["to_location"]):r["duration"] for r in goal["routes"]}
    candidates=[]
    for task in tasks:
        values=[o for o in offers if task["task_id"] in o["task_ids"] and any(w["date"]==task["date"] and w["start"]<=task["earliest"] and task["latest"]<=w["end"] for w in o["windows"])]
        if not task["required"]:
            values.append(None)
        if not values:
            return False
        candidates.append(values)
    def coherent(chosen,complete=False):
        assigned={tasks[i]["task_id"]:(tasks[i],offer) for i,offer in enumerate(chosen) if offer is not None}
        for owner in goal["participants"]:
            own=sorted((t for t,o in assigned.values() if o["owner_id"]==owner),key=lambda t:(t["date"],t["earliest"]))
            for left,right in zip(own,own[1:]):
                transfer=0 if left["end_location"]==right["start_location"] else routes.get((left["end_location"],right["start_location"]))
                gap=(date.fromisoformat(right["date"])-date.fromisoformat(left["date"])).days*1440+right["earliest"]-left["latest"]
                if transfer is None or gap<transfer:
                    return False
        for t,offer in assigned.values():
            for pid in t["predecessors"]:
                if pid in assigned and (assigned[pid][0]["date"],assigned[pid][0]["latest"])>(t["date"],t["earliest"]):
                    return False
                if complete and pid not in assigned:
                    return False
            for condition in [c for c in offer["conditions"] if c["task_id"]==t["task_id"]]:
                receiver=assigned.get(condition["receiver_task_id"])
                if receiver and (receiver[1]["owner_id"]!=condition["receiver_id"] or receiver[0]["date"]!=t["date"] or receiver[0]["earliest"]<t["latest"] or receiver[0]["latest"]>condition["by"]):
                    return False
                if complete and receiver is None:
                    return False
        return True
    def visit(chosen):
        if len(chosen)==len(tasks):
            return coherent(chosen,complete=True)
        for offer in candidates[len(chosen)]:
            next_chosen=chosen+[offer]
            if coherent(next_chosen) and visit(next_chosen):
                return True
        return False
    return visit([])


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--corpus",type=Path,default=ROOT/"evidence/living-planning-corpus.json")
    parser.add_argument("--output",type=Path,default=ROOT/"evidence/living-planning-validation.json")
    args=parser.parse_args()
    if not args.corpus.exists():
        corpus={"format":"common-ground.authored-planning-corpus/v2","authorship":"One deterministic authored generator; shared across partitions; no independent authorship or sealed test claim","cases":[generate_case(i) for i in range(180)]}
        corpus["digest"]=digest(corpus); save(args.corpus,corpus)
    corpus=json.loads(args.corpus.read_text())
    assert corpus["digest"]==digest({k:v for k,v in corpus.items() if k!="digest"})
    started=utc_now(); rows=[]
    for case in corpus["cases"]:
        goal=validate_goal(case["goal"])
        full=oracle(goal,case["oracle_full_offers"])
        attainable=oracle(goal,case["released_offers"])
        tick=time.monotonic(); result=solve(goal,case["released_offers"],max_seconds=2)
        candidate=result["status"] in ("OPTIMAL","FEASIBLE")
        checked=check(goal,case["released_offers"],result["assignments"])["valid"] if candidate else None
        status="PASS" if ((candidate and checked and attainable) or (result["status"]=="INFEASIBLE" and not attainable)) else "UNKNOWN" if result["status"]=="UNKNOWN" else "FAIL"
        rows.append({"id":case["id"],"partition":case["partition"],"family":case["family"],"owners":len(goal["participants"]),"responsibilities":len(goal["tasks"]),"full_authority_feasible":full,"attainable_with_released_offers":attainable,"additional_question_permission":False,"solver_status":result["status"],"independent_check":checked,"result":status,"elapsed_ms":round(1000*(time.monotonic()-tick),3)})
    sources={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ("scripts/evaluate_living.py","broker/living_solver.py","broker/living_checker.py","shared/living.py")}
    report={"format":"common-ground.authored-planning-validation/v2","started_at":started,"finished_at":utc_now(),"corpus_digest":corpus["digest"],"source_hashes":sources,"baseline":"Reviewed structured goal + released offers + CP-SAT; no model, questions or execution","limits":["Shared authored generator; no independent or sealed held-out claim","Fixed exact intervals; does not cover every flexible-time assignment","Oracle full offers are evaluation-only and never sent to any provider","No measured model advantage, human time saving, calendar fault or household outcome claim"],"assigned":len(rows),"partitions":dict(Counter(r["partition"] for r in rows)),"results":dict(Counter(r["result"] for r in rows)),"globally_infeasible":sum(not r["full_authority_feasible"] for r in rows),"information_limited":sum(r["full_authority_feasible"] and not r["attainable_with_released_offers"] for r in rows),"cases":rows}
    save(args.output,report)
    print(json.dumps({k:v for k,v in report.items() if k not in ("cases","source_hashes")},indent=2))
    if any(r["result"]!="PASS" for r in rows):
        raise SystemExit(1)


if __name__=="__main__":
    main()
