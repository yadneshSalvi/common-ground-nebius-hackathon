# Reproducible local evidence

`sample-proof.json` is a sanitized snapshot of the authored interactive sample. Its historical offers, exact approvals, failed/successful actual Fireworks attempts, model requests, assignments and recovery observations are retained. It is development evidence, not a held-out benchmark or participant study.

```sh
.venv/bin/python scripts/verify_evidence.py evidence/sample-proof.json
.venv/bin/python scripts/export_proof.py
npm test
```

The export script reads the private local broker pairing code without printing it, fetches the allowlisted proof, scans configured credentials/capabilities, and verifies it before writing. It never reads owner notes or signing keys. The proof's source hashes describe files at export time, not historical process bytes. Historical provider requests retain their exact prompt revision/settings.

`sample-proof.verification.json` reports offline signature/hash/constraint checks. `validation.json` records measured local test/browser results and their scope. Existing sessions, vaults, pairing links, private notes and owner screenshots remain in ignored runtime/test directories and are excluded from this folder.

The local adapter has real separate persistent event stores; fault modes are deliberately injected. No real calendar account, external participant study, deployment or final Nebius Ultra qualification is claimed.
