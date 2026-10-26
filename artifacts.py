"""Artifacts: things a city crafts for its ideology, and can trade to any city.

Each ideology has five (ARTIFACTS), made from resources alone: no tech level or research, only what they take.
A city crafts its own ideology's; any city can own, enshrine and trade any of them, so the buff a city wants may
mean buying another ideology's artifact from a city that follows it.

Every artifact rolls three stats from 1 to 100, like a beast's:
    Potency    how strong its first buff is
    Resonance  how strong its second buff is
    Purity     makes both stronger: they work at (0.5 + 0.5 * purity / 100)
A buff at its full value (FULL) needs 100 in its stat and in Purity. Stats roll very low: each is 100 * u ** ROLL_POWER
for a random u, so most are under 20 (the average is about 11). One stat of 90 or more is about 1 craft in 75,
all three about 1 in 450,000, and a perfect artifact (100 in all three) about 1 in 4 billion.

Crafting is done in batches of up to MAX_BATCH. A batch keeps its best KEEP_PER_BATCH (by the sum of the three
stats; the rest crumble to dust), so a city can craft millions without filling its vault.
The vault holds VAULT_SIZE. A city enshrines up to SHRINE_SLOTS at once (one of each kind) and only those work;
its own ideology's work ATTUNED times as strongly.

state["artifacts"] = {"next_id": n, "vault": [artifact], "shrine": [ids]}; an artifact is
{"id", "kind", "stats": {"potency", "resonance", "purity"}, "made": time, "by": city}.

`game` imports this module and this module uses `game`, so nothing here may touch `game` at import time.
"""
import math
import random

import ideology

STATS = {"potency": "Potency", "resonance": "Resonance", "purity": "Purity"}
ROLL_POWER = 8          # a stat is 100 * u ** ROLL_POWER: very rarely high
MAX_BATCH = 10_000      # most crafted in one go
KEEP_PER_BATCH = 3      # the best this many of a batch are kept
VAULT_SIZE = 60         # most artifacts a city can hold
SHRINE_SLOTS = 3        # most enshrined (working) at once
ATTUNED = 1.25          # an artifact of the city's own ideology works this much more strongly
GRADES = [(100, "S"), (90, "A"), (75, "B"), (50, "C"), (25, "D"), (10, "E"), (0, "F")]

# What each buff is worth at its full value (100 in its stat and in Purity), by ideology.describe's keys.
FULL = {"speed": 0.15, "speed_all": 0.06, "explore_speed": 0.25, "explore_cost": 0.15, "wildlife_speed": 0.4,
        "attracts": 1.0, "housing": 20, "power": 0.15, "beast_xp": 0.4, "beast_power": 0.25, "hatch_speed": 0.4,
        "egg_chance": 0.06, "mission_speed": 0.25, "night_shelter": 0.25, "weather_shelter": 0.25,
        "cauldron_power": 0.3, "cauldron_cost": 0.3}

