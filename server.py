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

import gzip
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import signal
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import beasts
import game
import market
import weather

ROOT = Path(__file__).parent
# Where the live game's data lives. Next to the code by default; a server can keep it elsewhere
# (DCB_DATA, see deploy/) so that updating or replacing the code never touches it.
DATA = Path(os.environ.get("DCB_DATA") or ROOT)
SAVES = DATA / "saves"
MARKET_FILE = DATA / "market.json"
PRESENTS_FILE = DATA / "presents.json"   # presents sent from the console, waiting to be handed out
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
ONLINE = {}               # name -> when its own player's page last asked for it
ONLINE_SECONDS = 45       # a city not heard from for this long has no window open (pages ask every 3-20s)
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
        MARKET.setdefault("beast_offers", [])
        MARKET.setdefault("duels", [])
        for offer in MARKET["beast_offers"]:    # beasts put on offer before every beast had a sex
            offer["beast"].setdefault("sex", random.choice(beasts.SEXES))


def run_bills(now):
    """Market upkeep done before every request: bills that are due, empty offers to clear."""
    market.run_bills(MARKET, now, lambda name: find_city(name, now))
    market.tidy(MARKET, now, lambda name: find_city(name, now))
    deliver_presents(now)


def deliver_presents(now):
    """Hand out presents the admin has sent from the console (python server.py --present ...).
    The console only writes them to PRESENTS_FILE; the running game picks them up here, so
    nothing has to be stopped or reloaded."""
    if not PRESENTS_FILE.exists():
        return
    taken = PRESENTS_FILE.with_suffix(".taken")
    try:
        os.replace(PRESENTS_FILE, taken)
        waiting = json.loads(taken.read_text(encoding="utf-8"))
        taken.unlink()
    except (OSError, ValueError):
        return
    for present in waiting:
        names = all_city_names() if present["to"] == "all" else [present["to"]]
        for name in names:
            state = find_city(name, now)
            if state:
                game.give_present(state, now, present["message"], present["gifts"], present.get("egg"),
                                  present.get("people", 0))
    flush()


def send_present(args):
    """The --present command. Returns what to print."""
    usage = ("Usage: python server.py --present CityName|all \"message\" wood=100 food=50 egg=rare people=5\n"
             f"  materials: {', '.join(game.RESOURCES)}\n  egg: {', '.join(beasts.RARITIES)}\n"
             "  people: new arrivals (they move in even if every bed is taken)")
    if len(args) < 2:
        return usage
    to, message, gifts, egg, people = args[0], args[1], {}, None, 0
    if to != "all" and not (CITY_NAME.match(to) and (SAVES / f"{to}.json").exists()):
        return f"There is no city called {to}. City names are case-sensitive: {', '.join(all_city_names()) or 'none yet'}."
    for word in args[2:]:
        key, _, value = word.partition("=")
        if key == "egg" and value in beasts.RARITIES:
            egg = value
        elif key == "people" and value.isdigit() and 0 < int(value) <= 10_000:
            people += int(value)
        elif key in game.RESOURCES and value.isdigit() and 0 < int(value) <= 1_000_000:
            gifts[key] = gifts.get(key, 0) + int(value)
        else:
            return f"Did not understand '{word}'.\n{usage}"
    if "=" in message and not args[2:]:
        return f"The message comes before the gifts, in quotes.\n{usage}"
    waiting = json.loads(PRESENTS_FILE.read_text(encoding="utf-8")) if PRESENTS_FILE.exists() else []
    waiting.append({"to": to, "message": message[:game.MAX_PRESENT_MESSAGE], "gifts": gifts, "egg": egg, "people": people})
    _write(PRESENTS_FILE, waiting)
    inside = ([f"{v} {game.RESOURCES[k]}" for k, v in gifts.items()] + ([f"a {egg} egg"] if egg else [])
              + ([f"{people} people"] if people else []))
    return (f"Present for {'every city' if to == 'all' else to}: {', '.join(inside) or 'nothing but the message'}.\n"
            "It is handed out the next time anyone uses the game.")


DEFS_VERSION = None    # a short fingerprint of game.defs(), so a page that already has them isn't sent them again


def _tile(value):
    """ "x,y" (the tile the player has selected) -> (x, y), or None."""
    try:
        x, y = (int(v) for v in str(value).split(","))
        return x, y
    except (TypeError, ValueError):
        return None


