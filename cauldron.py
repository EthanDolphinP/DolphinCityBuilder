"""The Cauldron: open from the start. The player sets one recipe and how much of it goes in; every hour the cauldron
takes those ingredients and brews for that hour, again and again, until the recipe is changed or stopped.

One brew at a time. A brew always lasts BREW_TIME (an hour). Putting in more of the recipe ("times" its least
ingredients) makes the brew stronger, with no top: like a ritual's gift or a hex's, every doubling adds the same
step (GIFT_STRENGTH), so each extra handful adds a little less than the one before but never nothing.

state["cauldron"] = {"recipe", "times", "start", "until", "brewing"}: the hour now under way runs from start to
until; brewing is False for an hour the ingredients were not there (it tries again at until). game.advance_time
stops at every until and calls renew(), so a city brews hour after hour while its player is away.

A recipe can be made once the city has every one of its ingredients: once it reaches the tech level that first
makes one (RESOURCE_TECH), or as soon as it has some (bought on the market, say).

`game` imports this module and this module uses `game`, so nothing here may touch `game` at import time.
"""
import math

import ideology

MIN, HOUR = 60, 3600
BREW_TIME = HOUR           # every brew lasts this long, then the next one is made from the same recipe
GIFT_STRENGTH = 0.35       # every doubling of the ingredients makes the brew this much stronger (no top)
RESOURCE_TECH = {"food": 0, "wood": 0, "stone": 0, "livestock": 0, "knowledge": 0,
                 "ore": 1, "gold": 1, "tools": 2, "electronics": 4}

# Recipes. ingredients: what one brew (an hour) takes at the least; effects: as an ideology's (see
# ideology.describe), at the least ingredients. colour: of the brew in the pot.
RECIPES = {
    "harvest_stew": {"name": "Harvest Stew", "ingredients": {"food": 40, "livestock": 1}, "colour": "#c8823c",
                     "effects": {"speed": {"food": 0.1}, "attracts": 0.4},
                     "desc": "Meat, roots and a long simmer. The fields work on full bellies, and the smell brings travellers in."},
    "woodland_tonic": {"name": "Woodland Tonic", "ingredients": {"wood": 40, "stone": 20, "food": 10}, "colour": "#7d9a4a",
                       "effects": {"speed": {"materials": 0.08}, "wildlife_speed": 0.25},
                       "desc": "Bark, moss and river stones. Loggers and quarrymen swear by it, and wild animals follow the smell."},
    "sages_tea": {"name": "Sage's Tea", "ingredients": {"knowledge": 15, "food": 20}, "colour": "#6fa8dc",
                  "effects": {"speed": {"knowledge": 0.08}, "beast_xp": 0.15, "hatch_speed": 0.1},
                  "desc": "Steeped over a scroll of old notes. Sharpens scholars and beasts alike, and warms the eggs."},
    "golden_elixir": {"name": "Golden Elixir", "ingredients": {"gold": 20, "food": 20, "livestock": 1}, "colour": "#e8c547",
                      "effects": {"speed": {"trade": 0.08}, "mission_speed": 0.12, "egg_chance": 0.04},
                      "desc": "Flecks of real gold in honey. Merchants feel lucky, beasts find more to do, expeditions more eggs."},
    "wayfarers_draught": {"name": "Wayfarer's Draught", "ingredients": {"ore": 25, "food": 30, "livestock": 1},
                          "colour": "#a0675a", "effects": {"explore_speed": 0.18, "explore_cost": 0.08},
                          "desc": "Tastes of rust and makes legs like iron. Teams march further and carry less."},
    "tinkers_oil": {"name": "Tinker's Oil", "ingredients": {"tools": 10, "ore": 15}, "colour": "#8f8f8f",
                    "effects": {"power": 0.1, "speed": {"all": 0.03}},
                    "desc": "Not for drinking: rubbed into every gear and hinge in the city."},
    "moonlit_ward": {"name": "Moonlit Ward", "ingredients": {"electronics": 5, "stone": 30, "knowledge": 20},
                     "colour": "#4b3f8f", "effects": {"night_shelter": 0.3, "weather_shelter": 0.3, "power": 0.06},
                     "desc": "It hums and glows. The city works on through the dark and the storms, and the generators run hot."},
    "grand_panacea": {"name": "Grand Panacea",
                      "ingredients": {"food": 20, "wood": 20, "stone": 20, "ore": 10, "tools": 5, "gold": 10,
                                      "electronics": 2, "livestock": 1, "knowledge": 10},
                      "colour": "#e07bd8", "effects": {"speed": {"all": 0.06}, "attracts": 0.3, "beast_xp": 0.1},
                      "desc": "A little of everything the city has. Everything works a little better."},
}


def has(state, resource):
    """True once the city can put this resource in the pot."""
    return state["tech"] >= RESOURCE_TECH.get(resource, 0) or state["resources"].get(resource, 0) > 0


def locked(state, rid):
    """The ingredients the city does not have yet, or []."""
    return [k for k in RECIPES[rid]["ingredients"] if not has(state, k)]


def strength(times):
    """How strong a brew of `times` the least ingredients is. No top: each doubling adds the same step."""
    return 1 + GIFT_STRENGTH * math.log2(max(1.0, times))


def cost(rid, times):
    """What one brew (an hour) of `times` the recipe takes."""
    return {k: math.ceil(v * times) for k, v in RECIPES[rid]["ingredients"].items()}


def _good_times(times):
    return isinstance(times, (int, float)) and not isinstance(times, bool) and times == times and times != float("inf")


