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
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import beasts
import discord_bot
import game
import market
import moderation
import weather

ROOT = Path(__file__).parent
# Where the live game's data lives. Next to the code by default; a server can keep it elsewhere
# (DCB_DATA, see deploy/) so that updating or replacing the code never touches it.
DATA = Path(os.environ.get("DCB_DATA") or ROOT)
SAVES = DATA / "saves"
REMOVED = DATA / "removed"     # saves of cities an admin removed (kept, never deleted)
moderation.EXTRA_FILE = DATA / "blocked_words.json"   # words an admin blocked with /blockword
MARKET_FILE = DATA / "market.json"
PRESENTS_FILE = DATA / "presents.json"   # presents sent from the console, waiting to be handed out
CITY_NAME = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
BAD_NAME = "City names are 1-24 letters, digits, - or _."
AUTOSAVE_SECONDS = 60
MAX_BODY = 64_000                # bytes of request body read (Discord's commands can be a few kB)

PRIVATE = ("auth", "sessions")   # parts of a save that never leave the server
MIN_PASSWORD, MAX_PASSWORD = 4, 100
MAX_SESSIONS = 10                # browsers that can stay signed in to one city
LOCKOUT_TRIES, LOCKOUT_SECONDS = 5, 30
SIGN_IN = {"error": "Sign in to this city first.", "auth": True}

LOCK = threading.Lock()   # guards everything below
CITIES = {}               # name -> state
DIRTY = set()             # names changed since the last write to disk
TOUCHED = set()           # names read or changed while answering the request in hand (an action saves just these)
LAST_UPKEEP = 0.0         # when bills, the market's tidying and presents were last seen to
UPKEEP_SECONDS = 3        # ...done at most this often, not before every request
BOARD = {"at": 0.0, "rows": {}, "done": {}}     # the leaderboard: name -> row, and when each row was worked out
BOARD_SECONDS = 15
BOARD_BUDGET = 0.08       # seconds a leaderboard request may spend on rows; the rest wait for later requests
MARKET = None
FAILED = {}               # name -> [wrong passwords in a row, locked until]
ONLINE = {}               # name -> when its own player's page last asked for it (in use or not)
ACTIVE = {}               # name -> when its page last asked while being used (on screen, touched lately)
ONLINE_SECONDS = 45       # used this lately: online (a page in use asks every 3-20s)
IDLE_SECONDS = 180        # heard from this lately but not used: idle (a page in the background checks in once a minute)


def presence(name, now):
    """"online", "idle" or None (offline) for a city's player."""
    if now - ACTIVE.get(name, 0) <= ONLINE_SECONDS:
        return "online"
    if now - ONLINE.get(name, 0) <= IDLE_SECONDS:
        return "idle"
    return None


def _seen(name, now, idle):
    ONLINE[name] = now
    if not idle:
        ACTIVE[name] = now
LAST_SAVE = 0             # when everything was last written to disk


def _write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _loaded(name, now, create=False):
    """The city in memory, loaded from its save if it isn't yet (not brought up to date), or None."""
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
    return state


def get_city(name, now, create=False):
    """The city brought up to the present moment, or None if it doesn't exist."""
    state = _loaded(name, now, create)
    if state is None:
        return None
    game.advance_time(state, now)
    DIRTY.add(name)
    TOUCHED.add(name)
    return state


def _board_row(name, now, catch_up):
    state = _loaded(name, now)
    if state is None:
        BOARD["rows"].pop(name, None)
        return
    if catch_up:
        game.advance_time(state, now)       # only reading: not saved for this (its next save covers it)
    BOARD["rows"][name] = game.summary(state)
    BOARD["done"][name] = now


