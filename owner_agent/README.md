# Owner-local agent

One factory runs Asha, Ravi or Leena as a separate local process:

```sh
.venv/bin/python -m owner_agent --config /absolute/path/to/owner/config.json
```

The provisioner supplies `owner_id`, `port`, `broker_url`, `broker_ingest_token`, `service_token`, `pair_code` and `data_dir`. Each directory is mode0700; signing/encryption keys and databases are mode0600. `origin` defaults to the exact `http://127.0.0.1:<port>` origin. The app serves `dist/owner` (or the configured `dist_dir`).

`POST /api/session` requires the local pairing secret and exact owner Origin. It returns a one-hour bearer capability; only its hash is persisted. No cookies are issued. All private routes require that session, mutations require the owner Origin, and an explicitly different Origin is denied even with a valid bearer. A service capability can use only `/coordination/*` and is rejected on browser-origin requests. The broker ingest capability cannot read private routes.

Preferences, authored source calendar entries, corrections, reusable declarative skills, release/approval history and standing consent state are Fernet-encrypted inside the vault SQLite database. Calendar effects live in a separate real SQLite calendar. Neither process boundaries nor encryption protect against hostile code running as the same operating-system user or an OS administrator; that is outside this local sample's threat model.

Release previews are exact public payloads. Their `X-Preview-Digest` header can be submitted as `preview_digest` to bind a UI decision to that payload. A current valid release with unchanged scope is idempotent. A changed release/preference invalidates approvals and pending reservations. Owner-authored corrections persist across restart and withdraw dependent offers. Failed transmissions remain in a durable owner-to-broker outbox; state polling retries exact signed messages.

Approval fetches the immutable proposal directly from the broker, verifies both digests, independently checks the confirmed task catalog, assignments, private allowlist/calendar/windows, capacity and between-task travel, then signs the exact manifest and conditional compensation policy. Prepare requires this exact locally stored approval before consulting private constraints. It obtains a durable five-minute reservation and monotonically increasing fence. Every fresh or resumed transmission rechecks the current grant, approval, proposal, revisions, key, lease, fence and calendar preconditions.

The dispatch authorization point is the vault transaction that persists the action's fenced intent. Withdrawal and calendar-send scheduling serialize under the owner executor lock. The explicit `pause_before_send` fixture commits that intent and returns before transmission, allowing withdrawal and process restart in the gap. Withdrawal cancels unsent actions and conditionally recovers existing effects. An already transmitted operation cannot be recalled atomically.

Calendar event IDs are deterministic from action IDs. A timeout after a real write produces AMBIGUOUS, and reconciliation reads that event before any possible retry. Events are verified against actual storage. `/coordination/events` only observes and updates receipts; it never resends or deletes. Missing or changed verified entries become NEEDS_ATTENTION. Compensation deletes only an unchanged event covered by the signed policy. User-edited text stays private, while remaining-effect identifiers and times can be reported to the coordinator. `/coordination/cancel` also releases a partially prepared reservation, preventing it from blocking the next proposal.

Fault modes are labeled authored fixtures: failure before write, timeout after write, pause before send, and conflict before write. `/api/calendar/{event_id}/edit` is a local user-edit fixture. The authenticated owner calendar export uses `icalendar` for escaping, UTC timestamps, CRLF and Unicode-safe line folding. No Google Calendar connection, real calendar or outbound invitation is involved.

If an edited event blocks compensation, its owner can explicitly remove that local event after reviewing its current summary/time and confirming the irreversible decision. `POST /api/calendar/{event_id}/remove` requires the private owner session, exact owner Origin, current `expected_etag`, and `confirmation: "remove-this-local-event"`. A stale ETag preserves the entry; service capabilities cannot use this route. A durable encrypted `calendar_resolutions` record precedes the conditional calendar deletion. The public action receipt reveals only the resolution ID, kind and times. Subsequent reconciliation confirms absence and permits closing the old agreement. This explicit owner operation does not broaden automatic compensation's authority.