def city_view(state, now, area=0, find=None, tile=None, have_defs=None, stats=False):
    global DEFS_VERSION
    out = game.view(state, area if isinstance(area, int) else 0, _tile(tile))
    if DEFS_VERSION is None:
        DEFS_VERSION = hashlib.sha1(json.dumps(game.defs(), sort_keys=True).encode()).hexdigest()[:12]
    out["defs_version"] = DEFS_VERSION
    if have_defs == DEFS_VERSION:
        del out["defs"]           # the page has these already: about 80 KB less on every update
    if isinstance(find, str) and ":" in find:      # the Find box: "kind:what"
        out["found"] = game.find(state, *find.split(":", 1))
    out["state"] = {k: v for k, v in state.items() if k not in PRIVATE}
    out["now"] = now
    out["market"] = dict(MARKET, beast_offers=market.beast_offers_view(MARKET), duels=market.duels_view(MARKET, state["name"]))
    out["cities"] = all_city_names()
    out["online"] = sorted(n for n, seen in ONLINE.items() if now - seen <= ONLINE_SECONDS)
    # Bills are part of what the city gains and loses per hour.
    rates = out["status"]["rates"]
    for k, v in market.bill_rates(MARKET, state["name"]).items():
        rates[k] = round(rates[k] + v, 1)
    if stats:       # only while the Stats tab is open: it is the most work of any reply
        out["stats"] = game.city_stats(state, now, rates)
        out["stats"].insert(-1, market_stats(state, now))
    return out