def leaderboard(now):
    """Every city's leaderboard row. Rows are kept, and each request works out again only the oldest ones, for at
    most BOARD_BUDGET seconds (the cities in use most often), so the board never holds up everyone else. A city
    nobody has a row for yet is shown as last saved, and caught up on a later round."""
    if now - BOARD["at"] >= BOARD_SECONDS:
        BOARD["at"] = now
        for gone in set(BOARD["rows"]) - set(all_city_names()):
            BOARD["rows"].pop(gone, None)
    start = time.perf_counter()
    for name in all_city_names():   # a city not loaded yet (just after a restart) joins once it is: see warm_up()
        if name not in BOARD["rows"] and (name in CITIES or time.perf_counter() - start < BOARD_BUDGET):
            _board_row(name, now, catch_up=False)
    start = time.perf_counter()
    stale = sorted((n for n in BOARD["rows"] if now - BOARD["done"].get(n, 0) >= BOARD_SECONDS),
                   key=lambda n: (n not in ONLINE, BOARD["done"].get(n, 0)))
    for name in stale:
        if time.perf_counter() - start >= BOARD_BUDGET:
            break
        _board_row(name, now, catch_up=True)
    return [BOARD["rows"][n] for n in sorted(BOARD["rows"])]


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
    if name not in all_city_names() and match_city(name):    # the same name with other capitals
        return 400, {"error": f"There is already a city called {match_city(name)}: sign in with its name written the same way."}
    tries = FAILED.setdefault(name, [0, 0])
    if now < tries[1]:
        return 429, {"error": f"Too many wrong passwords. Try again in {int(tries[1] - now) + 1} seconds."}

    state = get_city(name, now)
    reply = {}
    if state is None:
        problem = moderation.check_name(name) or (
            f"There is already a city called {match_city(name)}: sign in with its name written the same way."
            if match_city(name) else None)
        if problem:
            return 400, {"error": problem}
        state = get_city(name, now, create=True)
        set_password(state, password)
        reply["created"] = True
        discord_bot.announce(f"\U0001F3D5\uFE0F A new city has been founded: **{name}**.")
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
    flush(TOUCHED | {name})
    return 200, reply


def find_city(name, now):
    """A city named by a player or by saved market data; None if there is no such city."""
    if not isinstance(name, str) or not CITY_NAME.match(name):
        return None
    return get_city(name, now)


DISK_NAMES = {"at": -1e9, "names": set()}    # the saves folder's list of cities, looked at every NAMES_SECONDS
NAMES_SECONDS = 30


def all_city_names():
    """Every city: those in memory (a new one is at once) and those saved. The folder is listed at most every
    NAMES_SECONDS (every update sends the list, and listing a folder is slow on a web host's network disk)."""
    clock = time.time()
    if clock - DISK_NAMES["at"] >= NAMES_SECONDS:
        DISK_NAMES.update(at=clock, names={p.stem for p in SAVES.glob("*.json")} if SAVES.exists() else set())
    return sorted(set(CITIES) | DISK_NAMES["names"])


def match_city(name):
    """The city's own name for `name`, matched without minding capitals, or None."""
    names = all_city_names()
    return name if name in names else next((n for n in names if n.lower() == str(name).lower()), None)


def _rename_in(value, old, new, pattern):
    """`value` with every mention of the city `old` changed to `new`: whole strings, dict keys, and the name as a
    word inside text (log lines, messages)."""
    if isinstance(value, str):
        return new if value == old else pattern.sub(new, value)
    if isinstance(value, list):
        return [_rename_in(v, old, new, pattern) for v in value]
    if isinstance(value, dict):
        return {(new if k == old else k): _rename_in(v, old, new, pattern) for k, v in value.items()}
    return value


def rename_city(old, new, now):
    """An admin's: give a city a new name, everywhere it is mentioned (other cities, the market). Needs LOCK.
    Returns an error, or None."""
    old = match_city(old)
    if not old:
        return "There is no such city."
    if not isinstance(new, str) or not CITY_NAME.match(new):
        return BAD_NAME
    if new.lower() != old.lower() and match_city(new):
        return f"There is already a city called {match_city(new)}."
    problem = moderation.check_name(new)
    if problem:
        return problem
    global MARKET
    pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(old)}(?![A-Za-z0-9_-])")
    for name in all_city_names():
        state = get_city(name, now)
        if state is not None:
            CITIES[name] = _rename_in(state, old, new, pattern)
    CITIES[new] = CITIES.pop(old)
    CITIES[new]["name"] = new
    MARKET = _rename_in(MARKET, old, new, pattern)
    for book in (ONLINE, ACTIVE, FAILED):
        if old in book:
            book[new] = book.pop(old)
    DIRTY.discard(old)
    DIRTY.update(CITIES)
    flush()
    DISK_NAMES["at"] = -1e9         # list the folder again: the old name is gone
    old_file = SAVES / f"{old}.json"
    if old_file.exists() and old.lower() != new.lower():
        old_file.unlink()          # its contents are in the new file now
    elif old_file.exists():       # only the capitals changed: on Windows that is the same file
        old_file.rename(SAVES / f"{new}.json")
    return None


