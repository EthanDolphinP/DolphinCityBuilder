"""The Cauldron: open from the start, it brews once an hour from whatever the city throws in.

Each recipe takes set ingredients (resources) and gives a bonus for a while. Throwing in more makes the brew
stronger and last longer, with no top: like a ritual's gift or a hex's, every doubling of the ingredients adds the
same step (GIFT_STRENGTH, GIFT_TIME), so each extra handful adds a little less than the one before but never
nothing. The cauldron takes a new brew once every BREW_EVERY; brews already bubbling keep going, so a strong
one can still be running when the next is made. Brewing a recipe that is still running starts it again.

A recipe can be made once the city has every one of its ingredients: once it reaches the tech level that first
makes one (RESOURCE_TECH), or as soon as it has some (bought on the market, say).

`game` imports this module and this module uses `game`, so nothing here may touch `game` at import time.
"""
import math

import ideology

MIN, HOUR = 60, 3600
BREW_EVERY = HOUR          # the cauldron takes a new brew this often
BREW_TIME = HOUR           # how long a brew of the least ingredients lasts
GIFT_STRENGTH = 0.35       # every doubling of the ingredients makes the brew this much stronger...
GIFT_TIME = 0.5            # ...and last this much longer
RESOURCE_TECH = {"food": 0, "wood": 0, "stone": 0, "livestock": 0, "knowledge": 0,
                 "ore": 1, "gold": 1, "tools": 2, "electronics": 4}

# Recipes. ingredients: the least of each resource; effects: as an ideology's (see ideology.describe), at the
# least ingredients. colour: of the brew in the pot.
RECIPES = {
    "hearty_stew": {"name": "Hearty Stew", "ingredients": {"food": 30, "livestock": 1}, "colour": "#c8823c",
                    "effects": {"speed": {"food": 0.1}},
                    "desc": "Meat, roots and a long simmer. Everyone in the fields works with a full belly."},
    "bark_tonic": {"name": "Bark Tonic", "ingredients": {"wood": 40, "food": 10}, "colour": "#8a6a3a",
                   "effects": {"speed": {"materials": 0.08}},
                   "desc": "Bitter, woody and good for the back. Loggers and quarrymen swear by it."},
    "stone_soup": {"name": "Stone Soup", "ingredients": {"stone": 30, "food": 20}, "colour": "#9aa0a6",
                   "effects": {"attracts": 0.5},
                   "desc": "A pot of water and a stone, and soon everyone passing adds something. Travellers stay for a bowl."},
    "thinkers_tea": {"name": "Thinker's Tea", "ingredients": {"knowledge": 10, "food": 15}, "colour": "#6fa8dc",
                     "effects": {"speed": {"knowledge": 0.08}},
                     "desc": "Steeped over a scroll of old notes. Sharpens the mind, if not the taste."},
    "beast_broth": {"name": "Beast Broth", "ingredients": {"livestock": 2, "food": 20}, "colour": "#b45f5f",
                    "effects": {"beast_xp": 0.2, "hatch_speed": 0.15},
                    "desc": "Rich bone broth for the beasts and their eggs."},
    "wild_musk": {"name": "Wild Musk", "ingredients": {"livestock": 1, "wood": 20}, "colour": "#7d9a4a",
                  "effects": {"wildlife_speed": 0.3},
                  "desc": "A smoky brew whose smell carries for miles. Wild animals come to see what it is."},
    "golden_elixir": {"name": "Golden Elixir", "ingredients": {"gold": 20, "food": 20}, "colour": "#e8c547",
                      "effects": {"speed": {"trade": 0.08}},
                      "desc": "Flecks of real gold in honey. Merchants feel lucky all day."},
    "iron_draught": {"name": "Iron Draught", "ingredients": {"ore": 25, "stone": 15}, "colour": "#a0675a",
                     "effects": {"explore_speed": 0.15},
                     "desc": "Tastes of rust and makes legs like iron. Expeditions march further each day."},
    "lucky_charm": {"name": "Lucky Charm Brew", "ingredients": {"gold": 15, "livestock": 1}, "colour": "#57c27a",
                    "effects": {"egg_chance": 0.05, "mission_speed": 0.15},
                    "desc": "A clover, a coin and a whisker in the pot. Beasts find more to do, and expeditions more eggs."},
    "tinkers_oil": {"name": "Tinker's Oil", "ingredients": {"tools": 10, "ore": 15}, "colour": "#5a5a5a",
                    "effects": {"power": 0.08, "speed": {"all": 0.02}},
                    "desc": "Not for drinking: rubbed into every gear and hinge in the city."},
    "travellers_flask": {"name": "Traveller's Flask", "ingredients": {"tools": 8, "food": 30, "livestock": 1},
                         "colour": "#c9a96e", "effects": {"explore_cost": 0.1, "explore_speed": 0.08},
                         "desc": "A flask for every pack. Teams carry less and walk further."},
    "spark_draught": {"name": "Spark Draught", "ingredients": {"electronics": 5, "gold": 20}, "colour": "#9fe8ff",
                      "effects": {"power": 0.12},
                      "desc": "It fizzes and it hums. Generators run hot while it bubbles."},
    "night_owl": {"name": "Night Owl Brew", "ingredients": {"electronics": 4, "knowledge": 20}, "colour": "#4b3f8f",
                  "effects": {"night_shelter": 0.3},
                  "desc": "Strong enough to keep the whole city up past dark."},
    "storm_ward": {"name": "Storm Ward", "ingredients": {"electronics": 4, "stone": 30}, "colour": "#3d6b8a",
                   "effects": {"weather_shelter": 0.3},
                   "desc": "Poured on the city walls, it turns the worst of the weather aside."},
    "grand_panacea": {"name": "Grand Panacea",
                      "ingredients": {"food": 20, "wood": 20, "stone": 20, "ore": 10, "tools": 5, "gold": 10,
                                      "electronics": 2, "livestock": 1, "knowledge": 10},
                      "colour": "#e07bd8", "effects": {"speed": {"all": 0.05}},
                      "desc": "A little of everything the city has. Everything works a little better."},
}


