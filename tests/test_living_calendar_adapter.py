from copy import deepcopy
import re
from concurrent.futures import ThreadPoolExecutor

import pytest

from owner_agent.living_calendar import LivingCalendarStore, event_id_for


def intent(action="pickup-ravi"):
    return {"schema_version": 2, "action_id": action, "commitment_id": "commit-"+action, "owner_id": "ravi", "task_id": "pickup", "event_id": event_id_for(action), "label": "Pick up Dev", "date": "2026-11-02", "timezone": "Asia/Kolkata", "start": 800, "end": 840, "location": {"start": "home", "end": "clinic"}, "creation": {"agreement_id": "agreement-1", "revision": 1, "created_at": "2026-10-28T10:00:00Z"}}


def test_stable_identity_and_restart_preserve_exact_creation(tmp_path):
    path = tmp_path / "calendar.db"
    store = LivingCalendarStore(path)
    item = intent()
    first = store.insert(item)
    assert re.fullmatch(r"[a-v0-9]{5,1024}", first["event_id"])
    assert LivingCalendarStore(path).insert(item) == first
    amended = {**item, "start": 810, "end": 850}
    ok, changed = store.update_if_unchanged(item["event_id"], first["etag"], amended)
    assert ok and changed["etag"] != first["etag"]
    assert changed["creation"] == first["creation"]
    assert LivingCalendarStore(path).get(item["event_id"]) == changed
    assert store.update_if_unchanged(item["event_id"], first["etag"], item) == (False, changed)
    assert store.delete_if_unchanged(item["event_id"], first["etag"]) == (False, changed)
    assert store.delete_if_unchanged(item["event_id"], changed["etag"]) == (True, None)
    assert store.delete_if_unchanged(item["event_id"], None) == (True, None)


def test_manual_edit_blocks_automatic_update_delete_even_with_current_etag(tmp_path):
    store = LivingCalendarStore(tmp_path / "calendar.db")
    item = intent()
    first = store.insert(item)
    changed = store.edit(item["event_id"], "Private owner correction")
    for etag in (first["etag"], changed["etag"]):
        assert store.update_if_unchanged(item["event_id"], etag, item) == (False, changed)
        assert store.delete_if_unchanged(item["event_id"], etag) == (False, changed)
    with pytest.raises(ValueError, match="precondition"):
        store.insert(item)
    assert store.get(item["event_id"]) == changed


def test_conflicting_identity_or_creation_is_never_reassigned(tmp_path):
    store = LivingCalendarStore(tmp_path / "calendar.db")
    item = intent()
    first = store.insert(item)
    for changed in ({**item, "owner_id": "asha"}, {**item, "creation": {**item["creation"], "revision": 2}}):
        with pytest.raises(ValueError, match="immutable"):
            store.update_if_unchanged(item["event_id"], first["etag"], changed)
        with pytest.raises(ValueError, match="precondition"):
            store.insert(changed)
    assert store.get(item["event_id"]) == first


def test_two_calendar_instances_cannot_both_spend_one_version(tmp_path):
    path = tmp_path / "calendar.db"
    a, b = LivingCalendarStore(path), LivingCalendarStore(path)
    item = intent()
    first = a.insert(item)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda p: p[0].update_if_unchanged(item["event_id"], first["etag"], {**item, "label": p[1]}), [(a, "First change"), (b, "Second change")]))
    assert sum(ok for ok, _ in results) == 1
    assert a.get(item["event_id"])["label"] in ("First change", "Second change")


def test_intent_is_detached_and_public_fields_only(tmp_path):
    store = LivingCalendarStore(tmp_path / "calendar.db")
    item = intent()
    item["private_note"] = "Never release me"
    normalized = store.intended(item)
    item["location"]["start"] = "changed later"
    assert "private_note" not in normalized
    assert normalized["location"]["start"] == "home"
    first = store.insert(normalized)
    first["creation"]["revision"] = 999
    assert store.get(first["event_id"])["creation"]["revision"] == 1
    malformed = deepcopy(normalized)
    malformed["event_id"] = "wrong-event"
    with pytest.raises(ValueError):
        store.insert(malformed)


@pytest.mark.parametrize("patch", [
    {"date": "2026-03-08", "timezone": "America/New_York", "start": 150, "end": 180},
    {"date": "2026-11-01", "timezone": "America/New_York", "start": 90, "end": 120},
    {"date": "2026-03-08", "timezone": "America/New_York", "start": 90, "end": 210},
    {"date": "20261102"},
])
def test_unrepresentable_wall_time_cannot_become_verified_calendar_content(tmp_path, patch):
    store = LivingCalendarStore(tmp_path / "calendar.db")
    with pytest.raises(ValueError):
        store.insert({**intent(), **patch})
    assert store.list() == []
