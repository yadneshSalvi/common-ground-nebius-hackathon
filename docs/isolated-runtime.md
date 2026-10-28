# Local runtime isolation

The original trusted-process sample and its historical store remain available with `npm start`. It is not hostile same-UID isolation. For a new explicitly fictional profile, `scripts/run_isolated.py` runs the broker and three owners as unprivileged containers. Each has its own persistent data volume and read-only config volume. The source image contains only an allowlist of application files and the built owner UI; no checkout, host directory, Docker socket or parent `.env` is mounted.

Each owner service has a separate internal network to the broker, with no owner-to-owner network or public TCP egress. Docker internal networks do not publish browser ports in the tested engine. A separate stateless ingress container for each owner therefore connects its own internal network to its own ingress network and exposes the loopback browser port. It has no volumes, config or credentials, forwards only to its fixed owner, and does not follow redirects or support arbitrary upstreams/CONNECT. The broker never handles owner browser sessions. The broker has those three networks plus its own inference egress network. Only the broker receives the allowlisted provider keys, in its own read-only config volume. Owner pairing secrets do not enter broker configuration. All published ports bind to `127.0.0.1`. Containers have read-only roots, no Linux capabilities, no privilege escalation, bounded memory/CPU/PIDs and small temporary filesystems.

These are stronger local boundaries under **one host administrator**. They are not independent owner accounts/devices, a hostile kernel escape audit, or a deployed security claim. The local sample operator can intentionally switch among the fictional owner roles. Public sample entry is enabled only by the explicit `--fictional-sample` provision flag; existing non-sample profiles cannot be silently converted. Fictional initial setup is a deliberate exception: a narrowly scoped sample endpoint applies authored initial decisions, never real-owner consent or amendment approval. Its gate and exact scope are tested separately. Existing histories and user edits are retained.

## Run

Build both interfaces first with `npm run build`. Select an existing Linux Docker context explicitly. On this development Mac the dedicated `colima-passage` context already exists; the launcher never changes the default context.

```sh
.venv/bin/python scripts/run_isolated.py \
  --context colima-passage \
  --profile cg-living \
  --runtime .runtime/isolated-living \
  --fictional-sample --build
```

Ports 4301, 4302 and 4311–4313 must be free. The launcher refuses to take them from another process. It removes only the containers/networks it created on shutdown. Persistent named volumes, local profile configuration and prior evidence remain. Do not remove those volumes to reset a demo; create a new named profile/runtime when a fresh installation is needed.

The Python base image is pinned by digest; Python packages use exact lockfile versions. The launcher records the final image ID. Image builds require package registry access. Runtime owner containers do not receive that access.

## Check actual boundaries

```sh
.venv/bin/python scripts/check_isolation.py \
  --manifest .runtime/isolated-living/runtime-manifest.json \
  --output docs/isolated-runtime-development-qa.json
```

This inspects the actual mounts, network membership and resource constraints, then checks from each running process that configs are read-only, private stores are disjoint, owners cannot resolve one another or make a public TCP connection, and broker service capabilities cannot read owner private APIs. Results must be generated from a running final image; merely having the script is not a qualification result.
