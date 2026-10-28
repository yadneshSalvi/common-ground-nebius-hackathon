"""Stateless fixed-upstream ingress for one isolated owner, never the broker.

No volume, service capability, provider key, redirects, CONNECT or arbitrary URL
forwarding. This only makes an internal owner service reachable on its loopback
browser port; owner authentication and exact-Origin checks stay in that service.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx

HOP = {"host", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "content-length", "content-encoding"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", choices=("asha", "ravi", "leena"), required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    target = f"http://{args.owner}:{args.port}"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def forward(self):
            if not self.path.startswith("/") or self.path.startswith("//"):
                self.send_error(400)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400)
                return
            if length < 0 or length > 1024 * 1024 or self.headers.get("Transfer-Encoding"):
                self.send_error(413)
                return
            body = self.rfile.read(length) if length else None
            headers = {key: value for key, value in self.headers.items() if key.lower() not in HOP and not key.lower().startswith("x-forwarded-")}
            try:
                with httpx.Client(follow_redirects=False, timeout=90, trust_env=False) as client:
                    response = client.request(self.command, target + self.path, headers=headers, content=body)
                content = response.content
                if len(content) > 16 * 1024 * 1024:
                    self.send_error(502)
                    return
                self.send_response(response.status_code)
                for key, value in response.headers.items():
                    if key.lower() not in HOP:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(content)
            except (httpx.HTTPError, BrokenPipeError, ConnectionResetError):
                self.close_connection = True
                try:
                    self.send_error(502, "Owner service unavailable")
                except OSError:
                    pass

        do_GET = do_HEAD = do_POST = do_OPTIONS = forward

    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