# Five artifacts per ideology, and a sixth for the Cauldron. buffs: [first (Potency), second (Resonance)], each a buff key, or "speed:<category>".
ARTIFACTS = {
    # ---- The Old Faith ----
    "reliquary_of_dawn": {"name": "Reliquary of Dawn", "ideology": "faith", "buffs": ["speed:knowledge", "night_shelter"],
                          "cost": {"gold": 40, "stone": 60, "knowledge": 20}, "desc": "A saint's lantern that never quite goes out."},
    "votive_idol": {"name": "Votive Idol", "ideology": "faith", "buffs": ["attracts", "weather_shelter"],
                    "cost": {"stone": 80, "gold": 30}, "desc": "Pilgrims come from far away to leave it gifts, and pray the storms away."},
    "harvest_censer": {"name": "Harvest Censer", "ideology": "faith", "buffs": ["speed:food", "hatch_speed"],
                       "cost": {"food": 120, "ore": 20, "gold": 20}, "desc": "Its warm smoke blesses the fields, and the eggs in the nest."},
    "saints_bones": {"name": "Saint's Bones", "ideology": "faith", "buffs": ["beast_xp", "mission_speed"],
                     "cost": {"livestock": 2, "gold": 40, "stone": 20}, "desc": "Beasts grow calm and eager near them."},
    "prayer_wheel": {"name": "Prayer Wheel", "ideology": "faith", "buffs": ["speed_all", "housing"],
                     "cost": {"wood": 60, "tools": 10, "gold": 30}, "desc": "Every turn is a small blessing on the whole city and every home in it."},
    # ---- Progress ----
    "clockwork_heart": {"name": "Clockwork Heart", "ideology": "progress", "buffs": ["power", "speed:materials"],
                        "cost": {"tools": 30, "ore": 40, "gold": 20}, "desc": "It ticks faster when there is work to be done."},
    "difference_engine": {"name": "Difference Engine", "ideology": "progress", "buffs": ["speed:knowledge", "mission_speed"],
                          "cost": {"tools": 40, "knowledge": 30, "gold": 30}, "desc": "Brass wheels that work sums nobody asked for."},
    "brass_telescope": {"name": "Brass Telescope", "ideology": "progress", "buffs": ["explore_speed", "egg_chance"],
                        "cost": {"ore": 30, "tools": 20, "gold": 40}, "desc": "Sees the far hills, and what is nesting on them."},
    "tesla_coil": {"name": "Tesla Coil", "ideology": "progress", "buffs": ["power", "night_shelter"],
                   "cost": {"electronics": 4, "ore": 40, "tools": 20}, "desc": "Lightning in a jar, lighting the whole night."},
    "automaton_hand": {"name": "Automaton Hand", "ideology": "progress", "buffs": ["speed:materials", "speed:trade"],
                       "cost": {"tools": 40, "electronics": 2, "ore": 20}, "desc": "It never tires, and never drops a thing."},
    # ---- Commerce ----
    "golden_scales": {"name": "Golden Scales", "ideology": "commerce", "buffs": ["speed:trade", "explore_cost"],
                      "cost": {"gold": 80, "ore": 20}, "desc": "Always fair, always in the seller's favour."},
    "ledger_of_ages": {"name": "Ledger of Ages", "ideology": "commerce", "buffs": ["speed:trade", "speed:knowledge"],
                       "cost": {"gold": 50, "knowledge": 30, "wood": 20}, "desc": "Every deal ever made, and what came of it."},
    "merchants_compass": {"name": "Merchant's Compass", "ideology": "commerce", "buffs": ["explore_cost", "attracts"],
                          "cost": {"gold": 60, "ore": 30}, "desc": "It points to the nearest profit, and the customers follow."},
    "jewelled_crown": {"name": "Jewelled Crown", "ideology": "commerce", "buffs": ["attracts", "speed:trade"],
                       "cost": {"gold": 120, "stone": 20}, "desc": "Worn on market days, to bring the crowds."},
    "coin_of_plenty": {"name": "Coin of Plenty", "ideology": "commerce", "buffs": ["speed:food", "housing"],
                       "cost": {"gold": 70, "food": 60}, "desc": "Spent and spent again, and always comes back."},
    # ---- Kinship with the Wild ----
    "antler_crown": {"name": "Antler Crown", "ideology": "wild", "buffs": ["wildlife_speed", "beast_power"],
                     "cost": {"wood": 60, "livestock": 2, "food": 40}, "desc": "The herds bow to whoever wears it."},
    "world_tree_seed": {"name": "Seed of the World Tree", "ideology": "wild", "buffs": ["speed:food", "weather_shelter"],
                        "cost": {"wood": 80, "food": 60, "knowledge": 10}, "desc": "Wherever it is kept, things grow."},
    "wolf_fang": {"name": "Wolf Fang Amulet", "ideology": "wild", "buffs": ["beast_xp", "beast_power"],
                  "cost": {"livestock": 3, "ore": 10, "food": 40}, "desc": "Your beast fights as if it had the pack behind it."},
    "feather_cloak": {"name": "Feather Cloak", "ideology": "wild", "buffs": ["explore_speed", "wildlife_speed"],
                      "cost": {"wood": 40, "livestock": 2, "food": 60}, "desc": "Light as air, and the birds follow it."},
    "phoenix_egg": {"name": "Phoenix Egg", "ideology": "wild", "buffs": ["hatch_speed", "egg_chance"],
                    "cost": {"livestock": 2, "gold": 30, "stone": 40}, "desc": "Warm to the touch, and never hatches."},
    # ---- The Wayfarers ----
    "star_map": {"name": "Star Map", "ideology": "wayfarers", "buffs": ["explore_speed", "explore_cost"],
                 "cost": {"knowledge": 30, "wood": 40, "gold": 20}, "desc": "Every road, marked by the star above it."},
    "sextant": {"name": "Sextant", "ideology": "wayfarers", "buffs": ["egg_chance", "night_shelter"],
                "cost": {"ore": 30, "tools": 10, "gold": 30}, "desc": "Read by starlight: it finds what lies out there, and keeps the night at bay."},
    "weathered_sail": {"name": "Weathered Sail", "ideology": "wayfarers", "buffs": ["weather_shelter", "explore_speed"],
                       "cost": {"wood": 80, "livestock": 1, "food": 40}, "desc": "It has seen every storm, turned them all, and still caught the wind."},
    "lodestone": {"name": "Lodestone", "ideology": "wayfarers", "buffs": ["power", "explore_cost"],
                  "cost": {"ore": 60, "stone": 40}, "desc": "Pulls at iron, turns the dynamos, and always points the short way home."},
    "travellers_lantern": {"name": "Traveller's Lantern", "ideology": "wayfarers", "buffs": ["night_shelter", "attracts"],
                           "cost": {"ore": 20, "wood": 40, "gold": 30}, "desc": "Lit in the window, it brings travellers home."},
    # ---- Community ----
    "hearthstone": {"name": "Hearthstone", "ideology": "community", "buffs": ["housing", "attracts"],
                    "cost": {"stone": 80, "wood": 40}, "desc": "Wherever it sits, people want to live."},
    "loom_of_kinship": {"name": "Loom of Kinship", "ideology": "community", "buffs": ["speed:trade", "housing"],
                        "cost": {"wood": 60, "tools": 10, "food": 40}, "desc": "Everyone weaves a thread: cloth to sell, and blankets for every new home."},
    "common_bell": {"name": "Common Bell", "ideology": "community", "buffs": ["speed_all", "night_shelter"],
                    "cost": {"ore": 50, "tools": 10, "gold": 20}, "desc": "It rings the start of work, and the end."},
    "feast_table": {"name": "Feast Table", "ideology": "community", "buffs": ["speed:food", "mission_speed"],
                    "cost": {"wood": 60, "food": 100}, "desc": "Long enough for the whole city, beasts included."},
    "guild_charter": {"name": "Guild Charter", "ideology": "community", "buffs": ["speed:materials", "housing"],
                      "cost": {"knowledge": 20, "gold": 40, "wood": 30}, "desc": "Signed by every guild in the city, and kept by all."},
    # ---- one more for each ideology: for the Cauldron ----
    "anointed_ladle": {"name": "Anointed Ladle", "ideology": "faith", "buffs": ["cauldron_power", "cauldron_cost"],
                       "cost": {"gold": 60, "food": 120, "knowledge": 30}, "desc": "Blessed at the altar: what it stirs is stronger, and goes further."},
    "precision_still": {"name": "Precision Still", "ideology": "progress", "buffs": ["cauldron_cost", "speed:materials"],
                        "cost": {"tools": 40, "ore": 40, "gold": 30}, "desc": "Not a drop wasted: brews take less, and the workshops hum along."},
    "merchants_measure": {"name": "Merchant's Measure", "ideology": "commerce", "buffs": ["cauldron_cost", "speed:trade"],
                          "cost": {"gold": 120, "wood": 40}, "desc": "Weighs every ingredient to the grain, and every coin."},
    "green_mans_bowl": {"name": "Green Man's Bowl", "ideology": "wild", "buffs": ["cauldron_power", "wildlife_speed"],
                        "cost": {"wood": 100, "food": 80, "livestock": 1}, "desc": "Carved from a living oak: brews in it run wild and strong."},
    "travellers_flask": {"name": "Traveller's Flask", "ideology": "wayfarers", "buffs": ["cauldron_power", "explore_speed"],
                         "cost": {"gold": 60, "stone": 40, "food": 60}, "desc": "Every road's best recipe, carried home in one battered flask."},
    "hearth_cauldron": {"name": "Hearth Cauldron", "ideology": "community", "buffs": ["cauldron_power", "housing"],
                        "cost": {"stone": 100, "wood": 60, "food": 60}, "desc": "The pot the whole village cooks in: stronger brews, and room at the fire."},
}


