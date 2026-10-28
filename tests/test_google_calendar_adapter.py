"""Authored HTTP semantics tests. These do not qualify Google OAuth/accounts."""
from copy import deepcopy
import json

import httpx
import pytest

from owner_agent.connectors.google_calendar import CalendarAmbiguous, CalendarConflict, CalendarUnavailable, GoogleCalendarStore
from tests.test_living_calendar_adapter import intent


class CalendarEndpoint:
    def __init__(self):
        self.events = {}
        self.version = 0
        self.calls = []
        self.lose_after = None
        self.denied = False
        self.hidden = False
        self.race_before = None
        self.fail_readback = False
        self.transport = httpx.MockTransport(self.route)

    def change(self, event_id, **fields):
        self.version += 1
        self.events[event_id].update(fields)
        self.events[event_id]["etag"] = f'"v{self.version}"'

    def route(self, request):
        self.calls.append((request.method, request.url.path, request.headers.get("if-match")))
        assert request.url.host == "www.googleapis.com"
        assert request.headers["authorization"] == "Bearer owner-test-token"
        if self.denied:
            return httpx.Response(403, json={"error": "denied"})
        if self.hidden:
            return httpx.Response(404, json={"error": "not found"})
        if not request.url.path.endswith("/events") and "/events/" not in request.url.path:
            return httpx.Response(200, json={"id": "dedicated-calendar"})
        event_id = request.url.path.split("/events/")[-1] if "/events/" in request.url.path else None
        if request.method == "GET":
            if self.fail_readback and self.events:
                return httpx.Response(503, json={"error": "temporary"})
            return httpx.Response(200, json=deepcopy(self.events[event_id])) if event_id in self.events else httpx.Response(404, json={})
        assert request.url.params["sendUpdates"] == "none"
        if request.method == "POST":
            body = json.loads(request.content)
            assert "attendees" not in body
            event_id = body["id"]
            if event_id in self.events:
                return httpx.Response(409, json={})
            self.events[event_id] = body
            self.change(event_id, kind="calendar#event", eventType="default", endTimeUnspecified=False, status="confirmed", sequence=0)
        else:
            if self.race_before == request.method:
                self.race_before = None
                self.change(event_id, description="An owner's new private note")
            if event_id not in self.events:
                return httpx.Response(404, json={})
            if request.headers.get("if-match") != self.events[event_id]["etag"]:
                return httpx.Response(412, json={})
            if request.method == "PATCH":
                self.change(event_id, **json.loads(request.content))
            elif request.method == "DELETE":
                self.events.pop(event_id)
        if self.lose_after == request.method:
            self.lose_after = None
            raise httpx.ReadTimeout("Authored loss after server commit", request=request)
        return httpx.Response(204) if request.method == "DELETE" else httpx.Response(200, json=deepcopy(self.events[event_id]))


def adapter(tmp_path, endpoint):
    return GoogleCalendarStore(tmp_path / "ledger.db", "dedicated-calendar", lambda: "owner-test-token", transport=endpoint.transport)


