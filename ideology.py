"""Ideologies: what a city believes in, chosen once it becomes a Village.

Each ideology gives a bonus straight away, and then has perks of its own that
fit it: the Old Faith's perks are blessings from its gods, Progress's are great
inventions, and so on. Every tech level from Village up earns one point, spent
on a perk whenever the player likes (Village earns 1, Megacity 5 in all). Each
ideology has ten perks, two in each of five tiers; a perk can be taken once the
city has reached its tier, so a city ends up with five of the ten.

Effects, added up over the ideology and its perks taken:

    speed          {building category or "all": 0.1} = those buildings 10% faster
    explore_speed  0.25 = expeditions travel 25% faster
    explore_cost   0.15 = expeditions need 15% fewer supplies
    wildlife_speed 0.5 = wild animals appear 50% more often
    attracts       extra arrivals per meal
    housing        people housed
    power          0.2 = generators give 20% more power
    beast_xp / beast_power / hatch_speed / egg_chance / mission_speed   as in beasts.py

`game` imports this module and this module uses `game`, so nothing here may
touch `game` at import time: only inside functions.
"""

import game

IDEOLOGIES = {
    "faith": {
        "name": "The Old Faith", "perk_word": "Blessing", "perk_plural": "Blessings of the gods",
        "desc": "The city keeps the old gods, and they keep the city. Their blessings reach every part of life.",
        "effects": {"speed": {"food": 0.10, "knowledge": 0.10}},
        "perks": {
            "harvest_mother": {"name": "Blessing of the Harvest Mother", "tier": 1, "effects": {"speed": {"food": 0.15}},
                               "desc": "The fields are never quite empty."},
            "hearth_keeper":  {"name": "Blessing of the Hearth Keeper", "tier": 1, "effects": {"housing": 30},
                               "desc": "There is always room for one more by the fire."},
            "wanderer":       {"name": "Blessing of the Wanderer", "tier": 2, "effects": {"explore_speed": 0.25, "explore_cost": 0.15},
                               "desc": "Roads run straight and rivers stay low for the faithful."},
            "beast_mother":   {"name": "Blessing of the Beast Mother", "tier": 3, "effects": {"beast_power": 0.25, "mission_speed": 0.25},
                               "desc": "The great beasts know whose city this is."},
            "sun_father":     {"name": "Blessing of the Sun Father", "tier": 4, "effects": {"power": 0.20},
                               "desc": "Every fire burns a little hotter."},
            "plenty":         {"name": "Miracle of Plenty", "tier": 5, "effects": {"speed": {"all": 0.08}},
                               "desc": "Nobody can explain it. Nobody complains."},
            "stone_father":   {"name": "Blessing of the Stone Father", "tier": 2, "effects": {"speed": {"materials": 0.12}},
                               "desc": "Seams of ore open where the miners pray."},
            "coin_god":       {"name": "Blessing of the Two-Faced Coin", "tier": 3, "effects": {"speed": {"trade": 0.15}},
                               "desc": "The god of bargains smiles on honest weights."},
            "night_owl":      {"name": "Blessing of the Night Owl", "tier": 4, "effects": {"speed": {"knowledge": 0.20}},
                               "desc": "The goddess of wisdom keeps the scholars' lamps burning."},
            "many_armed":     {"name": "Blessing of the Many-Armed", "tier": 5, "effects": {"housing": 60, "attracts": 1},
                               "desc": "Pilgrims come from every land, and the temple finds them all a bed."},
        },
    },
    "progress": {
        "name": "Progress", "perk_word": "Breakthrough", "perk_plural": "Great breakthroughs",
        "desc": "Measure, test, improve. The city puts its faith in invention, and every age brings a great leap forward.",
        "effects": {"speed": {"materials": 0.15}},
        "perks": {
            "parts":       {"name": "Interchangeable Parts", "tier": 1, "effects": {"speed": {"materials": 0.15}},
                            "desc": "Any bolt fits any nut, so nothing waits for a smith."},
            "movable_type": {"name": "Movable Type", "tier": 1, "effects": {"speed": {"knowledge": 0.15}},
                             "desc": "A book a day instead of a book a year."},
            "steam":       {"name": "Steam Power", "tier": 2, "effects": {"power": 0.20},
                            "desc": "Boilers, pistons and a great deal of noise."},
            "instruments": {"name": "Precision Instruments", "tier": 3, "effects": {"explore_speed": 0.30},
                            "desc": "Sextants, chronometers and maps that are actually right."},
            "assembly":    {"name": "Assembly Science", "tier": 4, "effects": {"speed": {"materials": 0.10, "trade": 0.10}},
                            "desc": "Every task timed, every step improved."},
            "thinking_machine": {"name": "The Thinking Machine", "tier": 5, "effects": {"speed": {"all": 0.10}},
                                 "desc": "It plans the city's work better than any council could."},
            "crop_rotation": {"name": "Crop Rotation", "tier": 2, "effects": {"speed": {"food": 0.15}},
                              "desc": "Rest the soil, feed the soil, and it feeds you back."},
            "vaccination":   {"name": "Vaccination", "tier": 3, "effects": {"housing": 40, "attracts": 1},
                              "desc": "Fewer fevers, bigger families, and word spreads."},
            "refrigeration": {"name": "Refrigeration", "tier": 4, "effects": {"speed": {"food": 0.12, "trade": 0.08}},
                              "desc": "Nothing spoils, so everything can be sold."},
            "superconductors": {"name": "Superconductors", "tier": 5, "effects": {"power": 0.35},
                                "desc": "Power carried across the city without losing a spark."},
        },
    },
    "commerce": {
        "name": "Commerce", "perk_word": "Charter", "perk_plural": "Royal charters",
        "desc": "The city lives by trade. Its merchants buy charters that open new markets, routes and riches.",
        "effects": {"speed": {"trade": 0.20}},
        "perks": {
            "guild":    {"name": "Merchant Guild Charter", "tier": 1, "effects": {"speed": {"trade": 0.15}},
                         "desc": "Fair weights, fair prices, and a cut for the guild."},
            "caravan":  {"name": "Caravan Charter", "tier": 1, "effects": {"explore_cost": 0.25},
                         "desc": "Expeditions travel with the caravans and share their supplies."},
            "bank":     {"name": "Bank Charter", "tier": 2, "effects": {"speed": {"knowledge": 0.10, "trade": 0.05}},
                         "desc": "Ledgers, loans and clerks who can count."},
            "bazaar":   {"name": "Grand Bazaar Charter", "tier": 3, "effects": {"attracts": 1},
                         "desc": "People come from far away to buy, and some of them stay."},
            "shipping": {"name": "Shipping Charter", "tier": 4, "effects": {"speed": {"food": 0.10, "materials": 0.10}},
                         "desc": "Whatever the city needs arrives by the boatload."},
            "golden_age": {"name": "Golden Age", "tier": 5, "effects": {"speed": {"all": 0.08}, "attracts": 1},
                           "desc": "Everyone is doing well, and everyone wants to live here."},
            "mining":     {"name": "Mining Charter", "tier": 2, "effects": {"speed": {"materials": 0.12}},
                           "desc": "Claims sold to whoever will dig fastest."},
            "exploration": {"name": "Exploration Charter", "tier": 3, "effects": {"explore_speed": 0.25, "egg_chance": 0.05},
                            "desc": "Investors pay for the expedition, and want rare things brought home."},
            "menagerie":  {"name": "Menagerie Charter", "tier": 4, "effects": {"beast_power": 0.25, "beast_xp": 0.25},
                           "desc": "Crowds pay to see your beast, and it rather likes the attention."},
            "free_port":  {"name": "Free Port Charter", "tier": 5, "effects": {"speed": {"trade": 0.20}, "explore_cost": 0.20},
                           "desc": "No tolls, no tariffs, and ships from everywhere."},
        },
    },
    "wild": {
        "name": "Kinship with the Wild", "perk_word": "Pact", "perk_plural": "Pacts with the wild",
        "desc": "The city lives alongside the animals and the great beasts, and makes pacts with the wild places around it.",
        "effects": {"beast_xp": 0.25, "wildlife_speed": 0.5},
        "perks": {
            "herd":    {"name": "Pact of the Herd", "tier": 1, "effects": {"speed": {"food": 0.10}, "wildlife_speed": 0.5},
                        "desc": "Wild herds graze closer to the city every year."},
            "nest":    {"name": "Pact of the Nest", "tier": 1, "effects": {"hatch_speed": 1.0, "egg_chance": 0.05},
                        "desc": "Eggs are kept warm, and found where others would miss them."},
            "fang":    {"name": "Pact of the Fang", "tier": 2, "effects": {"beast_power": 0.30},
                        "desc": "Your beast fights for the city as if for its own den."},
            "seasons": {"name": "Pact of the Seasons", "tier": 3, "effects": {"mission_speed": 0.50},
                        "desc": "Your beast is restless, and asks more of the city more often."},
            "deep_woods": {"name": "Pact of the Deep Woods", "tier": 4, "effects": {"speed": {"materials": 0.15}},
                           "desc": "The forest gives up its timber and stone without a fight."},
            "heart":   {"name": "Heart of the Wild", "tier": 5, "effects": {"beast_power": 0.30, "beast_xp": 0.50},
                        "desc": "The city and its beast are one creature now."},
            "swift":   {"name": "Pact of the Swift", "tier": 2, "effects": {"explore_speed": 0.25},
                        "desc": "Birds show the expeditions the quickest way."},
            "burrow":  {"name": "Pact of the Burrow", "tier": 3, "effects": {"housing": 35},
                        "desc": "Homes dug into the hillsides, warm in winter and cool in summer."},
            "river":   {"name": "Pact of the River", "tier": 4, "effects": {"speed": {"food": 0.15}},
                        "desc": "The river floods only where the fields want water."},
            "migration": {"name": "Pact of the Great Migration", "tier": 5,
                          "effects": {"wildlife_speed": 1.0, "attracts": 1, "mission_speed": 0.25},
                          "desc": "Every spring the herds pass through, and people follow them."},
        },
    },
    "wayfarers": {
        "name": "The Wayfarers", "perk_word": "Discovery", "perk_plural": "Great discoveries",
        "desc": "Born explorers. The city looks over every horizon, and each age brings home something nobody has seen before.",
        "effects": {"explore_speed": 0.25, "explore_cost": 0.15},
        "perks": {
            "star_charts":   {"name": "Star Charts", "tier": 1, "effects": {"explore_speed": 0.25},
                              "desc": "Nobody gets lost under a clear sky."},
            "strange_seeds": {"name": "Strange Seeds", "tier": 1, "effects": {"speed": {"food": 0.12}},
                              "desc": "Crops from far away that grow faster than anything at home."},
            "lost_library":  {"name": "The Lost Library", "tier": 2, "effects": {"speed": {"knowledge": 0.20}},
                              "desc": "Found in a ruin, and still being read."},
            "far_nests":     {"name": "Nests of the Far Lands", "tier": 3, "effects": {"egg_chance": 0.10},
                              "desc": "Expeditions know where the great beasts lay."},
            "light_packs":   {"name": "Light Packs", "tier": 4, "effects": {"explore_cost": 0.25},
                              "desc": "Expeditions live off the land and carry half as much."},
            "far_horizons":  {"name": "Far Horizons", "tier": 5, "effects": {"speed": {"all": 0.06}, "attracts": 1},
                              "desc": "Travellers from every land settle in the city that found them."},
            "ore_veins":     {"name": "Foreign Ore Veins", "tier": 2, "effects": {"speed": {"materials": 0.12}},
                              "desc": "Prospectors came back with better ways to find stone and ore."},
            "trade_winds":   {"name": "The Trade Winds", "tier": 3, "effects": {"speed": {"trade": 0.15}},
                              "desc": "Winds that carry ships to market and back again."},
            "map_of_everything": {"name": "The Map of Everything", "tier": 4, "effects": {"explore_speed": 0.30, "explore_cost": 0.15},
                                  "desc": "Every road, river and pass, drawn on one enormous sheet."},
            "wonders":       {"name": "Wonders of the World", "tier": 5, "effects": {"beast_power": 0.25, "speed": {"knowledge": 0.15}},
                              "desc": "Ancient ruins full of beasts and secrets."},
        },
    },
    "community": {
        "name": "Community", "perk_word": "Tradition", "perk_plural": "Traditions",
        "desc": "Everyone has a place, and everyone helps. The city grows its people and keeps its traditions.",
        "effects": {"housing": 15, "attracts": 1},
        "perks": {
            "festivals":  {"name": "Festival Days", "tier": 1, "effects": {"attracts": 1},
                           "desc": "Music in the square, and newcomers every season."},
            "hearths":    {"name": "Shared Hearths", "tier": 1, "effects": {"housing": 40},
                           "desc": "Families take in whoever needs a roof."},
            "fields":     {"name": "Common Fields", "tier": 2, "effects": {"speed": {"food": 0.15}},
                           "desc": "Everyone helps with the harvest."},
            "guild_halls": {"name": "Guild Halls", "tier": 3, "effects": {"speed": {"materials": 0.12}},
                            "desc": "Masters teach apprentices, and nobody works alone."},
            "elders":     {"name": "Council of Elders", "tier": 4, "effects": {"speed": {"knowledge": 0.20}},
                           "desc": "Old heads, long memories, good advice."},
            "golden_generation": {"name": "The Golden Generation", "tier": 5, "effects": {"speed": {"all": 0.06}, "attracts": 1},
                                  "desc": "Children raised by the whole city, ready for anything."},
            "barn_raising": {"name": "Barn Raising", "tier": 2, "effects": {"speed": {"materials": 0.12}},
                             "desc": "The whole street turns out to build, and it is done by supper."},
            "market_day":   {"name": "Market Day", "tier": 3, "effects": {"speed": {"trade": 0.15}},
                             "desc": "Once a week the square fills with stalls from end to end."},
            "storytellers": {"name": "Storytellers", "tier": 4, "effects": {"beast_xp": 0.30, "mission_speed": 0.25},
                             "desc": "Every child knows the tales of your beast, and it tries to live up to them."},
            "open_gates":   {"name": "Open Gates", "tier": 5, "effects": {"housing": 60, "attracts": 2},
                             "desc": "Anyone who asks is welcome, and many ask."},
        },
    },
}


