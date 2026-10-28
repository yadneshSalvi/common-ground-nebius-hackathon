# Methodology and claim limits

Common Ground v2 is an authored local demonstration of living agreements. The care recipient, owners, shared goals, private memories and decisions are fictional. A local operator can play each role. This work is not a participant study, an independently administered household trial, or evidence of improved coordination or clinical outcomes.

The [living contract](LIVING_CONTRACT.md) defines v2. The original v1 behavior, [sanitized proof](../evidence/sample-proof.json), [verification result](../evidence/sample-proof.verification.json) and [validation record](../evidence/validation.json) remain historical evidence. No v1 signature authorizes v2 execution.

## What is authored, proposed, reviewed and observed

The fictional entry creates an authored starting arrangement through the normal local consent and calendar path. It labels those initial decisions as sample decisions. Public sample sessions exist only in explicitly configured fictional profiles, require the exact service Origin, and issue that service's own limited session. The broker never receives owner browser credentials.

The optional authored carry-forward policy is off by default. Existing owner memory, policy, history and edits are retained when another sample starts. A carry-forward policy is a distinct reviewed, revocable owner choice. It permits a fresh attestation only when the owner's content, direct counterpart bindings, recipients, complete required coverage and cancellation scope are unchanged. A policy attestation is not a new exact review of the whole document. New or changed responsibilities always need exact review.

A shared goal contains 2–6 registered participants and 2–12 responsibilities. A local form or an explicitly disclosed provider extraction creates a draft. The coordinator reviews the complete subject, dates, timezone, durations, windows, places, named dependencies, directional travel facts and supporting source quotes. Missing critical facts remain unresolved. Goal confirmation establishes reviewed shared facts, not owner offers or consent.

Only reviewed public offers and the shared request can reach the selected inference provider. Fireworks and Nebius grants are separate. Private memory content, private reasons and unrelated calendar text stay owner-local. There is no silent provider fallback. A provider response is untrusted: the solver produces assignments from released authority, a separate checker verifies hard constraints, and owners independently validate their own exact content and direct handoff bindings.

The flagship disruption withdraws Ravi's return while retaining his pickup. A permitted question can ask Leena about the uncovered return; it cannot turn Asha's exclusion into driving. Leena reviews a return conditional on Asha receiving by 16:15. Asha's direct counterpart changes, so her fresh consent is required even with an unchanged handoff interval. An exact approved delta requests only its listed calendar mutations. Retained event identity and original creation provenance are immutable. A partial sequence is never Active.

Offers, commitments, calendar readbacks and human-reported completion remain distinct. A signed readback is evidence tied to an owner key and an observed app-created entry. It does not establish that a person arrived, a handoff happened, or a private assertion was true. Expiry and unavailable observation turn current-looking information historical or unconfirmed. Browser session loss stops unauthenticated polling and requires re-entry.

## Private structured memory and request scope

Owners explicitly review structured capability exclusions, weekly capacity, request permissions, handoff deadlines and named-receiver requirements. Rules carry provenance, scope, revision and optional expiry. Unconfirmed suggestions have no effect. A separate note is private context and is never released as a reason.

Correction and deletion affect subsequent applicable decisions and dependent authority. Deletion removes the content while retaining a content-free deletion receipt. Request permission and refusal are separate from willingness to undertake a task. A refusal suppresses further requests in its scope until a fresh explicit invitation is accepted. Questions have a bounded per-disruption budget. Retained questions from earlier goals or disruptions are history, not current accepted progress.

## Reproducible validation

```sh
npm test
npm run build
npm run format:check
npm run test:living-ui
LIVING_QA_SAMPLE=1 LIVING_QA_FULL=1 npm run test:living-ui
LIVING_QA_APPROVAL=1 npm run test:living-ui
```

The offline suite covers strict schemas, signatures and canonicalization, replay and expiry, origin/capability separation, goal graphs, solver/checker constraints, scoped withdrawal and refusal, exact review and policy scope, durable authorization/fences, readback observations and selective persistent calendar effects. Controlled interruption and concurrency fixtures are authored tests, not measurements of production failure rates.

