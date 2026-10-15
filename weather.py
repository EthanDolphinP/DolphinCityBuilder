"""Day and night, and the weather in each area.

Day and night follow the clock of the player's own device: the page sends its
time zone and the city remembers it, so a city's nights fall when its player's
nights do, even while they are away. Night is from 20:00 to 06:00.

Every area always has some weather, and it changes at every meal. What it is
can't be predicted by the player but is fixed: it is worked out from the city,
the area and the meal, so it comes out the same whether the city is being
watched or catching up after the player was away. Each kind of land has its
own likely weather (deserts get heatwaves and sandstorms, the tundra snow and
blizzards) and a few kinds are rare.

Day, night and weather each make some kinds of building faster and others
slower (see GROUPS for the kinds). They multiply a building's work speed, or a
generator's power. Only rare weather, and night for solar power, can bring
something to a stop.

`game` imports this module and this module uses `game`, so nothing here may
touch `game` at import time: only inside functions.
"""

import random

import game

NIGHT_START, NIGHT_END = 20, 6         # local hours: 20:00 to 06:00 is night

# What day and night do. Keys are building groups (see groups()); values multiply speed or power.
DAY = {"name": "Day", "effects": {"crops": 1.15, "solar": 1.0},
       "desc": "Crops grow well in daylight."}
NIGHT = {"name": "Night", "effects": {"crops": 0.3, "solar": 0.0, "livestock": 0.85, "cat:materials": 0.8,
                                      "cat:trade": 0.85, "fishing": 1.15, "nightlife": 1.4, "stargazing": 1.5},
         "desc": "Crops barely grow and solar panels stop, mines and shops slow down; night fishing, "
                 "taverns and the like, and anything that studies the sky do better. Taverns and inns "
                 "each bring one more arrival per meal at night."}
NIGHTLIFE_ATTRACTS = ("tavern", "bath_house", "resort")     # one more arrival each per meal, at night

# Weather. weight: how common; land: multipliers on the weight by kind of land ("hot", "cold", "wet");
# rare: shown as rare. effects: building group -> multiplier ("all" = every building).
WEATHER = {
    "clear":   {"name": "Clear skies", "weight": 30, "effects": {"crops": 1.1, "solar": 1.2},
                "desc": "Sunshine: crops and solar panels do well."},
    "cloudy":  {"name": "Cloudy", "weight": 22, "effects": {"solar": 0.6, "crops": 0.95},
                "desc": "Grey and still. Solar panels suffer."},
    "rain":    {"name": "Rain", "weight": 18, "land": {"wet": 1.6, "hot": 0.3},
                "effects": {"crops": 1.25, "cat:materials": 0.85, "solar": 0.4, "fishing": 1.1},
                "desc": "Good for the fields, bad for the quarries."},
    "windy":   {"name": "Windy", "weight": 12, "land": {"coastal": 1.6},
                "effects": {"wind": 1.6, "fishing": 0.75}, "desc": "Wind turbines spin fast; boats stay in."},
    "fog":     {"name": "Fog", "weight": 8, "land": {"wet": 1.5},
                "effects": {"fishing": 0.7, "cat:trade": 0.9}, "desc": "Nobody can see the next street."},
    "heatwave": {"name": "Heatwave", "weight": 5, "land": {"hot": 3, "cold": 0},
                 "effects": {"crops": 0.7, "livestock": 0.85, "solar": 1.4, "nightlife": 1.2},
                 "desc": "Too hot to work the fields, perfect for the solar farms and the bath houses."},
    "cold_snap": {"name": "Cold snap", "weight": 5, "land": {"cold": 3, "hot": 0},
                  "effects": {"crops": 0.6, "livestock": 0.8, "fuel_power": 1.1},
                  "desc": "Frost on everything; furnaces roar."},
    "snow":    {"name": "Snow", "weight": 4, "land": {"cold": 4, "hot": 0, "mild": 0.3},
                "effects": {"crops": 0.5, "cat:materials": 0.75, "solar": 0.5, "livestock": 0.8},
                "desc": "A white blanket over the fields and the mines."},
    "storm":   {"name": "Thunderstorm", "weight": 4, "land": {"wet": 1.5},
                "effects": {"crops": 1.15, "fishing": 0.5, "solar": 0.3, "wind": 1.3, "cat:materials": 0.85},
                "desc": "Rain for the crops, danger for the boats."},
    # rare
    "blizzard": {"name": "Blizzard", "weight": 0.6, "rare": True, "land": {"cold": 1, "hot": 0, "mild": 0, "wet": 0},
                 "effects": {"crops": 0.0, "cat:materials": 0.3, "livestock": 0.5, "fishing": 0.2, "solar": 0.1, "cat:trade": 0.7},
                 "desc": "Nothing moves outdoors. The fields stop entirely."},
    "sandstorm": {"name": "Sandstorm", "weight": 0.6, "rare": True, "land": {"hot": 1, "cold": 0, "mild": 0, "wet": 0},
                  "effects": {"cat:materials": 0.4, "crops": 0.4, "solar": 0.1, "cat:trade": 0.5},
                  "desc": "Walls of sand. Stay inside."},
    "monsoon": {"name": "Monsoon", "weight": 0.6, "rare": True, "land": {"wet": 1, "hot": 0, "cold": 0, "mild": 0},
                "effects": {"crops": 1.6, "cat:materials": 0.5, "fishing": 1.3, "water_power": 1.5},
                "desc": "Weeks of rain in a day: the paddies overflow and the rivers roar."},
    "drought": {"name": "Drought", "weight": 0.5, "rare": True, "land": {"cold": 0},
                "effects": {"crops": 0.3, "fishing": 0.6, "water_power": 0.5, "livestock": 0.8},
                "desc": "Dry wells and cracked fields."},
    "aurora":  {"name": "Aurora", "weight": 0.4, "rare": True, "land": {"cold": 2, "hot": 0},
                "effects": {"stargazing": 2.0, "cat:knowledge": 1.5, "nightlife": 1.3},
                "desc": "Curtains of light across the sky. Everyone is out watching, and the scholars take notes."},
    "rainbow": {"name": "Rainbow", "weight": 0.4, "rare": True,
                "effects": {"all": 1.15}, "desc": "A good omen: everything goes a little better."},
    "meteors": {"name": "Meteor shower", "weight": 0.3, "rare": True,
                "effects": {"stargazing": 2.5, "cat:knowledge": 1.3}, "desc": "Falling stars all night long."},
    "eclipse": {"name": "Eclipse", "weight": 0.1, "rare": True,
                "effects": {"solar": 0.0, "crops": 0.5, "stargazing": 3.0},
                "desc": "The sun goes out at noon. Very rare."},
}

