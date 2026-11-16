"""Adventures: a party of heroes, raised and equipped from what the city makes, goes into the lands the city has
explored, with the city's active beast fighting beside them.

Heroes (state["adventure"]["heroes"]) are recruited one at a time, each of a class (CLASSES), for food, gold and
tools that cost more for every hero the city already has. Each has four stats, rolled once like a beast's, that grow
with its level (experience from adventures and battles) and with its three pieces of gear (weapon, armour, charm),
which the city upgrades with its materials, a level at a time.

Up to PARTY_SIZE[tech level] heroes go out at once, with the active beast if it has hatched. Every area the city
holds is somewhere to go: the further from home, the harder, and every win there opens the next delve (depth)
deeper in, harder again and richer. An adventure takes time; when it is over the fight is fought (team_fight) and
the party comes home with materials (more the bigger the city: see _loot), experience for every hero and the beast,
and sometimes a beast egg or an artifact. A beaten party comes home with nothing much and rests a while first.

In the ranked arena (arena.py) a city's Party 1 fights other cities' Party 1 for rank points.

What makes a party stronger, faster or richer is the city's adventure bonuses ("adv_*" below), which come from
the same places as everything else: buildings and their additions, the ideology (and its perks, rituals and trees),
Cauldron brews, enshrined artifacts and, for experience, the city's trained people. A hex that slows a city's
expeditions slows its adventures too.

state["adventure"] = {"next_id", "heroes": [hero], "party": [hero ids], "trip": None or {...}, "depth": {area: n},
                      "reports": [...], "rest": time the party may set out again}
hero = {"id", "name", "cls", "level", "xp", "stats": {"hp", "atk", "def", "spd"}, "gear": {"weapon", "armor", "charm"}}

`game` imports this module and this module uses `game`, so nothing here may touch `game` at import time.
"""
import math
import random

import beasts
import ideology

MIN, HOUR = 60, 3600
OPENS_TECH = 2                     # a Town (see game.FEATURES)
PARTY_SIZE = [0, 0, 3, 4, 5, 6]    # heroes who go out together, by tech level
BASE_HEROES = 6                    # heroes a city can keep (more from buildings: "hero_slots")
BENCH_SLOTS = 6                    # heroes in no party (they don't fight), on top of hero_cap
MAX_PARTIES = 6                    # parties out at once: 1, and 1 more for each "adv_parties" (adventure buildings)
STAT_SPREAD = 0.15                 # a hero's stats are rolled within this of its class's
LEVEL_STEP = 0.07                  # every level past the first: all stats this much more
MAX_LEVEL = 200
GEAR_GROWTH = 1.45                 # every gear level costs this many times the one before
GEAR_CAP = [0, 0, 10, 20, 35, 60]  # highest gear level, by tech level
RECRUIT_COST = {"food": 400, "gold": 200, "tools": 30}
RECRUIT_GROWTH = 1.6               # every hero the city has makes the next cost this many times as much
STAT_NAMES = ("hp", "atk", "def", "spd")    # Health, Attack, Defense, Speed (as a beast's)

# The classes. stats: (health, attack, defense, speed). role: what the class does besides fighting:
#   guard    enemies strike it first (most of the time)
#   scout    every one in the party makes adventures SCOUT_SPEED quicker
#   splash   each blow also hits a second enemy for SPLASH of the damage
#   heal     mends the most hurt ally (HEAL_SHARE of its attack) instead of attacking, when one is under HEAL_BELOW
#   loot     harder to hit (ROGUE_DODGE), and every one in the party brings home ROGUE_LOOT more
#   inspire  every one in the party gives it BARD_XP more experience and BARD_ATK more attack
CLASSES = {
    "warrior": {"name": "Warrior", "stats": (110, 14, 16, 8), "role": "guard",
                "desc": "Heavy armour and a big shield. Enemies strike warriors first."},
    "ranger": {"name": "Ranger", "stats": (70, 17, 9, 18), "role": "scout",
               "desc": "Knows every path: each ranger in the party makes adventures 8% quicker."},
    "mage": {"name": "Mage", "stats": (55, 24, 6, 12), "role": "splash",
             "desc": "Every spell also hits a second enemy for 40% as much."},
    "cleric": {"name": "Cleric", "stats": (75, 10, 11, 10), "role": "heal",
               "desc": "Mends the most hurt friend instead of attacking, whenever one is below 60% health."},
    "rogue": {"name": "Rogue", "stats": (65, 16, 8, 22), "role": "loot",
              "desc": "Hard to hit, and light-fingered: each rogue in the party brings home 10% more loot."},
    "bard": {"name": "Bard", "stats": (60, 11, 9, 14), "role": "inspire",
             "desc": "Songs on the road: each bard gives the party 10% more experience and 5% more attack."},
}
SCOUT_SPEED, SPLASH, HEAL_SHARE, HEAL_BELOW = 0.08, 0.4, 0.6, 0.6
ROGUE_DODGE, ROGUE_LOOT, BARD_XP, BARD_ATK = 0.1, 0.1, 0.1, 0.05
GUARD_PULL = 0.7                  # how often an enemy strikes a guard when there is one standing