# ---- Pictures, drawn in text like the beasts. Each ideology has a colour; its
# perks are drawn in dark grey until taken, then lit up in that colour.
COLOURS = {"faith": "#e6c35c", "progress": "#5ad0d8", "commerce": "#f0a05a",
           "wild": "#7fc97f", "wayfarers": "#7fb8ff", "community": "#e58fd0"}

ART = {
    "faith": [
        r"       /\       ",
        r"     _/__\_     ",
        r"    | |  | |    ",
        r"    | |  | |    ",
        r"   /________\   ",
    ],
    "progress": [
        r"    _  _  _     ",
        r"   ( \/ \/ )    ",
        r"  --(  ()  )--  ",
        r"   (_/\_/\_)    ",
        r"      ||        ",
    ],
    "commerce": [
        r"      _|_       ",
        r"    _/ | \_     ",
        r"   (___|___)    ",
        r"    $  |  $     ",
        r"     __|__      ",
    ],
    "wild": [
        r"     .-''-.     ",
        r"    ( (  ) )    ",
        r"     `-||-'     ",
        r"  o o  ||  o o  ",
        r"   O   ||   O   ",
    ],
    "wayfarers": [
        r"       N        ",
        r"       ^        ",
        r"   W <-+-> E    ",
        r"       v        ",
        r"       S        ",
    ],
    "community": [
        r"   /\    /\     ",
        r"  /  \  /  \    ",
        r"  |[]|__|[]|    ",
        r"  |  |[]|  |    ",
    ],
}

