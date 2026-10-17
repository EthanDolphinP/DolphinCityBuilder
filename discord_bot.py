"""The game on Discord: slash commands answered by the game server, and announcements posted to a channel.

No program has to keep running for this. Discord sends each slash command to
the game's own web address (/api/discord, see handle()), and the game server
answers it from the live cities. Announcements (a new city, a new tech level)
are posted to a channel through a Discord webhook, and a daily leaderboard can
be posted by a scheduled task (`python discord_bot.py daily`).

Setup, once (see README.md, "Discord"):
    python discord_bot.py setup       asks for the bot's keys and writes DATA/discord.json
    python discord_bot.py register    tells Discord about the slash commands (again whenever they change)
After each update of the game:
    python discord_bot.py update ["a message"]   posts what changed (the git commits since the last time)

/claim gives a player the "Land Owner" role (ROLE_NAME) for a city they own. To show it
is theirs they also type the city's link code, which only its own player sees, on the
game's Settings tab (link_code). The bot needs the Manage Roles permission, and its own
role must be above Land Owner in the server's role list.
then set the bot's Interactions Endpoint URL to https://<your game>/api/discord.

The keys live in DATA/discord.json, next to the saves and never in the code, so
they don't end up on GitHub. Without that file, everything here does nothing.

Every request Discord sends is signed: handle() checks the Ed25519 signature
against the bot's public key and refuses anything else. PyNaCl is used for that
when it is installed; otherwise the pure-Python check below (RFC 8032) does it.
"""

import base64
import hashlib
import hmac
import json
import secrets
import subprocess
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/EthanDolphinP/DolphinCityBuilder, 1.0)"
TOP = 10                     # cities in a leaderboard, offers in a market list
COLOUR = 0xE6C35C            # the game's gold, down the side of every embed
ADMINISTRATOR = 0x8           # Discord's permission bit for server administrators
ROLE_NAME = "Land Owner"     # the role /claim gives (made if the server has none by that name)


def _data_dir():
    return Path(os.environ.get("DCB_DATA") or Path(__file__).resolve().parent)


CONFIG_FILE = _data_dir() / "discord.json"


def config():
    """The bot's settings, or {} if Discord has not been set up."""
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(settings):
    CONFIG_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)    # only you can read the token
    except OSError:
        pass


def link_code(city):
    """The code that shows a Discord member owns `city`: only its own player sees it, in the game. None if Discord is not set up."""
    settings = config()
    if not settings.get("public_key"):
        return None
    if not settings.get("link_secret"):          # made once; changing it would change every city's code
        settings["link_secret"] = secrets.token_hex(16)
        _save(settings)
    digest = hmac.new(settings["link_secret"].encode(), city.lower().encode(), hashlib.sha256).digest()
    return base64.b32encode(digest)[:6].decode()


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
    # Admin only: hidden from everyone without the Administrator permission ("default_member_permissions"),
    # and checked again in handle() (is_admin), in case a server changes who may see them.
    {"name": "present", "description": "Admin: send a present to a city, or to every city", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR),
     "options": [{"type": 3, "name": "to", "description": "A city's name, or all", "required": True},
                 {"type": 3, "name": "message", "description": "Shown when the present is opened", "required": True},
                 {"type": 3, "name": "gifts", "description": "e.g. wood=500 gold=200 egg=rare people=5", "required": False}]},
    {"name": "announce", "description": "Admin: post a message to the announcements channel", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR),
     "options": [{"type": 3, "name": "message", "description": "What to say", "required": True}]},
    {"name": "resetpassword", "description": "Admin: let the next person to sign in to a city choose its password", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR),
     "options": [{"type": 3, "name": "city", "description": "The city's name", "required": True}]},
    {"name": "claim", "description": f"Get the {ROLE_NAME} role for your city", "dm_permission": False,
     "options": [{"type": 3, "name": "city", "description": "Your city's name", "required": True},
                 {"type": 3, "name": "code", "description": "The Discord code on your city's Settings tab in the game", "required": True}]},
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
    if name == "claim":
        return 200, _claim(server, now, request, str(options.get("city") or "")[:24], str(options.get("code") or ""))
    if name in ("present", "announce", "resetpassword"):
        if not is_admin(request, settings):
            return 200, _reply(_embed("Not for you", "Only the game's admins can use that."), private=True)
        return 200, _reply(_admin(server, now, name, options), private=True)
    return 200, _reply(_embed("Unknown command", "Try /leaderboard, /city, /market, /online or /game."), private=True)


# ------------------------------------------------------------ admin only --