def grade(value):
    return next(g for floor, g in GRADES if value >= floor)


def roll(rng):
    """Three stats, each 1 to 100 and very rarely high."""
    return {k: max(1, round(100 * rng.random() ** ROLL_POWER)) for k in STATS}


def score(art):
    return sum(art["stats"].values())


def _store(state):
    return state.setdefault("artifacts", {"next_id": 1, "vault": [], "shrine": []})


def get(state, art_id):
    return next((a for a in _store(state)["vault"] if a["id"] == art_id), None)


def strength(art, state=None):
    """How strongly each buff works: [first, second], each 0 to 1 (or up to ATTUNED for the city's own ideology)."""
    s = art["stats"]
    pure = 0.5 + 0.5 * s["purity"] / 100
    own = ATTUNED if state is not None and ARTIFACTS[art["kind"]]["ideology"] == state.get("ideology") else 1.0
    return [s["potency"] / 100 * pure * own, s["resonance"] / 100 * pure * own]


def effects_of(art, state=None):
    """The buffs of one artifact as an effects dict (see ideology.describe)."""
    out = {"speed": {}}
    for buff, x in zip(ARTIFACTS[art["kind"]]["buffs"], strength(art, state)):
        if buff.startswith("speed:"):
            cat = buff.split(":", 1)[1]
            out["speed"][cat] = out["speed"].get(cat, 0) + FULL["speed"] * x
        elif buff == "speed_all":
            out["speed"]["all"] = out["speed"].get("all", 0) + FULL["speed_all"] * x
        else:
            out[buff] = out.get(buff, 0) + FULL[buff] * x
    return out