# Gear: each level adds this much of the hero's own stat (0.08 = 8% per level), and costs `cost` x GEAR_GROWTH ** level;
# from level 10 the weapon and charm need electronics too ("late").
GEAR = {
    "weapon": {"name": "Weapon", "stats": {"atk": 0.08}, "cost": {"ore": 60, "tools": 20},
               "late": {"electronics": 3}, "desc": "Sharper, heavier, better balanced."},
    "armor": {"name": "Armour", "stats": {"hp": 0.06, "def": 0.08}, "cost": {"stone": 80, "ore": 30, "livestock": 1},
              "desc": "Plate, mail and good leather."},
    "charm": {"name": "Charm", "stats": {"spd": 0.06, "hp": 0.02, "atk": 0.02, "def": 0.02}, "cost": {"gold": 60, "knowledge": 30},
              "late": {"electronics": 2}, "desc": "Lucky trinkets and old wards."},
}
LATE_GEAR = 10

# The bonuses (see ideology.describe for their words). adv_cost x makes recruits and gear cost 1 / (1 + x).
BONUSES = ("adv_power", "adv_speed", "adv_loot", "adv_xp", "adv_heal", "adv_beast", "adv_cost")

# ---- adventures ----
ADV_TIME = 30 * MIN               # the closest delve; every step out or delve deeper takes longer (see trip_time)
TIME_STEP = 0.3                   # ...this much longer per step of distance or depth
REST_TIME = HOUR                  # a beaten party rests this long (longer the harder it was) before setting out again
ENEMY_BASE = (55, 11, 7, 10)      # one enemy at distance 0, depth 0
ENEMY_GROWTH = 1.22               # every step of distance or depth: enemies this much stronger...
ENEMY_TECH = [1, 1, 1, 1.25, 1.5, 1.8]    # ...and in the lands of a bigger city (it holds richer, wilder land)
LOOT_HOURS = 1.0                  # loot of each kind: at least this many hours of what the city makes of it...
LOOT_HOURS_STEP = 0.2             # ...plus this per step
LOOT_BASE = {"food": 80, "wood": 60, "stone": 50, "ore": 40, "gold": 40, "tools": 15, "knowledge": 25,
             "livestock": 2, "electronics": 3}
LOOT_TECH = [1, 1, 2, 4, 8, 15]   # the plain amounts, by tech level
LOOT_STEP = 1.3                   # the plain amounts grow this much per step
LOOT_KINDS = 3                    # kinds of material in each haul
HERO_XP = 30                      # experience for every hero on a won adventure, at distance 0...
HERO_XP_STEP = 1.2                # ...times this per step
LOST_XP = 0.25                    # a lost adventure gives this share of it
BEAST_XP = 4                      # experience for the beast on a won adventure (a beast mission gives 10)
EGG_CHANCE, EGG_STEP, EGG_MAX = 0.04, 0.01, 0.25
ART_CHANCE, ART_STEP, ART_MAX = 0.02, 0.005, 0.10
ART_ROLL_POWER = 6                # artifacts found on adventures roll a little better than crafted ones (8)
REPORTS_KEPT = 10

# The enemies, weakest first: which come out depends on how hard the delve is. (name, role)
ENEMIES = ["Goblin", "Giant Rat", "Bandit", "Wolf", "Skeleton", "Bog Lurker", "Orc", "Harpy", "Troll", "Wraith",
           "Ogre", "Stone Golem", "Wyvern", "Basilisk", "Minotaur", "Lich", "Hill Giant", "Chimera", "Iron Colossus",
           "Dragonkin", "Elder Wyrm", "Titan"]
LAIRS = ["Old Ruins", "Bandit Camp", "Sunken Crypt", "Goblin Warren", "Haunted Barrow", "Troll Bridge", "Lost Mine",
         "Witch's Hollow", "Drowned Temple", "Giant's Steps", "Dragon's Roost", "Forgotten Vault"]
FIRST_NAMES = ["Aldric", "Bryn", "Cass", "Dorian", "Elsa", "Fenn", "Greta", "Hollis", "Isolde", "Jory", "Kael", "Lira",
               "Marek", "Nessa", "Oren", "Petra", "Quill", "Rowan", "Sable", "Tamsin", "Ulric", "Vera", "Wren", "Yara",
               "Zeke", "Ansel", "Brielle", "Corwin", "Dagny", "Edric", "Fiora", "Gideon", "Hesper", "Ivo", "Juno"]

# ---- arena fights (see arena.py) ----
BATTLE_XP = 10                    # experience for every hero of the winning party
FIGHT_ROUNDS = 60


def _store(state):
    store = state.setdefault("adventure", {"next_id": 1, "heroes": [], "parties": [_new_party()], "beast_party": 0,
                                           "depth": {}, "reports": []})
    if "parties" not in store:
        migrate(state)
    return store


def _new_party():
    return {"heroes": [], "trip": None, "rest": 0}