PERK_ART = {
    # The Old Faith
    "harvest_mother": [r" \ | / ", r"  \|/  ", r" __|__ "],
    "hearth_keeper":  [r"  ( )  ", r" (   ) ", r" \___/ "],
    "wanderer":       [r"  .  . ", r" .  .  ", r"======="],
    "beast_mother":   [r" o o o ", r"o (_) o", r"  ' '  "],
    "sun_father":     [r" \ | / ", r"-( o )-", r" / | \ "],
    "plenty":         [r"  ___  ", r" (o o)\_", r"  \___/ "],
    "stone_father":   [r"  /\   ", r" /  \/\ ", r"/______\ "],
    "coin_god":       [r" .--.  ", r"( $$ ) ", r" '--'  "],
    "night_owl":      [r" ,_,   ", r"(o,o)  ", r"/)_)   "],
    "many_armed":     [r"\ \|/ /", r" -(o)- ", r"/ /|\ \ "],
    # Progress
    "parts":          [r" [==]  ", r"  ||   ", r"  ||   "],
    "movable_type":   [r" ____  ", r"|ABC | ", r"|____| "],
    "steam":          [r"  ~ ~  ", r" _|=|_ ", r"(o___o)"],
    "instruments":    [r"    __ ", r" __/ / ", r"/_/    "],
    "assembly":       [r"[]-[]-[]", r"========", r" o  o  o"],
    "thinking_machine": [r" _____ ", r"|01010|", r"|_____|"],
    "crop_rotation":  [r"|| || ||", r"## .. ##", r"========"],
    "vaccination":    [r"   |   ", r" [===]>", r"   |   "],
    "refrigeration":  [r" \ * / ", r"* -*- *", r" / * \ "],
    "superconductors": [r"(~~~~~)", r" >>>>> ", r"(~~~~~)"],
    # Commerce
    "guild":          [r" ____  ", r"|GILD| ", r"|____| "],
    "caravan":        [r"  _  _  ", r" / \/ \_", r" |  |  |"],
    "bank":           [r" _____ ", r" | | | ", r"_|_|_|_"],
    "bazaar":         [r"  /\   ", r" /  \  ", r"/_||_\ "],
    "shipping":       [r"   |\  ", r"   | \ ", r"\_____/"],
    "golden_age":     [r"\/\/\/ ", r"|****| ", r"|____| "],
    "mining":         [r" __/\_ ", r"   /   ", r"  /    "],
    "exploration":    [r" _____ ", r"| X ~ |", r"|_~___|"],
    "menagerie":      [r" _____ ", r"|o|o|o|", r"|_|_|_|"],
    "free_port":      [r"  _o_  ", r"   |   ", r" \_|_/ "],
    # Kinship with the Wild
    "herd":           [r" ^__^  ", r" (oo)\_", r" (__)  "],
    "nest":           [r" o O o ", r"\_____/"],
    "fang":           [r" /\/\  ", r" \  /  ", r"  \/   "],
    "seasons":        [r"* . o  ", r" ~ * ~ ", r"o . *  "],
    "deep_woods":     [r"  ^  ^ ", r" /^\/^\ ", r"  |  | "],
    "heart":          [r" _  _  ", r"( \/ ) ", r" \  /  ", r"  \/   "],
    "swift":          [r"_    _ ", r" \/\/  "],
    "burrow":         [r"  ___  ", r" / o \ ", r"/_____\ "],
    "river":          [r"~~~~~~~", r" ~~~~~~", r"~~~~~~~"],
    "migration":      [r"> > >  ", r" > > > ", r"> > >  "],
    # The Wayfarers
    "star_charts":    [r" .  *  ", r"   *  .", r"*  .   "],
    "strange_seeds":  [r"  ,  , ", r" (.)(.)", r"  '  ' "],
    "lost_library":   [r" ____  ", r"|=||=| ", r"|=||=| "],
    "far_nests":      [r" .--.  ", r"( () ) ", r" `--'  "],
    "light_packs":    [r"  __   ", r" [==]  ", r" |__|  "],
    "far_horizons":   [r" \|/   ", r"-(_)-  ", r"~~~~~~~"],
    "ore_veins":      [r"/\/\/\ ", r"\*/\*/ ", r"/\/\/\ "],
    "trade_winds":    [r"  |\   ", r"  |~\  ", r"__|__\ "],
    "map_of_everything": [r" _____ ", r"|~/\~ |", r"|_~_/_|"],
    "wonders":        [r"   /\   ", r"  /  \  ", r" /____\ "],
    # Community
    "festivals":      [r" * o * ", r"\o/ \o/", r" |   | "],
    "hearths":        [r"  ( )  ", r" __|__ ", r"|_____|"],
    "fields":         [r" \|/\|/", r" ||| ||", r"======="],
    "guild_halls":    [r"  /\   ", r" /[]\  ", r" |__|  "],
    "elders":         [r" o  o  ", r"/|\/|\ ", r"/ \/ \ "],
    "golden_generation": [r"\o/\o/ ", r" |  |  ", r"/ \/ \ "],
    "barn_raising":   [r"  /\   ", r" /||\  ", r"/_||_\ "],
    "market_day":     [r"_/\_/\_", r"|$| |@|", r"-------"],
    "storytellers":   [r"  o    ", r" /|\ ~ ", r" / \ ~ "],
    "open_gates":     [r"|\   /|", r"| \ / |", r"|  .  |"],
}

