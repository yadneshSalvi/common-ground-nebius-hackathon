# Common Ground

**Make a plan together. Keep your private reasons yours.**

A complete local coordination product for three fictional personal agents. Asha, Ravi and Leena release bounded offers, compare an appointment plan, approve exact calendar effects, and recover when plans change. The shared room sees released facts; preferences and signing screens live on separate owner services.

## Run locally

Requires Node 22 and Python 3.11. No Docker, cloud resource or real calendar account is needed.

```sh
uv venv --python 3.11 .venv
uv pip sync --python .venv/bin/python requirements.lock
npm ci
npm run build
npm start
```

The supervisor runs the shared room at `http://127.0.0.1:4301`, released-data API 4302, and private owner services 4311–4313. It preserves `.runtime/` across restarts. Stop with Ctrl+C; do not delete runtime state to recover an interrupted write.

Open the local launch URLs in `.runtime/pairing-links.json` once for the broker and each owner. This private generated file is never served by the broker. The `#pair` fragment is removed immediately and exchanged for a one-hour bearer session. Each origin stores only its own session and expiry; **Lock workspace** clears that browser session. No cookies carry authority between ports. Use `127.0.0.1` consistently.

The fictional operator may switch all roles. This is a trusted-process sample: hostile same-UID code and the OS administrator are out of scope. Separate processes and encrypted vault fields do not create independent OS-user/device isolation.

## Complete walkthrough

1. Open each owner’s workspace. Review exact offered facts and recipients. Circle sharing and Fireworks inference permission are separate choices. Confirm each release.
2. In the shared room, request live Nemotron planning or the labeled local structured workflow. Circle-only releases work locally and block remote inference.
3. Review the actual timeline. Leena also offers return driving and handoff, so alternatives are real. The model suggests; OR-Tools solves hard constraints and lexicographic objectives; a separate checker verifies.
4. Each affected owner reviews the exact proposal version and calendar manifest, including conditional cancellation of unchanged app-created events. Their agent privately rechecks current preferences, conflicts and travel before signing.
5. Apply the agreement. Each independent local calendar persists and verifies its own events. Download an owner/agreement ICS and portable proof JSON.
6. For recovery, set Ravi’s labeled **timeout after write** fixture before applying. An event exists while the result is ambiguous. Restart the supervisor, clear the fault and reconcile: the deterministic event is found rather than duplicated.
7. Change Asha’s availability to end before 16:00, release the corrected offer, safely close the previous round and request another plan. Leena can take handoff. Every new version needs fresh approval. Withdrawn driving can leave pickup uncovered; the product does not invent an offer.

User-edited events remain **Needs attention** during automatic compensation. Only their owner may explicitly review/remove them. Withdrawal stops future use; pending/existing effects need reconciliation. It cannot recall information already disclosed.

## Model configuration and verification

The server reads `FIREWORKS_AI_API_KEY` from parent `../.env` or the server environment. Never copy real credentials into source. The qualified development route is NVIDIA `accounts/fireworks/models/nemotron-3-ultra-nvfp4` on Fireworks, high reasoning, 32,000 output tokens, 480-second timeout, prompt schema and strict local validation. Exact request/settings, usage, provider identity and failed attempts are retained. The separate `reasoning_content` field is excluded; final content may still contain unexpected diagnostic prose.

The declared final Nebius Ultra route remains pending completion qualification and disabled for development. No silent fallback exists. Private preferences use structured local forms; raw notes/calendar titles never reach inference.

```sh
npm test                        # offline protocol/owner/solver/oracle/full-cluster suite
npm run test:ui                 # read-only browser+axe checks on running production services
npm run test:live               # actual Fireworks request in isolated fictional stores
.venv/bin/python scripts/live_validation.py --offline
.venv/bin/python scripts/verify_evidence.py path/to/common-ground-proof.json
```

`test:live` leaves the main sample untouched. It uses in-process owner/broker HTTP transports, real separate SQLite calendars and actual Fireworks inference. Normal tests make no paid calls. Browser QA reuses cached Playwright Chromium.

See [protocol/threat model](docs/PROTOCOL.md), [methodology/claims](docs/METHODOLOGY.md), and [asset licenses](public/assets-manifest.json).

This release has no real Google Calendar integration, external participant study, deployment, distributed isolation, medical workflow or clinical/efficiency outcome claim. It genuinely creates/verifies/modifies local events. Fault injection is labeled. Feasibility means current released-offer plus private checks, not guaranteed attendance.

Runtime vaults, keys, local plans, pairing/session capabilities and private QA evidence are ignored. Public proof is constructed from released data, scanned against canaries/configured credentials, and verified offline for canonical hashes, Ed25519 signatures, exact manifests and assignment validity. Signing fingerprints still need an independent trusted identity channel.
