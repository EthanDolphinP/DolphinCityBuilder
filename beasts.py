"""Beasts: companions that set a city a mission each day and grow as it completes them.

Every city starts with one common egg. Each egg comes with one small mission
of its own. It hatches once it has been kept warm for a while and that mission
is done. Egg missions never run out of time, every egg has its own, and they
have nothing to do with the daily beast mission: any number of eggs can be
hatched in a day.

A hatched beast gains experience from beast missions, levels up, and gives the
city a bonus that depends on its species ("nature") and grows with its level.
Only the city's active beast sets beast missions (one each day) and gives its
bonus; the others wait. Only a hatched beast can be the active one.

Every beast also has four stats (STATS) and its species has a picture (ART).
Beasts and eggs can be traded between cities: see the beast offers in
market.py, which use take() and give() here to move a beast.

More eggs can be found by expeditions; rarer species are likelier far from home.

Content lives in the tables below: RARITIES, SPECIES and MISSIONS. The
buildings, research and additions that support beasts are in game.py with the
rest, and use these fields (added up over the whole city):

    beast_xp       0.5 = missions give 50% more experience
    beast_power    0.25 = the active beast's bonus is 25% stronger
    hatch_speed    1.0 = eggs hatch twice as fast
    egg_chance     0.05 = expeditions are 5 points likelier to find an egg
    mission_speed  0.5 = missions come 50% more often

`game` imports this module and this module uses `game`, so nothing here may
touch `game` at import time: only inside functions.
"""

import random

import game

HOUR = 3600
MISSION_TIME = 24 * HOUR    # a new mission this often
HATCH_TIME = 2 * HOUR       # warmth an egg needs (as well as its own mission)
MAX_LEVEL = 10
MISSION_XP = 10             # experience for a completed mission, before bonuses
EGG_CHANCE = 0.15           # chance an expedition finds an egg...
EGG_CHANCE_PER_STEP = 0.05  # ...plus this for every step of distance from home
EGG_CHANCE_MAX = 0.6
RARER_PER_STEP = 0.25       # how much each step of distance favours the rarer species

RARITIES = {    # weight: how often an egg found by an expedition is of this rarity
    "common":    {"name": "Common",    "weight": 60, "color": "#cfd8d3"},
    "uncommon":  {"name": "Uncommon",  "weight": 25, "color": "#7fc97f"},
    "rare":      {"name": "Rare",      "weight": 10, "color": "#5aa7d8"},
    "epic":      {"name": "Epic",      "weight": 4,  "color": "#c58fe5"},
    "legendary": {"name": "Legendary", "weight": 1,  "color": "#e6c35c"},
}

