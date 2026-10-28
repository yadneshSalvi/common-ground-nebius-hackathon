"""Persistent local container profile with disjoint owner stores and networks.

Only this profile's labeled containers/networks are removed on exit. Persistent
volumes and previous evidence remain. Docker context is always explicit; the
user's default context is never modified. Provider credentials enter only the
broker's read-only config volume, through stdin rather than process arguments.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time

from dotenv import dotenv_values
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import ROOT, provision, save_private

OWNER_PORTS = {"asha": 4311, "ravi": 4312, "leena": 4313}
PROVIDER_KEYS = ("FIREWORKS_AI_API_KEY", "FIREWORKS_API_KEY", "NEBIUS_API_KEY", "TOGETHER_API_KEY", "TOGETHER_AI_API_KEY")
INIT = """import json,os,pathlib,sys
p=json.load(sys.stdin)
d=pathlib.Path('/data');d.mkdir(exist_ok=True);os.chown(d,1000,1000);d.chmod(0o700)
c=pathlib.Path('/config');c.mkdir(exist_ok=True);os.chown(c,1000,1000);c.chmod(0o700)
f=c/'service.json'
encoded=json.dumps(p['config'],sort_keys=True,indent=2)
if f.exists() and json.loads(f.read_text()) != p['config']:
 old=json.loads(f.read_text());migrated=json.loads(f.read_text())
 # One presentation-only migration: add loopback browser URLs to the broker
 # peer registry. Service URLs, keys, scopes, ownership and state cannot change.
 ports={'asha':4311,'ravi':4312,'leena':4313}
 for peer in migrated.get('owners',[]):
  if peer.get('id') in ports and 'browser_url' not in peer:peer['browser_url']='http://127.0.0.1:'+str(ports[peer['id']])
 if migrated != p['config']:raise SystemExit('Existing immutable profile config differs; choose a new profile')
 backup=c/'service.before-browser-url.json';backup.write_text(json.dumps(old));os.chown(backup,1000,1000);backup.chmod(0o400)
f.write_text(encoded);os.chown(f,1000,1000);f.chmod(0o400)
if p.get('provider') is not None:
 f=c/'provider.env';f.write_text(p['provider']);os.chown(f,1000,1000);f.chmod(0o400)
