"""Disposable browser bridge to a real in-process authored protocol cluster.

No loopback service ports are contacted: Cluster's HTTPX transport dispatches
owner/broker calls to TestClients. Only this temporary browser port is bound.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import signal
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_living_integration import living_cluster, proposed_repair

with tempfile.TemporaryDirectory(prefix="cg-approval-browser-") as directory:
    cluster = living_cluster(Path(directory))
    _, repaired = proposed_repair(cluster)
    client = cluster.clients[4313]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path == "/__qa/report":
                state = cluster.app.state.living.store.read()
                body = json.dumps({"model_attempts": len(state["model_runs"]), "pending_revision": state["pending"]["revision"], "owner_signed_approval_present": "leena" in state["consents"], "transport": "In-process TestClients; no root runtime sockets"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.forward()

        def do_POST(self):
            self.forward()

        def forward(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "connection", "content-length"}}
            response = client.request(self.command, self.path, headers=headers, content=body)
            self.send_response(response.status_code)
            for key, value in response.headers.items():
                if key.lower() not in {"content-length", "transfer-encoding", "connection", "content-encoding"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    origin = f"http://127.0.0.1:{server.server_port}"
    # The actual owner middleware accepts this disposable browser origin.
    # Internal coordination remains on the in-process transport.
    cluster.configs["leena"]["origin"] = origin
    print(json.dumps({"url": origin, "pair_code": cluster.configs["leena"]["pair_code"], "revision": repaired["pending"]["revision"]}), flush=True)

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        for local_client in cluster.clients.values():
            local_client.close()