# bonus: what the beast gives per level while it is the active beast.
#   speed           {building category, or "all": 0.02} = those buildings 2% faster per level
#   explore_speed   expeditions faster (0.06 = 6% per level)
#   wildlife_speed  wildlife appears more often
#   power           generators give more
#   housing         people housed, per level
#   attracts        extra arrivals per meal, per level (rounded down in total)
SPECIES = {
    "mossback":    {"name": "Mossback Tortoise", "rarity": "common", "nature": "Patient grower",
                    "bonus": {"speed": {"food": 0.02}},
                    "desc": "A slow, green-backed tortoise. Crops seem to like having it around."},
    "stonehorn":   {"name": "Stonehorn", "rarity": "common", "nature": "Tireless digger",
                    "bonus": {"speed": {"materials": 0.02}},
                    "desc": "A stocky, horned burrower that cannot leave a rock unturned."},
    "glimmerwing": {"name": "Glimmerwing", "rarity": "common", "nature": "Curious",
                    "bonus": {"speed": {"knowledge": 0.02}},
                    "desc": "A moth the size of a cat, drawn to lamplight and open books."},
    "magpie_drake": {"name": "Magpie Drake", "rarity": "common", "nature": "Hoarder",
                     "bonus": {"speed": {"trade": 0.02}},
                     "desc": "A small drake with an eye for anything that glitters."},
    "trailhound":  {"name": "Trailhound", "rarity": "uncommon", "nature": "Pathfinder",
                    "bonus": {"explore_speed": 0.06},
                    "desc": "A long-legged hound that always knows the way back."},
    "herdmother":  {"name": "Herdmother", "rarity": "uncommon", "nature": "Shepherd",
                    "bonus": {"wildlife_speed": 0.1, "speed": {"food": 0.01}},
                    "desc": "A shaggy giant that other animals follow without being asked."},
    "sunscale":    {"name": "Sunscale Lizard", "rarity": "uncommon", "nature": "Basks in power",
                    "bonus": {"power": 0.03},
                    "desc": "Its scales hum faintly near anything that turns or burns."},
    "hearth_lynx": {"name": "Hearth Lynx", "rarity": "rare", "nature": "Homely",
                    "bonus": {"housing": 2, "attracts": 0.2},
                    "desc": "A great soft cat. People settle where it sleeps."},
    "stormcrest":  {"name": "Stormcrest Eagle", "rarity": "rare", "nature": "Inspiring",
                    "bonus": {"speed": {"all": 0.015}},
                    "desc": "It circles the city at dawn, and everyone works a little harder."},
    "goldmaw":     {"name": "Goldmaw Toad", "rarity": "rare", "nature": "Lucky",
                    "bonus": {"speed": {"trade": 0.05}},
                    "desc": "Merchants rub its head for luck. It seems to work."},
    "world_turtle": {"name": "World Turtle", "rarity": "epic", "nature": "Carries a village",
                     "bonus": {"housing": 4, "speed": {"food": 0.02}},
                     "desc": "Big enough to build on, and it does not seem to mind."},
    "frost_wyrm":  {"name": "Frost Wyrm", "rarity": "epic", "nature": "Ancient mind",
                    "bonus": {"speed": {"knowledge": 0.06}, "explore_speed": 0.03},
                    "desc": "Older than the hills, and willing to share some of what it remembers."},
    "sky_serpent": {"name": "Sky Serpent", "rarity": "legendary", "nature": "Sovereign",
                    "bonus": {"speed": {"all": 0.03}, "explore_speed": 0.06, "attracts": 0.2},
                    "desc": "A ribbon of cloud and scale. Cities it favours are spoken of far away."},
}

# Every beast has four stats of its own. They are for show and for trading:
# nothing in the city depends on them. Each is rolled once, when the egg is
# found, within STAT_SPREAD of its species' base value below.
STATS = {"hp": "Health", "atk": "Attack", "def": "Defense", "spd": "Speed"}
STAT_SPREAD = 0.15
BASE_STATS = {      # (health, attack, defense, speed)
    "mossback":     (70, 8, 18, 4),
    "stonehorn":    (60, 14, 14, 6),
    "glimmerwing":  (35, 9, 6, 18),
    "magpie_drake": (45, 12, 8, 14),
    "trailhound":   (55, 16, 10, 20),
    "herdmother":   (90, 12, 16, 8),
    "sunscale":     (50, 18, 12, 14),
    "hearth_lynx":  (70, 22, 14, 22),
    "stormcrest":   (65, 26, 12, 28),
    "goldmaw":      (95, 16, 22, 8),
    "world_turtle": (160, 20, 40, 4),
    "frost_wyrm":   (110, 38, 24, 18),
    "sky_serpent":  (150, 45, 30, 36),
}

