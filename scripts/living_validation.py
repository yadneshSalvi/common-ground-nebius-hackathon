"""Explicit live NVIDIA qualification; owner HTTP is in-process, calendars real/local.

All participants and decisions are authored fiction. No Google/human validation.
"""
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from broker.living_models import LivingProvider
from tests.test_living_integration import living_cluster,sample,state,withdraw_return,release,plan,approve
from shared.living import validate_goal
from shared.protocol import utc_now


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")
    path.chmod(0o600)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--provider",choices=("fireworks","nebius"),required=True)
    parser.add_argument("--directory",type=Path)
    args=parser.parse_args()
    directory=args.directory or ROOT/"evidence"/"private"/("living-"+args.provider+"-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    directory.mkdir(parents=True,exist_ok=False)
    cluster=living_cluster(directory/"stores")
    living=cluster.app.state.living
    living.config["env_path"]=str(ROOT.parent/".env")
    living.provider=LivingProvider(living.config)
    report={"kind":"Actual provider; authored fictional data; in-process owner HTTP; durable local calendars","provider":args.provider,"started_at":utc_now(),"human_participants":0,"google_account_qualification":False,"checks":[],"directory":str(directory)}
    print(json.dumps({"event":"started","provider":args.provider,"directory":str(directory)}),flush=True)
    try:
        original=sample(cluster,args.provider)
        withdraw_return(cluster)
        first=plan(cluster,args.provider)
        print(json.dumps({"event":"question","status":first["planning"]["status"]}),flush=True)
        assert first["status"]=="NEEDS_HELP" and first["pending"] is None,first["planning"]
        assert any(q["owner_id"]=="leena" and q["task_id"]=="return" for q in first["questions"]),first["planning"]
        assert not any(q["owner_id"]=="asha" and q["task_id"]=="return" for q in first["questions"])
        report["checks"].append("Actual NVIDIA selected a permitted missing-return question, without asking Asha to drive.")
        release(cluster,"leena",args.provider)
        repaired=plan(cluster,args.provider); pending=repaired["pending"]
        print(json.dumps({"event":"repair","status":repaired["planning"]["status"]}),flush=True)
        assert pending,repaired["planning"]
        assert sorted(m["kind"] for m in pending["delta"]["calendar_mutations"])==["delete","insert"]
        assert next(c for c in pending["commitments"] if c["task_id"]=="return")["conditions"][0]["by"]==975
        statuses={r["owner_id"]:r for r in repaired["approval_status"]}
        assert statuses["asha"]["status"]=="needs_review" and statuses["ravi"]["basis"]=="standing-policy"
        approve(cluster,"leena",pending)
        assert cluster.op("/api/v2/execute",{"agreement_id":pending["agreement_id"],"revision":pending["revision"]}).status_code==409
        approve(cluster,"asha",pending)
        response=cluster.op("/api/v2/execute",{"agreement_id":pending["agreement_id"],"revision":pending["revision"]})
        assert response.status_code==200,response.text
        final=response.json(); assert final["status"]=="ACTIVE",final["planning"]
        old=next(c for c in original["commitments"] if c["task_id"]=="outbound")
        new=next(c for c in final["commitments"] if c["task_id"]=="outbound")
        assert (old["event_id"],old["etag"])==(new["event_id"],new["etag"])
        report["checks"].extend(["Conditional Leena return required fresh Asha handoff consent.","Selective actual delete/insert preserved pickup ID and ETag."])
        save(directory/"flagship-proof.json",living.evidence())
        day1=(datetime.now(timezone.utc).date()+timedelta(days=10)).isoformat()
        day2=(datetime.now(timezone.utc).date()+timedelta(days=11)).isoformat()
        source=(f"This fictional shared request has Asha and Leena, registered IDs asha and leena, in Asia/Kolkata. On {day1}, accompany Dev at home from 10:00 until 10:30 (30 minutes). "
                f"On {day2}, prepare a meal at home from 11:00 until 11:20 (20 minutes), then hand the meal over at home from 11:20 until 11:30 (10 minutes). "
                "Accompaniment concerns Dev. Preparation and handoff concern the meal. All three responsibilities are required. Meal handoff depends on meal preparation. There is no driving or travel.")
        response=cluster.op("/api/v2/goal/draft",{"source_text":source,"provider":args.provider,"allow_inference":True})
        assert response.status_code==202,response.text
        drafted=state(cluster); draft=drafted["draft"]
        print(json.dumps({"event":"new-goal","status":drafted["planning"]["status"]}),flush=True)
        assert draft and draft["status"]=="REVIEW_REQUIRED",drafted["planning"]
        goal=draft["goal"]
        assert len(goal["tasks"])==3 and {t["date"] for t in goal["tasks"]}=={day1,day2}
        capabilities={t["capability"] for t in goal["tasks"]}
        assert "accompaniment" in capabilities and "handoff" in capabilities and capabilities & {"meal","preparation"}
        assert not draft["questions"] and goal["routes"]==[]
        goal["confirmed_at"]=utc_now(); goal["confirmed_by"]="authored-validation-reviewed-form"
        goal=validate_goal(goal)
        response=cluster.op("/api/v2/goal/confirm",{"goal":goal,"expected_revision":drafted["revision"]})
        assert response.status_code==200,response.text
        for owner in goal["participants"]:
            release(cluster,owner,args.provider)
        planned=plan(cluster,args.provider); pending=planned["pending"]
        assert pending,planned["planning"]
        for owner in {c["owner_id"] for c in pending["commitments"]}:
            approve(cluster,owner,pending)
        response=cluster.op("/api/v2/execute",{"agreement_id":pending["agreement_id"],"revision":pending["revision"]})
        assert response.status_code==200 and response.json()["status"]=="ACTIVE",response.text
        report["checks"].append("Actual semantic parse produced and enacted a new two-owner, three-task, two-date structure after explicit authored review.")
        report["status"]="PASSED"
    except Exception as exc:
        report.update(status="FAILED",error=str(exc)[:1500],error_type=type(exc).__name__)
        print(json.dumps({"event":"failed","type":type(exc).__name__,"error":str(exc)[:1000]}),flush=True)
    finally:
        final=state(cluster)
        report.update(finished_at=utc_now(),model_runs=len(final["model_runs"]),known_estimated_cost_usd=round(sum(r.get("estimated_cost_usd",0) for r in final["model_runs"]),8),unknown_usage_attempts=sum(bool(r.get("transmitted_at")) and not r.get("usage_known") for r in final["model_runs"]))
        save(directory/"final-state.json",final); save(directory/"proof.json",living.evidence()); save(directory/"report.json",report)
        print(json.dumps({k:v for k,v in report.items() if k!="checks"},ensure_ascii=False),flush=True)
    if report["status"]!="PASSED":
        raise SystemExit(1)


if __name__=="__main__":
    main()
