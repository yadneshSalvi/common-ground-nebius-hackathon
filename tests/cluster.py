"""Full HTTP protocol cluster with in-process transport; no external inference."""
import httpx
from fastapi.testclient import TestClient
from owner_agent.app import create_app as owner_app
from broker.app import create_app as broker_app

class Cluster:
    def __init__(self, directory):
        self.clients, self.apps, self.configs, self.tokens = {}, {}, {}, {}
        self.drop_ack = False
        self.ingest = "test-ingest-capability-" + "x" * 32
        self.transport = httpx.MockTransport(self.route)
        peers = []
        for index, owner in enumerate(("asha", "ravi", "leena")):
            port = 4311 + index
            config = {"owner_id": owner, "port": port, "broker_url": "http://127.0.0.1:4302", "broker_ingest_token": self.ingest, "service_token": f"test-service-{owner}-" + "s" * 32, "pair_code": f"test-pair-{owner}-" + "p" * 32, "data_dir": str(directory / owner), "broker_transport": self.transport}
            self.configs[owner] = config
            self.apps[owner] = owner_app(config)
            self.clients[port] = TestClient(self.apps[owner], base_url=f"http://127.0.0.1:{port}")
            peers.append({"id": owner, "url": f"http://127.0.0.1:{port}", "service_token": config["service_token"]})
        config = {"data_dir": str(directory / "broker"), "pair_code": "test-coordinator-pair-" + "b" * 32, "broker_ingest_token": self.ingest, "owners": peers, "owner_transport": self.transport, "env_path": str(directory / "no-env")}
        self.broker_config = config
        self.app = broker_app(config)
        self.engine = self.app.state.engine
        self.clients[4302] = TestClient(self.app, base_url="http://127.0.0.1:4302")
        self.broker_token = self.clients[4302].post("/api/session", headers={"Origin": "http://127.0.0.1:4301"}, json={"pair_code": config["pair_code"]}).json()["token"]
        for owner, config in self.configs.items():
            self.tokens[owner] = self.clients[config["port"]].post("/api/session", headers={"Origin": self.origin(owner)}, json={"pair_code": config["pair_code"]}).json()["token"]

    def route(self, request):
        response = self.clients[request.url.port].request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
        if self.drop_ack and request.url.path == "/v1/releases":
            self.drop_ack = False
            assert response.status_code == 200
            raise httpx.ReadTimeout("Injected response loss after broker commit", request=request)
        return httpx.Response(response.status_code, headers=dict(response.headers), content=response.content)

    def origin(self, owner):
        return f"http://127.0.0.1:{self.configs[owner]['port']}"

    def headers(self, owner=None):
        return {"Origin": self.origin(owner) if owner else "http://127.0.0.1:4301", "Authorization": "Bearer " + (self.tokens[owner] if owner else self.broker_token)}

    def op(self, path, body=None, owner=None):
        client = self.clients[self.configs[owner]["port"] if owner else 4302]
        return client.request("GET" if body is None else "POST", path, headers=self.headers(owner), json=body)

    def state(self):
        response = self.op("/api/state")
        assert response.status_code == 200, response.text
        return response.json()

    def release_all(self, inference=True):
        for owner in self.configs:
            response = self.op("/api/release", {"expected_revision": 1, "allow_inference": inference}, owner)
            assert response.status_code == 200, response.text

    def plan(self):
        response = self.op("/api/plan", {"mode": "local", "expected_revision": self.state()["revision"]})
        assert response.status_code == 202, response.text
        state = self.state()
        assert state["proposal"], state["planning"]
        return state["proposal"]

    def approve(self, proposal):
        for owner in {a["owner_id"] for a in proposal["actions"]}:
            response = self.op("/api/approve", {"proposal_id": proposal["proposal_id"], "expected_version": proposal["version"]}, owner)
            assert response.status_code == 200, response.text

    def enact(self, proposal):
        response = self.op("/api/execute", {"proposal_id": proposal["proposal_id"], "expected_version": proposal["version"]})
        assert response.status_code == 200, response.text
        return response.json()