# A small picture of each species, drawn in text.
ART = {
    "mossback": [
        r"     ____",
        r"  __/_\/_\__",
        r" (o_|_/\_|__)~",
        r"   U      U",
    ],
    "stonehorn": [
        r"  \\  //",
        r"  (o__o)____",
        r"  /         \~",
        r"  |_|-----|_|",
    ],
    "glimmerwing": [
        r"  /\  o o  /\ ",
        r" /**\ ( ) /**\ ",
        r" \**/ ( ) \**/",
        r"  \/   v   \/",
    ],
    "magpie_drake": [
        r"    __",
        r"  <(o )___/|",
        r"   ( ._>  /",
        r"    `--^^'   $",
    ],
    "trailhound": [
        r"   /\_",
        r"  ( o \______",
        r"   \_  ____  )~",
        r"    |_|    |_|",
    ],
    "herdmother": [
        r"  (\_____/)",
        r"  ( o   o )~~~",
        r"  /~~~~~~~\ ",
        r"  |_|~~~|_|",
    ],
    "sunscale": [
        r"   \ | /",
        r"  __(o)>____",
        r" <__  ____  \_",
        r"    ^^    ^^  `~",
    ],
    "hearth_lynx": [
        r"  /\_/\ ",
        r" ( o.o )",
        r"  > ^ <   _",
        r" (_____)_//",
    ],
    "stormcrest": [
        r" \\\    ///",
        r"  \\\__///",
        r"    (o>",
        r"    /| |\ ",
    ],
    "goldmaw": [
        r"   @..@",
        r"  (----)   $",
        r" ( >__< )",
        r" ^^ ~~ ^^",
    ],
    "world_turtle": [
        r"    _A_n_A_",
        r"   /_|_|_|_\ ",
        r" (o___________)~",
        r"   UU      UU",
    ],
    "frost_wyrm": [
        r"   * /^\ *",
        r"  __( o o )",
        r" /  \ vv /~~\_",
        r" \___\__/____/",
    ],
    "sky_serpent": [
        r" ~~  _/^\_  ~~",
        r"  ~ ( o o )__",
        r" ~~~ \_v_/   \__",
        r"  ~~~~~~~~~~\___)",
    ],
}

# kind of mission -> how it is asked for.
#   pay        a resource the city hands over with the Deliver button, or
#   event      something the city does: "build", "tame", "research", "explore"
#   base / per_level   how much, for an egg (level 0) and extra per level
#   min_level  the beast's level before it asks for this
MISSIONS = {
    "feed":     {"text": "Bring it {n} Food", "pay": "food", "base": 20, "per_level": 20, "min_level": 0},
    "nest":     {"text": "Bring {n} Wood for its nest", "pay": "wood", "base": 15, "per_level": 15, "min_level": 0},
    "build":    {"text": "Build {n} new building{s} for it to inspect", "event": "build", "base": 1, "per_level": 0.34, "min_level": 0},
    "tame":     {"text": "Tame {n} wild animal{s} for it to meet", "event": "tame", "base": 1, "per_level": 0.5, "min_level": 1},
    "treat":    {"text": "Bring it {n} Livestock as a treat", "pay": "livestock", "base": 1, "per_level": 1, "min_level": 1},
    "shiny":    {"text": "Bring it {n} Gold to sleep on", "pay": "gold", "base": 10, "per_level": 15, "min_level": 2},
    "research": {"text": "Research {n} new thing{s} to show it", "event": "research", "base": 1, "per_level": 0, "min_level": 2},
    "explore":  {"text": "Complete {n} expedition{s} and tell it what you saw", "event": "explore", "base": 1, "per_level": 0, "min_level": 3},
}


# ----------------------------------------------------------------- beasts --

def new_egg(state, now, species):
    state["beast_count"] = state.get("beast_count", 0) + 1
    beast = {"id": state["beast_count"], "species": species, "stage": "egg", "level": 0, "xp": 0,
             "obtained": now, "missions": 0}
    beast["task"] = _egg_task(random.Random())
    beast["stats"] = roll_stats(species, random.Random())
    state["beasts"].append(beast)
    return beast


def roll_stats(species, rng):
    """This one beast's stats: its species' base values, each a little higher or lower."""
    return {key: max(1, round(base * rng.uniform(1 - STAT_SPREAD, 1 + STAT_SPREAD)))
            for key, base in zip(STATS, BASE_STATS[species])}


def take(state, beast_id):
    """Take a beast or egg out of the city, to be traded. Returns (beast, None) or (None, why not)."""
    beast = get(state, beast_id)
    if not beast:
        return None, "You have no such beast."
    if beast["stage"] != "egg" and beast["id"] == state.get("beast_active"):
        return None, "Your active beast can't be traded. Make another beast active first."
    state["beasts"].remove(beast)
    return beast, None


def give(state, now, beast):
    """Add a beast or egg that came from another city (or back from the market)."""
    state["beast_count"] = state.get("beast_count", 0) + 1
    beast["id"] = state["beast_count"]
    state["beasts"].append(beast)
    tick(state, now)
    return beast


