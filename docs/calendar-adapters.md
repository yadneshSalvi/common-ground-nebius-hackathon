# Calendar effects and their limits

The v2 runtime uses `LivingCalendarStore`: a separate SQLite calendar for each fictional owner. Its content is the exact reviewed public intent, with a stable action/event ID and immutable creation provenance. Amendments do not rename or recreate retained events. Unsupported ambiguous/nonexistent wall times and intervals crossing a timezone offset change are rejected explicitly; no hidden DST fold is selected. Creation timestamps require an offset. Conditional updates and removals require the last observed ETag and refuse any marked owner edit. Independent database connections cannot both spend one version. The owner protocol persists authorization and mutation intent before calling the adapter and reads actual state before reporting verification.

`owner_agent/connectors/google_calendar.py` adds an optional Google Calendar v3 adapter with the same mutation interface. It is **not enabled in the local sample**. It accepts an owner-local token callback and dedicated app-created calendar; it does not acquire OAuth authorization, connect a Google account, or create a calendar. Live-account qualification is pending. No real calendar event has been created by these tests.

The connector sends no attendees or invitations. It tracks only known app event IDs rather than listing unrelated personal events. Tokens are never written to its SQLite journal. Pending operations are saved before transmission; a timeout is ambiguous and is never silently retried. An exact later read can reconcile an insert/update after response loss. Deletes require confirmed absence, and an event 404 additionally requires readable calendar metadata: lost access must not masquerade as a successful removal. Provider ETags protect the interval between observation and mutation. Any change in the acknowledged version or mutable content, including unrecognized provider fields, marks an event edited. Automatic compensation preserves it even when given its fresh ETag. The v2 release does not implement automatic re-adoption or removal of a manually edited event: it stays visibly in need of owner resolution. This is a limitation, not a successful recovery claim.

The journal is bound to one calendar and expects one owner process as its writer. Container isolation and opaque capabilities do not remove the authority of the host administrator. OAuth lifecycle, provider retention behavior, concurrent external-account qualification and independent household testing remain unqualified. A verified calendar effect never establishes attendance or human completion.

## Development checks

`python -m pytest -q tests/test_living_calendar_adapter.py tests/test_google_calendar_adapter.py`

The authored local/HTTP-transport checks cover persistent exact insert/update/delete; stale and racing ETags; duplicate/collision handling; manual/private edits; loss after all three write kinds; restart readback; access revocation; failed readback after an acknowledged write; token exclusion; calendar binding; immutable identity/provenance; concurrent local writers; and public-field normalization. HTTP response fixtures test adapter behavior, not Google's service or real OAuth.

## Primary API contracts

- [Conditional resource modification](https://developers.google.com/workspace/calendar/api/guides/version-resources): use `If-Match` for mutation and treat 412 as a conflict.
- [Event insertion](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert): custom IDs use the base32hex alphabet. The v2 ID is `cg2` plus 40 SHA-256 hexadecimal characters derived from the stable action ID.
- [Calendar scopes](https://developers.google.com/workspace/calendar/api/auth): `calendar.app.created` limits access to secondary calendars created by the app. This scope is a planned account-connection boundary, not an OAuth grant already obtained.
- [Calendar metadata retrieval](https://developers.google.com/workspace/calendar/api/v3/reference/calendars/get): supports this scope and is used to distinguish missing event from unavailable calendar access.
