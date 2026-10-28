# Living agreements v2 — implementation contract

28 October 2026. This is the implemented-work contract for the local upgrade, not a claim of external calendar qualification or a human study. V1 remains explicitly legacy and its authored evidence is preserved. No v1 signature authorizes v2 work.

## Ownership

- Lead: `shared/living.py`, `shared/protocol.py`, `broker/living*.py`, `broker/app.py`, broker/solver/checker/provider/export tests and evidence.
- Owner worker: `owner_agent/living.py`, owner engine/app/storage, owner tests. Do not edit calendar or connector modules.
- UI worker: `web/`, `owner-web/`, public assets and frontend configuration/QA.
- Root: `owner_agent/calendar.py`, `owner_agent/living_calendar.py`, connector modules, runtime/isolation/launcher scripts and their tests; independent in-app-browser acceptance. No worker commits.

## Generalized reviewed goal

`Goal` has `schema_version:2,goal_id,revision,title,description,timezone,participants:[owner_id],subject,source_text,tasks,routes,confirmed_at,confirmed_by`.
There are 2–6 registered participants and 2–12 tasks. `confirmed_by` is the coordinator's explicit local review, not invented owner approval. Goal confirmation precedes any owner offer or enactment. A goal draft has a separate identity and never establishes confirmed facts.

Task: `{task_id,label,capability,date,duration,earliest,latest,start_location,end_location,predecessors,required,subject,source_quote}`. Capability is preparation/driving/accompaniment/handoff/meal/visit. Times are integer local minutes on the task's explicit ISO date; latest is latest END. Source quote must occur in the reviewed source. All critical facts appear in the editable review. No missing date, duration, location or journey duration is silently filled by inference. Routes `{from_location,to_location,duration,source_quote}` are directional confirmed inputs; same-location travel is zero. No route between distinct places means unknown, not an invented 40 minutes. Dates, timezones, acyclic dependencies, subject continuity and reachable transfers are checked independently of model prose. Same-subject, same-day responsibilities require a reviewed dependency order; the independent checker also checks occupancy/location across all selected responsibilities. Nonexistent or ambiguous wall times and goals spanning UTC-offset changes are rejected before consent; separate reviewed goals are required on either side of a clock change.

## Stable commitments and deltas

Agreement: `{schema_version:2,agreement_id,revision,base_revision,goal,goal_digest,commitments,intents,delta,created_at,expires_at,checker,model_receipt_id,explanation}`. The first revision has base_revision 0. A competing amendment must match the current base exactly.

Commitment: `{commitment_id,task_id,owner_id,date,timezone,start,end,start_location,end_location,capability,label,subject,dependencies,conditions,offer_id,offer_revision}`. Identity is stable for the same agreement/task/owner. Dependency entries bind the direct predecessor AND successor task's commitment ID, owner, date, interval and locations. Complete required coverage is an explicit consent invariant. A changed handoff counterpart changes the dependency digest even if the owner's event is unchanged. No private-memory rule ID, private note, or hash of a private reason enters this object.

`delta` contains `retained,changed,new,withdrawn` commitment IDs, `affected_owners`, `approval_required`, and `calendar_mutations`. Calendar mutations are `{mutation_id,kind:'insert'|'update'|'delete',owner_id,commitment_id,action_id,event_id,intent|null,expected_etag|null}`. Retained unchanged intents cause no mutation. Old calendar creation provenance remains immutable. A partial mutation sequence is never ACTIVE. V2 records calendar effects, not physical performance; the flagship takes place before the responsibilities start. Calendar deletion cannot undo a journey already performed.

## Root-owned calendar interface

New `owner_agent.living_calendar.LivingCalendarStore(path)` leaves the legacy `CalendarStore` untouched. Interface:

- `event_id_for(action_id: str) -> str`: provider-valid deterministic ID; no agreement revision in the input.
- `intended(intent: dict) -> dict`: normalized exact public app-created content.
- `get(event_id) -> dict|None`, `list() -> list[dict]`: current observed state; an unavailable read raises, not absence.
- `insert(intent) -> dict`: exact idempotent insert; collisions with different content fail.
- `update_if_unchanged(event_id, expected_etag, intent) -> tuple[bool,dict|None]`: current ETag and unedited predicate required; conflicts preserve observed content.
- `delete_if_unchanged(event_id, expected_etag) -> tuple[bool,dict|None]`: absence is success; version conflict preserves content.
- `edit(event_id, summary) -> dict`: local authored user-edit fixture only.

Calendar intent: `{schema_version:2,action_id,commitment_id,owner_id,task_id,event_id,label,date,timezone,start,end,location:{start,end},creation:{agreement_id,revision,created_at}}`. Normalized stored content uses the same keys. Observation adds opaque `etag` and `user_edited`. Creation refers to the first inserted event and must not change when a later agreement retains/updates it. An external adapter may have additional provider metadata, but owner comparison uses only `intended` fields and the observed ETag. Edited summary/text is never sent to broker/model. Google adapter tests alone do not qualify real OAuth/accounts.