def text(art, state=None):
    eff = effects_of(art, state)
    if eff.get("housing"):
        eff["housing"] = int(eff["housing"])
    return ideology.describe(eff)


def enshrined(state):
    store = _store(state)
    return [a for a in (get(state, i) for i in store["shrine"]) if a]


def effects(state):
    """What every enshrined artifact gives, added up (as ideology.effects)."""
    total = {"speed": {}}
    for art in enshrined(state):
        for key, value in effects_of(art, state).items():
            if key == "speed":
                for cat, x in value.items():
                    total["speed"][cat] = total["speed"].get(cat, 0) + x
            elif key == "housing":
                total[key] = total.get(key, 0) + int(value)
            else:
                total[key] = total.get(key, 0) + value
    return total


def speed_bonus(state, category):
    """(multiplier, label) the enshrined artifacts put on a building of this category, or None."""
    per = effects(state)["speed"]
    extra = per.get(category, 0) + per.get("all", 0)
    return (1 + extra, "Artifacts") if extra else None


def craft(state, now, kind, times=1):
    """Craft `times` of one of the city's ideology's artifacts; the best KEEP_PER_BATCH are kept. Returns an error or None."""
    import game
    if kind not in ARTIFACTS:
        return "That is not an artifact."
    art = ARTIFACTS[kind]
    if not state.get("ideology"):
        return "Choose an ideology first: each crafts its own artifacts."
    if art["ideology"] != state["ideology"]:
        return f"Only cities of {ideology.IDEOLOGIES[art['ideology']]['name']} can craft that. Buy one from one on the market."
    if not isinstance(times, int) or isinstance(times, bool) or not 1 <= times <= MAX_BATCH:
        return f"Craft from 1 to {MAX_BATCH:,} at a time."
    store = _store(state)
    keep = min(KEEP_PER_BATCH, times)
    if len(store["vault"]) + keep > VAULT_SIZE:
        return f"Your vault is full ({VAULT_SIZE}). Sell or break up some artifacts first."
    cost = {k: v * times for k, v in art["cost"].items()}
    short = game._missing(state, cost)
    if short:
        return f"Not enough to craft {times:,} (need {game.fmt_goods(short)})."
    game._pay(state, cost)
    rng = random.Random()
    best = sorted((roll(rng) for _ in range(times)), key=lambda st: -sum(st.values()))[:keep]
    made = []
    for st in best:
        a = {"id": store["next_id"], "kind": kind, "stats": st, "made": now, "by": state["name"]}
        store["next_id"] += 1
        store["vault"].append(a)
        made.append(a)
    game.tally(state, "artifacts_crafted", times)
    top = made[0]
    grades = "".join(grade(v) for v in top["stats"].values())
    game.log(state, now, f"Crafted {times:,} {art['name']}{'s' if times != 1 else ''} from {game.fmt_goods(cost)}: kept the best "
                         f"{len(made)} (the best is {grades}: " + ", ".join(f"{STATS[k]} {v}" for k, v in top["stats"].items()) + ").")
    return None