def public(beast):
    """What other cities may know about a beast on offer. What is inside an egg stays a surprise."""
    species = SPECIES[beast["species"]]
    rarity = RARITIES[species["rarity"]]
    if beast["stage"] == "egg":
        return {"egg": True, "name": f"{rarity['name']} egg", "rarity": rarity["name"], "color": rarity["color"]}
    return {"egg": False, "name": species["name"], "species": beast["species"], "rarity": rarity["name"],
            "color": rarity["color"], "level": beast["level"], "stats": beast["stats"], "nature": species["nature"]}


def _egg_task(rng):
    """The one small mission an egg needs done before it will hatch."""
    kind = rng.choice([k for k, m in MISSIONS.items() if m["min_level"] == 0])
    m = MISSIONS[kind]
    need = max(1, int(m["base"]))
    return {"kind": kind, "need": need, "done": 0, "complete": False, "pay": m.get("pay"),
            "text": m["text"].format(n=need, s="" if need == 1 else "s")}


def random_species(rng, distance=0, rarity=None):
    """Pick a species: of the given rarity, or weighted by rarity (rarer ones likelier far from home)."""
    names = list(RARITIES)
    if rarity is None:
        weights = [RARITIES[r]["weight"] * (1 + RARER_PER_STEP * distance * i) for i, r in enumerate(names)]
        rarity = rng.choices(names, weights=weights)[0]
    return rng.choice([s for s, d in SPECIES.items() if d["rarity"] == rarity])


def setup(state, now, rng=None):
    """Give a city its first egg and first mission."""
    rng = rng or random.Random()
    state.update(beasts=[], beast_count=0, mission=None, mission_at=now, reports=state.get("reports", []))
    state["beast_active"] = new_egg(state, now, random_species(rng, rarity="common"))["id"]
    tick(state, now)


def migrate(state, now):
    if "beasts" not in state:       # a city from before beasts
        setup(state, now)
        game.log(state, now, "A strange egg has been found at the edge of the city. See the Beast tab.")
    state.setdefault("reports", [])
    for beast in state["beasts"]:
        if "stats" not in beast:    # a beast from before stats
            beast["stats"] = roll_stats(beast["species"], random.Random())
    # Eggs used to share the daily mission; now each has a mission of its own.
    for beast in state["beasts"]:
        if beast["stage"] == "egg" and beast["missions"] < 1 and "task" not in beast:
            old = state.get("mission")
            if old and not old["complete"] and old.get("beast") == beast["id"]:
                beast["task"] = {k: old[k] for k in ("kind", "need", "done", "complete", "pay", "text")}
                state["mission"] = None
            else:
                beast["task"] = _egg_task(random.Random())
    _pick_active(state)


def _pick_active(state):
    """Only a hatched beast can be active. If the active one is an egg (or missing) and the
    city has a hatched beast, the highest-level one takes over."""
    beast = active(state)
    hatched = [b for b in state["beasts"] if b["stage"] != "egg"]
    if hatched and (not beast or beast["stage"] == "egg"):
        state["beast_active"] = max(hatched, key=lambda b: b["level"])["id"]


def get(state, beast_id):
    return next((b for b in state["beasts"] if b["id"] == beast_id), None)


def active(state):
    return get(state, state.get("beast_active"))


def set_active(state, now, beast_id):
    beast = get(state, beast_id)
    if not beast:
        return "You have no such beast."
    if beast["stage"] == "egg":
        return "Only a hatched beast can be the active one. Eggs hatch wherever they are."
    state["beast_active"] = beast_id
    game.log(state, now, f"{title(beast)} is now the city's active beast.")
    return None


def title(beast):
    if beast["stage"] == "egg":
        return f"The {RARITIES[SPECIES[beast['species']]['rarity']]['name'].lower()} egg"
    return SPECIES[beast["species"]]["name"]


def xp_needed(level):
    """Experience to go from `level` to the next."""
    return 10 + 5 * level


def _power(state):
    return 1 + game.city_stat(state, "beast_power")


def bonus(state, key):
    """The active beast's bonus of this kind right now (0 if it has none, or is still an egg)."""
    beast = active(state)
    if not beast or beast["stage"] == "egg":
        return 0
    return SPECIES[beast["species"]]["bonus"].get(key, 0) * beast["level"] * _power(state)