def setup(state):
    state.setdefault("ideology", None)
    state.setdefault("perks", [])


def chosen(state):
    return IDEOLOGIES.get(state.get("ideology"))


def points(state):
    """Perk points to spend: one for every tech level from Village up, less those spent."""
    return max(0, state["tech"]) - len(state.get("perks", []))


def effects(state):
    """Everything the ideology and the perks taken give, added up."""
    ideo = chosen(state)
    if not ideo:
        return {}
    total = {"speed": {}}
    for eff in [ideo["effects"]] + [ideo["perks"][p]["effects"] for p in state.get("perks", []) if p in ideo["perks"]]:
        for key, value in eff.items():
            if key == "speed":
                for cat, x in value.items():
                    total["speed"][cat] = total["speed"].get(cat, 0) + x
            else:
                total[key] = total.get(key, 0) + value
    return total


def value(state, key):
    """One number from effects(), 0 if the city has none of it."""
    return effects(state).get(key, 0) if key != "speed" else 0


def speed_bonus(state, category):
    """(multiplier, label) for a building of this category, or None."""
    ideo = chosen(state)
    if not ideo:
        return None
    per = effects(state)["speed"]
    extra = per.get(category, 0) + per.get("all", 0)
    return (1 + extra, ideo["name"]) if extra else None


