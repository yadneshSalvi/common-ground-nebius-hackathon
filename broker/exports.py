from __future__ import annotations
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event
from shared.protocol import digest, utc_now
from broker.engine import BrokerError


def evidence(engine):
    engine.refresh_active_effects()
    state = engine.store.read()
    observed = []
    if state["proposal"]:
        for owner in {a["owner_id"] for a in state["proposal"]["actions"]}:
            try:
                observed.append(engine.owner_call(owner, "/coordination/events?proposal_id=" + state["proposal"]["proposal_id"]))
            except BrokerError as error:
                observed.append({"owner_id": owner, "error": str(error), "status": "UNKNOWN"})
    root = Path(__file__).resolve().parents[1]
    sources = {}
    for folder in ("broker", "shared", "owner_agent"):
        for path in (root / folder).glob("*.py"):
            sources[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    content = {"format": "common-ground-proof/v1", "generated_at": utc_now(), "scenario": state["goal"], "current_state": state["state"], "current_proposal_id": state["proposal"]["proposal_id"] if state["proposal"] else None, "members": state["owners"], "proposals": list(state["archive"].values()), "signed_messages": state.get("protocol_messages", []), "action_receipts": state.get("action_receipts", []), "closed_rounds": state.get("rounds", []), "model_runs": state["model_runs"], "disclosures": state["disclosures"], "history": state["history"], "observed_calendar_effects": observed, "source_hashes": sources, "limitations": ["Fictional local sample, not real calendar-account or medical data.", "Trusted-process demo: hostile same-UID code and OS administrators are out of scope.", "Separate owner services enforce HTTP capabilities; no distributed filesystem-isolation claim.", "Hashes detect corruption; verify member fingerprints out of band for identity trust.", "Model suggestions are untrusted; solver checks released offers only and owners revalidate privately.", "No human studies, cloud deployment, final Nebius Ultra completion qualification or real-world attendance claim.", "Provider transmission attempts may be uncertain after transport failure; retained receipts say what was observed."], "rerun": "python scripts/verify_evidence.py FILE; python -m pytest"}
    # Older receipts may contain an edited version identifier; public proof does
    # not need that private version, including in retained historical receipts.
    def sanitize_versions(value):
        if isinstance(value, dict):
            remaining = value.get("remaining_effect")
            if isinstance(remaining, dict) and remaining.get("user_edited"):
                remaining.pop("etag", None)
            for child in value.values():
                sanitize_versions(child)
        elif isinstance(value, list):
            for child in value:
                sanitize_versions(child)
    sanitize_versions(content)
    engine.provider.assert_clean(content)
    content["source_hashes_scope"] = "Files on disk at export time; not a claim about historical process bytes."
    encoded = json.dumps(content)
    capabilities = [engine.config["pair_code"], engine.config["broker_ingest_token"], *[peer["service_token"] for peer in engine.config["owners"]]]
    if any(capability in encoded for capability in capabilities):
        raise BrokerError("A local capability was blocked from the public proof.", 500)
    return {"content": content, "content_sha256": digest(content)}


def calendar_bytes(engine):
    engine.refresh_active_effects()
    state = engine.store.read()
    proposal = state["proposal"]
    if not proposal:
        raise BrokerError("There is no agreement to export.", 404)
    calendar = Calendar()
    calendar.add("prodid", "-//Common Ground//Fictional Local Agreement//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", "Common Ground · fictional appointment")
    for action in proposal["actions"]:
        event = Event()
        event.add("uid", action["event_id"] + "@common-ground.local")
        midnight = datetime.fromisoformat(action["date"]).replace(tzinfo=ZoneInfo(action["timezone"]))
        event.add("dtstart", (midnight + timedelta(minutes=action["start"])).astimezone(timezone.utc))
        event.add("dtend", (midnight + timedelta(minutes=action["end"])).astimezone(timezone.utc))
        event.add("dtstamp", datetime.now(timezone.utc))
        receipt = state["actions"].get(action["action_id"], {})
        status = receipt.get("status", "PENDING_APPROVAL")
        event.add("summary", action["owner_id"].title() + " · " + action["label"])
        event.add("description", f"Fictional sample. Proposal v{proposal['version']}. Local adapter status at export: {status}. Timezone: {action['timezone']}. Importing this file is a separate user action; it does not enact or update the signed local agreement.")
        event.add("status", "CONFIRMED" if status == "VERIFIED" else "CANCELLED" if status == "CANCELLED" else "TENTATIVE")
        event.add("sequence", proposal["version"])
        event.add("x-common-ground-action", action["action_id"])
        calendar.add_component(event)
    return calendar.to_ical()
