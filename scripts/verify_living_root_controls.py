"""Repeat root's fixed IAB proof tamper controls, not a general model evaluator.

Copy evidence/living-iab-proof.json as proof.json, this script and
scripts/verify_living_evidence.py into a new directory. Install only the pinned
cryptography/rfc8785 dependencies and run this script there. Each altered copy
gets a newly computed outer digest; the signed/internal binding must reject it.
"""
import copy, hashlib, json, subprocess, sys
from pathlib import Path
import rfc8785

base=json.loads(Path('proof.json').read_text())
ref=base['current_agreement']
aid=ref['agreement_id']
pickup='cg246f5ffaf48ef8cefadde5b645ee35ebff4b4251c'

def current(p):
    return next(a for a in p['agreements'] if a['agreement_id']==aid and a['revision']==2)
def altered_goal(p):
    next(g for g in p['goals'] if g['goal_id']==current(p)['goal']['goal_id'])['title']='Altered title'
def altered_dependency(p):
    c=next(c for c in current(p)['commitments'] if c['task_id']=='handoff')
    c['dependencies'][0]['owner_id']='ravi'
def altered_etag(p):
    next(r for r in p['receipts'] if r['event_id']==pickup)['etag']='"forged"'
def missing_owner(p):
    p['observations']=[m for m in p['observations'] if not(m['body']['issuer']=='ravi' and m['body']['payload']['agreement_id']==aid)]
def historical_receipt_replay(p):
    cancelled=next(r for r in p['receipts'] if r['status']=='CANCELLED' and r['commitment_id']=='commitment-a25a8c81d1d0005413ad9ed4a14019cb')
    historical=next(h['receipt'] for h in p['receipt_history'] if h['receipt']['event_id']==cancelled['event_id'] and h['receipt']['status']=='VERIFIED')
    cancelled.clear();cancelled.update(copy.deepcopy(historical))
def stale_head(p):
    i=next(i for i,m in enumerate(p['observations']) if m['body']['issuer']=='ravi' and m['body']['payload']['agreement_id']==aid)
    old=[m for m in p['observation_history'] if m['body']['issuer']=='ravi' and m['body']['payload']['agreement_id']==aid and m['body']['payload']['observed_at']<p['observations'][i]['body']['payload']['observed_at']]
    assert old
    p['observations'][i]=copy.deepcopy(min(old,key=lambda m:m['body']['payload']['observed_at']))
def forged_time(p):
    p['observed_at']='2099-01-01T00:00:00Z'
def forged_current_ref(p):
    p['current_agreement']['revision']=1

def run(name,change=None):
    p=copy.deepcopy(base)
    if change:change(p)
    p['digest']=hashlib.sha256(rfc8785.dumps({k:v for k,v in p.items() if k!='digest'})).hexdigest()
    path=Path(name+'.json');path.write_text(json.dumps(p,indent=2)+'\n')
    result=subprocess.run([sys.executable,'verify_living_evidence.py',str(path)],capture_output=True,text=True,env={'PATH':'/usr/bin:/bin','PYTHONNOUSERSITE':'1'})
    report=json.loads(result.stdout)
    assert report['valid']==(change is None),(name,report)
    assert result.returncode==(0 if change is None else 1)
    return {'case':name,'outer_digest_recomputed':True,'exit_code':result.returncode,**report}

results=[run('untouched')]
for name,change in [('top-level-goal-title',altered_goal),('changed-handoff-counterpart',altered_dependency),('forged-pickup-etag',altered_etag),('missing-owning-current-observation',missing_owner),('historical-verified-receipt-replay',historical_receipt_replay),('stale-owner-head',stale_head),('forged-observed-time',forged_time),('forged-current-revision',forged_current_ref)]:
    results.append(run(name,change))
out={'scope':'Actual IAB-downloaded proof and verifier, copied outside repository into fresh venv; only cryptography50.0.2/rfc8785 0.1.4 installed; sanitized subprocess environment; no project imports, API credentials or runtime databases','proof_sha256':hashlib.sha256(Path('proof.json').read_bytes()).hexdigest(),'verifier_sha256':hashlib.sha256(Path('verify_living_evidence.py').read_bytes()).hexdigest(),'results':results,'all_passed':True}
Path('root-verification.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
