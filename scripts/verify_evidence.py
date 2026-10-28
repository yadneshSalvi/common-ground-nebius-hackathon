"""Offline portable proof verifier. Does not load runtime secrets or contact services."""
from __future__ import annotations
import argparse
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.protocol import digest, parse_time, verify_message
from shared.schema import BROKER_ID, CIRCLE_ID, validate_payload
from broker.checker import verify_assignments


def verify(bundle):
    content = bundle["content"]
    if content.get("format") != "common-ground-proof/v1" or digest(content) != bundle.get("content_sha256"):
        raise ValueError("Proof format or canonical content digest is invalid")
    serialized = json.dumps(content)
    if "CG_PRIVATE_" in serialized or "CG_CANARY_" in serialized:
        raise ValueError("Private canary found in public proof")
    members = {member["id"]: member for member in content["members"]}
    messages = content["signed_messages"]
    seen_ids, seen_nonces, grants, approvals = set(), set(), {}, []
    for message in messages:
        body = message["body"]
        member = members[body["issuer"]]
        # Verify historical integrity at issuance, never mistake this for current authority.
        checked = verify_message(message, member["public_key"], audience=BROKER_ID, now=parse_time(body["issued_at"]) + timedelta(microseconds=1))
        if checked["circle_id"] != CIRCLE_ID or checked["key_id"] != member["key_id"]:
            raise ValueError("Wrong historical circle or signing identity")
        validate_payload(checked["type"], checked["payload"])
        if body["message_id"] in seen_ids or (body["issuer"], body["nonce"]) in seen_nonces:
            raise ValueError("Duplicated message ID/nonce in append-only proof")
        seen_ids.add(body["message_id"])
        seen_nonces.add((body["issuer"], body["nonce"]))
        if body["type"] == "ReleaseGrant":
            offer = body["payload"]["offer"]
            grants[(offer["owner_id"], offer["offer_id"], offer["revision"])] = message
        if body["type"] == "Approval":
            approvals.append(message)
    proposals = {proposal["proposal_id"]: proposal for proposal in content["proposals"]}
    for proposal in proposals.values():
        offers = []
        for reference in proposal["offer_refs"]:
            grant = grants[(reference["owner_id"], reference["offer_id"], reference["revision"])]
            if grant["body"]["consent_revision"] != reference["consent_revision"]:
                raise ValueError("Proposal references a different release consent revision")
            offers.append(grant["body"]["payload"]["offer"])
        check = verify_assignments(proposal["tasks"], offers, proposal["assignments"])
        if not check["valid"]:
            raise ValueError("Independent assignment check failed: " + "; ".join(check["errors"]))
        assignments = {a["task_id"]: a for a in proposal["assignments"]}
        if len(proposal["actions"]) != len(assignments):
            raise ValueError("Action manifest does not match responsibilities")
        for action in proposal["actions"]:
            assignment = assignments[action["task_id"]]
            if any(action[k] != assignment[k] for k in ("owner_id", "start", "end")):
                raise ValueError("Action interval/owner diverges from responsibility")
            if action["event_id"] != "cg-" + hashlib.sha256(action["action_id"].encode()).hexdigest()[:40]:
                raise ValueError("Non-deterministic calendar event ID")
    for approval in approvals:
        payload = approval["body"]["payload"]
        proposal = proposals[payload["proposal_id"]]
        if digest(proposal) != payload["proposal_digest"] or digest(proposal["actions"]) != payload["manifest_digest"]:
            raise ValueError("Approval signed a different proposal/manifest")
        expected = sorted(a["action_id"] for a in proposal["actions"] if a["owner_id"] == approval["body"]["issuer"])
        if sorted(payload["action_ids"]) != expected or payload["version"] != proposal["version"]:
            raise ValueError("Approval action set/version is not exact")
    for receipt in content["model_runs"]:
        if receipt.get("request_body") and digest(receipt["request_body"]) != receipt.get("request_digest"):
            raise ValueError("Model request body hash mismatch")
        if receipt.get("permitted_input") and digest(receipt["permitted_input"]) != receipt.get("input_digest"):
            raise ValueError("Model permitted-input hash mismatch")
    return {"valid": True, "signed_messages": len(messages), "proposals": len(proposals), "approvals": len(approvals), "model_attempts": len(content["model_runs"]), "scope": "Historical signature/hash/assignment integrity; current authority and real-world outcomes require fresh owner observation."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("proof", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(json.loads(args.proof.read_text())), indent=2))
    except (KeyError, ValueError, TypeError) as error:
        print("Proof verification failed: " + str(error), file=sys.stderr)
        raise SystemExit(1)