def test_exact_insert_readback_idempotency_and_conditional_update_delete(tmp_path):
    endpoint = CalendarEndpoint()
    store = adapter(tmp_path, endpoint)
    item = intent()
    first = store.insert(item)
    assert first["user_edited"] is False
    assert store.insert(item) == first
    assert sum(method == "POST" for method, _, _ in endpoint.calls) == 1
    amended = {**item, "start": 810, "end": 850}
    ok, changed = store.update_if_unchanged(item["event_id"], first["etag"], amended)
    assert ok and changed["creation"] == first["creation"]
    assert ("PATCH", f'/calendar/v3/calendars/dedicated-calendar/events/{item["event_id"]}', first["etag"]) in endpoint.calls
    assert store.delete_if_unchanged(item["event_id"], first["etag"])[0] is False
    assert store.delete_if_unchanged(item["event_id"], changed["etag"]) == (True, None)


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_lost_write_response_is_ambiguous_then_restart_reads_actual_state(tmp_path, method):
    endpoint = CalendarEndpoint()
    store = adapter(tmp_path, endpoint)
    item = intent()
    first = store.insert(item) if method != "POST" else None
    endpoint.lose_after = method
    amended = {**item, "label": "Reviewed new pickup label"}
    with pytest.raises(CalendarAmbiguous):
        if method == "POST":
            store.insert(item)
        elif method == "PATCH":
            store.update_if_unchanged(item["event_id"], first["etag"], amended)
        else:
            store.delete_if_unchanged(item["event_id"], first["etag"])
    restarted = adapter(tmp_path, endpoint)
    observed = restarted.get(item["event_id"])
    if method == "DELETE":
        assert observed is None
    else:
        assert not observed["user_edited"]
        assert restarted.intended(observed) == (amended if method == "PATCH" else item)
    assert sum(m == method for m, _, _ in endpoint.calls) == 1


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_racing_user_edit_protected_by_provider_precondition(tmp_path, method):
    endpoint = CalendarEndpoint()
    store = adapter(tmp_path, endpoint)
    item = intent()
    first = store.insert(item)
    endpoint.race_before = method
    if method == "PATCH":
        ok, observed = store.update_if_unchanged(item["event_id"], first["etag"], {**item, "label": "New reviewed label"})
    else:
        ok, observed = store.delete_if_unchanged(item["event_id"], first["etag"])
    assert not ok and observed["user_edited"]
    assert endpoint.events[item["event_id"]]["description"] == "An owner's new private note"
    assert store.delete_if_unchanged(item["event_id"], observed["etag"])[0] is False


def test_unknown_mutable_fields_and_version_change_count_as_user_edit(tmp_path):
    endpoint = CalendarEndpoint()
    store = adapter(tmp_path, endpoint)
    item = intent()
    store.insert(item)
    endpoint.change(item["event_id"], newProviderFeature={"value": "private"})
    observed = store.get(item["event_id"])
    assert observed["user_edited"]
    assert "newProviderFeature" not in observed
    with pytest.raises(CalendarConflict):
        store.insert(item)


def test_missing_event_requires_calendar_access_and_403_is_never_absence(tmp_path):
    endpoint = CalendarEndpoint()
    store = adapter(tmp_path, endpoint)
    assert store.get(intent()["event_id"]) is None
    endpoint.hidden = True
    with pytest.raises(CalendarUnavailable, match="absence is unknown"):
        store.get(intent()["event_id"])
    endpoint.hidden, endpoint.denied = False, True
    with pytest.raises(CalendarUnavailable):
        store.delete_if_unchanged(intent()["event_id"], '"unused"')


def test_write_ack_with_unavailable_readback_never_reports_verified(tmp_path):
    endpoint = CalendarEndpoint()
    store = adapter(tmp_path, endpoint)
    endpoint.fail_readback = True
    with pytest.raises(CalendarUnavailable):
        store.insert(intent())
    assert len(endpoint.events) == 1
    endpoint.fail_readback = False
    assert not adapter(tmp_path, endpoint).get(intent()["event_id"])["user_edited"]


def test_ledger_is_bound_to_calendar_and_does_not_persist_token(tmp_path):
    endpoint = CalendarEndpoint()
    store = adapter(tmp_path, endpoint)
    store.insert(intent())
    assert b"owner-test-token" not in (tmp_path / "ledger.db").read_bytes()
    with pytest.raises(ValueError, match="different calendar"):
        GoogleCalendarStore(tmp_path / "ledger.db", "another-calendar", lambda: "unused", transport=endpoint.transport)
    with pytest.raises(ValueError, match="primary"):
        GoogleCalendarStore(tmp_path / "other.db", "primary", lambda: "unused")


def test_unknown_existing_event_is_never_adopted(tmp_path):
    endpoint = CalendarEndpoint()
    item = intent()
    endpoint.events[item["event_id"]] = {"id": item["event_id"], "etag": '"unowned"', "summary": "Unrelated private event"}
    store = adapter(tmp_path, endpoint)
    with pytest.raises(CalendarConflict):
        store.insert(item)
    assert endpoint.events[item["event_id"]]["summary"] == "Unrelated private event"
