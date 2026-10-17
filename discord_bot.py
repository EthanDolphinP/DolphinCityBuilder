"""The game on Discord: slash commands answered by the game server, and announcements posted to a channel.

No program has to keep running for this. Discord sends each slash command to
the game's own web address (/api/discord, see handle()), and the game server
answers it from the live cities. Announcements (a new city, a new tech level)
are posted to a channel through a Discord webhook, and a daily leaderboard can
be posted by a scheduled task (`python discord_bot.py daily`).

Setup, once (see README.md, "Discord"):
    python discord_bot.py setup       asks for the bot's keys and writes DATA/discord.json
    python discord_bot.py register    tells Discord about the slash commands
then set the bot's Interactions Endpoint URL to https://<your game>/api/discord.

The keys live in DATA/discord.json, next to the saves and never in the code, so
they don't end up on GitHub. Without that file, everything here does nothing.

Every request Discord sends is signed: handle() checks the Ed25519 signature
against the bot's public key and refuses anything else. PyNaCl is used for that
when it is installed; otherwise the pure-Python check below (RFC 8032) does it.
"""

import hashlib
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/EthanDolphinP/DolphinCityBuilder, 1.0)"
TOP = 10                     # cities in a leaderboard, offers in a market list
COLOUR = 0xE6C35C            # the game's gold, down the side of every embed


def _data_dir():
    return Path(os.environ.get("DCB_DATA") or Path(__file__).resolve().parent)


CONFIG_FILE = _data_dir() / "discord.json"


def config():
    """The bot's settings, or {} if Discord has not been set up."""
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------- signatures --
# Ed25519 verification, from the reference code in RFC 8032 section 6.

_P = 2 ** 255 - 19
_D = -121665 * pow(121666, _P - 2, _P) % _P
_Q = 2 ** 252 + 27742317777372353535851937790883648493
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _add(a, b):
    x = (a[1] - a[0]) * (b[1] - b[0]) % _P
    y = (a[1] + a[0]) * (b[1] + b[0]) % _P
    z = 2 * a[3] * b[3] * _D % _P
    w = 2 * a[2] * b[2] % _P
    e, f, g, h = y - x, w - z, w + z, y + x
    return (e * f, g * h, f * g, e * h)


def _mul(s, point):
    out = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            out = _add(out, point)
        point = _add(point, point)
        s >>= 1
    return out


