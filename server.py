"""LAN web server for the text city builder.

Run:  python server.py [port]
Then open the address it prints from any device on the same network.
Uses only the Python standard library.

To run it on a web host instead, point the host at wsgi.py (see README.md).
Both ways go through respond() below.

Cities are kept in memory while the server runs and written to saves/ after
every action and about once a minute while anyone is playing. Cities keep working while nobody is watching:
the time since a city was last looked at is simulated the next time it is
needed (including after the server has been off).

Each city has a password. Signing in gives the browser a token, which it sends
with every request. Only a salted hash of the password and hashes of the
tokens are stored, in the city's save file, and neither is ever sent out.
If someone forgets theirs, stop the server and run
    python server.py --reset-password CityName
and whoever signs in to that city next chooses its new password.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import game
import market

ROOT = Path(__file__).parent
SAVES = ROOT / "saves"
MARKET_FILE = ROOT / "market.json"
CITY_NAME = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
BAD_NAME = "City names are 1-24 letters, digits, - or _."
AUTOSAVE_SECONDS = 60
MAX_BODY = 10_000                # bytes of request body read

PRIVATE = ("auth", "sessions")   # parts of a save that never leave the server
MIN_PASSWORD, MAX_PASSWORD = 4, 100
MAX_SESSIONS = 10                # browsers that can stay signed in to one city
LOCKOUT_TRIES, LOCKOUT_SECONDS = 5, 30
SIGN_IN = {"error": "Sign in to this city first.", "auth": True}

LOCK = threading.Lock()   # guards everything below
CITIES = {}               # name -> state
DIRTY = set()             # names changed since the last write to disk
MARKET = None
FAILED = {}               # name -> [wrong passwords in a row, locked until]
LAST_SAVE = 0             # when everything was last written to disk


def _write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def get_city(name, now, create=False):
    """The city brought up to the present moment, or None if it doesn't exist."""
    state = CITIES.get(name)
    if state is None:
        path = SAVES / f"{name}.json"
        if path.exists():
            state = game.migrate(json.loads(path.read_text(encoding="utf-8")), now)
        elif create:
            state = game.new_game(name, now)
        else:
            return None
        CITIES[name] = state
    game.advance_time(state, now)
    DIRTY.add(name)
    return state


def _password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000).hex()


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def set_password(state, password):
    salt = secrets.token_hex(16)
    state["auth"] = {"salt": salt, "hash": _password_hash(password, salt)}


def signed_in(state, token):
    """True if `token` was issued for this city and is still valid."""
    return bool(state and token and _token_hash(token) in state.get("sessions", []))


def login(name, password, now):
    """Sign in to a city, creating it (or giving it its first password) if need be.

    Returns (http status, reply).
    """
    if not isinstance(name, str) or not CITY_NAME.match(name):
        return 400, {"error": BAD_NAME}
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        return 400, {"error": f"Passwords are {MIN_PASSWORD} to {MAX_PASSWORD} characters."}
    tries = FAILED.setdefault(name, [0, 0])
    if now < tries[1]:
        return 429, {"error": f"Too many wrong passwords. Try again in {int(tries[1] - now) + 1} seconds."}

    state = get_city(name, now)
    reply = {}
    if state is None:
        state = get_city(name, now, create=True)
        set_password(state, password)
        reply["created"] = True
    elif "auth" not in state:       # a city from before passwords: first to sign in claims it
        set_password(state, password)
        reply["claimed"] = True
    elif not hmac.compare_digest(_password_hash(password, state["auth"]["salt"]), state["auth"]["hash"]):
        tries[0] += 1
        if tries[0] >= LOCKOUT_TRIES:
            tries[:] = [0, now + LOCKOUT_SECONDS]
        return 403, {"error": "Wrong password for that city."}
    FAILED.pop(name, None)

    reply["token"] = secrets.token_urlsafe(24)
    state.setdefault("sessions", []).append(_token_hash(reply["token"]))
    del state["sessions"][:-MAX_SESSIONS]
    flush()
    return 200, reply


