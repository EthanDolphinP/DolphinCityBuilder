"""Preview local frontend changes against the hosted game (no local game state)."""

import argparse
import json
import game
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
API_PATHS = {"/api/login", "/api/state", "/api/action", "/api/visit", "/api/leaderboard"}
UPSTREAM = "https://mangoclaw119.pythonanywhere.com"


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Do not log city names, tokens, or passwords.

    def reply(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def handle_request(self):
        # Bind only to loopback and reject foreign Host/Origin headers.
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            return self.reply(403, b'{"error":"Use the local preview address."}')
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{host}" for host in hosts}:
            return self.reply(403, b'{"error":"Foreign origins are not allowed."}')
        path = self.path.split("?", 1)[0]
        if self.command == "GET" and path == "/":
            return self.reply(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path not in API_PATHS:
            return self.reply(404, b'{"error":"Not found."}')
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.reply(400, b'{"error":"Invalid request size."}')
        if not 0 <= length <= 10000:
            return self.reply(413, b'{"error":"Request too large."}')
        body = self.rfile.read(length) if self.command == "POST" else None
        headers = {"Content-Type": "application/json"}
        if self.headers.get("X-Token"):
            headers["X-Token"] = self.headers["X-Token"]
        request = Request(UPSTREAM + self.path, data=body, headers=headers, method=self.command)
        try:
            with urlopen(request, timeout=25) as response:
                payload = response.read()
                # Derive new display metrics locally from the returned snapshot only.
                # The hosted city and its saved state are never changed here.
                if path in {"/api/state", "/api/action", "/api/visit", "/api/login"}:
                    data = json.loads(payload)
                    if "state" in data and "status" in data:
                        if "food_potential" not in data["status"]:
                            data["status"]["food_potential"] = game.view(data["state"], data.get("area", 0))["status"]["food_potential"]
                        if "unpaused_rates" not in data["status"] or "unpaused_power" not in data["status"]:
                            projection = game.unpaused_projection(data["state"])
                            data["status"].setdefault("unpaused_power", projection["power"])
                        if "unpaused_rates" not in data["status"]:
                            projected = projection["rates"]
                            current = game.view(data["state"], data.get("area", 0))["status"]["rates"]
                            # Preserve hosted bill income/costs in the projection.
                            data["status"]["unpaused_rates"] = {
                                k: round(v + data["status"]["rates"][k] - current[k], 1)
                                for k, v in projected.items()
                            }
                        payload = json.dumps(data).encode()
                self.reply(response.status, payload, response.headers.get("Content-Type", "application/json"))
        except HTTPError as error:
            if error.code >= 500:
                self.reply(error.code, json.dumps({"error": f"Live server returned HTTP {error.code}. Try again shortly."}).encode())
            else:
                self.reply(error.code, error.read(), error.headers.get("Content-Type", "application/json"))
        except (URLError, TimeoutError, OSError):
            self.reply(502, b'{"error":"Could not reach the live server. Try again shortly."}')

    do_GET = handle_request
    do_POST = handle_request


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18744)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), PreviewHandler)
    print(f"Local UI: http://127.0.0.1:{args.port}", flush=True)
    print(f"Live game: {UPSTREAM} (actions affect real cities)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