def is_admin(request, settings):
    """True for a server administrator, or a Discord user listed in admin_ids (python discord_bot.py setup)."""
    member = request.get("member") or {}
    user = (member.get("user") or request.get("user") or {}).get("id")
    if user and user in [str(x) for x in settings.get("admin_ids", [])]:
        return True
    try:
        return bool(int(member.get("permissions") or 0) & ADMINISTRATOR)
    except ValueError:
        return False


def _admin(server, now, name, options):
    """The admin commands. Each answers only the admin who used it."""
    if name == "present":
        words = [str(options.get("to") or "").strip(), str(options.get("message") or "")] + str(options.get("gifts") or "").split()
        # the same checks and wording as `python server.py --present`; it is handed out on the game's next request
        return _embed("Present", server.send_present(words))
    if name == "announce":
        message = str(options.get("message") or "").strip()
        if not message:
            return _embed("Nothing to say", "Write a message.")
        announce(message)
        return _embed("Announced", message[:1000])
    if name == "resetpassword":
        city = str(options.get("city") or "")[:24]
        names = server.all_city_names()
        match = city if city in names else next((n for n in names if n.lower() == city.lower()), None)
        state = server.get_city(match, now) if match else None
        if not state:
            return _embed("No such city", f"There is no city called **{city}**.")
        for key in server.PRIVATE:          # its password and every browser signed in to it
            state.pop(key, None)
        server.DIRTY.add(match)
        server.flush()
        return _embed("Password reset", f"Whoever signs in to **{match}** next chooses its new password. Tell its player to do it soon.")
    return _embed("Unknown command", "")


# ---------------------------------------------------------------- /claim --

def _claim(server, now, request, name, code):
    """Check the city and its code, then give the member the role. The role is given in the background (it
    takes calls to Discord), so the answer is "thinking..." at once, and becomes the result when done."""
    settings = config()
    names = server.all_city_names()
    match = name if name in names else next((n for n in names if n.lower() == name.lower()), None)
    if not match:
        return _reply(_embed("No such city", f"There is no city called **{name}**."), private=True)
    if not hmac.compare_digest(code.strip().upper(), link_code(match) or "-"):
        return _reply(_embed("That code is not right", f"Your city's code is on its **Settings** tab in the game, "
                                                       f"under Discord. Only the player of {match} can see it."), private=True)
    guild, member = request.get("guild_id"), (request.get("member") or {}).get("user", {}).get("id")
    if not (guild and member):
        return _reply(_embed("Use this in the server", "Run /claim in a channel of the Discord server."), private=True)
    if not settings.get("bot_token"):
        return _reply(_embed("Not set up", "The bot has no token: run python discord_bot.py setup."), private=True)
    state = server.get_city(match, now)
    state["discord_user"] = member                 # remembered, for whoever looks after the game
    token, app = request.get("token"), request.get("application_id") or settings.get("application_id")
    threading.Thread(target=_give_role, args=(settings, guild, member, match, app, token), daemon=True).start()
    return {"type": 5, "data": {"flags": 64}}      # "thinking...", seen only by the member