def find_city(name, now):
    """A city named by a player or by saved market data; None if there is no such city."""
    if not isinstance(name, str) or not CITY_NAME.match(name):
        return None
    return get_city(name, now)


def all_city_names():
    names = set(CITIES)
    if SAVES.exists():
        names.update(p.stem for p in SAVES.glob("*.json"))
    return sorted(names)


def flush():
    global LAST_SAVE
    LAST_SAVE = time.time()
    SAVES.mkdir(exist_ok=True)
    for name in DIRTY:
        _write(SAVES / f"{name}.json", CITIES[name])
    DIRTY.clear()
    _write(MARKET_FILE, MARKET)


def startup():
    """Load the market. Call once before the first request."""
    global MARKET
    if MARKET is None:
        MARKET = (json.loads(MARKET_FILE.read_text(encoding="utf-8"))
                  if MARKET_FILE.exists() else market.new_market())
        MARKET.setdefault("bills", [])


def run_bills(now):
    """Market upkeep done before every request: bills that are due, offers to restock."""
    market.run_bills(MARKET, now, lambda name: find_city(name, now))
    market.restock(MARKET, now, lambda name: find_city(name, now))


def city_view(state, now, area=0, find=None):
    out = game.view(state, area if isinstance(area, int) else 0)
    if isinstance(find, str) and ":" in find:      # the Find box: "kind:what"
        out["found"] = game.find(state, *find.split(":", 1))
    out["state"] = {k: v for k, v in state.items() if k not in PRIVATE}
    out["now"] = now
    out["market"] = MARKET
    out["cities"] = all_city_names()
    # Bills are part of what the city gains and loses per hour.
    rates = out["status"]["rates"]
    for k, v in market.bill_rates(MARKET, state["name"]).items():
        rates[k] = round(rates[k] + v, 1)
    return out


def _area(value):
    return int(value) if isinstance(value, str) and value.isdigit() else 0


def handle_get(path, query, token, now):
    """Answer a GET. Returns (status, body) or (status, body, content type). Needs LOCK."""
    if path == "/api/leaderboard":
        return 200, {"cities": [game.summary(get_city(n, now)) for n in all_city_names()]}

    if path == "/api/state":
        name = query.get("city", [""])[0]
        if not CITY_NAME.match(name):
            return 400, {"error": BAD_NAME}
        state = get_city(name, now)
        if not signed_in(state, token):
            return 401, SIGN_IN
        state["online"] = now
        out = city_view(state, now, _area(query.get("area", ["0"])[0]), query.get("find", [""])[0])
        out["away"] = game.check_in(state, now)
        return 200, out

    if path == "/api/visit":   # read-only look at someone else's city
        name, viewer = (query.get(k, [""])[0] for k in ("city", "viewer"))
        if not (CITY_NAME.match(name) and CITY_NAME.match(viewer)):
            return 400, {"error": BAD_NAME}
        if not signed_in(get_city(viewer, now), token):
            return 401, SIGN_IN
        CITIES[viewer]["online"] = now     # looking at someone else's city still counts as being here
        state = get_city(name, now)
        if state is None:
            return 404, {"error": f"There is no city called {name}."}
        if viewer in state["banned"]:
            return 403, {"error": f"{name} has banned your city from viewing it."}
        out = city_view(state, now, _area(query.get("area", ["0"])[0]))
        out["visiting"] = True
        return 200, out

    return 404, {"error": "Not found."}