def _equal(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _recover_x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    return _P - x if (x & 1) != sign else x


def _decompress(raw):
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


_GY = 4 * pow(5, _P - 2, _P) % _P
_G = (_recover_x(_GY, 0), _GY, 1, _recover_x(_GY, 0) * _GY % _P)


def _verify_pure(public, message, signature):
    if len(public) != 32 or len(signature) != 64:
        return False
    a, r = _decompress(public), _decompress(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if not a or not r or s >= _Q:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % _Q
    return _equal(_mul(s, _G), _add(r, _mul(h, a)))


def verify(public_hex, timestamp, body, signature_hex):
    """True if Discord signed this request (the timestamp followed by the body) with the bot's key."""
    try:
        public, signature = bytes.fromhex(public_hex), bytes.fromhex(signature_hex)
    except (TypeError, ValueError):
        return False
    message = timestamp.encode("utf-8") + body
    try:
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError
        try:
            VerifyKey(public).verify(message, signature)
            return True
        except (BadSignatureError, ValueError):
            return False
    except ImportError:
        return _verify_pure(public, message, signature)


# -------------------------------------------------------- the commands --

COMMANDS = [
    {"name": "leaderboard", "description": "The top cities in Dolphin City Builder",
     "options": [{"type": 3, "name": "by", "description": "What to rank them by (tech level if left out)", "required": False,
                  "choices": [{"name": n, "value": v} for v, n in (
                      ("tech", "Tech level"), ("population", "Population"), ("buildings", "Buildings"), ("research", "Research"),
                      ("areas", "Areas"), ("beast", "Beast level"), ("gold", "Gold"), ("food", "Food"), ("knowledge", "Knowledge"))]}]},
    {"name": "city", "description": "Everything public about one city",
     "options": [{"type": 3, "name": "name", "description": "The city's name", "required": True}]},
    {"name": "market", "description": "What is on sale on the market right now",
     "options": [{"type": 3, "name": "material", "description": "Only offers selling this", "required": False,
                  "choices": [{"name": n, "value": v} for v, n in (
                      ("food", "Food"), ("wood", "Wood"), ("stone", "Stone"), ("ore", "Ore"), ("tools", "Tools"),
                      ("gold", "Gold"), ("electronics", "Electronics"), ("livestock", "Livestock"))]}]},
    {"name": "online", "description": "Which cities have the game open right now"},
    {"name": "game", "description": "The whole game at a glance"},
]


def short(n):
    """1234567 -> "1.2M", as the game's "shorten big numbers" setting writes it."""
    n = float(n)
    for size, letter in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= 10000 and abs(n) >= size:
            return f"{n / size:.{0 if abs(n) / size >= 100 else 1}f}".rstrip("0").rstrip(".") + letter
    return f"{int(n):,}" if n == int(n) else f"{n:,.1f}"


def _embed(title, description="", fields=(), footer=None):
    out = {"title": title, "description": description[:4000], "color": COLOUR,
           "fields": [{"name": n, "value": str(v)[:1024] or "-", "inline": inline} for n, v, inline in fields][:25]}
    if footer:
        out["footer"] = {"text": footer}
    return out


def _reply(embed, private=False):
    """A slash command's answer. private: only the person who asked sees it."""
    data = {"embeds": [embed], "allowed_mentions": {"parse": []}}
    if private:
        data["flags"] = 64
    return {"type": 4, "data": data}


def _cities(server, now):
    """Every city's public summary (the leaderboard's row)."""
    import game
    return [game.summary(c) for c in (server.get_city(n, now) for n in server.all_city_names()) if c]


def _value(c, key):
    return c["resources"].get(key, 0) if key in c["resources"] else c.get(key, 0)


def _ranked(cities, key):
    return sorted(cities, key=lambda c: (-_value(c, key), -c["tech"], -c["population"], c["name"]))


LABELS = {"tech": "Tech level", "population": "Population", "buildings": "Buildings", "research": "Research",
          "areas": "Areas", "beast": "Beast level"}


def _show(c, key):
    return f"{c['tech_name']}" if key == "tech" else short(_value(c, key))


def _leaderboard(server, now, key="tech", title=None):
    import game
    cities = _cities(server, now)
    label = LABELS.get(key) or game.RESOURCES.get(key, key)
    medals = {0: "\U0001F947", 1: "\U0001F948", 2: "\U0001F949"}
    lines = [f"{medals.get(i, f'`{i + 1:>2}`')} **{c['name']}** - {_show(c, key)}" + ("" if key == "tech" else f" ({c['tech_name']})")
             for i, c in enumerate(_ranked(cities, key)[:TOP])]
    return _embed(title or f"Leaderboard: {label}", "\n".join(lines) or "No cities yet.",
                  footer=f"{len(cities)} {'city' if len(cities) == 1 else 'cities'} in the game")


def _city(server, now, name):
    import game
    # The name as the city spells it (people type "utopia" for Utopia); only a real city is ever loaded.
    names = server.all_city_names()
    match = name if name in names else next((n for n in names if n.lower() == str(name).lower()), None)
    state = server.get_city(match, now) if match else None
    if not state:
        return _embed("No such city", f"There is no city called **{name}**. Names are as on the leaderboard.")
    c = game.summary(state)
    cities = _cities(server, now)
    rank = 1 + sum(1 for o in cities if (o["tech"], o["population"]) > (c["tech"], c["population"]))
    online = now - server.ONLINE.get(c["name"], 0) <= server.ONLINE_SECONDS
    stores = sorted(c["resources"].items(), key=lambda kv: -kv[1])
    return _embed(f"{c['name']}" + (" \U0001F7E2" if online else ""),
                  f"A **{c['tech_name']}**" + (f" following **{c['ideology']}**" if c["ideology"] else "") + f". Rank #{rank} of {len(cities)}.",
                  [("Population", short(c["population"]), True), ("Buildings", short(c["buildings"]), True),
                   ("Research done", short(c["research"]), True), ("Areas", short(c["areas"]), True),
                   ("Best beast", f"level {c['beast']}" if c["beast"] else "none yet", True),
                   ("Online", "yes" if online else "no", True),
                   ("Biggest stores", ", ".join(f"{short(v)} {game.RESOURCES[k]}" for k, v in stores[:4] if v) or "nothing yet", False)])


def _market(server, material=None):
    import game
    offers = [o for o in server.MARKET["offers"] if not material or o["give"] == material]
    offers.sort(key=lambda o: o["want_qty"] / o["give_qty"])
    lines = [f"**{o['city']}** sells {short(o['give_qty'])} {game.RESOURCES[o['give']]} for {short(o['want_qty'])} "
             f"{game.RESOURCES[o['want']]} *({o['want_qty'] / o['give_qty']:.3g} each)*" for o in offers[:TOP]]
    what = game.RESOURCES.get(material, "")
    return _embed(f"Market: {what} on sale" if material else "Market: on sale now",
                  "\n".join(lines) or ("Nobody is selling that right now." if material else "Nothing is on sale right now."),
                  footer=f"{len(offers)} open {'offer' if len(offers) == 1 else 'offers'}" + (", cheapest for one first" if material else ""))


def _online(server, now):
    names = sorted(n for n, seen in server.ONLINE.items() if now - seen <= server.ONLINE_SECONDS)
    return _embed("Online now", "\n".join(f"\U0001F7E2 {n}" for n in names) or "Nobody has the game open right now.",
                  footer=f"{len(names)} online")


def _game(server, now):
    cities = _cities(server, now)
    if not cities:
        return _embed("Dolphin City Builder", "No cities yet.")
    lead = _ranked(cities, "tech")[0]
    online = sum(1 for seen in server.ONLINE.values() if now - seen <= server.ONLINE_SECONDS)
    return _embed("Dolphin City Builder", f"In the lead: **{lead['name']}**, a {lead['tech_name']} of {short(lead['population'])} people.",
                  [("Cities", short(len(cities)), True), ("People", short(sum(c["population"] for c in cities)), True),
                   ("Buildings", short(sum(c["buildings"] for c in cities)), True), ("Online now", short(online), True),
                   ("Offers on the market", short(len(server.MARKET["offers"])), True),
                   ("Recent trades", short(len(server.MARKET["history"])), True)],
                  footer=config().get("game_url", ""))


def handle(body, headers, now):
    """Answer a request Discord sent to /api/discord. Returns (status, reply). Called with the server's LOCK held."""
    import server
    settings = config()
    key = settings.get("public_key")
    if not key:
        return 404, {"error": "Discord is not set up on this server."}
    if not verify(key, headers.get("X-Signature-Timestamp") or "", body, headers.get("X-Signature-Ed25519") or ""):
        return 401, {"error": "Bad signature."}
    try:
        request = json.loads(body)
    except ValueError:
        return 400, {"error": "Bad request."}
    if request.get("type") == 1:           # Discord checking that the address works
        return 200, {"type": 1}
    if request.get("type") != 2:
        return 400, {"error": "Not a command."}
    data = request.get("data") or {}
    options = {o.get("name"): o.get("value") for o in data.get("options") or []}
    name = data.get("name")
    if name == "leaderboard":
        return 200, _reply(_leaderboard(server, now, options.get("by") or "tech"))
    if name == "city":
        return 200, _reply(_city(server, now, str(options.get("name") or "")[:24]))
    if name == "market":
        return 200, _reply(_market(server, options.get("material")))
    if name == "online":
        return 200, _reply(_online(server, now))
    if name == "game":
        return 200, _reply(_game(server, now))
    return 200, _reply(_embed("Unknown command", "Try /leaderboard, /city, /market, /online or /game."), private=True)


# ------------------------------------------------------- announcements --

def _post(url, payload, token=None, method="POST"):
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method=method,
                                     headers={"Content-Type": "application/json", "User-Agent": USER_AGENT,
                                              **({"Authorization": f"Bot {token}"} if token else {})})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read()


def announce(text):
    """Post a line to the announcements channel (if a webhook is set), without making the player wait."""
    hook = config().get("webhook")
    if not hook:
        return
    def send():
        try:
            _post(hook, {"content": text[:1900], "allowed_mentions": {"parse": []}})
        except Exception as error:      # Discord unreachable: the game carries on
            print(f"Discord announcement failed: {error}", file=sys.stderr)
    threading.Thread(target=send, daemon=True).start()


# ------------------------------------------------------------- console --

def _setup():
    old = config()
    print("Discord setup. Values come from https://discord.com/developers/applications, your application:")
    print("  General Information: Application ID and Public Key.  Bot: Reset Token (copy it once).")
    print("  An announcements webhook comes from a channel's settings: Integrations, Webhooks, New Webhook, Copy URL.")
    print("Press Enter to keep a value already set.\n")
    asks = [("application_id", "Application ID"), ("public_key", "Public Key"), ("bot_token", "Bot token"),
            ("webhook", "Announcements webhook URL (optional)"), ("game_url", "The game's address, e.g. https://you.pythonanywhere.com")]
    out = dict(old)
    for key, label in asks:
        shown = ("(set)" if key == "bot_token" else old.get(key)) if old.get(key) else ""
        value = input(f"{label} {('[' + shown + ']') if shown else ''}: ").strip()
        if value:
            out[key] = value
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(out, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)    # only you can read the token
    except OSError:
        pass
    print(f"\nSaved to {CONFIG_FILE}.")
    print("Next: python discord_bot.py register, then put this in the bot's Interactions Endpoint URL:")
    print(f"  {out.get('game_url', 'https://<your game>').rstrip('/')}/api/discord")


def _register():
    c = config()
    if not (c.get("application_id") and c.get("bot_token")):
        sys.exit("Run python discord_bot.py setup first.")
    status, body = _post(f"{API}/applications/{c['application_id']}/commands", COMMANDS, token=c["bot_token"], method="PUT")
    print(f"Registered {len(json.loads(body))} slash commands (HTTP {status}): " + ", ".join("/" + x["name"] for x in COMMANDS))
    print("They can take a minute to appear in Discord.")


def _daily():
    """Post today's leaderboard to the announcements channel (for a once-a-day scheduled task).
    Reads the saves on disk, so it does not need the game server; it shows the cities as last saved."""
    import game

    class Saved:      # just enough of server for _leaderboard(), reading the saves
        saves = _data_dir() / "saves"

        @staticmethod
        def all_city_names():
            return sorted(p.stem for p in Saved.saves.glob("*.json"))

        @staticmethod
        def get_city(name, now):
            try:
                return json.loads((Saved.saves / f"{name}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None

    hook = config().get("webhook")
    if not hook:
        sys.exit("No announcements webhook set: run python discord_bot.py setup.")
    status, _ = _post(hook, {"embeds": [_leaderboard(Saved, time.time(), "tech", "Today's leaderboard")], "allowed_mentions": {"parse": []}})
    print(f"Posted today's leaderboard (HTTP {status}).")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "setup":
        _setup()
    elif command == "register":
        _register()
    elif command == "daily":
        _daily()
    elif command == "test":
        announce("Test message from Dolphin City Builder.")
        time.sleep(5)
        print("Sent a test message to the announcements webhook (if one is set).")
    else:
        print(__doc__)