def speed_bonus(state, category):
    """(multiplier, label) for buildings of this category, or None."""
    beast = active(state)
    if not beast or beast["stage"] == "egg":
        return None
    per = SPECIES[beast["species"]]["bonus"].get("speed", {})
    extra = (per.get(category, 0) + per.get("all", 0)) * beast["level"] * _power(state)
    return (1 + extra, title(beast)) if extra else None


def hatch_time(state):
    return HATCH_TIME / (1 + game.city_stat(state, "hatch_speed"))


def mission_period(state):
    return MISSION_TIME / (1 + game.city_stat(state, "mission_speed"))


def give_xp(state, now, beast, amount):
    beast["xp"] += amount
    while beast["level"] < MAX_LEVEL and beast["xp"] >= xp_needed(beast["level"]):
        beast["xp"] -= xp_needed(beast["level"])
        beast["level"] += 1
        game.log(state, now, f"*** {title(beast)} has grown to level {beast['level']}. ***")
    if beast["level"] >= MAX_LEVEL:
        beast["xp"] = 0


# --------------------------------------------------------------- missions --

def _issue(state, now, rng):
    beast = active(state)
    if not beast or beast["stage"] == "egg":
        return
    level = beast["level"]
    kinds = [k for k, m in MISSIONS.items() if m["min_level"] <= level
             and (m.get("pay") != "livestock" or state["resources"]["livestock"] or level >= 3)]
    kind = rng.choice(kinds)
    m = MISSIONS[kind]
    need = max(1, int(m["base"] + m["per_level"] * level))
    old = state.get("mission")
    if old and not old["complete"]:
        game.log(state, now, f"A mission ran out of time: {old['text']}.")
    state["mission"] = {
        "kind": kind, "need": need, "done": 0, "complete": False, "issued": now, "beast": beast["id"],
        "pay": m.get("pay"), "text": m["text"].format(n=need, s="" if need == 1 else "s"),
    }
    game.log(state, now, f"{title(beast)} has a new mission for you: {state['mission']['text']}.")


def _complete(state, now):
    mission = state["mission"]
    mission["complete"] = True
    beast = get(state, mission["beast"])
    if not beast:
        return
    game.log(state, now, f"Mission complete: {mission['text']}.")
    if beast["stage"] != "egg":
        give_xp(state, now, beast, round(MISSION_XP * (1 + game.city_stat(state, "beast_xp"))))
    tick(state, now)


def _complete_egg(state, now, beast):
    beast["task"]["complete"] = True
    beast["missions"] = 1
    game.log(state, now, f"Egg mission complete: {beast['task']['text']}.")
    tick(state, now)


def _waiting_eggs(state):
    """Eggs whose own mission is still to do."""
    return [b for b in state["beasts"] if b["stage"] == "egg" and b.get("task") and not b["task"]["complete"]]


def note(state, now, event, amount=1):
    """Something happened in the city that missions may be waiting for. It counts towards
    the beast mission and towards every egg's own mission at once."""
    for beast in _waiting_eggs(state):
        task = beast["task"]
        if MISSIONS[task["kind"]].get("event") == event:
            task["done"] = min(task["need"], task["done"] + amount)
            if task["done"] >= task["need"]:
                _complete_egg(state, now, beast)
    mission = state.get("mission")
    if mission and not mission["complete"] and MISSIONS[mission["kind"]].get("event") == event:
        mission["done"] = min(mission["need"], mission["done"] + amount)
        if mission["done"] >= mission["need"]:
            _complete(state, now)


def deliver(state, now, egg_id=None):
    """Hand over what a "bring me" mission asks for: the beast mission, or the egg's own if `egg_id` is given."""
    egg = get(state, egg_id) if egg_id is not None else None
    if egg_id is not None and egg not in _waiting_eggs(state):
        return "That egg is not waiting for anything."
    mission = egg["task"] if egg else state.get("mission")
    if not mission or mission["complete"] or not mission["pay"]:
        return "There is nothing to deliver right now."
    if state["resources"][mission["pay"]] < mission["need"]:
        return f"You need {mission['need']} {game.RESOURCES[mission['pay']]} for that."
    state["resources"][mission["pay"]] -= mission["need"]
    mission["done"] = mission["need"]
    if egg:
        _complete_egg(state, now, egg)
    else:
        _complete(state, now)
    return None