# ---- parties ----
# The heroes can be split into several parties (as many as parties_allowed), each going out, fighting and resting
# on its own; or put together in one for a harder lair. Each party holds up to party_size heroes. Party 1 is the one
# that fights other cities' parties. The active beast goes with one party (store["beast_party"]).

def parties_allowed(state):
    import game
    return max(1, min(MAX_PARTIES, 1 + int(game.city_stat(state, "adv_parties"))))


def parties(state):
    """The city's parties, as many as it is allowed (a party past that, once home, is broken up)."""
    store = _store(state)
    ps = store["parties"]
    allowed = parties_allowed(state)
    while len(ps) < allowed:
        ps.append(_new_party())
    while len(ps) > allowed and not ps[-1]["trip"]:
        ps.pop()
    if store.get("beast_party", 0) >= len(ps):
        store["beast_party"] = 0
    return ps


def party_of(state, hero_id):
    """The index of the party this hero is in, or None (staying home)."""
    return next((n for n, p in enumerate(_store(state)["parties"]) if hero_id in p["heroes"]), None)


def away_ids(state):
    return {i for p in _store(state)["parties"] if p["trip"] for i in p["trip"]["party"]}


def _party_name(n):
    return f"Party {n + 1}"


def away(state):
    """A trip under way, or None (the first one found)."""
    return next((p["trip"] for p in _store(state)["parties"] if p["trip"]), None)


def resting(state, now, n=0):
    ps = _store(state)["parties"]
    rest = ps[n].get("rest", 0) if n < len(ps) else 0
    return rest if rest > now else 0


def call_home(store):
    """Every party home at once, rested (the heroes are moving to a vassal city)."""
    for p in store.get("parties", []):
        p.update(trip=None, rest=0)


def bonus(state, key):
    """One of the city's adventure bonuses: buildings, ideology, brews and artifacts (game.city_stat), and for
    experience its trained people too."""
    import beasts
    import game
    x = game.city_stat(state, key) + beasts.bonus(state, key)
    if key == "adv_xp":
        x += game.training_bonus(state)
    return x


def bonus_sources(state):
    """{bonus: [(where it comes from, amount)]}, for the page's breakdown."""
    import artifacts
    import beasts
    import cauldron
    import game
    totals = game._tile_totals(state)
    parts = [("Buildings", lambda k: totals.get(k, 0))]
    ideo = ideology.chosen(state)
    if ideo:
        own = ideology.own_effects(state)
        parts.append((ideo["name"], lambda k: own.get(k, 0)))
    brews, arts = cauldron.effects(state), artifacts.effects(state)
    parts += [("Cauldron", lambda k: brews.get(k, 0)), ("Artifacts", lambda k: arts.get(k, 0))]
    out = {}
    for key in BONUSES:
        rows = [(name, round(get(key), 3)) for name, get in parts if get(key)]
        if beasts.bonus(state, key):
            rows.append(("Active beast", round(beasts.bonus(state, key), 3)))
        if key == "adv_xp" and game.training_bonus(state):
            rows.append(("Trained people", round(game.training_bonus(state), 3)))
        out[key] = rows
    return out


def _cheaper(state, cost):
    k = 1 + bonus(state, "adv_cost")
    return {r: max(1, math.ceil(v / k)) if r != "livestock" else max(1, round(v / k)) for r, v in cost.items()}


def get(state, hero_id):
    return next((h for h in _store(state)["heroes"] if h["id"] == hero_id), None)


def hero_cap(state):
    """Heroes the city can keep, bench included."""
    import game
    return BASE_HEROES + int(game.city_stat(state, "hero_slots")) + BENCH_SLOTS


def bench(state):
    """The heroes in no party."""
    placed = {i for p in _store(state)["parties"] for i in p["heroes"]}
    return [h["id"] for h in _store(state)["heroes"] if h["id"] not in placed]


def party_size(state):
    return PARTY_SIZE[min(state["tech"], len(PARTY_SIZE) - 1)]


def recruit_cost(state):
    n = len(_store(state)["heroes"])
    return _cheaper(state, {k: _nice(v * RECRUIT_GROWTH ** n) for k, v in RECRUIT_COST.items()})


def gear_cost(state, hero, slot):
    lvl = hero["gear"][slot]
    g = GEAR[slot]
    cost = {k: v * GEAR_GROWTH ** lvl for k, v in g["cost"].items()}
    if lvl >= LATE_GEAR:
        for k, v in g.get("late", {}).items():
            cost[k] = cost.get(k, 0) + v * GEAR_GROWTH ** (lvl - LATE_GEAR)
    return _cheaper(state, {k: _nice(v) for k, v in cost.items()})


def gear_cap(state):
    return GEAR_CAP[min(state["tech"], len(GEAR_CAP) - 1)]


def _nice(x):
    step = 1 if x < 50 else 5 if x < 500 else 10 if x < 5000 else 50 if x < 50000 else 500
    return max(1, int(round(x / step)) * step)


def xp_needed(level):
    return round(40 * 1.22 ** (level - 1))