The living browser harness uses actual running browser origins and local services. The explicit full mode creates a fictional sample, keeps carry-forward policies off, withdraws only Ravi's return, reviews Leena's conditional offer, obtains exact owner reviews, applies the selective delta and compares the retained pickup's event ID and ETag. It also exercises memory creation/correction/deletion, checks that an authored private note is absent from broker evidence, and injects a browser session-expiry response to verify historical display and polling cessation. Missing-fact review and responsive layouts are inspected with Playwright and axe. Outputs are under `test-results/living/`.

A separate in-app-browser review can inspect the running product and downloads. These are development reviews; neither automated axe checks nor a second development reviewer establishes VoiceOver/NVDA usability, participant comprehension, independent owner administration or human benefit. Use the generated reports for actual scope and outcomes rather than copying a transient test total into this document.

The completed [independent browser acceptance](living-iab-development-qa.json) used two actual Nebius calls, fresh provider-specific releases and exact reviews by all three authored owner roles. It observed one calendar insert and one delete, no updates, and an unchanged pickup ID/ETag; ACTIVE survived the final corrected runtime restart. A separate disposable actual-browser fixture verified exact signed approval confirmation and its invalidation under changed agreement or authority, without touching the main runtime or a provider. Its [seven-check report](../evidence/living-approval-ui-review.json) distinguishes injected state changes from real signed consent.

Final integration review exposed and fixed a memory revision reset: clearing invalidated live offers had reset the next public offer revision. Retained per-goal release history now supplies only the monotonic counter; revoked permissions remain revoked. The regression exercises correction, a newly released scope, bounded help, a replacement offer, exact consent and an ACTIVE selective repair. Another regression covers add/correct/delete across restart with increasing revisions.

Actual provider validation is deliberately separate from ordinary tests:

```sh
.venv/bin/python scripts/living_validation.py --provider fireworks
.venv/bin/python scripts/living_validation.py --provider nebius
```

These commands make external inference calls using authored fictional inputs and separate local stores. Owner HTTP transports in this script are in-process; calendar effects are persistent local SQLite operations. The script tests the conditional repair and a newly parsed, explicitly reviewed goal with a different structure. It does not reproduce container isolation, real Google accounts or external people.

Generated v2 qualification results are in [living-validation.json](../evidence/living-validation.json), with all actual attempts in the [v2 provider ledger](../evidence/living-provider-usage.json). The original v1 provider ledger remains unchanged. Actual Nebius Ultra completed the conditional repair and new two-owner, three-responsibility, two-date semantic goal after explicit authored review. The first Nebius repair tried to restore a withdrawn assignment; strict validation rejected it without amendment writes. The revised prompt explicitly lists current eligible owners and withdrawn assignments, passed Fireworks first, and then passed Nebius. Both attempts remain in the ledger. The first Fireworks workflow harness also failed after three valid completions because it incorrectly required `meal` instead of permitting the reviewed `preparation` capability; that failed workflow and its valid receipts remain separate from later successes.

Retained receipts are the authority for provider/model identity, exact request/settings, prompt revision, timing, known usage and success or failure. A configured route, HTTP 200, historical v1 success or a mocked response does not qualify another workflow. The separate reasoning-content field is excluded; bounded final content and failed structured decisions remain available.

`scripts/evaluate_living.py` freezes and evaluates 180 authored scheduling cases: 60 development and 120 validation cases from one deterministic generator. Four structures cover 2–6 owners, 2–12 responsibilities, conditions, parallel subjects, optional work and two dates. An exhaustive ordinary-Python fixed-time oracle labels full-authority feasibility separately from attainability with the released offers and no permission for further questions. CP-SAT is the strong no-model comparator. All 180 cases agreed, including 24 globally infeasible and 30 information-limited cases. The corpus, digest, source hashes, every assigned outcome and limits are retained in [living-planning-validation.json](../evidence/living-planning-validation.json). This is shared-generator authored validation, not independently authored or sealed held-out evaluation. It does not cover every flexible-time schedule, private-memory fault or runtime failure; those have separate protocol/integration tests. It establishes no model advantage or human workload reduction.