def tick(state, now):
    """Hatch eggs that are ready and hand out the next mission when it is due."""
    for beast in state["beasts"]:
        if beast["stage"] == "egg" and beast["missions"] >= 1 and now - beast["obtained"] >= hatch_time(state):
            beast.update(stage="hatched", level=1, xp=0, hatched=now)
            beast.pop("task", None)
            species = SPECIES[beast["species"]]
            game.log(state, now, f"*** The egg has hatched: a {species['name']} "
                                 f"({RARITIES[species['rarity']]['name'].lower()}), {species['nature'].lower()}. ***")
    _pick_active(state)
    beast = active(state)
    if not beast or beast["stage"] == "egg":
        return      # beast missions start once the city has a hatched beast
    if now >= state["mission_at"]:
        _issue(state, now, random.Random())
        # one mission per period; after a long absence the clock starts again from now
        state["mission_at"] += mission_period(state)
        if state["mission_at"] <= now:
            state["mission_at"] = now + mission_period(state)


# ------------------------------------------------------------ expeditions --

def expedition_egg(state, now, distance, rng):
    """Maybe find an egg on an expedition `distance` steps from home. Returns the new beast or None."""
    chance = min(EGG_CHANCE_MAX, EGG_CHANCE + EGG_CHANCE_PER_STEP * distance + game.city_stat(state, "egg_chance"))
    if rng.random() >= chance:
        return None
    return new_egg(state, now, random_species(rng, distance))


# ------------------------------------------------------------------- view --

def _describe(per, level, power):
    """The bonus in words, for a beast of this level."""
    out = []
    pct = lambda x: f"{round(x * level * power * 100, 1):g}%"
    for cat, x in per.get("speed", {}).items():
        what = "All buildings" if cat == "all" else f"{game.CATEGORIES[cat]} buildings"
        out.append(f"{what} {pct(x)} faster")
    if "explore_speed" in per:
        out.append(f"Expeditions {pct(per['explore_speed'])} faster")
    if "wildlife_speed" in per:
        out.append(f"Wildlife appears {pct(per['wildlife_speed'])} more often")
    if "power" in per:
        out.append(f"Generators give {pct(per['power'])} more power")
    if "housing" in per:
        out.append(f"Houses {int(per['housing'] * level * power)} people")
    if "attracts" in per:
        out.append(f"{int(per['attracts'] * level * power)} extra arrivals per meal")
    return out


def view(state, now):
    power = _power(state)
    beasts = []
    for b in state["beasts"]:
        species, egg = SPECIES[b["species"]], b["stage"] == "egg"
        rarity = RARITIES[species["rarity"]]
        entry = {"id": b["id"], "egg": egg, "active": b["id"] == state.get("beast_active"),
                 "rarity": rarity["name"], "color": rarity["color"], "level": b["level"]}
        if egg:     # what is inside stays a surprise
            entry.update(name=f"{rarity['name']} egg", warm=now - b["obtained"], warm_needed=hatch_time(state),
                         missions=b["missions"], task=b.get("task"))
        else:
            entry.update(name=species["name"], nature=species["nature"], desc=species["desc"],
                         species=b["species"], stats=b["stats"], art="\n".join(ART[b["species"]]),
                         xp=b["xp"], xp_needed=xp_needed(b["level"]), max_level=b["level"] >= MAX_LEVEL,
                         bonus=_describe(species["bonus"], b["level"], power),
                         next_bonus=_describe(species["bonus"], min(MAX_LEVEL, b["level"] + 1), power))
        beasts.append(entry)
    return {
        "beasts": beasts,
        "hatched": any(b["stage"] != "egg" for b in state["beasts"]),
        "mission": state.get("mission"),
        "mission_at": state["mission_at"],
        "mission_period": mission_period(state),
        "max_level": MAX_LEVEL,
        "xp_per_mission": round(MISSION_XP * (1 + game.city_stat(state, "beast_xp"))),
        "egg_chance": round(min(EGG_CHANCE_MAX, EGG_CHANCE + game.city_stat(state, "egg_chance")) * 100),
        "rarities": RARITIES,
        "stats": STATS,
        "species": {k: {"name": s["name"], "rarity": RARITIES[s["rarity"]]["name"]} for k, s in SPECIES.items()},
    }
