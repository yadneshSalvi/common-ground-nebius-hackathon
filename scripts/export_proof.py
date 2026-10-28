"""Fetch and validate a sanitized proof from the running local sample."""
import argparse
import json
from pathlib import Path
import sys
import httpx
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from broker.models import Provider
from scripts.verify_evidence import verify

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "sample-proof.json")
    args = parser.parse_args()
    config = json.loads((ROOT / ".runtime" / "config.json").read_text())
    with httpx.Client(base_url="http://127.0.0.1:4302", timeout=30, trust_env=False) as client:
        response = client.post("/api/session", headers={"Origin": "http://127.0.0.1:4301"}, json={"pair_code": config["pair_code"]})
        response.raise_for_status()
        token = response.json()["token"]
        response = client.get("/api/evidence", headers={"Authorization": "Bearer " + token})
        response.raise_for_status()
        proof = response.json()
    Provider(ROOT.parent / ".env").assert_clean(proof)
    encoded = json.dumps(proof, ensure_ascii=False, indent=2)
    private_capabilities = [token, config["pair_code"], config["broker_ingest_token"], *[peer["service_token"] for peer in config["owners"]]]
    if any(value in encoded for value in private_capabilities):
        raise ValueError("A capability was blocked from the proof file")
    result = verify(proof)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded + "\n")
    report = {**result, "content_sha256": proof["content_sha256"], "state": proof["content"]["current_state"], "proof": args.output.name}
    args.output.with_suffix(".verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