def market_stats(state, now):
    """The Stats tab's section on trading and other cities (it needs the market, which game.py doesn't see)."""
    name = state["name"]
    trades = [h for h in MARKET["history"] if name in (h["seller"], h["buyer"])]
    bills = [b for b in MARKET["bills"] if name in (b["from"], b["to"])]
    duels = market.duels_view(MARKET, name)
    book = state.get("social", {"lists": {}, "history": []})
    mail = state.get("messages", [])
    names = all_city_names()
    board = [game.summary(c) for c in (get_city(n, now) for n in names) if c]
    rank = lambda key: 1 + sum(1 for c in board if key(c) > key(game.summary(state)))
    pop_rank = rank(lambda c: c["population"])
    return {"id": "market", "title": "Market and other cities", "headline": f"#{pop_rank} of {len(board)} by population",
            "blocks": [{"rows": [
        ["Your open offers", sum(1 for o in MARKET["offers"] if o["city"] == name), f"of {len(MARKET['offers'])} on the market"],
        ["Finished offers kept", len(state.get("finished", [])), ""],
        ["Recent market trades you took part in", len(trades), f"of the last {len(MARKET['history'])} on the market"],
        ["  as the seller", sum(1 for h in trades if h["seller"] == name), ""],
        ["  as the buyer", sum(1 for h in trades if h["buyer"] == name), ""],
        ["Bills running", sum(1 for b in bills if b["status"] == "active"), ""],
        ["Bills waiting for an answer", sum(1 for b in bills if b["status"] != "active"), ""],
        ["Your beast offers", sum(1 for o in MARKET["beast_offers"] if o["city"] == name), f"of {len(MARKET['beast_offers'])} on the market"],
        ["Duel challenges for you", sum(1 for d in duels if d.get("to") == name), ""],
        ["Duel challenges you sent", sum(1 for d in duels if d["city"] == name), ""],
        ["Duels kept on record", len(state.get("duels", [])), f"{sum(1 for d in state.get('duels', []) if d['won'])} won"],
        ["Allies", sum(1 for v in book["lists"].values() if v == "ally"), ""],
        ["Enemies", sum(1 for v in book["lists"].values() if v == "enemy"), ""],
        ["Cities you have dealt with", len({h["city"] for h in book["history"] if h.get("city")}), "recently"],
        ["Banned from viewing your city", len(state.get("banned", [])), ""],
        ["Messages kept", len(mail), f"{sum(1 for m in mail if not m['read'])} unread"],
        ["Presents waiting to be opened", sum(1 for p in state.get("presents", []) if not p["opened"]), ""],
        ["Cities in the game", len(names), ""],
        ["Cities online now", sum(1 for seen in ONLINE.values() if now - seen <= ONLINE_SECONDS), ""],
        ["Rank by population", pop_rank, f"of {len(board)}"],
        ["Rank by tech level", rank(lambda c: c["tech"]), f"of {len(board)} (cities level with you share a rank)"],
        ["Rank by research", rank(lambda c: c["research"]), f"of {len(board)}"],
        ["Rank by buildings", rank(lambda c: c["buildings"]), f"of {len(board)}"],
        ["Rank by areas", rank(lambda c: c["areas"]), f"of {len(board)}"],
    ]}]}


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
        ONLINE[name] = now
        tz = query.get("tz", [""])[0]
        if re.fullmatch(r"-?\d{1,3}", tz):
            weather.set_timezone(state, int(tz))     # day and night follow the player's own clock
        out = city_view(state, now, _area(query.get("area", ["0"])[0]), query.get("find", [""])[0],
                        query.get("tile", [""])[0], query.get("defs", [""])[0], query.get("stats", [""])[0] == "1")
        out["away"] = game.check_in(state, now)
        return 200, out

    if path == "/api/visit":   # read-only look at someone else's city
        name, viewer = (query.get(k, [""])[0] for k in ("city", "viewer"))
        if not (CITY_NAME.match(name) and CITY_NAME.match(viewer)):
            return 400, {"error": BAD_NAME}
        if not signed_in(get_city(viewer, now), token):
            return 401, SIGN_IN
        state = get_city(name, now)
        if state is None:
            return 404, {"error": f"There is no city called {name}."}
        if viewer in state["banned"]:
            return 403, {"error": f"{name} has banned your city from viewing it."}
        out = city_view(state, now, _area(query.get("area", ["0"])[0]), None,
                        query.get("tile", [""])[0], query.get("defs", [""])[0])
        out["visiting"] = True
        out["state"].pop("social", None)    # who a city deals with, and its lists, are its own business
        out["state"].pop("messages", None)
        out["market"]["duels"] = []     # another city's challenges are its own business
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
    ONLINE[name] = now
    weather.set_timezone(state, data.get("tz"))

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
        ONLINE.pop(name, None)
        state["sessions"].remove(_token_hash(token))
        flush()
        return 200, {"error": None}
    elif action == "offer_post":
        error = market.post(MARKET, state, now, data)
    elif action == "offer_reactivate":
        error = market.reactivate(MARKET, state, now, data.get("offer"))
    elif action == "offer_edit":
        error = market.edit(state, data.get("offer"), data.get("give_qty"), data.get("want_qty"))
    elif action == "offer_forget":
        error = market.forget(state, data.get("offer"))
    elif action == "market_seen":      # the player has read what sold while they were away
        state["sales"] = []
        error = None
    elif action == "beast_offer_post":
        error = market.post_beast(MARKET, state, now, data)
    elif action == "beast_offer_cancel":
        error = market.cancel_beast(MARKET, state, now, data.get("offer"))
    elif action == "beast_offer_accept":
        error = market.accept_beast(MARKET, state, now, data.get("offer"),
                                    lambda seller: find_city(seller, now), data.get("pay"))
    elif action == "message_send":
        error = market.send_message(state, now, data.get("to"), data.get("text"),
                                    lambda other: find_city(other, now))
    elif action == "messages_read":
        error = market.read_messages(state, data.get("other"))
    elif action == "duel_post":
        error = market.post_duel(MARKET, state, now, data, lambda other: find_city(other, now))
    elif action == "duel_cancel":       # withdraw one you sent, or decline one sent to you
        error = market.cancel_duel(MARKET, state, now, data.get("duel"), lambda other: find_city(other, now))
    elif action == "duel_accept":
        error = market.accept_duel(MARKET, state, now, data.get("duel"),
                                   lambda other: find_city(other, now), data.get("beast"), data.get("bet"))
    elif action == "offer_cancel":
        error = market.cancel(MARKET, state, now, data.get("offer"))
    elif action == "offer_accept":
        error = market.accept(MARKET, state, now, data.get("offer"),
                              lambda seller: find_city(seller, now), data.get("lots"), data.get("amount"))
    elif action == "bill_propose":
        error = market.propose_bill(MARKET, state, now, data,
                                    lambda other: find_city(other, now))
    elif action == "bill_accept":
        error = market.accept_bill(MARKET, state, now, data.get("bill"), lambda other: find_city(other, now))
    elif action == "bill_cancel":
        error = market.cancel_bill(MARKET, state, now, data.get("bill"),
                                   lambda other: find_city(other, now))
    elif action in ("ban", "unban"):
        target = data.get("target")
        if not isinstance(target, str) or not CITY_NAME.match(target):
            error = BAD_NAME
        else:
            error = game.set_ban(state, now, target, action == "ban")
            if not error:
                market.social(state, now, target, "ban",
                              "You banned them." if action == "ban" else "You lifted your ban on them.")
            if action == "ban" and not error:
                market.drop_proposals(MARKET, target, name)
    else:
        error = game.apply_action(state, now, action, data)
    flush()
    out = city_view(state, now, 0 if action == "restart" else data.get("area", 0), data.get("find"),
                    data.get("tile"), data.get("defs"), data.get("stats") is True)
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
        return status, json.dumps(reply, separators=(",", ":")).encode("utf-8"), "application/json"


def compress(body, accept_encoding):
    """Gzip a reply if the browser accepts it: a city's update shrinks to about a tenth.
    Returns (body, extra headers)."""
    if len(body) > 1024 and "gzip" in (accept_encoding or ""):
        return gzip.compress(body, compresslevel=5), [("Content-Encoding", "gzip"), ("Vary", "Accept-Encoding")]
    return body, []


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status, body, content_type):
        body, extra = compress(body, self.headers.get("Accept-Encoding"))
        self.send_response(status)
        for name, value in extra:
            self.send_header(name, value)
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


def _stop(*_):
    raise KeyboardInterrupt


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
    if sys.argv[1:2] == ["--present"]:
        sys.exit(send_present(sys.argv[2:]))
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("DCB_PORT", 8000))
    host = os.environ.get("DCB_HOST", "0.0.0.0")      # 127.0.0.1 behind a web server such as Caddy
    # A service manager stops the game with SIGTERM: treat it like Ctrl+C, so everything is saved first.
    signal.signal(signal.SIGTERM, _stop)
    startup()
    server = ThreadingHTTPServer((host, port), Handler)
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