def remove_city(name, now):
    """An admin's: take a city out of the game. Its save is moved to the "removed" folder, not deleted, and its
    offers, bills and duels are taken off the market. Needs LOCK. Returns (its name, None) or (None, an error)."""
    name = match_city(name)
    if not name:
        return None, "There is no such city."
    get_city(name, now)
    flush()
    REMOVED.mkdir(exist_ok=True)
    path = SAVES / f"{name}.json"
    if path.exists():
        path.replace(REMOVED / f"{name}-{int(now)}.json")
    CITIES.pop(name, None)
    DIRTY.discard(name)
    for book in (ONLINE, ACTIVE, FAILED):
        book.pop(name, None)
    market.drop_city(MARKET, name)
    flush()
    DISK_NAMES["at"] = -1e9
    BOARD["rows"].pop(name, None)
    return name, None


def flagged_names(now):
    """[(city, what, the name)] for every city and area name the filter would not allow now."""
    out = []
    for name in all_city_names():
        if moderation.check_name(name):
            out.append((name, "city name", name))
        state = get_city(name, now)
        for area in (state or {}).get("areas", []):
            if area.get("label") and moderation.check_name(area["label"]):
                out.append((name, "area name", area["label"]))
    return out


def flush(names=None):
    """Write changed cities and the market to disk. With `names`, just those cities (the ones an action
    touched): every other city waits for the next autosave, so a click doesn't rewrite every save."""
    global LAST_SAVE
    SAVES.mkdir(exist_ok=True)
    if names is None:
        LAST_SAVE = time.time()
        names = set(DIRTY)
    for name in set(names):
        if name in CITIES:
            _write(SAVES / f"{name}.json", CITIES[name])
        DIRTY.discard(name)
    _write(MARKET_FILE, MARKET)


def warm_up():
    """Just after a restart: load every city into memory one at a time, letting go of LOCK between them, so the
    first player to open the leaderboard (or trade with a city nobody has opened yet) doesn't wait for all of them."""
    for name in all_city_names():
        with LOCK:
            if name not in CITIES:
                try:
                    _loaded(name, time.time())
                except Exception:
                    traceback.print_exc()
        time.sleep(0.02)


def startup():
    """Load the market, and start loading the cities. Call once before the first request."""
    global MARKET
    if MARKET is None:
        MARKET = (json.loads(MARKET_FILE.read_text(encoding="utf-8"))
                  if MARKET_FILE.exists() else market.new_market())
        MARKET.setdefault("bills", [])
        MARKET.setdefault("beast_offers", [])
        MARKET.setdefault("artifact_offers", [])
        MARKET.setdefault("duels", [])
        for offer in MARKET["beast_offers"]:    # beasts put on offer before every beast had a sex
            offer["beast"].setdefault("sex", random.choice(beasts.SEXES))
        threading.Thread(target=warm_up, daemon=True).start()


def run_bills(now):
    """Market upkeep, every few seconds: bills that are due, empty offers to clear, presents sent from the console."""
    global LAST_UPKEEP
    if now - LAST_UPKEEP < UPKEEP_SECONDS:
        return
    LAST_UPKEEP = now
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
        elif key in game.RESOURCES and value.isdigit() and 0 < int(value) <= 1_000_000_000_000:
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


# The tile facts the page uses for areas other than the one on screen (the mini maps, counts, Find, taming).
OTHER_AREA_TILE = ("terrain", "building", "animal", "additions")


def _sent_state(state, shown):
    """The save as the page gets it: nothing private, and only the area on screen with every fact about each tile.
    The others' tiles carry only what the page needs of them, and leave out what is empty (no building, no animal):
    the page reads a missing one as none."""
    out = {k: v for k, v in state.items() if k not in PRIVATE and k != "areas"}
    out["areas"] = [a if i == shown else {**{k: v for k, v in a.items() if k != "tiles"},
                                         "tiles": [[{k: t[k] for k in OTHER_AREA_TILE if t[k]} for t in row] for row in a["tiles"]]}
                    for i, a in enumerate(state["areas"])]
    return out


