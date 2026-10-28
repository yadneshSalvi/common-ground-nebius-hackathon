"""Collect existing actual v2 receipts without calls or private runtime reads.

Only explicit live-validation JSON exports and an optional sanitized runtime
proof are read. Original attempts, including failures, are left untouched.
"""
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from broker.living_models import LivingProvider
from shared.protocol import digest, utc_now


def write(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--runtime-proof",type=Path)
    args=parser.parse_args()
    receipts={}; reports=[]
    def include(proof,source):
        for receipt in proof["model_runs"]:
            if receipt["receipt_id"] not in receipts:
                receipts[receipt["receipt_id"]]={"source":source,"receipt":receipt}
            else:
                assert receipts[receipt["receipt_id"]]["receipt"]==receipt,"Conflicting receipt versions"
    for path in sorted((ROOT/"evidence/private").glob("living-*/report.json")):
        report=json.loads(path.read_text())
        include(json.loads((path.parent/"proof.json").read_text()),path.parent.name)
        reports.append({"run":path.parent.name,**{k:v for k,v in report.items() if k!="directory"}})
    if args.runtime_proof:
        include(json.loads(args.runtime_proof.read_text()),"independent-in-app-browser-isolated-runtime")
    values=list(receipts.values())
    summary={}
    for provider in sorted({v["receipt"]["provider_id"] for v in values}):
        rows=[v["receipt"] for v in values if v["receipt"]["provider_id"]==provider]
        summary[provider]={"attempts":len(rows),"statuses":dict(Counter(r["status"] for r in rows)),"known_input_tokens":sum(r.get("usage",{}).get("input_tokens",0) for r in rows),"known_output_tokens":sum(r.get("usage",{}).get("output_tokens",0) for r in rows),"unknown_usage_attempts":sum(bool(r.get("transmitted_at")) and not r.get("usage_known") for r in rows),"known_estimated_cost_usd":str(sum((Decimal(str(r.get("estimated_cost_usd",0))) for r in rows),Decimal(0)))}
    ledger={"format":"common-ground.actual-living-provider-usage/v2","generated_at":utc_now(),"scope":"Actual v2 provider attempts only; mocked/unit-test responses excluded; legacy v1 provider-usage.json unchanged","runtime_proof_included":args.runtime_proof is not None,"providers":summary,"receipts":values,"live_workflow_runs":reports,"limits":["All owners and decisions are authored fiction; zero independent human participants","Scripts use in-process service HTTP and real local calendars; runtime proof source identifies actual isolated services separately","Cost is the retained uncached input/output estimate, not an invoice or account-balance measurement","A workflow harness failure can contain valid model completions; statuses are reported separately","No model advantage or human benefit is measured"]}
    ledger["digest"]=digest(ledger)
    LivingProvider({"env_path":str(ROOT.parent/".env")}).assert_clean(ledger)
    write(ROOT/"evidence/living-provider-usage.json",ledger)
    print(json.dumps({"providers":summary,"runtime_proof_included":args.runtime_proof is not None,"workflow_runs":len(reports)},indent=2))


if __name__=="__main__":
    main()
