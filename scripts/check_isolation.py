"""Read-only qualification of one running, explicitly named local profile.

This checks tested container/filesystem/network boundaries. It is not a hostile
kernel escape audit or evidence of independently administered owner devices.
"""
import argparse
from datetime import datetime, timezone
import json
import socket
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_isolated import docker

OWNER_PROBE = r'''
import json,os,pathlib,socket
config=json.loads(pathlib.Path('/config/service.json').read_text())
checks={
 'unprivileged_uid':os.getuid()==1000,
 'read_only_config':not os.access('/config/service.json',os.W_OK),
 'own_data_writable':os.access('/data',os.W_OK),
 'provider_file_absent':not pathlib.Path('/config/provider.env').exists(),
 'host_repository_absent':not pathlib.Path('/Users').exists(),
 'docker_socket_absent':not pathlib.Path('/var/run/docker.sock').exists(),
 'no_provider_env':not any(k for k in os.environ if 'API_KEY' in k or 'TOKEN' in k or 'SECRET' in k),
 'config_has_no_other_owner_registry':'owners' not in config,
}
for peer in ('asha','ravi','leena'):
 if peer==config['owner_id']:continue
 try:socket.getaddrinfo(peer,4311);checks['cannot_resolve_'+peer]=False
 except socket.gaierror:checks['cannot_resolve_'+peer]=True
try:
 s=socket.create_connection(('1.1.1.1',443),timeout=1);s.close();checks['no_public_tcp_egress']=False
except OSError:checks['no_public_tcp_egress']=True
print(json.dumps(checks))
'''
BROKER_PROBE = r'''
import json,os,pathlib,httpx
config=json.loads(pathlib.Path('/config/service.json').read_text())
checks={'unprivileged_uid':os.getuid()==1000,'read_only_config':not os.access('/config/service.json',os.W_OK),'broker_provider_file_present':pathlib.Path('/config/provider.env').exists(),'host_repository_absent':not pathlib.Path('/Users').exists(),'docker_socket_absent':not pathlib.Path('/var/run/docker.sock').exists()}
for owner in config['owners']:
 with httpx.Client(timeout=5,trust_env=False) as c:
  r=c.get(owner['url']+'/api/v2/state',headers={'Authorization':'Bearer '+owner['service_token']})
 checks[owner['id']+'_service_cannot_read_private_api']=r.status_code in (401,403)
 checks[owner['id']+'_pairing_not_in_broker_config']='pair_code' not in owner
print(json.dumps(checks))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    context = manifest["context"]
    report = {"recorded_at": datetime.now(timezone.utc).isoformat(), "profile": manifest["profile"], "image_id": manifest["image_id"], "scope": "Actual local container/process/network checks; authored development evidence, one host administrator, no kernel escape audit or independent households.", "services": {}}
    all_volumes = []
    for name, service in manifest["services"].items():
        raw = json.loads(docker(context, "inspect", service["container"]))[0]
        mounts = raw["Mounts"]
        networks = raw["NetworkSettings"]["Networks"]
        cfg = raw["HostConfig"]
        runtime = {"read_only_root": cfg["ReadonlyRootfs"] is True, "all_capabilities_dropped": "ALL" in cfg["CapDrop"], "no_privilege_escalation": "no-new-privileges" in cfg["SecurityOpt"], "not_privileged": not cfg["Privileged"], "no_host_mount": all(m["Type"] == "volume" for m in mounts), "only_two_own_mounts": len(mounts) == 2 and {m["Name"] for m in mounts} == {service["config_volume"], service["data_volume"]}, "config_mount_readonly": any(m["Destination"] == "/config" and not m["RW"] for m in mounts), "expected_networks": len(networks) == (4 if name == "broker" else 1), "bounded_memory_pids": 0 < cfg["Memory"] <= 805306368 and cfg["PidsLimit"] == 96, "loopback_published_ports": all(entry["HostIp"] == "127.0.0.1" for values in (cfg["PortBindings"] or {}).values() for entry in values)}
        all_volumes.extend(m["Name"] for m in mounts)
        probe = BROKER_PROBE if name == "broker" else OWNER_PROBE
        actual = json.loads(docker(context, "exec", service["container"], "python", "-c", probe, timeout=20))
        report["services"][name] = {"runtime": runtime, "actual_process_checks": actual, "passed": all(runtime.values()) and all(actual.values())}
    report["ingresses"] = {}
    for owner, ingress in manifest.get("ingresses", {}).items():
        raw = json.loads(docker(context, "inspect", ingress["container"]))[0]
        cfg = raw["HostConfig"]
        checks = {"no_volumes": raw["Mounts"] == [], "unprivileged": raw["Config"]["User"] == "1000:1000", "read_only_root": cfg["ReadonlyRootfs"] is True, "all_capabilities_dropped": "ALL" in cfg["CapDrop"], "no_privilege_escalation": "no-new-privileges" in cfg["SecurityOpt"], "only_own_networks": set(raw["NetworkSettings"]["Networks"]) == {ingress["network"], ingress["owner_network"]}, "fixed_owner_command": raw["Config"]["Cmd"] == ["-m", "scripts.owner_ingress", "--owner", owner, "--port", str({"asha":4311,"ravi":4312,"leena":4313}[owner])], "loopback_published_ports": all(entry["HostIp"] == "127.0.0.1" for values in (cfg["PortBindings"] or {}).values() for entry in values)}
        port = {"asha":4311,"ravi":4312,"leena":4313}[owner]
        requests = {
            "absolute_upstream_rejected": (b"GET http://example.com/ HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n", b"400"),
            "connect_tunnel_rejected": (b"CONNECT example.com:443 HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n", b"501"),
            "oversized_body_rejected": (b"POST /api/v2/memory HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 1048577\r\nConnection: close\r\n\r\n", b"413"),
        }
        for key, (request, expected) in requests.items():
            with socket.create_connection(("127.0.0.1",port),timeout=3) as connection:
                connection.sendall(request)
                status = connection.recv(200).split(b"\r\n")[0].split()
            checks[key] = len(status) >= 2 and status[1] == expected
        report["ingresses"][owner] = {"checks": checks, "passed": all(checks.values())}
    report["disjoint_volumes"] = len(set(all_volumes)) == len(all_volumes)
    report["passed"] = report["disjoint_volumes"] and all(item["passed"] for item in report["services"].values()) and len(report["ingresses"]) == 3 and all(item["passed"] for item in report["ingresses"].values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "services": {k: v["passed"] for k, v in report["services"].items()}, "output": str(args.output)}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