def enshrine(state, now, art_id):
    import game
    store, art = _store(state), get(state, art_id)
    if not art:
        return "You have no such artifact."
    if art_id in store["shrine"]:
        return "That one is already enshrined."
    if len(enshrined(state)) >= SHRINE_SLOTS:
        return f"Your shrine is full ({SHRINE_SLOTS}). Take one out first."
    if any(a["kind"] == art["kind"] for a in enshrined(state)):
        return f"You already have a {ARTIFACTS[art['kind']]['name']} enshrined: one of each kind works."
    store["shrine"] = [i for i in store["shrine"] if get(state, i)] + [art_id]
    game.log(state, now, f"Enshrined a {ARTIFACTS[art['kind']]['name']}: {', '.join(text(art, state))}.")
    return None


def unenshrine(state, now, art_id):
    store = _store(state)
    if art_id not in store["shrine"]:
        return "That artifact is not enshrined."
    store["shrine"].remove(art_id)
    return None


def take(state, art_id):
    """Take an artifact out of the vault (to trade or break up). Returns (artifact, None) or (None, why not)."""
    art = get(state, art_id)
    if not art:
        return None, "You have no such artifact."
    if art_id in _store(state)["shrine"]:
        return None, "Take it out of your shrine first."
    _store(state)["vault"].remove(art)
    return art, None


def give(state, art):
    """Put an artifact into the city's vault (a trade, or one coming back). It may go over VAULT_SIZE: never lost."""
    store = _store(state)
    art = dict(art, id=store["next_id"])
    store["next_id"] += 1
    store["vault"].append(art)
    return art


def break_up(state, now, art_id):
    art, error = take(state, art_id)
    return error


def public(art):
    """An artifact as any city may see it (on the market)."""
    a = ARTIFACTS[art["kind"]]
    return {"kind": art["kind"], "name": a["name"], "ideology": a["ideology"], "stats": art["stats"], "by": art.get("by"),
            "grades": {k: grade(v) for k, v in art["stats"].items()}, "text": text(art)}


def defs():
    return {"kinds": {k: {"name": a["name"], "ideology": a["ideology"], "desc": a["desc"], "cost": a["cost"],
                          "buffs": a["buffs"], "full": text({"kind": k, "stats": {s: 100 for s in STATS}})}
                      for k, a in ARTIFACTS.items()},
            "stats": STATS, "max_batch": MAX_BATCH, "keep": KEEP_PER_BATCH, "vault": VAULT_SIZE, "slots": SHRINE_SLOTS,
            "attuned": ATTUNED, "roll_power": ROLL_POWER}


def view(state):
    store = _store(state)
    shrine = [a["id"] for a in enshrined(state)]
    return {"vault": [dict(public(a), id=a["id"], text=text(a, state), enshrined=a["id"] in shrine) for a in store["vault"]],
            "shrine": shrine, "total": ideology.describe(effects(state))}