def _brew(state, when):
    """Make the hour's brew from the set recipe, if the ingredients are there. Returns what was missing, or None."""
    import game
    pot = state["cauldron"]
    rid, times = pot["recipe"], pot["times"]
    price = cost(rid, times)
    short = game._missing(state, price) or ({k: 1 for k in locked(state, rid)} or None)
    pot.update(start=when, until=when + BREW_TIME, brewing=not short)
    if short:
        return short
    game._pay(state, price)
    game.tally(state, "brews")
    return None


def set_recipe(state, now, rid, times=1):
    """Set the cauldron's recipe and how much goes in, and brew the first hour of it now. Returns an error, or None."""
    import game
    if rid not in RECIPES:
        return "That is not a recipe."
    if not _good_times(times):
        return "Say how much to put in."
    if times < 1:
        return "Put in at least the recipe's least."
    if any(v * times == float("inf") for v in RECIPES[rid]["ingredients"].values()):
        return f"Not enough for {RECIPES[rid]['name']}: no city has that much."
    missing = locked(state, rid)
    if missing:
        return f"You have no {', '.join(game.RESOURCES[k] for k in missing)} to put in yet."
    price = cost(rid, times)
    short = game._missing(state, price)
    if short:
        return f"Not enough for an hour of {RECIPES[rid]['name']} (need {game.fmt_goods(short)})."
    state["cauldron"] = {"recipe": rid, "times": times}
    _brew(state, now)
    words = ", ".join(ideology.describe(ideology._scaled(RECIPES[rid]["effects"], strength(times))))
    game.log(state, now, f"*** The cauldron is brewing {RECIPES[rid]['name']} from {game.fmt_goods(price)} an hour: "
                         f"{words}. It brews again every hour while the ingredients are there. ***")
    return None


def stop(state, now):
    """Take the recipe off: the brew under way finishes its hour, and no more are made."""
    import game
    pot = state.get("cauldron")
    if not pot or not pot.get("recipe"):
        return "Nothing is set to brew."
    pot["recipe_stopped"] = pot.pop("recipe")
    game.log(state, now, f"The cauldron will not brew {RECIPES[pot['recipe_stopped']]['name']} again after this hour.")
    return None


def renew(state, when):
    """At the end of an hour (game.advance_time stops here): brew the next hour from the same recipe."""
    import game
    pot = state.get("cauldron")
    if not pot or pot.get("until") != when:
        return
    if not pot.get("recipe") or pot["recipe"] not in RECIPES:
        state.pop("cauldron", None)        # stopped: the last brew is over
        return
    was = pot.get("brewing")
    short = _brew(state, when)
    name = RECIPES[pot["recipe"]]["name"]
    if short and was:
        game.log(state, when, f"The cauldron went cold: not enough for another hour of {name} "
                              f"(need {game.fmt_goods(short)}). It tries again every hour.")
    elif not short and not was:
        game.log(state, when, f"The cauldron is bubbling again: {name}.")


def hourly(state):
    """What the cauldron takes each hour while it is brewing ({} when it is empty, stopped or cold), for the city's
    per-hour figures."""
    pot = state.get("cauldron")
    if not pot or not pot.get("recipe") or pot["recipe"] not in RECIPES or not pot.get("brewing"):
        return {}
    return {k: v * HOUR / BREW_TIME for k, v in cost(pot["recipe"], pot["times"]).items()}


def ends(state):
    """When the hour under way ends, for game.advance_time (it stops there and calls renew)."""
    pot = state.get("cauldron")
    return [pot["until"]] if pot and "until" in pot else []


def active(state):
    """(recipe id, strength) of the brew working at the moment being worked out, or None."""
    pot = state.get("cauldron")
    t = state.get("ritual_now", state["updated"])
    rid = pot and (pot.get("recipe") or pot.get("recipe_stopped"))
    if not pot or not pot.get("brewing") or rid not in RECIPES or not pot["start"] <= t < pot["until"]:
        return None
    return rid, strength(pot["times"])


def effects(state):
    """What the brew working now gives (as ideology.effects)."""
    now = active(state)
    if not now:
        return {"speed": {}}
    out = ideology._scaled(RECIPES[now[0]]["effects"], now[1])
    out.setdefault("speed", {})
    return out


def speed_bonus(state, category):
    """(multiplier, label) the brew puts on a building of this category, or None."""
    per = effects(state)["speed"]
    extra = per.get(category, 0) + per.get("all", 0)
    return (1 + extra, "Cauldron") if extra else None


def tidy(state):
    """Forget what is finished: the brews of the old Cauldron (one per recipe) and a stopped one that has ended."""
    state.pop("potions", None)
    state.pop("cauldron_next", None)
    pot = state.get("cauldron")
    if pot and not pot.get("recipe") and pot.get("until", 0) <= state["updated"]:
        state.pop("cauldron", None)


def defs():
    """The recipes as the page shows them."""
    return {"recipes": {rid: {"name": r["name"], "desc": r["desc"], "colour": r["colour"], "ingredients": r["ingredients"],
                              "effects": r["effects"], "text": ideology.describe(r["effects"])}
                        for rid, r in RECIPES.items()},
            "time": BREW_TIME, "gift_strength": GIFT_STRENGTH, "resource_tech": RESOURCE_TECH}


def view(state):
    pot = state.get("cauldron") or {}
    rid = pot.get("recipe") or pot.get("recipe_stopped")
    now = active(state)
    return {"recipe": pot.get("recipe"), "stopped": pot.get("recipe_stopped"), "times": pot.get("times", 1),
            "until": pot.get("until"), "brewing": bool(now),
            "cost": cost(rid, pot["times"]) if rid else None,
            "text": ideology.describe(ideology._scaled(RECIPES[now[0]]["effects"], now[1])) if now else [],
            "locked": {r: locked(state, r) for r in RECIPES}}