# Which kinds of land count as hot, cold, wet or coastal; everything else is "mild".
LAND = {"hot": {"desert", "savanna", "badlands", "volcanic", "steppe"},
        "cold": {"tundra", "taiga", "highlands"},
        "wet": {"jungle", "delta", "lakeland", "coast", "islands", "woodland"},
        "coastal": {"coast", "islands", "steppe"}}

# Building groups, for the effects above. "cat:<category>" groups are the build menu's kinds.
GROUP_NAMES = {"crops": "Crops", "livestock": "Livestock", "fishing": "Fishing", "solar": "Solar power",
               "wind": "Wind power", "water_power": "Water power", "fuel_power": "Fuel power",
               "nightlife": "Taverns, inns and shows", "stargazing": "Stargazers", "all": "Everything",
               "cat:materials": "Materials", "cat:trade": "Shops and trade", "cat:knowledge": "Knowledge"}
STARGAZING = {"observatory", "shaman_hut"}
NIGHTLIFE = {"tavern", "bath_house", "resort", "stadium", "zoo", "museum"}
WIND = {"wind_turbine"}
WATER_POWER = {"hydro_dam", "water_mill", "tidal_generator", "tidal_array"}

_GROUPS = {}
_CACHE = {}


def groups(bid):
    """The groups a building belongs to."""
    if bid not in _GROUPS:
        b = game.BUILDINGS[bid]
        mods = set(b.get("modifiers", []))
        out = {"all", "cat:" + b.get("category", "")}
        animals = b.get("herd") or b.get("livestock_speed") or "livestock" in b.get("produces", {})
        if mods & {"fertility", "crop_temperature"} and b.get("category") == "food" and not animals:
            out.add("crops")
        if animals:
            out.add("livestock")
        if "fish" in mods:
            out.add("fishing")
        if "sunlight" in b.get("generates_modifiers", []):
            out.add("solar")
        if bid in WIND:
            out.add("wind")
        if bid in WATER_POWER:
            out.add("water_power")
        if b.get("generates") and b.get("consumes"):
            out.add("fuel_power")
        if bid in NIGHTLIFE:
            out.add("nightlife")
        if bid in STARGAZING:
            out.add("stargazing")
        _GROUPS[bid] = out
    return _GROUPS[bid]


# ---- time ----

def local_hour(state, t):
    """The hour (0-24, with fractions) on the player's own clock at time t."""
    return ((t + state.get("tz", 0) * 60) % 86400) / 3600


