# Reproducible local evidence

The current living-agreement evidence is separate from the unchanged accepted v1 JSON files below:

- `living-validation.json`: measured offline, browser, actual-provider and runtime scope, with remaining limits.
- `living-provider-usage.json`: all actual v2 attempts, including failures, full permitted requests, validated responses and known/unknown accounting. Regenerate from existing JSON exports with `scripts/collect_living_evidence.py`; add a sanitized runtime export with `--runtime-proof` to include independent browser requests. This command makes no provider calls.
- `living-scripted-proof.json` and its verification result: fresh readback from the persisted stores of the successful real Nebius workflow; original inference requests and decisions are unchanged. The workflow used in-process service HTTP and actual separate local calendar stores.
- `living-planning-corpus.json` and `living-planning-validation.json`: frozen authored 60/120 partitions, independent fixed-time feasibility labels and strong no-model baseline results. One generator authored both partitions; this is not a sealed or independently authored benchmark.
- `living-ui-review.json`: authored browser workflow, privacy/expiry checks and responsive/accessibility findings. Independent in-app-browser acceptance and actual isolation evidence are identified separately in the final validation manifest.
- `living-approval-ui-review.json`: seven narrow actual-browser checks using a separate disposable local owner fixture, including real signed approval and injected stale/mismatching contexts; no main-runtime or provider calls.
- `living-iab-proof.json` and `living-iab-proof.verification.json`: actual UI-downloaded evidence from the independent in-app-browser Nebius run and outside-checkout positive/eight rehashed negative controls. The narrative and screenshots are in `docs/living-iab-development-qa.json`.

```sh
.venv/bin/python scripts/verify_living_evidence.py evidence/living-scripted-proof.json
.venv/bin/python scripts/evaluate_living.py
```

The downloaded v2 verifier runs outside the checkout with only Python, `cryptography` and `rfc8785`. Owner-key signatures and exact current authority/readback are verified, not independent human identity, physical attendance, completeness of a copied historical log or real Google OAuth. Private stores, secrets, user-edited calendar details and private notes are excluded. Actual isolation is under one host administrator.

## Preserved v1 record

`sample-proof.json` is a sanitized snapshot of the authored interactive sample. Its historical offers, exact approvals, failed/successful actual Fireworks attempts, model requests, assignments and recovery observations are retained. It is development evidence, not a held-out benchmark or participant study.

```sh
.venv/bin/python scripts/verify_evidence.py evidence/sample-proof.json
.venv/bin/python scripts/export_proof.py
npm test
```

The export script reads the private local broker pairing code without printing it, fetches the allowlisted proof, scans configured credentials/capabilities, and verifies it before writing. It never reads owner notes or signing keys. The proof's source hashes describe files at export time, not historical process bytes. Historical provider requests retain their exact prompt revision/settings.

`sample-proof.verification.json` reports offline signature/hash/constraint checks. `validation.json` records measured local test/browser results and their scope. Existing sessions, vaults, pairing links, private notes and owner screenshots remain in ignored runtime/test directories and are excluded from this folder.

The v1 local adapter has real separate persistent event stores; fault modes are deliberately injected. This historical record does not claim a real calendar account, external participant study, deployment or Nebius qualification. Current v2 Nebius evidence is listed separately above.
