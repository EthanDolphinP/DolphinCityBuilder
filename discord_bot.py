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
                      ("areas", "Areas"), ("beast", "Beast level"), ("quests", "Ideology quests"), ("gold", "Gold"), ("food", "Food"),
                      ("knowledge", "Knowledge"))]}]},
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
    {"name": "tag", "description": "Admin: give a city a tag (Alpha, Beta, ... or any name), or take one back", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR),
     "options": [{"type": 3, "name": "to", "description": "A city's name, or all", "required": True},
                 {"type": 3, "name": "tag", "description": "alpha, beta, founder, developer, moderator, tester, bug_hunter, supporter, event_winner, or any name", "required": True},
                 {"type": 3, "name": "action", "description": "Give it (the default) or take it back", "required": False,
                  "choices": [{"name": "Give", "value": "give"}, {"name": "Take back", "value": "take"}]}]},
    {"name": "announce", "description": "Admin: post a message to the announcements channel", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR),
     "options": [{"type": 3, "name": "message", "description": "What to say", "required": True}]},
    {"name": "resetpassword", "description": "Admin: let the next person to sign in to a city choose its password", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR),
     "options": [{"type": 3, "name": "city", "description": "The city's name", "required": True}]},
    {"name": "renamecity", "description": "Admin: give a city a new name (for a name that is not allowed)", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR),
     "options": [{"type": 3, "name": "city", "description": "The city's name now", "required": True},
                 {"type": 3, "name": "new", "description": "Its new name", "required": True}]},
    {"name": "removecity", "description": "Admin: take a city out of the game (its save is kept aside)", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR),
     "options": [{"type": 3, "name": "city", "description": "The city's name", "required": True}]},
    {"name": "blockword", "description": "Admin: block a word in city names, area names and messages", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR),
     "options": [{"type": 3, "name": "word", "description": "The word (or 'list' to see the ones you added)", "required": True},
                 {"type": 3, "name": "action", "description": "Block it (the default) or unblock it", "required": False,
                  "choices": [{"name": "Block", "value": "add"}, {"name": "Unblock", "value": "remove"}]}]},
    {"name": "badnames", "description": "Admin: list city and area names the filter does not allow", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR)},
    {"name": "profile", "description": "A city's tags, wonders and standing",
     "options": [{"type": 3, "name": "city", "description": "The city's name", "required": True}]},
    {"name": "suggest", "description": "Suggest something for the game (posted in the suggestions forum)", "dm_permission": False,
     "options": [{"type": 3, "name": "title", "description": "Your idea in a few words", "required": True, "max_length": 90},
                 {"type": 3, "name": "details", "description": "What it is and why it would be good", "required": True, "max_length": 1500}]},
    {"name": "bug", "description": "Report a bug (posted in the bug forum, with your city and the game's version)", "dm_permission": False,
     "options": [{"type": 3, "name": "title", "description": "What went wrong, in a few words", "required": True, "max_length": 90},
                 {"type": 3, "name": "details", "description": "What you did, what happened, and what you expected", "required": True, "max_length": 1500}]},
    {"name": "setforum", "description": "Admin: choose the forum channel /suggest or /bug posts go to", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR),
     "options": [{"type": 3, "name": "kind", "description": "Which command", "required": True,
                  "choices": [{"name": "Suggestions (/suggest)", "value": "suggest"}, {"name": "Bugs (/bug)", "value": "bug"}]},
                 {"type": 7, "name": "channel", "description": "The forum channel", "required": True, "channel_types": [15]}]},
    {"name": "claimtag", "description": "Admin: a game tag everyone gets when they /claim their city (e.g. alpha), or off", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR),
     "options": [{"type": 3, "name": "tag", "description": "alpha, beta, ... any name, or off", "required": True}]},
    {"name": "syncroles", "description": "Admin: give every claimed city's player the roles for its tech level and ideology", "dm_permission": False,
     "default_member_permissions": str(ADMINISTRATOR)},
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
    if hasattr(server, "leaderboard"):      # the running game: its leaderboard, worked out at most every few seconds
        return server.leaderboard(now)
    import game
    return [game.summary(c) for c in (server.get_city(n, now) for n in server.all_city_names()) if c]