def is_night(state, t):
    h = local_hour(state, t)
    return h >= NIGHT_START or h < NIGHT_END


def set_timezone(state, minutes):
    """The page reports its time zone (minutes ahead of UTC) with every request of the city's own player."""
    if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and -840 <= minutes <= 840:
        state["tz"] = int(minutes)


# ---- weather ----

def phase(state):
    """When in each MEAL_TIME this city's meals fall. advance_time() notes it before it moves the clock on."""
    return state.get("wphase", (state["updated"] - state["meal"]) % game.MEAL_TIME)


def _slot(state, t):
    """Which meal it is at time t: the weather changes when a new one starts."""
    return int((t - phase(state)) // game.MEAL_TIME)


def _land(env):
    kinds = {k for k, envs in LAND.items() if env in envs}
    return kinds or {"mild"}


def weather_at(state, ai, t):
    """The weather id in area `ai` at time t."""
    area = state["areas"][ai]
    slot = _slot(state, t)
    key = (state.get("seed"), area["rx"], area["ry"], slot, area["env"])
    if key not in _CACHE:
        if len(_CACHE) > 20000:
            _CACHE.clear()
        kinds = _land(area["env"])
        ids, weights = [], []
        for wid, w in WEATHER.items():
            weight = w["weight"]
            for kind, mult in w.get("land", {}).items():
                if kind in kinds:
                    weight *= mult
            if weight > 0:
                ids.append(wid)
                weights.append(weight)
        _CACHE[key] = random.Random(f"{key[0]}:{key[1]}:{key[2]}:{slot}").choices(ids, weights=weights)[0]
    return _CACHE[key]


def _effect(effects, gset):
    mult = 1.0
    for g, x in effects.items():
        if g in gset:
            mult *= x
    return mult


def job_factors(state, jobs, t):
    """For each job (see game.work_plan) at time t: (work speed multiplier, power multiplier, [labels])
    from day or night and the weather in its area."""
    when = NIGHT if is_night(state, t) else DAY
    skies = {}
    out = []
    for job in jobs:
        ai, bid = job["area"], job["tile"]["building"]
        if ai not in skies:
            skies[ai] = WEATHER[weather_at(state, ai, t)]
        gset = groups(bid)
        mult, notes = 1.0, []
        for label, effects in ((when["name"], when["effects"]), (skies[ai]["name"], skies[ai]["effects"])):
            x = _effect(effects, gset)
            if x != 1.0:
                mult *= x
                notes.append(f"{label} x{x:.2f}")
        # A generator's power changes with the weather; how fast it burns fuel does not.
        if job["power_out"]:
            out.append((1.0, mult, notes))
        else:
            out.append((mult, 1.0, notes))
    return out


def night_attracts(state, t):
    """Extra arrivals per meal at night: one for each tavern, bath house and resort."""
    if not is_night(state, t):
        return 0
    return sum(1 for tile in game.all_tiles(state) if tile["building"] in NIGHTLIFE_ATTRACTS)


# ---- for the page ----

def describe(effects):
    """{"crops": 1.25, ...} -> ["Crops +25%", ...]"""
    out = []
    for g, x in effects.items():
        name = GROUP_NAMES.get(g, g)
        out.append(f"{name} stop" if x == 0 else f"{name} {'+' if x > 1 else '-'}{round(abs(x - 1) * 100)}%")
    return out


def defs():
    return {"weather": {wid: {"name": w["name"], "rare": bool(w.get("rare")), "desc": w["desc"], "text": describe(w["effects"])}
                        for wid, w in WEATHER.items()},
            "day": {"name": DAY["name"], "desc": DAY["desc"], "text": describe(DAY["effects"])},
            "night": {"name": NIGHT["name"], "desc": NIGHT["desc"], "text": describe(NIGHT["effects"])},
            "night_hours": [NIGHT_START, NIGHT_END]}


def view(state, t):
    """The time and every area's weather now and next, for the page."""
    h = local_hour(state, t)
    night = is_night(state, t)
    # seconds until day turns to night or night to day
    until = ((NIGHT_END - h) % 24 if night else (NIGHT_START - h) % 24) * 3600
    next_change = game.MEAL_TIME - (t - phase(state)) % game.MEAL_TIME
    return {"night": night, "clock": f"{int(h):02d}:{int(h * 60) % 60:02d}", "switch_in": round(until),
            "tz": state.get("tz", 0), "change_in": round(next_change),
            "areas": [{"now": weather_at(state, i, t), "next": weather_at(state, i, t + game.MEAL_TIME)}
                      for i in range(len(state["areas"]))]}
