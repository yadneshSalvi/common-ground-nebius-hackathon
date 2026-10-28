"""Trusted local launcher. Pairing material stays outside broker ownership."""
import argparse
import json
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]

def save_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, indent=2))
    path.chmod(0o600)

def provision(runtime=None):
    runtime = Path(runtime or ROOT / ".runtime").resolve()
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime.chmod(0o700)
    config_path = runtime / "config.json"
    if config_path.exists():
        return config_path
    ingest, coordinator_pair = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
    peers, links = [], {"broker": "http://127.0.0.1:4301/#pair=" + coordinator_pair}
    for owner_id, port in (("asha", 4311), ("ravi", 4312), ("leena", 4313)):
        directory = runtime / "owners" / owner_id
        pairing, service = secrets.token_urlsafe(32), secrets.token_urlsafe(40)
        config = {"owner_id": owner_id, "port": port, "broker_url": "http://127.0.0.1:4302", "broker_ingest_token": ingest, "service_token": service, "pair_code": pairing, "data_dir": str(directory), "dist_dir": str(ROOT / "dist" / "owner")}
        save_private(directory / "config.json", config)
        peers.append({"id": owner_id, "url": f"http://127.0.0.1:{port}", "service_token": service})
        links[owner_id] = f"http://127.0.0.1:{port}/#pair=" + pairing
    save_private(config_path, {"data_dir": str(runtime / "broker"), "origin": "http://127.0.0.1:4301", "pair_code": coordinator_pair, "broker_ingest_token": ingest, "owners": peers})
    save_private(runtime / "pairing-links.json", links)
    return config_path

def wait_ready(url, process):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("A service exited during startup; read its terminal error.")
        try:
            if httpx.get(url, timeout=1).is_success:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.15)
    raise RuntimeError("A service did not become ready in 40 seconds.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provision-only", action="store_true")
    args = parser.parse_args()
    config = provision()
    print("Private launch links: " + str(ROOT / ".runtime" / "pairing-links.json"), flush=True)
    print("Pair each owner once. The shared room never receives owner pairing codes.", flush=True)
    if args.provision_only:
        return
    if not all((ROOT / "dist" / name / "index.html").exists() for name in ("owner", "broker")):
        raise SystemExit("Build both interfaces first: npm run build")
    for port in (4301, 4302, 4311, 4312, 4313):
        with socket.socket() as check:
            if check.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is occupied. Stop only that Common Ground process first.")
    children = []
    def stop(*_):
        for process in children:
            if process.poll() is None:
                process.terminate()
        for process in children:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    signal.signal(signal.SIGTERM, lambda *args: (stop(), sys.exit(0)))
    signal.signal(signal.SIGINT, lambda *args: (stop(), sys.exit(0)))
    try:
        for owner_id, port in (("asha", 4311), ("ravi", 4312), ("leena", 4313)):
            process = subprocess.Popen([sys.executable, "-m", "owner_agent", "--config", str(ROOT / ".runtime" / "owners" / owner_id / "config.json")], cwd=ROOT)
            children.append(process)
            wait_ready(f"http://127.0.0.1:{port}/health", process)
        process = subprocess.Popen([sys.executable, "-m", "broker", "--config", str(config)], cwd=ROOT)
        children.append(process)
        wait_ready("http://127.0.0.1:4302/health", process)
        process = subprocess.Popen(["node", "node_modules/vite/bin/vite.js", "preview", "--host", "127.0.0.1", "--port", "4301", "--strictPort"], cwd=ROOT)
        children.append(process)
        wait_ready("http://127.0.0.1:4301/", process)
        print("Common Ground ready: shared room http://127.0.0.1:4301; owner services4311–4313", flush=True)
        while all(process.poll() is None for process in children):
            time.sleep(1)
    finally:
        stop()

if __name__ == "__main__":
    main()