def handle_post(path, data, token, now):
    """Answer a POST whose JSON body is `data`. Returns (status, body). Needs LOCK."""
    if path == "/api/login":
        return login(data.get("city"), data.get("password"), now)
    if path != "/api/action":
        return 404, {"error": "Not found."}
    name, action = data.get("city"), data.get("action")
    if not isinstance(name, str) or not CITY_NAME.match(name):
        return 400, {"error": BAD_NAME}
    state = get_city(name, now)
    if not signed_in(state, token):
        return 401, SIGN_IN
    state["online"] = now

    if action == "restart":
        market.drop_city(MARKET, name)
        fresh = game.new_game(name, now)
        fresh.update({k: state[k] for k in PRIVATE if k in state})   # same owner
        state = CITIES[name] = fresh
        error = None
    elif action == "set_password":
        password = data.get("password")
        if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
            error = f"Passwords are {MIN_PASSWORD} to {MAX_PASSWORD} characters."
        else:
            set_password(state, password)
            state["sessions"] = [_token_hash(token)]    # signs every other browser out
            error = None
    elif action == "sign_out":
        state["sessions"].remove(_token_hash(token))
        flush()
        return 200, {"error": None}
    elif action == "offer_post":
        error = market.post(MARKET, state, now, data)
    elif action == "offer_restock":
        error = market.set_restock(MARKET, state, now, data.get("offer"), data.get("on"))
    elif action == "market_seen":      # the player has read what sold while they were away
        state["sales"] = []
        error = None
    elif action == "offer_cancel":
        error = market.cancel(MARKET, state, now, data.get("offer"))
    elif action == "offer_accept":
        error = market.accept(MARKET, state, now, data.get("offer"),
                              lambda seller: find_city(seller, now), data.get("lots"))
    elif action == "bill_propose":
        error = market.propose_bill(MARKET, state, now, data,
                                    lambda other: find_city(other, now))
    elif action == "bill_accept":
        error = market.accept_bill(MARKET, state, now, data.get("bill"))
    elif action == "bill_cancel":
        error = market.cancel_bill(MARKET, state, now, data.get("bill"),
                                   lambda other: find_city(other, now))
    elif action in ("ban", "unban"):
        target = data.get("target")
        if not isinstance(target, str) or not CITY_NAME.match(target):
            error = BAD_NAME
        else:
            error = game.set_ban(state, now, target, action == "ban")
            if action == "ban" and not error:
                market.drop_proposals(MARKET, target, name)
    else:
        error = game.apply_action(state, now, action, data)
    flush()
    out = city_view(state, now, 0 if action == "restart" else data.get("area", 0), data.get("find"))
    out["error"] = error
    return 200, out


def respond(method, path, query="", token=None, body=b""):
    """Answer one HTTP request, however it arrived.

    Returns (status code, body bytes, content type).
    """
    now = time.time()
    if method == "GET" and path == "/":
        return 200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8"
    data = None
    if method == "POST":
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            method = None
    with LOCK:
        if method in ("GET", "POST"):
            run_bills(now)
            if method == "GET":
                status, reply = handle_get(path, parse_qs(query), token, now)
            else:
                status, reply = handle_post(path, data, token, now)
            if DIRTY and now - LAST_SAVE >= AUTOSAVE_SECONDS:
                flush()
        else:
            status, reply = 400, {"error": "Bad request."}
        return status, json.dumps(reply).encode("utf-8"), "application/json"


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        self._reply(*respond("GET", url.path, url.query, self.headers.get("X-Token")))

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        body = self.rfile.read(min(length, MAX_BODY))
        self._reply(*respond("POST", urlparse(self.path).path, "", self.headers.get("X-Token"), body))

    def log_message(self, *args):
        pass  # keep the console quiet


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packets are sent; just picks the LAN interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    if sys.argv[1:2] == ["--reset-password"]:
        path = SAVES / f"{sys.argv[2]}.json" if len(sys.argv) > 2 and CITY_NAME.match(sys.argv[2]) else None
        if not path or not path.exists():
            sys.exit("Usage: python server.py --reset-password CityName   (with the server stopped)")
        saved = json.loads(path.read_text(encoding="utf-8"))
        for key in PRIVATE:
            saved.pop(key, None)
        _write(path, saved)
        sys.exit(f"{sys.argv[2]} has no password now. Whoever signs in to it next chooses the new one.")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    startup()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("Text City Builder is running.")
    print(f"  On this computer:      http://localhost:{port}")
    print(f"  On your local network: http://{lan_ip()}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with LOCK:
            flush()
        print("\nSaved and stopped.")