def city_view(state, now, area=0, find=None, tile=None, have_defs=None, stats=False):
    with game.reading():        # the work plan and city stats once for the whole reply
        return _city_view(state, now, area, find, tile, have_defs, stats)


def _city_view(state, now, area=0, find=None, tile=None, have_defs=None, stats=False):
    global DEFS_VERSION
    out = game.view(state, area if isinstance(area, int) else 0, _tile(tile))
    if DEFS_VERSION is None:
        DEFS_VERSION = hashlib.sha1(json.dumps(game.defs(), sort_keys=True).encode()).hexdigest()[:12]
    out["defs_version"] = DEFS_VERSION
    if have_defs == DEFS_VERSION:
        del out["defs"]           # the page has these already: about 80 KB less on every update
    if isinstance(find, str) and ":" in find:      # the Find box: "kind:what"
        out["found"] = game.find(state, *find.split(":", 1), here=out["area"])
    out["state"] = _sent_state(state, out["area"])
    out["now"] = now
    out["market"] = dict(MARKET, beast_offers=market.beast_offers_view(MARKET), duels=market.duels_view(MARKET, state["name"]),
                         artifact_offers=market.artifact_offers_view(MARKET))
    out["cities"] = all_city_names()
    out["online"] = sorted(n for n in ONLINE if presence(n, now) == "online")
    out["idle"] = sorted(n for n in ONLINE if presence(n, now) == "idle")
    # Bills are part of what the city gains and loses per hour.
    rates = out["status"]["rates"]
    for k, v in market.bill_rates(MARKET, state["name"]).items():
        rates[k] = round(rates[k] + v, 1)
        out["status"]["unpaused_rates"][k] = round(out["status"]["unpaused_rates"][k] + v, 1)
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
        ["Cities online now", sum(1 for n in ONLINE if presence(n, now) == "online"), f"{sum(1 for n in ONLINE if presence(n, now) == 'idle')} more idle"],
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
        return 200, {"cities": leaderboard(now)}

    if path == "/api/state":
        name = query.get("city", [""])[0]
        if not CITY_NAME.match(name):
            return 400, {"error": BAD_NAME}
        state = get_city(name, now)
        if not signed_in(state, token):
            return 401, SIGN_IN
        _seen(name, now, query.get("idle", [""])[0] == "1")
        tz = query.get("tz", [""])[0]
        if re.fullmatch(r"-?\d{1,3}", tz):
            weather.set_timezone(state, int(tz))     # day and night follow the player's own clock
        out = city_view(state, now, _area(query.get("area", ["0"])[0]), query.get("find", [""])[0],
                        query.get("tile", [""])[0], query.get("defs", [""])[0], query.get("stats", [""])[0] == "1")
        out["away"] = game.check_in(state, now)
        out["discord_code"] = discord_bot.link_code(name)      # for /claim; only this city's player sees it
        return 200, out

    if path == "/api/ping":    # a page in the background: still open, not in use
        name = query.get("city", [""])[0]
        if not CITY_NAME.match(name):
            return 400, {"error": BAD_NAME}
        state = CITIES.get(name)          # no need to load or bring a city up to date just to say hello
        if not state or not signed_in(state, token):
            return 401, SIGN_IN
        _seen(name, now, query.get("idle", ["1"])[0] == "1")
        return 200, {}

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


# Fields of an action that name something (a building, a resource, a city...) must be text, or the game
# would look a list or an object up in its tables. Anything else there is dropped, and the action then
# says what is missing. "bet" (and a beast trade's "want") may be small objects, whose own name fields are checked too.
NAME_FIELDS = {"action", "building", "addition", "research", "ideology", "perk", "ritual", "give", "want", "to", "text",
               "other", "name", "list", "kind", "find", "tile", "defs", "password", "res", "species", "city", "curse", "recipe"}


