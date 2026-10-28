"""Explicit metered check in isolated fictional stores, never the main demo."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.cluster import Cluster
from broker.models import Provider
from shared.protocol import digest
from scripts.verify_evidence import verify

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    directory = ROOT / ".runtime" / "live-validation" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True, mode=0o700)
    cluster = Cluster(directory)
    cluster.engine.provider = Provider(ROOT.parent / ".env")
    cluster.release_all(inference=not args.offline)
    response = cluster.op("/api/plan", {"mode": "local" if args.offline else "live", "expected_revision": cluster.state()["revision"]})
    state = cluster.state()
    if response.status_code == 202 and state["proposal"]:
        cluster.approve(state["proposal"])
        state = cluster.enact(state["proposal"])
    proof = cluster.op("/api/evidence").json()
    proof["content"]["validation_environment"] = "Isolated in-process FastAPI owner/broker HTTP transports, real separate SQLite calendars; actual Fireworks inference unless explicitly offline. Not the main interactive demo."
    proof["content_sha256"] = digest(proof["content"])
    cluster.engine.provider.assert_clean(proof)
    (directory / "proof.json").write_text(json.dumps(proof, indent=2, ensure_ascii=False))
    result = verify(proof)
    print(json.dumps({"state": state["state"], "planning": state["planning"], "proof": str(directory / "proof.json"), "verification": result, "usage": [{"provider": r["provider"], "model": r["model"], "status": r["status"], "usage": r.get("usage"), "estimated_cost_usd": r.get("estimated_cost_usd")} for r in state["model_runs"]]}, indent=2))
    return 0 if state["state"] == "ACTIVE" else 1

if __name__ == "__main__":
    raise SystemExit(main())