# ---- the fighters ----

def _roles(state, ids):
    roles = {}
    for h in (get(state, i) for i in ids):
        if h:
            roles[CLASSES[h["cls"]]["role"]] = roles.get(CLASSES[h["cls"]]["role"], 0) + 1
    return roles


def hero_stats(state, hero, inspire=0):
    """A hero's stats now: rolled, times its level, its gear and the city's party bonus (and its bards' songs)."""
    level = 1 + LEVEL_STEP * (hero["level"] - 1)
    power = 1 + bonus(state, "adv_power")
    out = {}
    for k, v in hero["stats"].items():
        gear = 1 + sum(GEAR[slot]["stats"].get(k, 0) * hero["gear"][slot] for slot in GEAR)
        out[k] = max(1, round(v * level * gear * power * (1 + BARD_ATK * inspire if k == "atk" else 1)))
    return out


def beast_stats(state, beast):
    """The active beast's stats on an adventure or in a battle: its own, by its level, and the city's bonuses."""
    grow = 1 + 0.06 * (beast["level"] - 1)
    power = (1 + bonus(state, "adv_beast")) * (1 + bonus(state, "adv_power"))
    return {k: max(1, round(v * grow * power)) for k, v in beast["stats"].items()}


def party_beast(state):
    beast = beasts.active(state)
    return beast if beast and beast["stage"] != "egg" else None


def team(state, ids=None, n=0):
    """Party `n` (or these heroes, with the beast if it goes with party `n`) as fighters:
    [{"name", "role", "hp", "atk", "def", "spd", "hero" or "beast"}]."""
    store = _store(state)
    ps = store["parties"]
    ids = [i for i in ((ps[n]["heroes"] if n < len(ps) else []) if ids is None else ids) if get(state, i)]
    inspire = _roles(state, ids).get("inspire", 0)
    out = []
    for h in (get(state, i) for i in ids):
        out.append(dict(hero_stats(state, h, inspire), name=h["name"], role=CLASSES[h["cls"]]["role"], hero=h["id"],
                        cls=h["cls"], level=h["level"]))
    beast = party_beast(state)
    if beast and store.get("beast_party", 0) == n:
        out.append(dict(beast_stats(state, beast), name=beasts.title(beast), role=None, beast=beast["id"], level=beast["level"]))
    return out


def power(units):
    """One number for how strong a group of fighters is (for ratings and the leaderboard, not for fights)."""
    if not units:
        return 0
    hp = sum(u["hp"] * (1 + u["def"] / 40) for u in units)
    hit = sum(u["atk"] * (1 + u["spd"] / 60) * (1 + SPLASH if u.get("role") == "splash" else 1) for u in units)
    return round(math.sqrt(hp * hit))


def team_fight(sides, rng, labels=("your party", "the enemy")):
    """Two groups of fighters fight to the end (or FIGHT_ROUNDS rounds). Returns (winner 0 or 1, rounds, story, left):
    story is a few lines of what happened; left is each side's fighters still standing, with the health they have."""
    units = [[dict(u, max=u["hp"], side=s) for u in side] for s, side in enumerate(sides)]
    story = []

    def standing(s):
        return [u for u in units[s] if u["hp"] > 0]

    rnd = 0
    for rnd in range(1, FIGHT_ROUNDS + 1):
        order = sorted((u for s in (0, 1) for u in units[s] if u["hp"] > 0), key=lambda u: (-u["spd"], rng.random()))
        for u in order:
            if u["hp"] <= 0:
                continue
            friends, foes = standing(u["side"]), standing(1 - u["side"])
            if not foes:
                break
            if u.get("role") == "heal":
                hurt = min(friends, key=lambda f: f["hp"] / f["max"])
                if hurt["hp"] / hurt["max"] < HEAL_BELOW:
                    hurt["hp"] = min(hurt["max"], hurt["hp"] + max(1, round(u["atk"] * HEAL_SHARE * rng.uniform(0.8, 1.2))))
                    continue
            guards = [f for f in foes if f.get("role") == "guard"]
            target = rng.choice(guards) if guards and rng.random() < GUARD_PULL else rng.choice(foes)
            hits = [(target, 1.0)]
            if u.get("role") == "splash" and len(foes) > 1:
                hits.append((rng.choice([f for f in foes if f is not target]), SPLASH))
            for t, share in hits:
                dodge = max(0, min(0.35, (t["spd"] - u["spd"]) / (t["spd"] + u["spd"]))) + (ROGUE_DODGE if t.get("role") == "loot" else 0)
                if rng.random() < dodge:
                    continue
                dmg = max(1, round((u["atk"] * rng.uniform(0.8, 1.2) - t["def"] * 0.5) * share))
                t["hp"] = max(0, t["hp"] - dmg)
                if t["hp"] == 0 and len(story) < 12:
                    story.append(f"Round {rnd}: {u['name']} brought down {t['name']}.")
        if not standing(0) or not standing(1):
            break
    alive = [standing(0), standing(1)]
    if alive[0] and alive[1]:     # nobody fell: whoever has the bigger share of their health left wins
        share = [sum(u["hp"] for u in units[s]) / max(1, sum(u["max"] for u in units[s])) for s in (0, 1)]
        winner = 0 if share[0] >= share[1] else 1
        story.append(f"After {rnd} rounds neither side had fallen; {labels[winner]} held more ground.")
    else:
        winner = 0 if alive[0] else 1
    left = [[{"name": u["name"], "hp": u["hp"], "max": u["max"]} for u in units[s]] for s in (0, 1)]
    return winner, rnd, story, left