def _clean(data, inner=False):
    out = {}
    objects = {"bet", "want"} if data.get("action") == "beast_offer_post" else {"bet"}   # only a beast trade wants an object
    for key, value in data.items():
        if key in objects and isinstance(value, dict) and not inner:
            out[key] = _clean(value, inner=True)
        elif key == "target":
            out[key] = value if isinstance(value, (str, int)) and not isinstance(value, bool) else None
        elif key in NAME_FIELDS:
            out[key] = value if isinstance(value, str) else None
        else:
            out[key] = value
    return out


def handle_post(path, data, token, now):
    """Answer a POST whose JSON body is `data`. Returns (status, body). Needs LOCK."""
    if not isinstance(data, dict):
        return 400, {"error": "Bad request."}
    data = _clean(data)
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
    _seen(name, now, False)
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
        ACTIVE.pop(name, None)
        state["sessions"].remove(_token_hash(token))
        flush(TOUCHED)
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
    elif action == "artifact_offer_post":
        error = market.post_artifact(MARKET, state, now, data.get("artifact"), data.get("res"), data.get("qty"))
    elif action == "artifact_offer_cancel":
        error = market.cancel_artifact(MARKET, state, now, data.get("offer"))
    elif action == "artifact_offer_accept":
        error = market.accept_artifact(MARKET, state, now, data.get("offer"), lambda seller: find_city(seller, now))
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
    elif action == "curse_cast":
        target = find_city(data.get("target"), now)
        error = game.ideology.cast_curse(state, target, now, data.get("curse"), data.get("gold"))
        if not error:
            ideo = game.ideology.chosen(state)
            curse = ideo["curses"][data["curse"]]
            market.social(state, now, target["name"], "curse", f"{curse['name']}: you {ideo['curse_past']} them.")
            market.social(target, now, name, "curse", f"{curse['name']}: they {ideo['curse_past']} you.")
            discord_bot.announce(f"\U0001F56F\uFE0F **{name}** {ideo['curse_past']} **{target['name']}**: **{curse['name']}**.")
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
        tech, belief = state["tech"], state.get("ideology")
        error = game.apply_action(state, now, action, data)
        if not error and state["tech"] > tech:
            discord_bot.announce(f"\U0001F389 **{name}** is now a **{game.TECH_LEVELS[state['tech']]['name']}**!")
        if not error and state.get("ideology") and not belief:
            discord_bot.announce(f"\U0001F54A\uFE0F **{name}** has taken up **{game.ideology.IDEOLOGIES[state['ideology']]['name']}**.")
    if action == "restart":
        TOUCHED.add(name)
    flush(TOUCHED)
    out = city_view(state, now, 0 if action == "restart" else data.get("area", 0), data.get("find"),
                    data.get("tile"), data.get("defs"), data.get("stats") is True)
    out["error"] = error
    return 200, out


def respond(method, path, query="", token=None, body=b"", headers=None):
    """Answer one HTTP request, however it arrived.

    Returns (status code, body bytes, content type).
    """
    now = time.time()
    if method == "GET" and path == "/":
        return 200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8"
    if method == "POST" and path == "/api/discord":     # a slash command from Discord (see discord_bot.py)
        with LOCK:
            try:
                status, reply = discord_bot.handle(body, headers or {}, now)
            except Exception:
                traceback.print_exc()
                status, reply = 500, {"error": "Something went wrong."}
        return status, json.dumps(reply, separators=(",", ":")).encode("utf-8"), "application/json"
    data = None
    if method == "POST":
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            method = None
    with LOCK:
        TOUCHED.clear()
        if method in ("GET", "POST"):
            try:
                run_bills(now)
                if method == "GET":
                    status, reply = handle_get(path, parse_qs(query), token, now)
                else:
                    status, reply = handle_post(path, data, token, now)
            except Exception:
                # A bug: say so to the player instead of dropping the connection, and keep the details for the admin.
                traceback.print_exc()
                status, reply = 500, {"error": "Something went wrong on the server. Try again; if it keeps happening, tell the admin."}
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
        self._reply(*respond("POST", urlparse(self.path).path, "", self.headers.get("X-Token"), body,
                             {k: self.headers.get(k) for k in ("X-Signature-Ed25519", "X-Signature-Timestamp")}))

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