Owner receipt: `{mutation_id,commitment_id,action_id,event_id,status,etag,verified_at,error?,intent_id?,fence?,transmitted_at?,remaining_effect?}`. Status is VERIFIED/CANCELLED/AMBIGUOUS/PAUSED/FAILED/NEEDS_ATTENTION/UNCONFIRMED. For delete, CANCELLED means observed absence. Readback is required; lost access is UNCONFIRMED. `remaining_effect` contains only event/action/commitment IDs in this implementation, never edited text, date, time or location. The owner persists authority before I/O, retains uncertain intents over restart and rechecks current revision/fence/expiry immediately before sending. A before-send pause fixture remains testable. Preserved edited entries need manual owner resolution; v2 does not automatically re-adopt or remove them.

## Signed v2 messages and owner state

Existing canonical Ed25519 envelope gains schema_version 2 and message types LivingRelease, LivingConsent, LivingWithdrawal, LivingRefusal, LivingObservation. Circle is `dev-circle` for this fictional installation; membership is the registered owner set, never a model-created key. New types use v2 only. Every recipient/revision/expiry/nonce/key check remains mandatory. V1 signatures cannot be reused.

LivingRelease payload: `{goal_id,goal_revision,goal_digest,offer_id,offer_revision,owner_id,constraint_revision,task_ids,windows,conditions,recipients,request_categories,expires_at}`. Windows are `{date,start,end}`; conditions are `{task_id,receiver_id,by,receiver_task_id}` and mean receiver_task_id must be assigned to receiver_id and end by the deadline on the offered task's date. Recipients `{humans:[registered IDs],broker:'common-ground-broker',inference:['fireworks'|'nebius']}` are exact; provider grants never carry across routes. A public counter-offer is reviewed before release. Source private memory/provenance stays private.

LivingConsent payload: `{agreement_id,revision,base_revision,agreement_digest,goal_digest,owner_id,consent_revision,constraint_revision,commitment_digests,dependency_digests,mutation_ids,execution_not_after,compensation_policy:'unchanged-app-created-only',basis:'exact-review'|'standing-policy',policy_revision}`. Maps cover the owner's exact commitments in this revision and include direct dependency hashes; mutation IDs cover only that owner's new/changed/removed effects. `policy_revision` is null for exact review. A standing policy is explicit, revocable and owner-local. It permits a fresh attestation only if own content, direct counterpart/dependencies, recipients, complete required coverage and compensation scope are unchanged. No policy means exact review. New/changed commitments always require review. Never claim all owners signed the revised document if some supplied standing-policy attestations.

LivingWithdrawal payload: `{agreement_id,base_revision,goal_id,owner_id,commitment_ids,consent_revision}`. Withdraw only listed commitments, with no reason. A fresh release excludes withdrawn tasks but may retain pickup. A signed refusal is `{goal_id,request_id,owner_id,task_id,consent_revision}` with no reason. One refusal per scope suppresses further requests unless a new explicit invitation is accepted. Default question budget is 3 per disruption.

LivingObservation payload: `{agreement_id,owner_id,receipts,authorities,observed_at}`. The owner reads its own calendar and derives each authority entry `{revision,agreement_digest,consent_message_id|null,authority_current,withdrawn_commitment_ids}` from its own reviewed agreement, consent, release, key/policy/constraint/expiry state. Callers cannot supply observations or signatures. Entries bind the exact locally consented revision; withdrawn IDs are intersected with that revision's own commitments. This permits the enacted and pending revision to coexist without conflating their authority. A matching calendar entry with revoked consent is not current authority. Broker observations are fenced against agreement identity, revision generation and observation order. An old read cannot overwrite a newer agreement, receipts or timestamp.

Portable evidence includes explicit current/pending agreement references, withdrawal scope, latest signed owner/agreement observation heads and their history. The standalone verifier checks current ACTIVE against exact consent IDs, current authority and readback for all current intents and deleted effects. It rejects superseded observation heads, historical receipt substitution, another owner's readback, changed counterpart bindings and forged current timestamps. The timestamp is the oldest required signed observation, not a newly invented export time. A copied historical snapshot cannot prove that later events were not omitted or authorize current execution. Signing identities still require independent verification.

Owner-local living state includes reviewed goals, per-goal offers, per-agreement commitments/approvals, structured memories, request permissions/refusals, carry-forward policy, durable requests/reservations/mutation outbox and fictional status. Structured memory types: excluded_capability, weekly_capacity, request_category, handoff_deadline, require_receiver. Memory has ID, revision, provenance, created/updated timestamps, scope, expiry and optional private note. Correct/delete operations change the next decision and invalidate only affected authority; deletion removes content, retaining only a content-free deletion receipt. Unconfirmed suggestions cannot affect offers. No private-memory inference is needed.