Unknown usage remains unknown rather than zero. Cost figures, when reported, are labeled estimates using the recorded accounting basis. Failed or cancelled transmissions remain in the receipt history; a cancellation does not erase an attempt or make uncertain transmission impossible. Model reasoning text is not a substitute for a verified response contract.

## Portable proof and offline verification

The shared record view downloads sanitized v2 evidence and `verify_living_evidence.py`. The standalone verifier needs Python, `cryptography` and `rfc8785`, with no project imports, private keys, database or network:

```sh
.venv/bin/python scripts/verify_living_evidence.py path/to/common-ground-living-evidence.json
# The downloaded script also runs outside this checkout:
python verify_living_evidence.py common-ground-living-evidence.json
```

The proof retains reviewed goals, immutable agreement revisions and deltas, signed releases/consents/withdrawals/refusals, owner-signed observations, actual provider receipts and mutation history. It excludes private rule content and notes, unrelated event text or edited date/time/location, private signing keys, browser/session/service capabilities and environment credentials. Verification checks historical integrity, signatures and exact scope against the included owner keys. Current ACTIVE claims require the owning signer's latest exported observation, exact revision/consent identity and current authority, and verified current intents plus cancelled removed effects. Superseded observations and historical receipts cannot satisfy a newer claim. Verify owner identity through an independent trusted channel before treating those keys as identities. A copied snapshot cannot prove that later records were not omitted or authorize present execution, and a valid record does not prove attendance. Source hashes describe files at export time, not historical process bytes.

The credential-free `?recorded=1` viewer serves the unchanged original sanitized v1 snapshot with an explicit historical label. `?legacy=1` retains the original interactive source and owner surfaces with launcher pairing. Original v1 prompt revisions, failed attempts and evidence are not rewritten as v2 successes.

The [actual IAB proof](../evidence/living-iab-proof.json) and downloaded verifier were copied outside the repository into a fresh environment with only the pinned `cryptography` and `rfc8785` dependencies. The positive copy passed. Eight altered copies, each with a recomputed outer digest, were rejected: changed top-level goal, handoff counterpart, ETag, missing owning observation, historical receipt replay, stale signed head, forged observation time and forged current revision. [Results](../evidence/living-iab-proof.verification.json) and the fixed-fixture instructions in `scripts/verify_living_root_controls.py` preserve the exact scope; this does not turn the evidence into an independent identity authority.

Legacy validation remains available through `npm run test:ui`, `npm run test:live`, `scripts/live_validation.py --offline` and `scripts/verify_evidence.py`. Its finite authored oracle scenarios and retained solver regressions are development coverage, not a sealed household benchmark. Its round replacement/compensation workflow is distinct from v2's stable commitments and selective amendments.

## Runtime and calendar limits

The [isolated runtime](isolated-runtime.md) uses actual unprivileged containers, separate persistent stores/config mounts, disjoint owner networks and constrained capabilities. Stateless ingress exposes each owner's browser origin, and only the broker has inference egress and provider credentials. Runtime-boundary probes must run against the actual final image; configuration files alone do not establish the result. These boundaries remain under **one host administrator** and do not establish independently administered users, devices or households. The ordinary-process launcher has the weaker trusted-process boundary.

The [calendar adapter notes](calendar-adapters.md) define the actual effect semantics. The sample uses separate SQLite calendars. The optional Google Calendar v3 connector is covered by controlled HTTP-transport tests; it does not obtain OAuth authorization, connect a real account or qualify Google's live service. No real Google calendar effect is claimed.

Mutation authority is persisted before I/O, and ambiguous outcomes remain durable for readback. Conditional updates and removals require the observed version and unchanged app-created content. Loss of access is unconfirmed, not absence. User-edited v2 entries are preserved and require manual owner resolution. The release does not automatically re-adopt or remove them, so edited-event interruption is not an automatic recovery success. Legacy removal controls do not change that v2 limitation.

No external calendar atomicity, immediate recall of an already transmitted request, deployed latency percentile, guaranteed attendance, human workload reduction, clinical impact, participant pilot, interview result or independent security audit is established. Released information cannot be undisclosed. Authored local evidence should be reported within these limits.