# ---- where to go ----

def depth(state, ai):
    return _store(state)["depth"].get(str(ai), 0)


def _steps(state, ai):
    area = state["areas"][ai]
    return abs(area["rx"]) + abs(area["ry"]) + depth(state, ai)


def enemies(state, ai):
    """The enemies at the next delve in area `ai`: the same until the delve is won (seeded by the city, area and depth)."""
    steps = _steps(state, ai)
    rng = random.Random(f"{state.get('seed', 0)}:{ai}:{depth(state, ai)}")
    n = min(6, 3 + steps // 3)
    scale = ENEMY_GROWTH ** steps * ENEMY_TECH[min(state["tech"], 5)]
    top = min(len(ENEMIES) - 1, steps)
    out = []
    for i in range(n):
        name = ENEMIES[max(0, top - rng.randint(0, 3))]
        stats = {k: max(1, round(v * scale * rng.uniform(0.85, 1.15))) for k, v in zip(("hp", "atk", "def", "spd"), ENEMY_BASE)}
        out.append(dict(stats, name=name, role=None))
    return out


def lair(state, ai):
    rng = random.Random(f"{state.get('seed', 0)}:lair:{ai}")
    return LAIRS[rng.randrange(len(LAIRS))]


def trip_time(state, ai, ids):
    """Seconds an adventure into area `ai` takes for these heroes, there and back, fight and all."""
    scouts = _roles(state, ids).get("scout", 0)
    speed = (1 + bonus(state, "adv_speed") + SCOUT_SPEED * scouts) * ideology.curse_factor(state, "explore")
    return ADV_TIME * (1 + TIME_STEP * _steps(state, ai)) / max(0.1, speed)


def rating(mine, theirs):
    if not theirs:
        return "Easy"
    r = mine / theirs
    return "Easy" if r >= 1.6 else "Fair" if r >= 1.15 else "Risky" if r >= 0.85 else "Deadly"


def _loot(state, ai, rng, rogues):
    import game
    steps = _steps(state, ai)
    kinds = [k for k in LOOT_BASE if k != "electronics" or state["tech"] >= 4]
    picks = rng.sample(kinds, LOOT_KINDS)
    more = 1 + bonus(state, "adv_loot") + ROGUE_LOOT * rogues
    out = {}
    with game.reading():
        for k in picks:
            plain = LOOT_BASE[k] * LOOT_STEP ** steps * LOOT_TECH[min(state["tech"], 5)]
            earned = beasts._income(state, k) * (LOOT_HOURS + LOOT_HOURS_STEP * steps)
            out[k] = max(1, round(max(plain, earned) * more * rng.uniform(0.8, 1.2)))
    return out


def loot_kinds(state):
    return [k for k in LOOT_BASE if k != "electronics" or state["tech"] >= 4]


# ---- actions ----

def recruit(state, now, cls, name=None):
    import game
    if cls not in CLASSES:
        return "Pick a class for the new hero."
    store = _store(state)
    if len(store["heroes"]) >= hero_cap(state):
        return f"Your city can keep {hero_cap(state)} heroes. Build a guild hall (or let one go) to make room."
    seat = any(not p["trip"] and len(p["heroes"]) < party_size(state) for p in parties(state))
    if not seat and len(bench(state)) >= BENCH_SLOTS:
        return f"Every party and all {BENCH_SLOTS} bench places are full. Let a hero go first."
    cost = recruit_cost(state)
    short = game._missing(state, cost)
    if short:
        return f"Not enough to recruit a hero (need {game.fmt_goods(short)})."
    game._pay(state, cost)
    rng = random.Random()
    taken = {h["name"] for h in store["heroes"]}
    names = [n for n in FIRST_NAMES if n not in taken] or FIRST_NAMES
    base = CLASSES[cls]["stats"]
    hero = {"id": store["next_id"], "name": rng.choice(names), "cls": cls, "level": 1, "xp": 0, "recruited": now,
            "stats": {k: max(1, round(v * rng.uniform(1 - STAT_SPREAD, 1 + STAT_SPREAD))) for k, v in zip(STAT_NAMES, base)},
            "gear": {slot: 0 for slot in GEAR}}
    store["next_id"] += 1
    store["heroes"].append(hero)
    for party in parties(state):
        if not party["trip"] and len(party["heroes"]) < party_size(state):
            party["heroes"].append(hero["id"])
            break
    game.tally(state, "heroes")
    game.log(state, now, f"{hero['name']} the {CLASSES[cls]['name']} joined your adventurers, for {game.fmt_goods(cost)}.")
    return None


def dismiss(state, now, hero_id):
    import game
    hero = get(state, hero_id)
    if not hero:
        return "You have no such hero."
    store = _store(state)
    if hero_id in away_ids(state):
        return f"{hero['name']} is away on an adventure."
    store["heroes"].remove(hero)
    for p in store["parties"]:
        p["heroes"] = [i for i in p["heroes"] if i != hero_id]
    game.log(state, now, f"{hero['name']} the {CLASSES[hero['cls']]['name']} left your adventurers.")
    return None


def set_party(state, now, hero_id, n):
    """Move a hero into party `n`, or (n None) keep them home."""
    hero = get(state, hero_id)
    if not hero:
        return "You have no such hero."
    ps = parties(state)
    if n is not None and not (isinstance(n, int) and not isinstance(n, bool) and 0 <= n < len(ps)):
        return "Pick a party."
    if hero_id in away_ids(state):
        return f"{hero['name']} is away on an adventure: move them when they are back."
    if n is not None:
        if hero_id in ps[n]["heroes"]:
            return None
        if ps[n]["trip"]:
            return f"{_party_name(n)} is away."
        if len(ps[n]["heroes"]) >= party_size(state):
            return f"{_party_name(n)} is full ({party_size(state)} heroes). Take someone out first."
    for p in ps:
        p["heroes"] = [i for i in p["heroes"] if i != hero_id]
    if n is None and party_of(state, hero_id) is not None and len(bench(state)) >= BENCH_SLOTS:
        return f"The bench is full ({BENCH_SLOTS} heroes). Swap instead, or put someone in a party first."
    if n is not None:
        ps[n]["heroes"].append(hero_id)
    return None


def swap(state, now, hero_id, other_id):
    """Two heroes change places (parties, or a party and the bench)."""
    a, b = get(state, hero_id), get(state, other_id)
    if not a or not b or a is b:
        return "Pick two heroes."
    gone = away_ids(state)
    for h in (a, b):
        if h["id"] in gone:
            return f"{h['name']} is away on an adventure: swap when they are back."
    ps = parties(state)
    pa, pb = party_of(state, a["id"]), party_of(state, b["id"])
    if pa == pb:
        return f"{a['name']} and {b['name']} are already together."
    for n, out, into in ((pa, a["id"], b["id"]), (pb, b["id"], a["id"])):
        if n is not None:
            heroes = ps[n]["heroes"]
            heroes[heroes.index(out)] = into
    return None


def set_beast_party(state, now, n):
    """Which party the active beast goes out with."""
    ps = parties(state)
    if not (isinstance(n, int) and not isinstance(n, bool) and 0 <= n < len(ps)):
        return "Pick a party."
    beast = party_beast(state)
    if beast and beast.get("adventure"):
        return "Your beast is away on an adventure: change this when it is back."
    if ps[n]["trip"]:
        return f"{_party_name(n)} is away."
    _store(state)["beast_party"] = n
    return None


def upgrade(state, now, hero_id, slot, times=1):
    import game
    hero = get(state, hero_id)
    if not hero:
        return "You have no such hero."
    if slot not in GEAR:
        return "Pick a piece of gear."
    if not isinstance(times, int) or isinstance(times, bool) or not 1 <= times <= 100:
        times = 1
    if hero_id in away_ids(state):
        return f"{hero['name']} is away on an adventure."
    done = 0
    for _ in range(times):
        if hero["gear"][slot] >= gear_cap(state):
            if not done:
                return f"Gear goes up to level {gear_cap(state)} at your tech level."
            break
        cost = gear_cost(state, hero, slot)
        short = game._missing(state, cost)
        if short:
            if not done:
                return f"Not enough to improve {hero['name']}'s {GEAR[slot]['name'].lower()} (need {game.fmt_goods(short)})."
            break
        game._pay(state, cost)
        hero["gear"][slot] += 1
        done += 1
    game.tally(state, "gear_levels", done)
    game.log(state, now, f"{hero['name']}'s {GEAR[slot]['name'].lower()} is now level {hero['gear'][slot]}.")
    return None


def start(state, now, ai, n=0):
    import game
    store = _store(state)
    ps = parties(state)
    if not isinstance(ai, int) or isinstance(ai, bool) or not 0 <= ai < len(state["areas"]):
        return "Pick somewhere to go."
    if not (isinstance(n, int) and not isinstance(n, bool) and 0 <= n < len(ps)):
        return "Pick a party."
    party, name = ps[n], _party_name(n)
    if party["trip"]:
        return f"{name} is already away."
    if resting(state, now, n):
        return f"{name} is resting after its last fight."
    ids = [i for i in party["heroes"] if get(state, i)]
    if not ids:
        return f"Put at least one hero in {name} first."
    other = next((m for m, p in enumerate(ps) if p["trip"] and p["trip"]["area"] == ai), None)
    if other is not None:
        return f"{_party_name(other)} is already in that lair. Pick another, or wait for it to come back."
    beast = party_beast(state) if store.get("beast_party", 0) == n else None
    if beast and beast.get("adventure"):
        beast = None
    took = trip_time(state, ai, ids)
    party["heroes"] = ids
    party["trip"] = {"area": ai, "depth": depth(state, ai), "party": ids, "beast": beast["id"] if beast else None,
                     "left": now, "back": now + took}
    if beast:
        beast["adventure"] = True
    game.log(state, now, f"{name} set out for the {lair(state, ai)} in {game.area_name(state['areas'][ai])} "
                         f"(delve {depth(state, ai) + 1}): back in {_dur(took)}.")
    return None


def _dur(sec):
    h, m = int(sec // 3600), int(sec % 3600 // 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def tick(state, now):
    """Each party comes home once its adventure is over: the fight is fought then (in the order they end)."""
    if not state.get("adventure"):
        return
    ps = _store(state)["parties"]
    done = sorted((p["trip"]["back"], n) for n, p in enumerate(ps) if p["trip"] and now >= p["trip"]["back"])
    for _, n in done:
        _finish(state, n)


def _finish(state, n):
    import artifacts
    import game
    store = _store(state)
    party = store["parties"][n]
    trip, name = party["trip"], _party_name(n)
    when, ai = trip["back"], trip["area"]
    party["trip"] = None
    beast = beasts.get(state, trip["beast"]) if trip.get("beast") else None
    if beast:
        beast.pop("adventure", None)
    if ai >= len(state["areas"]):
        return
    rng = random.Random()
    ids = [i for i in trip["party"] if get(state, i)]
    mine = team(state, ids)
    if beast and not any(u.get("beast") == beast["id"] for u in mine) and beast["stage"] != "egg":
        mine.append(dict(beast_stats(state, beast), name=beasts.title(beast), role=None, beast=beast["id"], level=beast["level"]))
    foes = enemies(state, ai)
    winner, rounds, story, left = team_fight([mine, foes], rng)
    won = winner == 0
    steps = _steps(state, ai)
    roles = _roles(state, ids)
    xp = HERO_XP * HERO_XP_STEP ** steps * (1 + bonus(state, "adv_xp") + BARD_XP * roles.get("inspire", 0))
    xp = round(xp if won else xp * LOST_XP)
    report = {"t": when, "party": name, "area": game.area_name(state["areas"][ai]), "lair": lair(state, ai), "delve": trip["depth"] + 1,
              "won": won, "rounds": rounds, "story": story, "left": left[0], "xp": xp, "loot": {}, "egg": None, "artifact": None}
    for h in (get(state, i) for i in ids):
        give_xp(state, when, h, xp)
    if won:
        loot = _loot(state, ai, rng, roles.get("loot", 0))
        for k, v in loot.items():
            state["resources"][k] += v
        report["loot"] = loot
        store["depth"][str(ai)] = trip["depth"] + 1
        if beast:
            beasts.give_xp(state, when, beast, BEAST_XP)
        if rng.random() < min(EGG_MAX, EGG_CHANCE + EGG_STEP * steps + 0.5 * game.city_stat(state, "egg_chance")):
            species = beasts.random_species(rng, distance=steps, env=state["areas"][ai].get("env"))
            egg = beasts.new_egg(state, when, species)
            report["egg"] = beasts.RARITIES[beasts.SPECIES[egg["species"]]["rarity"]]["name"]
        if rng.random() < min(ART_MAX, ART_CHANCE + ART_STEP * steps):
            kind = rng.choice(list(artifacts.ARTIFACTS))
            stats = {k: max(1, round(100 * rng.random() ** ART_ROLL_POWER)) for k in artifacts.STATS}
            art = artifacts.give(state, {"kind": kind, "stats": stats, "made": when, "by": state["name"]})
            report["artifact"] = artifacts.ARTIFACTS[art["kind"]]["name"]
        game.tally(state, "adventures_won")
        game.tally(state, "deepest_delve", 0)
        state["totals"]["deepest_delve"] = max(state["totals"].get("deepest_delve", 0), trip["depth"] + 1)
        beasts.note(state, when, "adventure")
        game.log(state, when, f"*** {name} won at the {report['lair']} in {report['area']} (delve {report['delve']}) and brought home "
                              f"{game.fmt_goods(loot)}" + (f", a {report['egg'].lower()} beast egg" if report["egg"] else "")
                              + (f" and a {report['artifact']}" if report["artifact"] else "") + ". ***")
    else:
        party["rest"] = when + REST_TIME * (1 + 0.15 * steps) / (1 + bonus(state, "adv_heal"))
        game.tally(state, "adventures_lost")
        game.log(state, when, f"{name} was beaten at the {report['lair']} in {report['area']} (delve {report['delve']}) and "
                              f"limped home. It rests for {_dur(party['rest'] - when)}.")
    store["reports"].append(report)
    del store["reports"][:-REPORTS_KEPT]


def give_xp(state, now, hero, amount):
    import game
    hero["xp"] += amount
    while hero["level"] < MAX_LEVEL and hero["xp"] >= xp_needed(hero["level"]):
        hero["xp"] -= xp_needed(hero["level"])
        hero["level"] += 1
        game.tally(state, "hero_levels")
        state["totals"]["best_hero"] = max(state["totals"].get("best_hero", 0), hero["level"])
    if hero["level"] >= MAX_LEVEL:
        hero["xp"] = 0


def battle_team(state):
    """Party 1 as it fights another city's party, or (None, why not)."""
    ps = _store(state)["parties"]
    if ps and ps[0]["trip"]:
        return None, "Party 1 is away on an adventure."
    units = team(state)
    beast = party_beast(state)
    if beast and beast.get("adventure"):
        units = [u for u in units if not u.get("beast")]
    if not any(u.get("hero") for u in units):
        return None, "Put at least one hero in Party 1 first (it is the one that fights other cities' parties)."
    return units, None


def battle_won(state, now, ids):
    for h in (get(state, i) for i in ids):
        if h:
            give_xp(state, now, h, round(BATTLE_XP * (1 + bonus(state, "adv_xp"))))


def party_power(state):
    """How strong the city's party is (the leaderboard's Party column)."""
    if state["tech"] < OPENS_TECH or not state.get("adventure", {}).get("heroes"):
        return 0
    import game
    with game._stats_cached():
        return max(power(team(state, n=n)) for n in range(len(_store(state)["parties"])))


def migrate(state):
    store = state.get("adventure")
    if store:
        store.setdefault("depth", {})
        store.setdefault("reports", [])
        if "parties" not in store:      # from before there could be several parties: the one party becomes Party 1
            store["parties"] = [{"heroes": store.pop("party", []), "trip": store.pop("trip", None), "rest": store.pop("rest", 0)}]
            store["beast_party"] = 0


# ---- what the page gets ----

def defs():
    return {"classes": {k: {"name": c["name"], "desc": c["desc"], "role": c["role"], "stats": dict(zip(STAT_NAMES, c["stats"]))}
                        for k, c in CLASSES.items()},
            "gear": {k: {"name": g["name"], "desc": g["desc"], "stats": g["stats"]} for k, g in GEAR.items()},
            "stats": STAT_NAMES, "party_size": PARTY_SIZE, "gear_cap": GEAR_CAP, "opens": OPENS_TECH, "max_parties": MAX_PARTIES}


def view(state, now):
    import game
    store = _store(state)
    with game.reading():
        ps = parties(state)
        gone = away_ids(state)
        beast = party_beast(state)
        inspire_of = {}
        out_parties = []
        for n, p in enumerate(ps):
            ids = [i for i in p["heroes"] if get(state, i)]
            inspire = _roles(state, ids).get("inspire", 0)
            for i in ids:
                inspire_of[i] = inspire
            out_parties.append({"heroes": ids, "trip": p["trip"], "rest": resting(state, now, n),
                                "power": power(team(state, n=n)), "beast": store.get("beast_party", 0) == n})
        heroes = [{**h, "role": CLASSES[h["cls"]]["role"], "now": hero_stats(state, h, inspire_of.get(h["id"], 0)),
                   "xp_needed": xp_needed(h["level"]), "party": party_of(state, h["id"]), "away": h["id"] in gone,
                   "costs": {slot: gear_cost(state, h, slot) for slot in GEAR}} for h in store["heroes"]]
        busy = {p["trip"]["area"]: n for n, p in enumerate(ps) if p["trip"]}
        places = []
        for ai, area in enumerate(state["areas"]):
            foes = enemies(state, ai)
            theirs = power(foes)
            places.append({"area": ai, "name": game.area_name(area), "lair": lair(state, ai), "env": area.get("env"),
                           "distance": abs(area["rx"]) + abs(area["ry"]), "delve": depth(state, ai) + 1,
                           "enemies": [{"name": f["name"], "hp": f["hp"], "atk": f["atk"], "def": f["def"], "spd": f["spd"]} for f in foes],
                           "power": theirs, "busy": busy.get(ai),
                           "ratings": [rating(q["power"], theirs) for q in out_parties],
                           "times": [round(trip_time(state, ai, q["heroes"])) for q in out_parties]})
        bonuses = {k: round(bonus(state, k), 3) for k in BONUSES}
    return {"open": state["tech"] >= OPENS_TECH, "heroes": heroes, "parties": out_parties, "party_size": party_size(state),
            "bench": bench(state), "bench_slots": BENCH_SLOTS,
            "parties_allowed": len(ps), "cap": hero_cap(state), "recruit": recruit_cost(state), "gear_cap": gear_cap(state),
            "power": out_parties[0]["power"],
            "beast": dict(beast_stats(state, beast), name=beasts.title(beast), level=beast["level"], id=beast["id"],
                          away=bool(beast.get("adventure"))) if beast else None,
            "places": places, "reports": store["reports"][::-1],
            "bonuses": bonuses, "sources": bonus_sources(state),
            "words": {k: ideology.describe({k: v})[0] if v else "" for k, v in bonuses.items()}}
