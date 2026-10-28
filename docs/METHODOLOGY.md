# Methodology and claim limits

This is an authored local product demonstration, not a participant study or evidence of improved clinical/coordination outcomes. The three owners, Dev, calendar data and November2 appointment are fictional. No real calendars, mail or medical records are accessed.

## What is authored, proposed, solved and approved

The confirmed input supplies five responsibilities, fixed appointment windows, durations and locations. Owner-local preferences supply candidate task scopes, broad availability and explicit burden weights. Offers are generated from those structured preferences only when the owner releases them; unrelated private conflicts remain local.

Nemotron uses released information to compare alternatives, suggest one owner per responsibility and explain tradeoffs. Its suggestion is a search hint and the last lexicographic tie-breaker, after preservation, explicit burden and travel. A model suggestion may differ from the final solved allocation. The UI identifies it as a proposed tradeoff.

OR-Tools CP-SAT assigns owners and intervals. A separate ordinary-Python checker verifies coverage, scope, duration, availability, precedence, capacity and travel. Each owner then privately validates its exact actions. Signatures prove integrity/key possession, not truth. Only persisted event state independently read back from each local calendar counts as a verified effect.

## Reproducible validation

- `npm test` is offline. It exercises signatures/canonicalization, replay and lost acknowledgments, expiry/revocation, strict origins and cross-owner capabilities, private canaries, exact-version approval, persistence, reservations/fences, concurrent withdrawal, real SQLite effects, ambiguous-write reconciliation, conditional compensation and ICS parsing.
- The solver oracle suite independently enumerates legal integer starts and assignments across 26 finite authored five-task scenarios, comparing feasibility and the exact four-part objective. It includes alternatives, missing capabilities, precedence, capacity, travel, infeasibility, UNKNOWN under a zero search budget, model-only ties, checker tampering and a real preference correction. These are not sealed held-out households or a general planning benchmark.
- The oracle exposed a real defect: the first implementation counted transfer costs in earliest-window order even when actual task order reversed. Temporal successor circuits replaced that assumption. The failing regression is retained.
- `npm run test:ui` pairs production browser origins using the private launch file, visits shared/private views at 1440/1024/768/390/320 widths, runs axe rules, tests zoom/overflow, checks runtime errors/cookies and reopens roles. This does not establish VoiceOver/NVDA usability or participant comprehension.
- `npm run test:live` explicitly makes real Fireworks inference in isolated local stores. Its service HTTP transports are in-process, while model transport is external and calendar effects are real independent SQLite entries. The main interactive sample is untouched. `--offline` checks the same script without inference.
- A separate orchestrator uses the in-app browser and actual loopback HTTP endpoints to inspect the live product, fault/replanning flow, exports and privacy. This is independent development review, not a user study.

Runtime receipts preserve unsuccessful model attempts. The first actual v1 request returned HTTP200 with valid model identity but failed the strict response contract; the public suggestion schema had not described all fields later enforced locally. v2 replaced the generic dictionary with a typed suggestion object and completed an actual proposal. v3 asks for friendly names, HH:mm times and clearly tentative prose. Historical receipts and proposal text retain their original prompt revision; they are not rewritten to look like later successes.

## Proof and accounting

The downloadable proof includes public signing keys, signed protocol history, immutable proposals, actual model request/settings/usage/outcomes, disclosure records, historical action receipts/closed rounds, fresh calendar observation and source hashes. It excludes private vault data, notes, source pointers, signing keys, pairing/session/service capabilities and environment credentials. Each payload uses canonical SHA-256 for corruption detection. `scripts/verify_evidence.py` independently verifies hashes, historical signatures, proposal/manifest binding and assignment constraints without network access.

The proof is not a standalone trusted identity authority: verify owner fingerprints through an independent channel. Historical signature verification at issuance does not authorize present execution. The source hashes describe files at export time, not earlier historical process bytes; actual provider request bodies and prompt revisions describe each historical invocation.

Only actual reported provider usage is counted. Fireworks cost is an explicitly labeled uncached-input estimate at $0.60 input/$2.40 output per million tokens. Unknown usage remains unknown, not zero. These are accounting rates, not a development spending cap. No development Nebius completions occur; final Nebius Ultra qualification is pending. No model comparison or efficacy advantage is claimed from these few development attempts.

## Remaining limitations

The service boundary is a trusted-process local demonstration, not hostile same-UID filesystem isolation or an independently administered multi-device deployment. No Google OAuth/calendar integration or cloud deployment is implemented. Local transport is loopback HTTP. External calendar atomicity and immediate recall of in-flight writes are not promised.

Already released availability carries metadata/inference risk and cannot be undisclosed. There is no information-theoretic privacy score or automatic additional-disclosure probing policy; owners manually review changes. No interviews, participant pilot, workload reduction, clinical outcome, deployed latency percentile or assistive-technology study has been completed. The authored scenario and bounded test results should not be promoted into those claims.