def _give_role(settings, guild, member, city, app, token):
    """Find (or make) the Land Owner role and give it to the member; then say how it went."""
    def call(method, url, payload=None):
        request = urllib.request.Request(f"{API}{url}", data=None if payload is None else json.dumps(payload).encode("utf-8"),
                                         method=method, headers={"Authorization": f"Bot {settings['bot_token']}",
                                                                 "Content-Type": "application/json", "User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read()
            return json.loads(body) if body else None
    role_name = settings.get("role_name") or ROLE_NAME
    try:
        role = next((r for r in call("GET", f"/guilds/{guild}/roles") if r["name"].lower() == role_name.lower()), None)
        if not role:
            role = call("POST", f"/guilds/{guild}/roles", {"name": role_name, "color": COLOUR, "mentionable": True})
        call("PUT", f"/guilds/{guild}/members/{member}/roles/{role['id']}")
        result = _embed(f"Welcome, land owner of {city}", f"You now have the **{role_name}** role.")
    except Exception as error:
        print(f"Discord /claim failed: {error}", file=sys.stderr)
        result = _embed("Could not give the role", f"The bot needs the **Manage Roles** permission, and its own role must be "
                                                   f"above **{role_name}** in the server's role list. ({error})")
    try:
        _post(f"{API}/webhooks/{app}/{token}/messages/@original", {"embeds": [result]}, method="PATCH")
    except Exception as error:
        print(f"Discord /claim reply failed: {error}", file=sys.stderr)


# ------------------------------------------------------- announcements --

class DiscordRefused(Exception):
    """Discord said no; the message says why, in words a person can act on."""


RETRIES = 3          # tries at most, when Discord says to slow down
MAX_WAIT = 30        # seconds: a longer wait than this is given up on


def _post(url, payload, token=None, method="POST"):
    """Send to Discord. When it says "too many requests" (429), wait as long as it asks and try again."""
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(RETRIES):
        request = urllib.request.Request(url, data=data, method=method,
                                         headers={"Content-Type": "application/json", "User-Agent": USER_AGENT,
                                                  **({"Authorization": f"Bot {token}"} if token else {})})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            if error.code != 429:
                raise DiscordRefused(f"Discord refused it (HTTP {error.code}): {body[:300]}") from None
            try:
                wait = float(json.loads(body).get("retry_after", 0))
            except ValueError:      # not Discord's own answer: its firewall blocking this server's address for a while
                raise DiscordRefused(
                    "Discord's firewall is turning this server away for now (HTTP 429). On PythonAnywhere many accounts share "
                    "one address, so this happens from time to time. Wait a few minutes and try again, or run the same command "
                    "on your own computer (python discord_bot.py setup there first).") from None
            wait = max(wait, float(error.headers.get("Retry-After") or 0))
            if wait > MAX_WAIT or attempt == RETRIES - 1:
                raise DiscordRefused(f"Discord asked to wait {wait:.0f} seconds before sending again. Try again in a minute.") from None
            print(f"Discord asked to wait {wait:.1f} seconds; waiting...", file=sys.stderr)
            time.sleep(wait + 0.5)


def announce(text):
    """Post a line to the announcements channel (if a webhook is set), without making the player wait."""
    hook = config().get("webhook")
    if not hook:
        return
    def send():
        try:
            _post(hook, {"content": text[:1900], "allowed_mentions": {"parse": []}})
        except Exception as error:      # Discord unreachable, or refusing: the game carries on
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
            ("webhook", "Announcements webhook URL (optional)"), ("game_url", "The game's address, e.g. https://you.pythonanywhere.com"),
            ("admin_ids", "Discord user IDs allowed the admin commands besides server admins, separated by spaces (optional)")]
    out = dict(old)
    for key, label in asks:
        shown = ("(set)" if key == "bot_token" else " ".join(old[key]) if key == "admin_ids" else old.get(key)) if old.get(key) else ""
        value = input(f"{label} {('[' + shown + ']') if shown else ''}: ").strip()
        if value:
            out[key] = value.split() if key == "admin_ids" else value
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _save(out)
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


def _update(message):
    """Announce an update: the message given, and the commits since the last announcement (or the last five)."""
    settings = config()
    hook = settings.get("webhook")
    if not hook:
        sys.exit("No announcements webhook set: run python discord_bot.py setup.")
    here = Path(__file__).resolve().parent
    def git(*args):
        return subprocess.run(["git", "-C", str(here), *args], capture_output=True, text=True).stdout.strip()
    head = git("rev-parse", "HEAD")
    since = settings.get("last_update")
    span = [f"{since}..HEAD"] if since and git("cat-file", "-t", since) == "commit" else ["-5"]
    changes = [line for line in git("log", "--no-merges", "--format=%s", *span).splitlines() if line.strip()]
    if not changes and not message:
        print("Nothing new since the last announcement. Give a message to announce anyway.")
        return
    lines = "\n".join(f"\u2022 {c}" for c in changes[:15]) + (f"\n...and {len(changes) - 15} more" if len(changes) > 15 else "")
    embed = _embed("\U0001F6E0\uFE0F The game has been updated", (message + "\n\n" if message else "") + (lines or ""),
                   footer=settings.get("game_url") or None)
    status, _ = _post(hook, {"embeds": [embed], "allowed_mentions": {"parse": []}})
    settings["last_update"] = head
    _save(settings)
    print(f"Announced the update (HTTP {status}): {len(changes)} change{'s' if len(changes) != 1 else ''}.")


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


def _main(command):
    if command == "setup":
        _setup()
    elif command == "register":
        _register()
    elif command == "daily":
        _daily()
    elif command == "update":
        _update(" ".join(sys.argv[2:]).strip())
    elif command == "test":
        announce("Test message from Dolphin City Builder.")
        time.sleep(5)
        print("Sent a test message to the announcements webhook (if one is set).")
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        _main(sys.argv[1] if len(sys.argv) > 1 else "")
    except DiscordRefused as why:
        sys.exit(str(why))
    except urllib.error.URLError as why:
        sys.exit(f"Could not reach Discord: {why.reason}. If this is PythonAnywhere's free plan, discord.com may be off its list "
                 f"of allowed sites; try the same command on your own computer.")