def _value(c, key):
    return c["resources"].get(key, 0) if key in c["resources"] else c.get(key, 0)


def _ranked(cities, key):
    return sorted(cities, key=lambda c: (-_value(c, key), -c["tech"], -c["population"], c["name"]))


LABELS = {"tech": "Tech level", "population": "Population", "buildings": "Buildings", "research": "Research",
          "areas": "Areas", "beast": "Beast level", "quests": "Ideology quests"}


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
    online = server.presence(c["name"], now)
    stores = sorted(c["resources"].items(), key=lambda kv: -kv[1])
    return _embed(f"{c['name']}" + {"online": " \U0001F7E2", "idle": " \U0001F319"}.get(online, ""),
                  f"A **{c['tech_name']}**" + (f" following **{c['ideology']}**" if c["ideology"] else "") + f". Rank #{rank} of {len(cities)}.",
                  [("Population", short(c["population"]), True), ("Buildings", short(c["buildings"]), True),
                   ("Research", short(c["research"]) + (f" (incl. {short(c['mastery'])} Mastery)" if c.get("mastery") else ""), True), ("Areas", short(c["areas"]), True),
                   ("Best beast", f"level {c['beast']}" if c["beast"] else "none yet", True),
                   ("Online", {"online": "yes", "idle": "idle (game open, not in use)"}.get(online, "no"), True),
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
    online = sorted(n for n in server.ONLINE if server.presence(n, now) == "online")
    idle = sorted(n for n in server.ONLINE if server.presence(n, now) == "idle")
    lines = [f"\U0001F7E2 {n}" for n in online] + [f"\U0001F319 {n} *(idle)*" for n in idle]
    return _embed("Online now", "\n".join(lines) or "Nobody has the game open right now.",
                  footer=f"{len(online)} online, {len(idle)} idle")


def _game(server, now):
    cities = _cities(server, now)
    if not cities:
        return _embed("Dolphin City Builder", "No cities yet.")
    lead = _ranked(cities, "tech")[0]
    online = sum(1 for n in server.ONLINE if server.presence(n, now) == "online")
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
    if name == "profile":
        return 200, _reply(_profile(server, now, str(options.get("city") or "")[:24]))
    if name in ("suggest", "bug"):
        return 200, _forum_post(server, now, request, name, str(options.get("title") or ""), str(options.get("details") or ""))
    if name in ("present", "tag", "setforum", "claimtag", "syncroles", "announce", "resetpassword", "renamecity", "removecity", "blockword", "badnames"):
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
    if name == "setforum":
        settings = config()
        settings[f"{options.get('kind')}_forum"] = str(options.get("channel") or "")
        _save(settings)
        return _embed("Forum chosen", f"/{options.get('kind')} now posts in <#{options.get('channel')}>. The bot needs to see it and create posts there.")
    if name == "claimtag":
        settings, tag = config(), str(options.get("tag") or "").strip()[:30]
        if tag.lower() in ("off", "none", ""):
            settings.pop("claim_tag", None)
            _save(settings)
            return _embed("Claim tag off", "Claiming a city gives no tag now.")
        settings["claim_tag"] = tag
        _save(settings)
        return _embed("Claim tag set", f"Everyone who claims their city from now on gets the **{tag}** tag. For cities claimed "
                                       f"before, use /tag with to: all, or `dolphincity tag all {tag}`.")
    if name == "syncroles":
        pairs = []
        for user, city in members()["cities"].items():
            state = server.get_city(city, now)
            if state:
                pairs.append((user, city_roles(state)))
        sync_roles(pairs)
        return _embed("Roles", f"Giving {len(pairs)} players the roles for their city's tech level and ideology. This takes a minute.")
    if name == "tag":
        words = [str(options.get("to") or "").strip(), str(options.get("tag") or "").strip()]
        return _embed("Tag", server.send_tag(words, take=options.get("action") == "take"))
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
    if name == "renamecity":
        city, new = str(options.get("city") or "")[:24], str(options.get("new") or "").strip()[:24]
        error = server.rename_city(city, new, now)
        if error:
            return _embed("Not renamed", error)
        return _embed("Renamed", f"That city is now called **{new}**, everywhere in the game. Its player signs in "
                                 f"with the new name and the same password.")
    if name == "removecity":
        removed, error = server.remove_city(str(options.get("city") or "")[:24], now)
        if error:
            return _embed("Not removed", error)
        return _embed("Removed", f"**{removed}** is out of the game. Its save was moved to the removed folder, not "
                                 f"deleted, and its market offers are gone.")
    if name == "blockword":
        import moderation
        word, action = moderation.plain(str(options.get("word") or ""))[:40], options.get("action") or "add"
        words = moderation.extra_words()
        if str(options.get("word") or "").strip().lower() == "list":
            return _embed("Words you blocked", ", ".join(f"||{w}||" for w in words) or "None yet (the built-in list still applies).")
        if len(word) < 3:
            return _embed("Too short", "Give a word of at least 3 letters.")
        words = sorted(set(words) - {word}) if action == "remove" else sorted(set(words) | {word})
        Path(moderation.EXTRA_FILE).write_text(json.dumps(words, indent=1), encoding="utf-8")
        flagged = [f"{c} ({what}: {n})" for c, what, n in server.flagged_names(now)]
        return _embed("Unblocked" if action == "remove" else "Blocked",
                      f"||{word}|| is {'allowed again' if action == 'remove' else 'blocked'} in names and messages." +
                      (f"\nNames that are not allowed now: {', '.join(flagged)[:900]}. Use /renamecity." if flagged else ""))
    if name == "badnames":
        flagged = server.flagged_names(now)
        return _embed("Names not allowed", "\n".join(f"**{c}** - {what}: ||{n}||" for c, what, n in flagged)[:3900]
                      or "Every city and area name is fine.")
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
    known = members()
    known["guild"] = guild
    known["cities"] = {u: c for u, c in known["cities"].items() if c != match}
    known["cities"][str(member)] = match
    _store(MEMBERS_FILE, known)
    claim_tag = settings.get("claim_tag")
    if claim_tag:
        import tags
        tag_id = claim_tag if claim_tag in tags.GIVEN else "custom_" + tags._slug(claim_tag)
        if tag_id not in state.get("tags", {}).get("have", {}):
            tags.give(state, now, claim_tag)
    server.DIRTY.add(match)
    sync_roles([(str(member), city_roles(state))])
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


# ------------------------------------------------------ game-side extras --
# Files next to discord.json, written by the game server:
#   discord_members.json  {Discord user id: city} for every /claim, and the server's id ("guild")
#   discord_firsts.json   which "first in the game" milestones have happened, so each is posted once
#   discord_weekly.json   last week's numbers for every city, for the weekly recap

MEMBERS_FILE = _data_dir() / "discord_members.json"
FIRSTS_FILE = _data_dir() / "discord_firsts.json"
WEEKLY_FILE = _data_dir() / "discord_weekly.json"
WEEK = 7 * 24 * 3600
WEEKLY_AT = (6, 17)          # Sunday (weekday 6), 17:00 UTC: when the weekly recap is posted
ROLE_COLOURS = [0x95A5A6, 0x7F8C8D, 0x3498DB, 0x2ECC71, 0x9B59B6, 0xE6C35C]     # Tribe ... Megacity


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _store(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def members():
    return _load(MEMBERS_FILE, {"guild": None, "cities": {}})


def member_city(user):
    return members()["cities"].get(str(user))


def first(key):
    """True the first time `key` happens in the whole game (and remembers it)."""
    seen = _load(FIRSTS_FILE, {})
    if key in seen:
        return False
    seen[key] = time.time()
    _store(FIRSTS_FILE, seen)
    return True


def _call(settings, method, url, payload=None):
    """One call to Discord's API as the bot."""
    request = urllib.request.Request(f"{API}{url}", data=None if payload is None else json.dumps(payload).encode("utf-8"),
                                     method=method, headers={"Authorization": f"Bot {settings['bot_token']}",
                                                             "Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read()
        return json.loads(body) if body else None


# ---- roles that follow the game: one for the tech level, one for the ideology ----

def _role_names():
    import game
    import ideology
    tech = [(lvl["name"], ROLE_COLOURS[i % len(ROLE_COLOURS)]) for i, lvl in enumerate(game.TECH_LEVELS)]
    ideo = [(i["name"], int(ideology.COLOURS[k].lstrip("#"), 16)) for k, i in ideology.IDEOLOGIES.items()]
    return tech, ideo


def city_roles(state):
    """The names of the roles a city's player should have: its tech level and its ideology."""
    import game
    import ideology
    out = [game.TECH_LEVELS[state["tech"]]["name"]]
    if ideology.chosen(state):
        out.append(ideology.chosen(state)["name"])
    return out


def sync_roles(pairs):
    """Give each (Discord user, wanted role names) the roles for their city, taking away the other tech and
    ideology roles. In the background: it takes calls to Discord, and the game must not wait for them."""
    settings, guild = config(), members().get("guild")
    if not (settings.get("bot_token") and guild and pairs) or settings.get("auto_roles") == "off":
        return
    def run():
        try:
            tech, ideo = _role_names()
            managed = {n.lower(): colour for n, colour in tech + ideo}
            roles = {r["name"].lower(): r for r in _call(settings, "GET", f"/guilds/{guild}/roles")}
            for user, wanted in pairs:
                for name in wanted:
                    if name.lower() not in roles:
                        roles[name.lower()] = _call(settings, "POST", f"/guilds/{guild}/roles",
                                                    {"name": name, "color": managed.get(name.lower(), COLOUR), "hoist": False})
                try:
                    have = set(_call(settings, "GET", f"/guilds/{guild}/members/{user}")["roles"])
                except urllib.error.HTTPError:
                    continue            # no longer in the server
                want = {roles[n.lower()]["id"] for n in wanted}
                for name in managed:
                    role = roles.get(name)
                    if not role:
                        continue
                    if role["id"] in want and role["id"] not in have:
                        _call(settings, "PUT", f"/guilds/{guild}/members/{user}/roles/{role['id']}")
                    elif role["id"] in have and role["id"] not in want:
                        _call(settings, "DELETE", f"/guilds/{guild}/members/{user}/roles/{role['id']}")
        except Exception as error:
            print(f"Discord roles failed: {error}. The bot needs Manage Roles, and its role above the tech and ideology roles.",
                  file=sys.stderr)
    threading.Thread(target=run, daemon=True).start()


def sync_city(name, state):
    """After a city's tech level or ideology changed: its player's roles follow."""
    users = [u for u, c in members()["cities"].items() if c == name]
    if users:
        sync_roles([(u, city_roles(state)) for u in users])


# ---- milestones posted to the announcements channel ----

def milestone_wonder(city, state, bid):
    """A city built a wonder: the first of its kind in the game, or (from Metropolis up) its own first."""
    import game
    b = game.BUILDINGS[bid]
    if first("wonder:" + bid):
        announce(f"\U0001F3DB️ **{city}** has built the first **{b['name']}** in the game!")
    elif b["tech"] >= 4 and game.wonder_counts(state).get(bid, 0) == 1:
        announce(f"\U0001F3DB️ **{city}** has built a **{b['name']}**.")


def milestone_quests(city, state, done):
    """A city finished an ideology quest: every fifth is posted, and the first city to reach each number."""
    import ideology
    ideo = ideology.chosen(state)
    word = ideo["quest_plural"] if ideo else "quests"
    if done % 5 == 0 and first(f"quests:{done}"):
        announce(f"\U0001F3C6 **{city}** is the first city to complete **{done} {word.lower()}**!")
    elif done % 5 == 0:
        announce(f"\U0001F3C6 **{city}** has completed **{done} {word.lower()}**.")


def milestone_tags(city, earned):
    """New tags: the first city to earn each rare-or-better tag, and every epic or legendary one."""
    import tags
    for tag_id in earned:
        t = tags.TAGS.get(tag_id)
        if not t or t["rarity"] in ("common", "uncommon"):
            continue
        if first("tag:" + tag_id):
            announce(f"\U0001F3F7️ **{city}** is the first city to earn the **{t['name']}** tag ({t['how'].lower()})!")
        elif t["rarity"] in ("epic", "legendary"):
            announce(f"\U0001F3F7️ **{city}** has earned the {t['rarity']} tag **{t['name']}** ({t['how'].lower()}).")


# ---- the weekly recap ----

def _snapshot(cities):
    return {c["name"]: {k: c.get(k, 0) for k in ("tech", "population", "research", "buildings", "quests", "wonders", "areas")}
            for c in cities}


def weekly_embed(cities, before):
    """This week in the game, from every city's summary now and last week's numbers."""
    import game
    now = _snapshot(cities)
    new = [n for n in now if n not in before]
    grew = lambda key: sorted(((now[n][key] - before[n].get(key, 0), n) for n in now if n in before), reverse=True)
    lines = []
    ups = [(n, now[n]["tech"]) for n in now if n in before and now[n]["tech"] > before[n].get("tech", 0)]
    if ups:
        lines.append("**New tech levels:** " + ", ".join(f"{n} ({game.TECH_LEVELS[t]['name']})" for n, t in ups[:10]))
    if new:
        lines.append(f"**New cities:** {', '.join(new[:10])}" + (f" and {len(new) - 10} more" if len(new) > 10 else ""))
    for key, label in (("population", "Most new people"), ("research", "Most research done"), ("buildings", "Most building"),
                       ("quests", "Most ideology quests"), ("wonders", "Most wonders raised")):
        top = [(d, n) for d, n in grew(key) if d > 0][:3]
        if top:
            lines.append(f"**{label}:** " + ", ".join(f"{n} (+{short(d)})" for d, n in top))
    lead = _ranked(cities, "tech")[:3]
    lines.append("**At the top:** " + ", ".join(f"{c['name']} ({c['tech_name']}, {short(c['population'])} people)" for c in lead))
    total = sum(c["population"] for c in cities)
    return _embed("\U0001F4F0 This week in Dolphin City", "\n".join(lines) or "A quiet week.",
                  footer=f"{len(cities)} cities, {short(total)} people in all")


def weekly_due(now):
    """True when a weekly recap is due (and remembers it). The first time, it only takes the numbers."""
    import datetime
    data = _load(WEEKLY_FILE, None)
    t = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
    day, hour = WEEKLY_AT
    mark = (t - datetime.timedelta(days=(t.weekday() - day) % 7)).replace(hour=hour, minute=0, second=0, microsecond=0)
    if mark > t:
        mark -= datetime.timedelta(days=7)
    return data is None or data.get("at", 0) < mark.timestamp()


def weekly(cities, now, post=True):
    """Post the recap (if `post` and there are last week's numbers) and keep this week's numbers for the next."""
    data = _load(WEEKLY_FILE, None)
    if post and data and config().get("webhook"):
        embed = weekly_embed(cities, data.get("cities", {}))
        hook = config()["webhook"]
        def send():
            try:
                _post(hook, {"embeds": [embed], "allowed_mentions": {"parse": []}})
            except Exception as error:
                print(f"Discord weekly recap failed: {error}", file=sys.stderr)
        threading.Thread(target=send, daemon=True).start()
    _store(WEEKLY_FILE, {"at": now, "cities": _snapshot(cities)})


# ---- /suggest and /bug: a post in a forum channel ----

def _forum_post(server, now, request, kind, title, details):
    settings = config()
    forum = settings.get(f"{kind}_forum")
    if not forum:
        return _reply(_embed("Not set up yet", f"An admin has to choose the forum first, with /setforum."), private=True)
    if not settings.get("bot_token"):
        return _reply(_embed("Not set up", "The bot has no token: run python discord_bot.py setup."), private=True)
    user = ((request.get("member") or {}).get("user") or request.get("user") or {}).get("id")
    city = member_city(user) if user else None
    try:
        version = server.page()["version"][:10]
    except Exception:
        version = "unknown"
    footer = [f"From <@{user}>" if user else "", f"City: **{city}**" if city else "City: not claimed (/claim)",
              f"Game version {version}" if kind == "bug" else ""]
    content = f"{details.strip()}\n\n-# " + " · ".join(x for x in footer if x)
    token, app = request.get("token"), request.get("application_id") or settings.get("application_id")
    guild = request.get("guild_id")
    def run():
        try:
            thread = _call(settings, "POST", f"/channels/{forum}/threads",
                           {"name": title.strip()[:100] or "Untitled", "message": {"content": content[:1900], "allowed_mentions": {"parse": []}}})
            link = f"https://discord.com/channels/{guild}/{thread['id']}"
            result = _embed("Posted", f"Thanks! It is here: {link}")
        except Exception as error:
            print(f"Discord /{kind} failed: {error}", file=sys.stderr)
            result = _embed("Could not post it", f"The bot needs to be able to see the forum and create posts in it. ({error})")
        try:
            _post(f"{API}/webhooks/{app}/{token}/messages/@original", {"embeds": [result]}, method="PATCH")
        except Exception as error:
            print(f"Discord /{kind} reply failed: {error}", file=sys.stderr)
    threading.Thread(target=run, daemon=True).start()
    return {"type": 5, "data": {"flags": 64}}


# ---- /profile ----

def _profile(server, now, name):
    import game
    import tags
    names = server.all_city_names()
    match = name if name in names else next((n for n in names if n.lower() == str(name).lower()), None)
    state = server.get_city(match, now) if match else None
    if not state:
        return _embed("No such city", f"There is no city called **{name}**. Names are as on the leaderboard.")
    c = game.summary(state)
    cities = _cities(server, now)
    rank = 1 + sum(1 for o in cities if (o["tech"], o["population"]) > (c["tech"], c["population"]))
    shown = c.get("tags", [])
    tag_text = (", ".join(f"**{t[0]}**" for t in shown[:3]) + (f" and {len(shown) - 3} more" if len(shown) > 3 else "")) if shown else "none yet"
    counts = game.wonder_counts(state)
    wonders = ", ".join(f"{game.BUILDINGS[b]['name']}" + (f" x{n}" if n > 1 else "") for b, n in counts.items()) or "none yet"
    rare = sum(1 for t in shown if t[1] in ("epic", "legendary", "special"))
    return _embed(f"{c['name']}", f"A **{c['tech_name']}**" + (f" following **{c['ideology']}**" if c["ideology"] else "") +
                  f". Rank #{rank} of {len(cities)}.",
                  [("Tags", f"{tag_text}\n-# {len(shown)} in all" + (f", {rare} of them epic, legendary or special" if rare else ""), False),
                   ("Wonders", wonders, False),
                   ("Ideology quests", short(c.get("quests", 0)), True), ("Population", short(c["population"]), True),
                   ("Research", short(c["research"]), True), ("Areas", short(c["areas"]), True)])


# ------------------------------------------------------------- console --

def _setup():
    old = config()
    print("Discord setup. Values come from https://discord.com/developers/applications, your application:")
    print("  General Information: Application ID and Public Key.  Bot: Reset Token (copy it once).")
    print("  An announcements webhook comes from a channel's settings: Integrations, Webhooks, New Webhook, Copy URL.")
    print("Press Enter to keep a value already set.\n")
    asks = [("application_id", "Application ID"), ("public_key", "Public Key"), ("bot_token", "Bot token"),
            ("webhook", "Announcements webhook URL (optional)"), ("game_url", "The game's address, e.g. https://yourname.duckdns.org"),
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
    elif command == "weekly":       # post the weekly recap now (the game posts one itself every Sunday)
        import game
        saves = _data_dir() / "saves"
        cities = [game.summary(s) for s in (_load(p, None) for p in sorted(saves.glob("*.json"))) if s]
        weekly(cities, time.time())
        time.sleep(5)
        print("Posted the weekly recap (if there were last week's numbers; otherwise it took this week's, for next time).")
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