## Routes frozen for frontend integration

Shared routes use existing broker bearer/session and Origin protections. `GET /api/v2/state` returns `{schema_version:2,revision,sample,goal,draft,owners,offers,agreement,pending,commitments,receipts,questions,history,model_runs,provider,planning,status,observed_at,limits}`. `pending` is the proposed full revision or null. `agreement` is the enacted revision or null. `commitments` are current view rows with covered/withdrawn/pending status, not another authoritative contract.

- `POST /api/v2/goal/draft {source_text,provider:'fireworks'|'nebius'|'local',allow_inference:boolean}`: explicit disclosure of the shared request only; live semantic parse is asynchronous with retained receipt. Local is a structured form, never an imitation model parse.
- `POST /api/v2/goal/confirm {goal,expected_revision}`: accepts reviewed complete graph; all registered members can inspect it.
- `POST /api/v2/plan {provider:'fireworks'|'nebius'|'local',expected_revision}`: plan or amendment from current reviewed offers. Actual provider must have every included owner's current grant. No fallback.
- `POST /api/v2/cancel {expected_revision}`: cancels the current model/planning attempt; never erases receipts or revokes an enacted agreement.
- `POST /api/v2/execute {agreement_id,revision}` and `POST /api/v2/reconcile {agreement_id,revision}`: exact version only.
- `GET /api/v2/evidence`: sanitized portable record; recorded legacy evidence separately accessible. `GET /api/v2/verifier` downloads its self-contained offline verifier.

Owner routes use existing private bearer and exact owner Origin:

- `GET /api/v2/state`: `{owner,sample,revision,memories,policy,goals,offers,requests,agreement,pending,receipts,calendar_events,coordinator_available,consent_revision,constraint_revision}`.
- `POST /api/v2/memory {expected_revision,memory}`; `POST /api/v2/memory/{memory_id}/delete {expected_revision}`.
- `POST /api/v2/policy {expected_revision,enabled,expires_at}`.
- `GET /api/v2/offer-preview?goal_id=...&provider=fireworks|nebius|none`: exact release plus private memory explanation in a separate private field; only release is signed.
- `POST /api/v2/release {goal_id,provider:'fireworks'|'nebius'|'none',preview_digest,expected_revision}`.
- `POST /api/v2/approve {agreement_id,revision,agreement_digest}`.
- `POST /api/v2/withdraw {agreement_id,base_revision,commitment_ids,expected_revision}`.
- `POST /api/v2/refuse {request_id,expected_revision}`; no public reason.

Owner coordination routes carry only the owner's narrow service capability and reject browser Origin:

- `GET /coordination/v2/status?goal_id=...`: current public grant, revisions/key status; no private rules.
- `POST /coordination/v2/goal {goal}`: save reviewed goal after independently validating shape/source; not owner consent.
- `POST /coordination/v2/question {request}`: respect local permission/refusal/budget; only public accepted/declined metadata returns.
- `POST /coordination/v2/attest {agreement}`: only explicit valid standing policy; otherwise returns needs_review, never auto-approves.
- `POST /coordination/v2/prepare {agreement,consent}` -> `{reservation_id,fence,lease_expires_at}`.
- `POST /coordination/v2/dispatch {agreement_id,revision,mutation_id,reservation_id,fence}` and `/reconcile` with same body.
- `GET /coordination/v2/events?agreement_id=...`: public receipts plus exact signed LivingObservation, no event summaries or edited timing.

Owner-to-broker uses `/v2/releases`, `/v2/consents`, `/v2/withdrawals`, `/v2/refusals` with `{message}`; GET `/v2/current` and `/v2/agreements/{agreement_id}/{revision}` returns `{agreement,pending,goal}` or exact agreement. Ingest and owner-service capabilities never gain interactive authority.

## Fictional entry and claims

Root's launcher must explicitly set `fictional_sample:true` before any public sample session/bootstrap endpoint exists. New owner `/sample/session` and broker `/sample/session` accept exact same-service UI Origin only and mint authority solely for fictional stores. They cannot be enabled on real-owner configs. Broker never receives owner sessions. UI opens the chosen owner origin, which pairs with its own fictional service. Starting a new sample must keep earlier evidence/history and must not clear private memory or delete user edits. A fresh fictional initial arrangement can use explicit authored sample decisions, clearly labeled; real approvals remain on owner surfaces. The exception independently reconstructs and checks the fixed sample source/shape and exact first revision; it cannot sign a custom goal or amendment. Optional sample policy is off unless deliberately selected, and retry cannot re-enable a revoked owner policy.

All UI counts come from persisted actual decisions/mutations. Session or observation expiry turns status historical; stop unauthenticated polling. Calendar verification never means a person arrived. No interviews, household impact, independent administrators, external OAuth or deployed results may be claimed from local authored tests.