def choose(state, now, ideology_id):
    if state["tech"] < 1:
        return "Ideologies are chosen once the city is a Village."
    if state.get("ideology"):
        return "Your city has already chosen its ideology."
    if ideology_id not in IDEOLOGIES:
        return "Pick one of the ideologies."
    state["ideology"] = ideology_id
    state["perks"] = []
    game.log(state, now, f"*** {state['name']} has taken up {IDEOLOGIES[ideology_id]['name']}. ***")
    return None


def take(state, now, perk_id):
    ideo = chosen(state)
    if not ideo:
        return "Choose an ideology first."
    perk = ideo["perks"].get(perk_id)
    if not perk:
        return "That is not one of your ideology's perks."
    if perk_id in state["perks"]:
        return "You already have that."
    if perk["tier"] > state["tech"]:
        return f"That needs your city to be a {game.TECH_LEVELS[perk['tier']]['name']} first."
    if points(state) < 1:
        return "You have no points to spend. Each new tech level gives one."
    state["perks"].append(perk_id)
    game.log(state, now, f"{ideo['perk_word']} gained: {perk['name']}.")
    return None


def describe(eff):
    """An effects dict in words: ["Food buildings 10% faster", ...]."""
    pct = lambda x: f"{round(x * 100):g}%"
    out = []
    for cat, x in eff.get("speed", {}).items():
        out.append(("All buildings" if cat == "all" else f"{game.CATEGORIES[cat]} buildings") + f" {pct(x)} faster")
    words = {
        "explore_speed": lambda x: f"Expeditions travel {pct(x)} faster",
        "explore_cost": lambda x: f"Expeditions need {pct(x)} fewer supplies",
        "wildlife_speed": lambda x: f"Wild animals appear {pct(x)} more often",
        "attracts": lambda x: f"{x:g} more {'arrival' if x == 1 else 'arrivals'} per meal",
        "housing": lambda x: f"Houses {x:g} more people",
        "power": lambda x: f"Generators give {pct(x)} more power",
        "beast_xp": lambda x: f"Beast missions give {pct(x)} more experience",
        "beast_power": lambda x: f"Your beast's bonus is {pct(x)} stronger",
        "hatch_speed": lambda x: f"Eggs hatch {pct(x)} faster",
        "egg_chance": lambda x: f"Expeditions {round(x * 100):g} points likelier to find an egg",
        "mission_speed": lambda x: f"Beast missions come {pct(x)} more often",
    }
    for key, x in eff.items():
        if key in words and x:
            out.append(words[key](x))
    return out


def defs():
    """The ideologies as the page shows them, with their effects in words."""
    return {iid: {"name": i["name"], "desc": i["desc"], "perk_word": i["perk_word"], "perk_plural": i["perk_plural"],
                  "text": describe(i["effects"]), "color": COLOURS[iid], "art": "\n".join(ART[iid]),
                  "perks": {pid: {"name": p["name"], "tier": p["tier"], "desc": p["desc"], "text": describe(p["effects"]),
                                  "art": "\n".join(PERK_ART[pid])}
                            for pid, p in i["perks"].items()}}
            for iid, i in IDEOLOGIES.items()}


def view(state):
    return {"id": state.get("ideology"), "perks": state.get("perks", []), "points": points(state),
            "total": describe(effects(state)) if chosen(state) else []}