def has(state, resource):
    """True once the city can put this resource in the pot."""
    return state["tech"] >= RESOURCE_TECH.get(resource, 0) or state["resources"].get(resource, 0) > 0


def locked(state, rid):
    """The ingredients the city does not have yet, or []."""
    return [k for k in RECIPES[rid]["ingredients"] if not has(state, k)]


def terms(times):
    """(strength, seconds) of a brew of `times` the least ingredients. No top: each doubling adds the same step."""
    d = math.log2(max(1.0, times))
    return 1 + GIFT_STRENGTH * d, BREW_TIME * (1 + GIFT_TIME * d)


def cost(rid, times):
    return {k: math.ceil(v * times) for k, v in RECIPES[rid]["ingredients"].items()}


def brew(state, now, rid, times=1):
    """Brew recipe `rid` from `times` its least ingredients. Returns an error, or None."""
    import game
    if rid not in RECIPES:
        return "That is not a recipe."
    if not (isinstance(times, (int, float)) and not isinstance(times, bool)) or times != times or times == float("inf"):
        return "Say how much to put in."
    if times < 1:
        return "Put in at least the recipe's least."
    missing = locked(state, rid)
    if missing:
        return f"You have no {', '.join(game.RESOURCES[k] for k in missing)} to put in yet."
    if now < state.get("cauldron_next", 0):
        wait = int(state["cauldron_next"] - now)
        return f"The cauldron is still bubbling. It takes a new brew in {wait // 60}m {wait % 60:02d}s."
    if any(v * times == float("inf") for v in RECIPES[rid]["ingredients"].values()):
        return f"Not enough for {RECIPES[rid]['name']}: no city has that much."
    price = cost(rid, times)
    short = game._missing(state, price)
    if short:
        return f"Not enough for {RECIPES[rid]['name']} (need {game.fmt_goods(short)})."
    game._pay(state, price)
    strength, seconds = terms(times)
    seconds = round(seconds)
    state.setdefault("potions", {})[rid] = {"start": now, "until": now + seconds, "scale": strength, "times": times}
    state["cauldron_next"] = now + BREW_EVERY
    game.tally(state, "brews")
    words = ", ".join(ideology.describe(ideology._scaled(RECIPES[rid]["effects"], strength)))
    game.log(state, now, f"*** The cauldron brewed {RECIPES[rid]['name']} from {game.fmt_goods(price)}. "
                         f"For {seconds // 3600}h {seconds % 3600 // 60:02d}m: {words}. ***")
    return None


def active(state):
    """(recipe id, brew) for every brew working at the moment being worked out (see game.advance_time)."""
    t = state.get("ritual_now", state["updated"])
    return [(rid, p) for rid, p in state.get("potions", {}).items() if rid in RECIPES and p["start"] <= t < p["until"]]


def effects(state):
    """What every brew working now gives, added up (as ideology.effects)."""
    total = {"speed": {}}
    for rid, p in active(state):
        for key, value in ideology._scaled(RECIPES[rid]["effects"], p["scale"]).items():
            if key == "speed":
                for cat, x in value.items():
                    total["speed"][cat] = total["speed"].get(cat, 0) + x
            else:
                total[key] = total.get(key, 0) + value
    return total


def speed_bonus(state, category):
    """(multiplier, label) the brews put on a building of this category, or None."""
    per = effects(state)["speed"]
    extra = per.get(category, 0) + per.get("all", 0)
    return (1 + extra, "Cauldron") if extra else None


def tidy(state):
    """Forget brews that have finished."""
    for rid in [rid for rid, p in state.get("potions", {}).items() if p["until"] <= state["updated"]]:
        del state["potions"][rid]


def ends(state):
    """When each brew stops, for game.advance_time."""
    return [p["until"] for p in state.get("potions", {}).values()]


def defs():
    """The recipes as the page shows them."""
    return {"recipes": {rid: {"name": r["name"], "desc": r["desc"], "colour": r["colour"], "ingredients": r["ingredients"],
                              "effects": r["effects"], "text": ideology.describe(r["effects"])}
                        for rid, r in RECIPES.items()},
            "every": BREW_EVERY, "time": BREW_TIME, "gift_strength": GIFT_STRENGTH, "gift_time": GIFT_TIME,
            "resource_tech": RESOURCE_TECH}


def view(state):
    return {"next": state.get("cauldron_next", 0),
            "locked": {rid: locked(state, rid) for rid in RECIPES},
            "active": {rid: {"until": p["until"], "scale": p["scale"], "times": p["times"],
                             "text": ideology.describe(ideology._scaled(RECIPES[rid]["effects"], p["scale"]))}
                       for rid, p in active(state)}}