"""


def docker(context, *args, stdin=None, timeout=90):
    result = subprocess.run(["docker", "--context", context, *args], input=stdin, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        # Command arguments never contain credentials. Avoid including stdin.
        raise RuntimeError(f"Docker {args[0]} failed: {result.stderr.strip()[:1200]}")
    return result.stdout.strip()


def configs(runtime, *, fictional_sample):
    config_path = provision(runtime, fictional_sample=fictional_sample)
    broker = json.loads(config_path.read_text())
    broker.update(data_dir="/data", env_path="/config/provider.env", allowed_hosts=["127.0.0.1", "localhost", "broker"])
    for peer in broker["owners"]:
        peer["url"] = f'http://{peer["id"]}:{OWNER_PORTS[peer["id"]]}'
        peer["browser_url"] = f'http://127.0.0.1:{OWNER_PORTS[peer["id"]]}'
    owners = {}
    for owner in OWNER_PORTS:
        item = json.loads((runtime / "owners" / owner / "config.json").read_text())
        item.update(data_dir="/data", dist_dir="/app/dist/owner", broker_url="http://broker:4302", origin=f"http://127.0.0.1:{OWNER_PORTS[owner]}", allowed_hosts=["127.0.0.1", "localhost", owner])
        owners[owner] = item
    return {"broker": broker, **owners}


def profile_plan(profile, image):
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,40}", profile):
        raise ValueError("Profile must use 3–41 lowercase letters, numbers or hyphens")
    services = {}
    for name, port in {"broker": 4302, **OWNER_PORTS}.items():
        container = profile + "-" + name
        network = profile + ("-egress" if name == "broker" else "-" + name + "-private")
        config_volume, data_volume = container + "-config", container + "-data"
        argv = ["create", "--name", container, "--label", "common-ground.profile=" + profile, "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=1000:1000", "--pids-limit=96", "--memory=" + ("768m" if name == "broker" else "384m"), "--cpus=1", "--tmpfs=/tmp:rw,noexec,nosuid,size=64m,uid=1000,gid=1000", "--network", network, "--network-alias", name, *(["--publish", f"127.0.0.1:{port}:{port}"] if name == "broker" else []), "--mount", f"type=volume,src={config_volume},dst=/config,readonly", "--mount", f"type=volume,src={data_volume},dst=/data", image, "--kind", "broker" if name == "broker" else "owner", "--port", str(port)]
        services[name] = {"container": container, "network": network, "config_volume": config_volume, "data_volume": data_volume, "argv": argv}
    return services


def provider_file(env_path):
    values = dotenv_values(env_path) if env_path.exists() else {}
    # JSON-quoted values are valid dotenv strings; no shell interpolation occurs.
    return "".join(key + "=" + json.dumps(os.environ.get(key) or values[key]) + "\n" for key in PROVIDER_KEYS if os.environ.get(key) or values.get(key))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--profile", default="cg-living")
    parser.add_argument("--image", default="common-ground-runtime:v2")
    parser.add_argument("--runtime", type=Path, default=ROOT / ".runtime" / "isolated-living")
    parser.add_argument("--provider-env", type=Path, default=ROOT.parent / ".env")
    parser.add_argument("--fictional-sample", action="store_true")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    services = profile_plan(args.profile, args.image)
    runtime = args.runtime.resolve()
    if not (ROOT / "dist" / "owner" / "index.html").exists():
        raise SystemExit("Build the reviewed interfaces first: npm run build")
    for port in (4301, 4302, 4311, 4312, 4313):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is occupied. Stop only its Common Ground service before starting this profile.")
    docker(args.context, "info", "--format", "{{.ServerVersion}}", timeout=10)
    if args.build:
        build = subprocess.run(["docker", "--context", args.context, "build", "-f", str(ROOT / "scripts/isolated-runtime.Dockerfile"), "-t", args.image, str(ROOT)])
        if build.returncode:
            raise SystemExit("Runtime image build failed")
    image_id = docker(args.context, "image", "inspect", args.image, "--format", "{{.Id}}")
    configs_by_name = configs(runtime, fictional_sample=args.fictional_sample)
    networks, containers, ingresses, web = [], [], {}, None
    def stop(*_):
        if web is not None and web.poll() is None:
            web.terminate()
            try:
                web.wait(timeout=5)
            except subprocess.TimeoutExpired:
                web.kill()
        for container in reversed(containers):
            try:
                docker(args.context, "rm", "-f", container, timeout=15)
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
        for network in reversed(networks):
            try:
                docker(args.context, "network", "rm", network, timeout=15)
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
    signal.signal(signal.SIGTERM, lambda *_: (stop(), sys.exit(0)))
    signal.signal(signal.SIGINT, lambda *_: (stop(), sys.exit(0)))
    try:
        for name, service in services.items():
            options = ["--internal"] if name != "broker" else []
            docker(args.context, "network", "create", "--label", "common-ground.profile=" + args.profile, *options, service["network"])
            networks.append(service["network"])
            for volume in (service["config_volume"], service["data_volume"]):
                docker(args.context, "volume", "create", "--label", "common-ground.profile=" + args.profile, volume)
            payload = {"config": configs_by_name[name], "provider": provider_file(args.provider_env) if name == "broker" else None}
            docker(args.context, "run", "--rm", "-i", "--network=none", "--user=0:0", "--entrypoint=python", "--mount", f'type=volume,src={service["config_volume"]},dst=/config', "--mount", f'type=volume,src={service["data_volume"]},dst=/data', image_id, "-c", INIT, stdin=json.dumps(payload))
            argv = [image_id if arg == args.image else arg for arg in service["argv"]]
            container_id = docker(args.context, *argv)
            containers.append(container_id)
        for owner in OWNER_PORTS:
            docker(args.context, "network", "connect", "--alias", "broker", services[owner]["network"], services["broker"]["container"])
        for owner, port in OWNER_PORTS.items():
            network = args.profile + "-" + owner + "-ingress"
            docker(args.context, "network", "create", "--label", "common-ground.profile=" + args.profile, network)
            networks.append(network)
            name = args.profile + "-" + owner + "-ingress"
            cid = docker(args.context, "create", "--name", name, "--label", "common-ground.profile=" + args.profile, "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=1000:1000", "--memory=96m", "--cpus=0.5", "--pids-limit=64", "--tmpfs=/tmp:rw,noexec,nosuid,size=8m,uid=1000,gid=1000", "--network", network, "--publish", f"127.0.0.1:{port}:{port}", "--entrypoint=python", image_id, "-m", "scripts.owner_ingress", "--owner", owner, "--port", str(port))
            containers.append(cid)
            docker(args.context, "network", "connect", services[owner]["network"], cid)
            ingresses[owner] = {"container": name, "network": network, "owner_network": services[owner]["network"], "scope": "Stateless fixed-owner ingress; no volumes, credentials or broker session handling"}
        for container in containers:
            docker(args.context, "start", container)
        deadline = time.monotonic() + 60
        pending = {name: (4302 if name == "broker" else OWNER_PORTS[name]) for name in services}
        while pending and time.monotonic() < deadline:
            for name, port in list(pending.items()):
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).is_success:
                        pending.pop(name)
                except httpx.HTTPError:
                    pass
            if pending:
                time.sleep(0.2)
        if pending:
            raise RuntimeError("Container startup did not become healthy: " + ", ".join(pending))
        web = subprocess.Popen(["node", "node_modules/vite/bin/vite.js", "preview", "--host", "127.0.0.1", "--port", "4301", "--strictPort"], cwd=ROOT)
        save_private(runtime / "runtime-manifest.json", {"profile": args.profile, "context": args.context, "image_id": image_id, "fictional_sample": args.fictional_sample, "services": {name: {k: v for k, v in service.items() if k != "argv"} for name, service in services.items()}, "ingresses": ingresses, "scope": "Disjoint containers, volumes and owner networks under one local host administrator; not independently administered devices."})
        print("Isolated Common Ground ready at http://127.0.0.1:4301; fictional sample: " + str(args.fictional_sample), flush=True)
        print("Persistent volumes retain all history. Profile metadata: " + str(runtime / "runtime-manifest.json"), flush=True)
        while web.poll() is None:
            time.sleep(1)
            for container in containers:
                if docker(args.context, "inspect", container, "--format", "{{.State.Running}}", timeout=5) != "true":
                    raise RuntimeError("A profile service stopped; inspect its labeled container logs")
    finally:
        stop()


if __name__ == "__main__":
    main()
