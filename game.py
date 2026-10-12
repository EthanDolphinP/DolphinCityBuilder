"""Game rules for the text city builder.

The game runs in real time. Every working building has a cycle time; when a
cycle finishes it pays out its "produces". Terrain and neighbouring tiles
change how long a cycle takes (see MODIFIERS).

A city owns one or more areas (square maps). It starts with its home area and
discovers more by sending expeditions. Population, resources and research are
shared by the whole city.

Everything about the game's content lives in the data tables at the top. To
add content you normally only need to add an entry to one of those tables:

  * new terrain     -> add to TERRAINS
  * new resource    -> add to RESOURCES (and START_RESOURCES if you start with some)
  * new tech tier   -> append to TECH_LEVELS
  * new building    -> add to BUILDINGS
  * new research    -> add to RESEARCH (point a building's or addition's
    "research" field at it to make it an unlock, or give it a "boost")
  * new addition    -> add to ADDITIONS
  * new environment -> add to ENVIRONMENTS (kinds of area found by exploring)
  * new animal      -> add to WILDLIFE
  * new terrain/building interaction -> add a function to MODIFIERS and list
    its name in a building's "modifiers"

The browser UI reads these tables from the server, so new entries show up
without touching index.html. Player-to-player trading lives in market.py.
"""

import math
import random

MIN = 60  # seconds

# --------------------------------------------------------------------------
# Data tables
# --------------------------------------------------------------------------

# Terrain fields:
#   glyph / color  how the tile is drawn
#   height / fertility / fish   (min, max) ranges rolled per tile
#   temp      added to the area's climate
#   weight    how common it is as ordinary land (terrains without one are
#             placed as water features or as rare variants)
#   groups    kinds it also counts as: a building for "forest" fits a dense
#             forest, "water" covers rivers, lakes and oceans, "fresh" is
#             anything that can water crops
#   from / chance   rare terrain: replaces `from` tiles. The chance grows the
#             further the area is from home (see RARE_* below)
#   boost     {building id: speed multiplier} for buildings standing on it
#   spread_from / near / need / chance   terrain that forms beside its own
#             kind: a `spread_from` tile with at least `need` neighbours that
#             are (or count as) one of `near` becomes this, with that chance
#   research  nothing can be built on it until this has been researched
TERRAINS = {
    # ---- ordinary land ----
    "plains": {"name": "Plains", "glyph": ".", "color": "#9bc46b", "weight": 38,
               "height": (1, 3), "fertility": (30, 90), "temp": 0},
    "forest": {"name": "Forest", "glyph": "T", "color": "#3f9a5a", "weight": 24,
               "height": (1, 4), "fertility": (50, 80), "temp": -2},
    "hill":   {"name": "Hill", "glyph": "^", "color": "#b79a7a", "weight": 18,
               "height": (4, 8), "fertility": (10, 30), "temp": 0},
    "desert": {"name": "Desert", "glyph": ":", "color": "#e0c070", "weight": 13,
               "height": (1, 3), "fertility": (0, 15), "temp": 10},
    # ---- water features (placed by _carve_water) ----
    "river":  {"name": "River", "glyph": "~", "color": "#5aa7d8", "groups": ["water", "fresh"],
               "height": (0, 0), "fertility": (0, 0), "fish": (30, 70), "temp": -2,
               "desc": "Runs across the land in a line. Fresh water."},
    "lake":   {"name": "Lake", "glyph": "O", "color": "#4f8fe0", "groups": ["water", "fresh"],
               "height": (0, 0), "fertility": (0, 0), "fish": (40, 90), "temp": -2,
               "desc": "A body of fresh water, usually rich in fish."},
    "ocean":  {"name": "Ocean", "glyph": "\u2248", "color": "#3a6fc4", "groups": ["water"],
               "height": (0, 0), "fertility": (0, 0), "fish": (60, 100), "temp": -3,
               "desc": "Open salt water teeming with fish. It cannot water crops."},
    # ---- rare land, more common far from home ----
    "dense_forest": {"name": "Dense Forest", "glyph": "#", "color": "#2b7a45",
                     "from": "forest", "chance": 0.35, "groups": ["forest"],
                     "height": (1, 4), "fertility": (60, 90), "temp": -3,
                     "boost": {"lumber_camp": 1.4, "sawmill": 1.4, "shaman_hut": 1.3},
                     "desc": "Ancient, tangled woodland. Timber buildings and shamans work much faster here."},
    "mountain": {"name": "Mountain", "glyph": "\u25b2", "color": "#d9d4cc",
                 "from": "hill", "chance": 0.3, "groups": ["hill"],
                 "height": (9, 12), "fertility": (0, 10), "temp": -2,
                 "desc": "Far higher than any hill, so quarries and mines here are much faster. Bitterly cold."},
    "oasis":  {"name": "Oasis", "glyph": "@", "color": "#4fd0b0",
               "from": "desert", "chance": 0.25, "groups": ["desert", "fresh"],
               "height": (1, 2), "fertility": (70, 95), "temp": 4,
               "desc": "A fertile spring in the desert. Can be farmed, and waters the land around it."},
    "marsh":  {"name": "Marsh", "glyph": ",", "color": "#8fae5a",
               "from": "plains", "chance": 0.12, "groups": ["fresh"],
               "height": (1, 1), "fertility": (80, 100), "temp": 0,
               "desc": "Waterlogged and extremely fertile. Only farms can be built here; it waters the land around it."},
    "volcanic": {"name": "Volcanic Plain", "glyph": "%", "color": "#e07a4a",
                 "from": "plains", "chance": 0.06, "groups": ["plains"],
                 "height": (1, 2), "fertility": (90, 100), "temp": 6,
                 "boost": {"farm": 1.25},
                 "desc": "Warm black soil, the richest farmland there is."},
    # ---- land that forms beside its own kind (see _spread_terrain) ----
    "sand_dunes": {"name": "Sand Dunes", "glyph": ")", "color": "#f0d890",
                   "spread_from": ["desert"], "near": ["desert"], "need": 2, "chance": 0.45,
                   "groups": ["desert"], "research": "desert_lore",
                   "height": (2, 4), "fertility": (0, 5), "temp": 12,
                   "boost": {"glassworks": 1.3, "caravanserai": 1.2, "wind_turbine": 1.2},
                   "desc": "Shifting sand in the heart of a desert. Fine sand makes glassworks faster, and caravans prefer it."},
    "salt_flat": {"name": "Salt Flat", "glyph": "_", "color": "#e8e8e0",
                  "spread_from": ["desert"], "near": ["sand_dunes", "ocean"], "need": 1, "chance": 0.3,
                  "height": (1, 1), "fertility": (0, 0), "temp": 12,
                  "desc": "A dried-up lake bed crusted with salt. Only a Salt Works can use it."},
    "swamp": {"name": "Swamp", "glyph": ";", "color": "#6f8f4a",
              "spread_from": ["plains", "forest"], "near": ["marsh", "lake"], "need": 1, "chance": 0.3,
              "groups": ["fresh"],
              "height": (1, 1), "fertility": (60, 90), "temp": 1,
              "desc": "Dark, drowned woodland beside marshes and lakes. It waters the land around it; rice paddies and peat cutters can work it."},
    "foothills": {"name": "Foothills", "glyph": "/", "color": "#c9b48a",
                  "spread_from": ["plains", "forest"], "near": ["hill"], "need": 2, "chance": 0.3,
                  "groups": ["hill"],
                  "height": (3, 4), "fertility": (30, 60), "temp": -1,
                  "desc": "Rolling ground at the feet of the hills: too low for a mine, but good for terrace farms."},
    "glacier": {"name": "Glacier", "glyph": "*", "color": "#bfe6f2",
                "spread_from": ["hill", "mountain"], "near": ["mountain"], "need": 1, "chance": 0.35,
                "groups": ["hill", "fresh"], "research": "mountaineering",
                "height": (10, 13), "fertility": (0, 0), "temp": -8,
                "desc": "A river of ice among the mountains. Its meltwater waters the land around it, and it is the highest ground there is."},
    "hot_springs": {"name": "Hot Springs", "glyph": "\u00a7", "color": "#f09a6a",
                    "spread_from": ["hill"], "near": ["mountain", "volcanic"], "need": 1, "chance": 0.3,
                    "height": (4, 7), "fertility": (20, 40), "temp": 12,
                    "desc": "Steaming pools heated from below. A Bath House draws visitors here, and later a Geothermal Plant draws power."},
    "ancient_grove": {"name": "Ancient Grove", "glyph": "\u2663", "color": "#57c27a",
                      "spread_from": ["forest", "dense_forest"], "near": ["dense_forest"], "need": 1, "chance": 0.3,
                      "groups": ["forest"],
                      "height": (1, 3), "fertility": (70, 95), "temp": -3,
                      "boost": {"shaman_hut": 1.6, "hunting_lodge": 1.3, "lumber_camp": 0.8, "sawmill": 0.8},
                      "desc": "The oldest trees, deep in the dense forest. Shamans and hunters thrive here; the huge trunks are slow to fell."},
    "meadow": {"name": "Meadow", "glyph": "\"", "color": "#c6e07a",
               "spread_from": ["plains"], "near": ["plains"], "need": 3, "chance": 0.3,
               "groups": ["plains"],
               "height": (1, 2), "fertility": (60, 90), "temp": 0,
               "boost": {"pasture": 1.4, "dairy": 1.3},
               "desc": "Open flowering grassland. The best grazing there is: pastures and dairies work faster here."},
}
GROUP_NAMES = {"water": "water", "fresh": "fresh water"}

# Chance multiplier for rare terrain: RARE_BASE at home, plus RARE_PER_DISTANCE
# for every area between it and home. The final chance never exceeds RARE_MAX.
RARE_BASE = 0.3
RARE_PER_DISTANCE = 0.35
RARE_MAX = 0.6


RESOURCES = {
    "food":  "Food",
    "wood":  "Wood",
    "stone": "Stone",
    "ore":   "Ore",
    "tools": "Tools",
    "gold":  "Gold",
    "livestock": "Livestock",
    "knowledge": "Knowledge",
}
UNTRADEABLE = {"knowledge"}   # cannot be offered or asked for on the market

START_RESOURCES = {"food": 30, "wood": 40}
START_POPULATION = 3
BASE_HOUSING = 3            # people who can live in the starting camp
AREA_SIZE = 5
MAP_GROWTH_PER_TECH = 2     # the home area gains a ring of new land on each advance
DEGREES_PER_HEIGHT = 2      # temperature drop per height level
DEMOLISH_REFUND = 0.5
MAX_ADDITIONS = 2           # additions one building can carry

MEAL_TIME = 15 * MIN        # everyone eats 1 food this often; a fed city also gains 1 person
HUNGRY_SPEED = 0.5          # work speed of non-food buildings while the city is hungry
SIM_STEP = 60               # seconds of game time simulated per step when catching up

EXPEDITION_TIME = 20 * MIN  # travel time per step of distance from home
MAX_EXPLORE_SPEED = 1.0     # most that buildings can add to expedition speed (1.0 = twice as fast)
LIVESTOCK_FOR_FULL_SPEED = 10   # herd size at which "livestock_speed" buildings run at normal speed
WILDLIFE_TIME = 45 * MIN    # how often a new animal wanders into each area
MAX_WILDLIFE = 4            # wild animals an area holds at once
TAME_FOOD_PER_HEAD = 3      # food used as bait, per livestock the animal is worth
AWAY_TIME = 5 * MIN         # unwatched for this long -> the player gets a "while you were away" report

# Index 0 is the starting level. The other entries say what it takes to advance
# *into* that level:
#   population  people the city must have
#   cost        resources paid
#   research    how many things the city must have researched (of any level)
#   areas       how many areas the city must own, counting home
TECH_LEVELS = [
    {"name": "Tribe"},
    {"name": "Village", "population": 12, "research": 3,
     "cost": {"food": 100, "wood": 150, "stone": 80, "knowledge": 20}},
    {"name": "Town", "population": 30, "research": 8, "areas": 2,
     "cost": {"wood": 400, "stone": 350, "ore": 120, "gold": 150, "knowledge": 100}},
    {"name": "City", "population": 60, "research": 15, "areas": 3,
     "cost": {"stone": 800, "ore": 300, "tools": 120, "gold": 500, "knowledge": 300}},
]

# Groups the build menu is divided into, in the order they are shown. Every
# building names one of these as its "category".
CATEGORIES = {
    "housing": "Housing",
    "food": "Food",
    "materials": "Materials",
    "trade": "Trade",
    "knowledge": "Knowledge",
    "power": "Power",
    "support": "Support",
}

# Building fields (all optional except name/glyph/tech/terrain/cost):
#   tech           minimum tech level index
#   category       which group of the build menu it is listed in (see CATEGORIES)
#   terrain        list of terrains it can stand on
#   cost           resources paid to build
#   workers        people needed to work at full speed
#   time           seconds one cycle takes at full speed, before modifiers
#   produces       resources gained each time a cycle finishes
#   consumes       resources used each time a cycle finishes
#   housing        people it can house
#   attracts       extra people who may arrive at each meal (see _arrivals)
#   explore_speed  0.25 = expeditions travel 25% faster (city-wide, capped)
#   wildlife_speed 0.5 = wild animals appear 50% more often (city-wide)
#   livestock_speed  True - works faster the more livestock the city owns
#   modifiers      names from MODIFIERS that speed up / slow down its cycle here
#   min_height / max_height / min_fertility / min_temp / max_temp   tile limits
#   adjacent       terrain that must be next to the tile
#   fertility_aura fertility added to the 8 surrounding tiles
#   speed_aura     {"for": [building ids], "bonus": 0.2} speeds up those neighbours
#   research       id from RESEARCH that must be researched before it can be built
#   herd           livestock it can hold; with per_head, each animal held adds
#                  that much to every cycle's output (rounded down)
#   generates      power it supplies while staffed (and fuelled, if it consumes)
#   generates_modifiers   names from MODIFIERS that scale what it generates here
#   power          power it needs. When the city generates less than its
#                  buildings need, every powered building slows down in proportion
BUILDINGS = {
    # ---- Tribe ----
    "hut": {
        "name": "Hut", "glyph": "h", "tech": 0, "category": "housing",
        "terrain": ["plains", "forest", "desert", "hill"],
        "cost": {"wood": 10}, "housing": 3,
        "desc": "Simple shelter.",
    },
    "farm": {
        "name": "Farm", "glyph": "F", "tech": 0, "category": "food",
        "terrain": ["plains", "oasis", "marsh"], "max_height": 2, "min_fertility": 40,
        "cost": {"wood": 8}, "workers": 2, "time": 12 * MIN, "produces": {"food": 6},
        "modifiers": ["fertility", "crop_temperature", "adjacent_water"],
        "desc": "Needs flat, fertile ground. Faster on fertile soil, near fresh water and in mild temperatures.",
    },
    "fishing_dock": {
        "name": "Fishing Dock", "glyph": "D", "tech": 0, "category": "food",
        "terrain": ["water"], "min_temp": 1,
        "cost": {"wood": 12}, "workers": 1, "time": 10 * MIN, "produces": {"food": 3},
        "modifiers": ["fish", "open_water"],
        "desc": "Fishes the water tile it stands on: the more fish there, the faster. Bigger bodies of water help too. Cannot be built on frozen water.",
    },
    "lumber_camp": {
        "name": "Lumber Camp", "glyph": "L", "tech": 0, "category": "materials",
        "terrain": ["forest"],
        "cost": {"wood": 5}, "workers": 2, "time": 10 * MIN, "produces": {"wood": 4},
        "modifiers": ["deep_forest"],
        "desc": "Cuts timber. Faster with more forest around it.",
    },
    "quarry": {
        "name": "Quarry", "glyph": "Q", "tech": 0, "category": "materials",
        "terrain": ["hill"],
        "cost": {"wood": 15}, "workers": 2, "time": 15 * MIN, "produces": {"stone": 4},
        "modifiers": ["height"],
        "desc": "Cuts stone from a hill. Faster on higher hills.",
    },
    "shaman_hut": {
        "name": "Shaman Hut", "glyph": "s", "tech": 0, "category": "knowledge",
        "terrain": ["plains", "forest", "desert", "hill"],
        "cost": {"wood": 15, "food": 10}, "workers": 1, "time": 15 * MIN, "produces": {"knowledge": 2},
        "modifiers": ["deep_forest"],
        "desc": "The shaman gathers knowledge, which pays for research. Faster with forest around it.",
    },
    "pasture": {
        "name": "Pasture", "glyph": "P", "tech": 0, "category": "food", "research": "animal_husbandry",
        "terrain": ["plains"],
        "cost": {"wood": 20}, "workers": 1, "time": 15 * MIN,
        "herd": 10, "per_head": {"food": 0.6},
        "modifiers": ["fertility"],
        "desc": "Keeps up to 10 of your livestock and farms them for food. Faster on fertile grass.",
    },
    "salt_lick": {
        "name": "Salt Lick", "glyph": "l", "tech": 0, "category": "support",
        "terrain": ["plains", "forest"],
        "cost": {"wood": 5, "food": 20}, "wildlife_speed": 0.5,
        "desc": "Draws animals in from the wild: wildlife appears 50% more often in all your areas.",
    },
    "hunting_lodge": {
        "name": "Hunting Lodge", "glyph": "N", "tech": 0, "category": "food",
        "terrain": ["forest"],
        "cost": {"wood": 12}, "workers": 1, "time": 15 * MIN, "produces": {"food": 3},
        "modifiers": ["deep_forest"],
        "desc": "Hunters bring in game from the woods. Faster with more forest around it.",
    },
    "reed_cutter": {
        "name": "Reed Cutter", "glyph": "R", "tech": 0, "category": "materials",
        "terrain": ["river", "lake"],
        "cost": {"wood": 8}, "workers": 1, "time": 12 * MIN, "produces": {"wood": 2},
        "modifiers": ["open_water"],
        "desc": "Cuts reeds and driftwood from fresh water: a source of wood without a forest.",
    },
    # ---- Village ----
    "house": {
        "name": "House", "glyph": "H", "tech": 1, "category": "housing",
        "terrain": ["plains", "forest", "desert", "hill"],
        "cost": {"wood": 20, "stone": 15}, "housing": 6,
        "desc": "Sturdy family home.",
    },
    "mine": {
        "name": "Mine", "glyph": "M", "tech": 1, "category": "materials",
        "terrain": ["hill"], "min_height": 5,
        "cost": {"wood": 30, "stone": 20}, "workers": 3, "time": 20 * MIN, "produces": {"ore": 4},
        "modifiers": ["height"],
        "desc": "Digs ore. Needs a tall hill; faster on higher hills.",
    },
    "well": {
        "name": "Well", "glyph": "W", "tech": 1, "category": "support",
        "terrain": ["plains", "desert"],
        "cost": {"stone": 20}, "fertility_aura": 25,
        "desc": "Adds +25 fertility to the 8 surrounding tiles.",
    },
    "trading_post": {
        "name": "Trading Post", "glyph": "$", "tech": 1, "category": "trade",
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"wood": 30, "stone": 20}, "workers": 2, "time": 20 * MIN, "produces": {"gold": 5},
        "modifiers": ["customers"],
        "desc": "Earns gold. Needs flat ground. Faster with homes next to it.",
    },
    "school": {
        "name": "School", "glyph": "K", "tech": 1, "category": "knowledge",
        "terrain": ["plains", "desert"],
        "cost": {"wood": 40, "stone": 30}, "workers": 2, "time": 15 * MIN, "produces": {"knowledge": 5},
        "modifiers": ["customers"],
        "desc": "Teaches and studies. Needed for Village research. Faster with homes next to it.",
    },
    "windmill": {
        "name": "Windmill", "glyph": "*", "tech": 1, "category": "support", "research": "windmills",
        "terrain": ["plains", "hill"],
        "cost": {"wood": 40, "stone": 20},
        "speed_aura": {"for": ["farm", "irrigated_farm"], "bonus": 0.2},
        "desc": "Mills grain for the farms on the 8 surrounding tiles, making them 20% faster.",
    },
    "stable": {
        "name": "Stable", "glyph": "q", "tech": 1, "category": "support", "research": "draft_animals",
        "terrain": ["plains", "desert"],
        "cost": {"wood": 40, "livestock": 3}, "explore_speed": 0.25,
        "speed_aura": {"for": ["farm", "orchard", "terrace_farm", "rice_paddy", "lumber_camp", "quarry"], "bonus": 0.1},
        "desc": "Pack and plough animals. Expeditions travel 25% faster, and farms, lumber camps and quarries on the 8 surrounding tiles work 10% faster. Costs 3 livestock to set up.",
    },
    "dairy": {
        "name": "Dairy", "glyph": "m", "tech": 1, "category": "food", "research": "dairying",
        "terrain": ["plains"],
        "cost": {"wood": 30, "stone": 10}, "workers": 2, "time": 15 * MIN, "produces": {"food": 7},
        "livestock_speed": True,
        "desc": "Milk, butter and cheese from your herd without slaughtering it. Works faster the more livestock the city owns: normal speed at 10.",
    },
    "weaver": {
        "name": "Weaver", "glyph": "x", "tech": 1, "category": "trade", "research": "weaving",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"wood": 35}, "workers": 2, "time": 20 * MIN, "produces": {"gold": 6},
        "livestock_speed": True,
        "desc": "Spins wool from your herd into cloth to sell. Works faster the more livestock the city owns: normal speed at 10.",
    },
    "rice_paddy": {
        "name": "Rice Paddy", "glyph": "p", "tech": 1, "category": "food", "research": "wet_farming",
        "terrain": ["marsh", "swamp"],
        "cost": {"wood": 25}, "workers": 2, "time": 12 * MIN, "produces": {"food": 9},
        "modifiers": ["crop_temperature"],
        "desc": "Flooded fields on marsh or swamp. A big harvest from land little else can use.",
    },
    "peat_cutter": {
        "name": "Peat Cutter", "glyph": "j", "tech": 1, "category": "materials", "research": "drainage",
        "terrain": ["swamp"],
        "cost": {"wood": 20}, "workers": 2, "time": 12 * MIN, "produces": {"wood": 6},
        "desc": "Cuts and dries peat from a swamp. It burns like wood and is counted as wood.",
    },
    "terrace_farm": {
        "name": "Terrace Farm", "glyph": "z", "tech": 1, "category": "food", "research": "terracing",
        "terrain": ["hill"], "max_height": 7,
        "cost": {"wood": 20, "stone": 20}, "workers": 2, "time": 12 * MIN, "produces": {"food": 6},
        "modifiers": ["crop_temperature", "adjacent_water"],
        "desc": "Stepped fields cut into a slope: food from hills and foothills, though not from mountains. Faster near fresh water and in mild temperatures.",
    },
    "salt_works": {
        "name": "Salt Works", "glyph": "+", "tech": 1, "category": "trade", "research": "salt_harvesting",
        "terrain": ["salt_flat"],
        "cost": {"wood": 30}, "workers": 2, "time": 15 * MIN, "produces": {"gold": 7},
        "desc": "Rakes salt from a salt flat to sell.",
    },
    "bath_house": {
        "name": "Bath House", "glyph": "6", "tech": 1, "category": "trade", "research": "masonry",
        "terrain": ["hot_springs"],
        "cost": {"wood": 20, "stone": 50}, "workers": 2, "time": 20 * MIN, "produces": {"gold": 8},
        "housing": 2, "attracts": 1,
        "desc": "Stone pools over hot springs. Earns gold, has rooms for 2, and its fame brings one extra arrival per meal like a tavern.",
    },
    "tavern": {
        "name": "Tavern", "glyph": "v", "tech": 1, "category": "housing",
        "terrain": ["plains", "forest", "desert", "hill"],
        "cost": {"wood": 40, "stone": 20}, "housing": 1, "attracts": 1,
        "desc": "Word gets around: one extra person may arrive at every meal. Each arrival still needs a free place to live and a spare meal in store. Has a bed for 1.",
    },
    "stilt_house": {
        "name": "Stilt House", "glyph": "t", "tech": 1, "category": "housing",
        "terrain": ["river", "lake"],
        "cost": {"wood": 35}, "housing": 4,
        "desc": "A home on stilts over fresh water, leaving the land free.",
    },
    "orchard": {
        "name": "Orchard", "glyph": "Y", "tech": 1, "category": "food", "research": "grafting",
        "terrain": ["plains", "oasis"], "min_fertility": 30,
        "cost": {"wood": 30}, "workers": 2, "time": 15 * MIN, "produces": {"food": 5, "wood": 2},
        "modifiers": ["fertility", "crop_temperature"],
        "desc": "Fruit trees: food, plus wood from pruning. Tolerates slopes a farm can't use.",
    },
    "tannery": {
        "name": "Tannery", "glyph": "n", "tech": 1, "category": "trade", "research": "tanning",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"wood": 30, "stone": 10}, "workers": 2, "time": 20 * MIN,
        "consumes": {"livestock": 1}, "produces": {"gold": 6, "food": 4},
        "modifiers": ["adjacent_water"],
        "desc": "Turns livestock into hides to sell and meat to eat. Faster next to fresh water.",
    },
    "caravanserai": {
        "name": "Caravanserai", "glyph": "C", "tech": 1, "category": "trade",
        "terrain": ["desert"], "adjacent": "fresh",
        "cost": {"wood": 30, "stone": 30}, "workers": 2, "time": 20 * MIN, "produces": {"gold": 7},
        "desc": "A desert inn for passing caravans. Must be on desert next to fresh water.",
    },
    "lighthouse": {
        "name": "Lighthouse", "glyph": "i", "tech": 1, "category": "support", "research": "navigation",
        "terrain": ["plains", "hill", "desert"], "adjacent": "water",
        "cost": {"wood": 20, "stone": 40},
        "speed_aura": {"for": ["fishing_dock", "fishery", "harbor", "reed_cutter"], "bonus": 0.2},
        "desc": "Built on land beside water. Docks, fisheries, harbors and reed cutters on the 8 surrounding tiles work 20% faster.",
    },
    # ---- Town ----
    "university": {
        "name": "University", "glyph": "U", "tech": 2, "category": "knowledge", "power": 2,
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 80, "ore": 20, "gold": 30}, "workers": 4, "time": 20 * MIN,
        "produces": {"knowledge": 14},
        "desc": "Serious scholarship. Needed for Town and City research. Needs flat ground.",
    },
    "sawmill": {
        "name": "Sawmill", "glyph": "S", "tech": 2, "category": "materials", "power": 2,
        "terrain": ["forest"],
        "cost": {"wood": 30, "stone": 30, "ore": 10}, "workers": 3, "time": 12 * MIN, "produces": {"wood": 10},
        "modifiers": ["deep_forest"],
        "desc": "Industrial timber. Faster with more forest around it.",
    },
    "irrigated_farm": {
        "name": "Irrigated Farm", "glyph": "I", "tech": 2, "category": "food",
        "terrain": ["plains", "desert"], "max_height": 3, "adjacent": "fresh",
        "cost": {"wood": 30, "stone": 20, "ore": 10}, "workers": 3, "time": 12 * MIN, "produces": {"food": 12},
        "modifiers": ["crop_temperature"],
        "desc": "Ignores fertility but must be next to fresh water. Works on desert.",
    },
    "smithy": {
        "name": "Smithy", "glyph": "X", "tech": 2, "category": "materials", "power": 2,
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 40, "ore": 20}, "workers": 2, "time": 25 * MIN,
        "consumes": {"ore": 4}, "produces": {"tools": 2},
        "modifiers": ["near_mine"],
        "desc": "Turns ore into tools. Faster next to a mine.",
    },
    "water_mill": {
        "name": "Water Mill", "glyph": "w", "tech": 2, "category": "power",
        "terrain": ["river"],
        "cost": {"wood": 50, "stone": 30}, "workers": 1, "generates": 4,
        "desc": "A wheel in the river. Steady power with no fuel.",
    },
    "steam_engine": {
        "name": "Steam Engine", "glyph": "E", "tech": 2, "category": "power",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 40, "ore": 25}, "workers": 2, "generates": 6,
        "time": 15 * MIN, "consumes": {"wood": 4},
        "desc": "Burns wood for power. Stops when the wood runs out.",
    },
    "fishery": {
        "name": "Fishery", "glyph": "f", "tech": 2, "category": "food", "power": 2,
        "terrain": ["lake", "ocean"], "min_temp": 1,
        "cost": {"wood": 50, "stone": 20, "ore": 10}, "workers": 3, "time": 12 * MIN, "produces": {"food": 10},
        "modifiers": ["fish", "open_water"],
        "desc": "Nets, boats and a packing shed on a lake or ocean. Faster with more fish and bigger water.",
    },
    "glassworks": {
        "name": "Glassworks", "glyph": "G", "tech": 2, "category": "trade", "power": 3, "research": "glassmaking",
        "terrain": ["desert"],
        "cost": {"stone": 50, "ore": 15}, "workers": 3, "time": 20 * MIN,
        "consumes": {"wood": 3}, "produces": {"gold": 12},
        "desc": "Melts desert sand into glass to sell. Burns wood.",
    },
    "observatory": {
        "name": "Observatory", "glyph": "Z", "tech": 2, "category": "knowledge", "power": 1, "research": "astronomy",
        "terrain": ["hill"], "min_height": 6,
        "cost": {"stone": 70, "gold": 30}, "workers": 2, "time": 20 * MIN, "produces": {"knowledge": 9},
        "modifiers": ["height"],
        "desc": "Studies the sky from high ground. The higher the better: superb on a mountain.",
    },
    # ---- City ----
    "apartments": {
        "name": "Apartments", "glyph": "A", "tech": 3, "category": "housing",
        "terrain": ["plains", "desert"],
        "cost": {"stone": 60, "tools": 10, "gold": 30}, "housing": 15,
        "desc": "Dense housing.",
    },
    "harbor": {
        "name": "Harbor", "glyph": "B", "tech": 3, "category": "food", "power": 3,
        "terrain": ["ocean", "lake"], "min_temp": 1,
        "cost": {"wood": 60, "stone": 40, "tools": 10}, "workers": 3, "time": 15 * MIN,
        "produces": {"food": 8, "gold": 5},
        "modifiers": ["fish", "open_water"],
        "desc": "Fishing fleet and trade by boat, on a lake or ocean. Faster with more fish and bigger water.",
    },
    "deep_mine": {
        "name": "Deep Mine", "glyph": "V", "tech": 3, "category": "materials", "power": 4,
        "terrain": ["hill"], "min_height": 5,
        "cost": {"stone": 60, "tools": 15}, "workers": 4, "time": 20 * MIN,
        "produces": {"ore": 9, "stone": 4},
        "modifiers": ["height"],
        "desc": "Deep shafts for ore and stone. Faster on higher hills.",
    },
    "geothermal_plant": {
        "name": "Geothermal Plant", "glyph": "0", "tech": 3, "category": "power", "research": "electricity",
        "terrain": ["hot_springs", "volcanic"],
        "cost": {"stone": 120, "tools": 25}, "workers": 2, "generates": 14,
        "desc": "Power from the heat underground, with no fuel. Only on hot springs or a volcanic plain.",
    },
    "wind_turbine": {
        "name": "Wind Turbine", "glyph": "y", "tech": 3, "category": "power", "research": "electricity",
        "terrain": ["plains", "hill", "desert"],
        "cost": {"stone": 40, "tools": 15}, "workers": 1, "generates": 5,
        "generates_modifiers": ["height"],
        "desc": "Power from the wind, with no fuel. Gives more the higher it stands.",
    },
    "hydro_dam": {
        "name": "Hydro Dam", "glyph": "=", "tech": 3, "category": "power", "research": "electricity",
        "terrain": ["river"], "adjacent": "hill",
        "cost": {"stone": 150, "tools": 25}, "workers": 3, "generates": 16,
        "desc": "Dams a river against a hill for a great deal of power with no fuel.",
    },
    "power_plant": {
        "name": "Power Plant", "glyph": "!", "tech": 3, "category": "power", "research": "electricity",
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 100, "ore": 40, "tools": 20}, "workers": 4, "generates": 22,
        "time": 15 * MIN, "consumes": {"wood": 10},
        "desc": "Burns a lot of wood for a lot of power. Needs flat ground.",
    },
    "factory": {
        "name": "Factory", "glyph": "&", "tech": 3, "category": "materials", "power": 6, "research": "mass_production",
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 120, "tools": 30, "gold": 60}, "workers": 5, "time": 20 * MIN,
        "consumes": {"ore": 8, "wood": 4}, "produces": {"tools": 7},
        "desc": "Makes tools in bulk from ore and wood. Needs flat ground.",
    },
    "greenhouse": {
        "name": "Greenhouse", "glyph": "u", "tech": 3, "category": "food", "power": 3, "research": "botany",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 60, "tools": 15, "gold": 30}, "workers": 3, "time": 12 * MIN, "produces": {"food": 14},
        "desc": "Heated glass houses that grow food anywhere, whatever the soil or weather.",
    },
    "laboratory": {
        "name": "Laboratory", "glyph": "J", "tech": 3, "category": "knowledge", "power": 5, "research": "scientific_method",
        "terrain": ["plains", "desert"],
        "cost": {"stone": 100, "tools": 25, "gold": 80}, "workers": 4, "time": 20 * MIN,
        "produces": {"knowledge": 30},
        "desc": "Experiments on an industrial scale.",
    },
}

# Research is bought with Knowledge. Fields:
#   tech      minimum tech level index
#   building  a building the city must have standing to research it
#   cost      resources paid (normally knowledge)
#   boost     {building id: speed multiplier} - a technique that speeds those up
#   effect    text shown to the player for anything the fields below do
#   taming            True - wild animals can be tamed
#   breeding          True - pastured herds grow
#   explore_range     how far from home expeditions can go
#   surveying         True - the Find box can search tiles (terrain, building sites)
#   explore_discount  multiplier on expedition costs
# Buildings and additions unlocked by a research name it in their "research" field.
RESEARCH = {
    # ---- Tribe ----
    "surveying": {
        "name": "Surveying", "tech": 0, "building": "shaman_hut", "cost": {"knowledge": 6},
        "surveying": True,
        "effect": "the Find box under the map can search every area for a kind of terrain, and for the best places to put a building",
        "desc": "Walking the land and remembering it.",
    },
    "stone_tools": {
        "name": "Stone Tools", "tech": 0, "building": "shaman_hut", "cost": {"knowledge": 10},
        "boost": {"lumber_camp": 1.15, "quarry": 1.15},
        "desc": "Better axes and picks.",
    },
    "animal_taming": {
        "name": "Animal Taming", "tech": 0, "building": "shaman_hut", "cost": {"knowledge": 8},
        "taming": True, "effect": "wild animals can be tamed into livestock",
        "desc": "Patience, bait and a soft voice.",
    },
    "fish_traps": {
        "name": "Fish Traps", "tech": 0, "building": "shaman_hut", "cost": {"knowledge": 12},
        "desc": "Woven traps that fish while nobody is watching.",
    },
    "seed_selection": {
        "name": "Seed Selection", "tech": 0, "building": "shaman_hut", "cost": {"knowledge": 15},
        "desc": "Keeping the best seed and guarding the crop.",
    },
    "animal_husbandry": {
        "name": "Animal Husbandry", "tech": 0, "building": "shaman_hut", "cost": {"knowledge": 15},
        "desc": "Fences, herding and milking.",
    },
    "pathfinding": {
        "name": "Pathfinding", "tech": 0, "building": "shaman_hut", "cost": {"knowledge": 20},
        "explore_range": 2, "effect": "expeditions can explore up to 2 areas away from home",
        "desc": "Reading stars, rivers and animal trails.",
    },
    "desert_lore": {
        "name": "Desert Lore", "tech": 0, "building": "shaman_hut", "cost": {"knowledge": 14},
        "effect": "sand dunes can be built on",
        "desc": "Where the sand holds, where the water hides.",
    },
    "dairying": {
        "name": "Dairying", "tech": 0, "building": "shaman_hut", "cost": {"knowledge": 15},
        "desc": "Milking, churning and keeping.",
    },
    "smoking": {
        "name": "Smoking and Curing", "tech": 0, "building": "shaman_hut", "cost": {"knowledge": 12},
        "desc": "Fish and meat that keep.",
    },
    # ---- Village ----
    "crop_rotation": {
        "name": "Crop Rotation", "tech": 1, "building": "school", "cost": {"knowledge": 25},
        "boost": {"farm": 1.2},
        "desc": "Resting fields in turn keeps the soil rich.",
    },
    "windmills": {
        "name": "Windmills", "tech": 1, "building": "school", "cost": {"knowledge": 30},
        "desc": "Harnessing the wind to mill grain.",
    },
    "masonry": {
        "name": "Masonry", "tech": 1, "building": "school", "cost": {"knowledge": 30},
        "desc": "Building in cut stone.",
    },
    "selective_breeding": {
        "name": "Selective Breeding", "tech": 1, "building": "school", "cost": {"knowledge": 30},
        "breeding": True, "boost": {"pasture": 1.15},
        "effect": "a pasture holding 2 or more animals adds 1 livestock per cycle while there is pasture room",
        "desc": "Choosing which animals raise the next generation.",
    },
    "pit_props": {
        "name": "Pit Props", "tech": 1, "building": "school", "cost": {"knowledge": 35},
        "desc": "Timber supports for deeper, safer digging.",
    },
    "cartography": {
        "name": "Cartography", "tech": 1, "building": "school", "cost": {"knowledge": 40},
        "explore_range": 99, "explore_discount": 0.75,
        "effect": "expeditions can go any distance and cost 25% less",
        "desc": "Maps that outlive the people who drew them.",
    },
    "draft_animals": {
        "name": "Draft Animals", "tech": 1, "building": "school", "cost": {"knowledge": 25},
        "desc": "Yokes, harness and pack saddles.",
    },
    "weaving": {
        "name": "Weaving", "tech": 1, "building": "school", "cost": {"knowledge": 25},
        "desc": "Wool into thread, thread into cloth.",
    },
    "terracing": {
        "name": "Terracing", "tech": 1, "building": "school", "cost": {"knowledge": 25},
        "desc": "Walls that turn a slope into fields.",
    },
    "wet_farming": {
        "name": "Wet Farming", "tech": 1, "building": "school", "cost": {"knowledge": 25},
        "desc": "Crops that like their feet in water.",
    },
    "drainage": {
        "name": "Drainage", "tech": 1, "building": "school", "cost": {"knowledge": 25},
        "desc": "Ditches and dykes to work sodden ground.",
    },
    "salt_harvesting": {
        "name": "Salt Harvesting", "tech": 1, "building": "school", "cost": {"knowledge": 20},
        "desc": "White gold, raked from the ground.",
    },
    "mountaineering": {
        "name": "Mountaineering", "tech": 1, "building": "school", "cost": {"knowledge": 30},
        "effect": "glaciers can be built on",
        "desc": "Ropes, spikes and a head for heights.",
    },
    "grafting": {
        "name": "Grafting", "tech": 1, "building": "school", "cost": {"knowledge": 25},
        "desc": "Fruit trees that breed true.",
    },
    "tanning": {
        "name": "Tanning", "tech": 1, "building": "school", "cost": {"knowledge": 25},
        "desc": "Hides into leather.",
    },
    "navigation": {
        "name": "Navigation", "tech": 1, "building": "school", "cost": {"knowledge": 30},
        "desc": "Beacons and safe channels.",
    },
    # ---- Town ----
    "bookkeeping": {
        "name": "Bookkeeping", "tech": 2, "building": "university", "cost": {"knowledge": 50},
        "desc": "Ledgers, weights and measures.",
    },
    "water_wheels": {
        "name": "Water Wheels", "tech": 2, "building": "university", "cost": {"knowledge": 60},
        "desc": "River power for saws and hammers.",
    },
    "metallurgy": {
        "name": "Metallurgy", "tech": 2, "building": "university", "cost": {"knowledge": 70},
        "boost": {"smithy": 1.3, "mine": 1.15},
        "desc": "Hotter furnaces and better alloys.",
    },
    "glassmaking": {
        "name": "Glassmaking", "tech": 2, "building": "university", "cost": {"knowledge": 50},
        "desc": "Sand, ash and a very hot fire.",
    },
    "mechanics": {
        "name": "Mechanics", "tech": 2, "building": "university", "cost": {"knowledge": 55},
        "desc": "Gears, belts and stored momentum.",
    },
    "astronomy": {
        "name": "Astronomy", "tech": 2, "building": "university", "cost": {"knowledge": 60},
        "desc": "Charting the heavens.",
    },
    # ---- City ----
    "plumbing": {
        "name": "Plumbing", "tech": 3, "building": "university", "cost": {"knowledge": 100},
        "desc": "Piped water and drains.",
    },
    "engineering": {
        "name": "Engineering", "tech": 3, "building": "university", "cost": {"knowledge": 120},
        "boost": {"deep_mine": 1.25, "harbor": 1.25, "sawmill": 1.15},
        "desc": "Cranes, pumps and precise plans.",
    },
    "botany": {
        "name": "Botany", "tech": 3, "building": "university", "cost": {"knowledge": 100},
        "desc": "How plants really grow.",
    },
    "electricity": {
        "name": "Electricity", "tech": 3, "building": "university", "cost": {"knowledge": 110},
        "desc": "Power carried down a wire.",
    },
    "mass_production": {
        "name": "Mass Production", "tech": 3, "building": "university", "cost": {"knowledge": 130},
        "desc": "Identical parts, made by the thousand.",
    },
    "scientific_method": {
        "name": "Scientific Method", "tech": 3, "building": "university", "cost": {"knowledge": 150},
        "desc": "Test everything; trust nothing untested.",
    },
}

# Additions are attached to a building that is already standing. Fields:
#   for       building ids it can be attached to
#   cost      resources paid to attach it
#   tech / research   optional requirements
#   adjacent  terrain that must be next to the building
#   speed     multiplier on the building's work speed
#   produces  extra resources each time the building finishes a cycle
#   housing   extra people the building houses
#   herd      extra livestock the building holds
#   generates extra power the building supplies
#   fertility_aura   extra fertility the building gives its neighbours
#   aura_bonus       added to the building's speed_aura bonus
#   explore_speed / wildlife_speed   added to the building's own
ADDITIONS = {
    "fish_traps": {
        "name": "Fish Traps", "for": ["fishing_dock"], "research": "fish_traps",
        "cost": {"wood": 15}, "produces": {"food": 2},
        "desc": "+2 Food per cycle.",
    },
    "scarecrow": {
        "name": "Scarecrow", "for": ["farm", "irrigated_farm", "orchard", "terrace_farm", "rice_paddy"], "research": "seed_selection",
        "cost": {"wood": 10, "food": 5}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "tool_shed": {
        "name": "Tool Shed", "for": ["lumber_camp", "quarry", "farm", "hunting_lodge", "reed_cutter", "terrace_farm", "peat_cutter"], "research": "stone_tools",
        "cost": {"wood": 20, "stone": 5}, "speed": 1.15,
        "desc": "15% faster.",
    },
    "extra_room": {
        "name": "Extra Room", "for": ["hut", "house", "stilt_house", "tavern"], "research": "masonry",
        "cost": {"wood": 15, "stone": 15}, "housing": 2,
        "desc": "Houses 2 more people.",
    },
    "support_beams": {
        "name": "Support Beams", "for": ["quarry", "mine", "deep_mine"], "research": "pit_props",
        "cost": {"wood": 40}, "speed": 1.25,
        "desc": "25% faster.",
    },
    "market_stalls": {
        "name": "Market Stalls", "for": ["trading_post", "caravanserai", "bath_house", "salt_works"], "research": "bookkeeping",
        "cost": {"wood": 40, "gold": 15}, "produces": {"gold": 2},
        "desc": "+2 Gold per cycle.",
    },
    "water_wheel": {
        "name": "Water Wheel", "for": ["sawmill", "smithy", "glassworks"], "research": "water_wheels",
        "adjacent": "fresh", "cost": {"wood": 50, "ore": 15}, "speed": 1.4,
        "desc": "40% faster. The building must be next to fresh water.",
    },
    "plumbing": {
        "name": "Plumbing", "for": ["house", "apartments"], "research": "plumbing",
        "cost": {"stone": 30, "tools": 5}, "housing": 4,
        "desc": "Houses 4 more people.",
    },
    "watering_trough": {
        "name": "Watering Trough", "for": ["salt_lick"],
        "cost": {"wood": 15}, "wildlife_speed": 0.25,
        "desc": "Wildlife appears a further 25% more often.",
    },
    "wagon_shed": {
        "name": "Wagon Shed", "for": ["stable"],
        "cost": {"wood": 40, "livestock": 2}, "explore_speed": 0.15,
        "desc": "Expeditions travel a further 15% faster. Costs 2 livestock.",
    },
    "cheese_cellar": {
        "name": "Cheese Cellar", "for": ["dairy"], "research": "masonry",
        "cost": {"stone": 30}, "produces": {"food": 2},
        "desc": "+2 Food per cycle.",
    },
    "dye_vats": {
        "name": "Dye Vats", "for": ["weaver"],
        "cost": {"wood": 20, "stone": 10}, "produces": {"gold": 2},
        "desc": "+2 Gold per cycle.",
    },
    "totem": {
        "name": "Totem", "for": ["shaman_hut"],
        "cost": {"wood": 20}, "produces": {"knowledge": 1},
        "desc": "+1 Knowledge per cycle.",
    },
    "smokehouse": {
        "name": "Smokehouse", "for": ["fishing_dock", "hunting_lodge", "fishery"], "research": "smoking",
        "cost": {"wood": 20}, "produces": {"food": 1},
        "desc": "+1 Food per cycle.",
    },
    "feeding_trough": {
        "name": "Feeding Trough", "for": ["pasture", "dairy"],
        "cost": {"wood": 15, "food": 10}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "barn": {
        "name": "Barn", "for": ["pasture"],
        "cost": {"wood": 40}, "herd": 5,
        "desc": "Holds 5 more livestock.",
    },
    "deep_shaft": {
        "name": "Deep Shaft", "for": ["well"],
        "cost": {"stone": 30}, "fertility_aura": 10,
        "desc": "+10 more fertility to the surrounding tiles.",
    },
    "sails": {
        "name": "Bigger Sails", "for": ["windmill"],
        "cost": {"wood": 30}, "aura_bonus": 0.1,
        "desc": "Surrounding farms get a further 10% faster.",
    },
    "great_lamp": {
        "name": "Great Lamp", "for": ["lighthouse"],
        "cost": {"stone": 20, "gold": 20}, "aura_bonus": 0.1,
        "desc": "Surrounding water buildings get a further 10% faster.",
    },
    "drying_racks": {
        "name": "Drying Racks", "for": ["tannery", "reed_cutter", "peat_cutter", "salt_works", "weaver"],
        "cost": {"wood": 20}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "library": {
        "name": "Library", "for": ["school", "university", "observatory", "laboratory"], "research": "masonry",
        "cost": {"wood": 30, "stone": 30}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "irrigation_pipes": {
        "name": "Irrigation Pipes", "for": ["irrigated_farm", "orchard", "greenhouse", "rice_paddy"], "research": "water_wheels",
        "cost": {"stone": 20, "ore": 15}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "flywheel": {
        "name": "Flywheel", "for": ["water_mill", "steam_engine"], "research": "mechanics",
        "cost": {"ore": 30}, "generates": 2,
        "desc": "+2 power.",
    },
    "crane": {
        "name": "Loading Crane", "for": ["harbor", "fishery"], "research": "mechanics",
        "cost": {"wood": 40, "ore": 20}, "speed": 1.25,
        "desc": "25% faster.",
    },
    "transformer": {
        "name": "Transformer", "for": ["wind_turbine", "hydro_dam", "power_plant", "geothermal_plant"], "research": "electricity",
        "cost": {"ore": 30, "tools": 10}, "generates": 4,
        "desc": "+4 power.",
    },
    "assembly_line": {
        "name": "Assembly Line", "for": ["factory", "glassworks", "smithy"], "research": "mass_production",
        "cost": {"tools": 20, "gold": 30}, "speed": 1.3,
        "desc": "30% faster.",
    },
}

# Kinds of area an expedition can find. Fields:
#   weight   how common it is (0 = never found by exploring)
#   terrain  multipliers on how common each terrain is (ordinary or rare)
#   river / lake / ocean   chance the area has one; lakes = how many tries
#   temp     added to the home climate
#   cost     what an expedition there needs, per step of distance from home
ENVIRONMENTS = {
    "homeland":  {"name": "Homeland",  "weight": 0, "terrain": {}, "temp": 0, "cost": {},
                  "river": 0.7, "lake": 0.5, "ocean": 0},
    "grassland": {"name": "Grassland", "weight": 3, "terrain": {"plains": 2.5}, "temp": 0,
                  "river": 0.6, "lake": 0.3, "ocean": 0.02,
                  "cost": {"food": 30, "wood": 10}},
    "woodland":  {"name": "Woodland",  "weight": 3, "terrain": {"forest": 3, "dense_forest": 1.5}, "temp": -1,
                  "river": 0.6, "lake": 0.4, "ocean": 0.02,
                  "cost": {"food": 30, "wood": 20}},
    "highlands": {"name": "Highlands", "weight": 2, "terrain": {"hill": 3.5, "mountain": 1.5}, "temp": -4,
                  "river": 0.5, "lake": 0.3, "ocean": 0,
                  "cost": {"food": 40, "wood": 30}},
    "lakeland":  {"name": "Lakeland",  "weight": 2, "terrain": {"marsh": 3}, "temp": 0,
                  "river": 0.6, "lake": 1, "lakes": 3, "ocean": 0.02,
                  "cost": {"food": 30, "wood": 50}},
    "desert":    {"name": "Desert",    "weight": 2, "terrain": {"desert": 6, "oasis": 1.5}, "temp": 8,
                  "river": 0.2, "lake": 0, "ocean": 0.02,
                  "cost": {"food": 80, "wood": 20}},
    "tundra":    {"name": "Tundra",    "weight": 1, "terrain": {"hill": 1.5}, "temp": -16,
                  "river": 0.4, "lake": 0.5, "ocean": 0.04,
                  "cost": {"food": 60, "wood": 50}},
    "coast":     {"name": "Coast",     "weight": 1, "terrain": {}, "temp": 0,
                  "river": 0.5, "lake": 0.1, "ocean": 1,
                  "cost": {"food": 30, "wood": 40}},
}

# Wild animals. terrain is where they appear; livestock is what one is worth
# once tamed (the species is not remembered after that).
WILDLIFE = {
    "rabbit":  {"name": "Rabbits",        "glyph": "r", "terrain": ["plains", "forest"], "livestock": 1, "weight": 4},
    "duck":    {"name": "Ducks",          "glyph": "k", "terrain": ["fresh"],            "livestock": 1, "weight": 3},
    "goat":    {"name": "Mountain Goats", "glyph": "g", "terrain": ["hill"],             "livestock": 2, "weight": 3},
    "sheep":   {"name": "Wild Sheep",     "glyph": "e", "terrain": ["plains", "hill"],   "livestock": 2, "weight": 3},
    "deer":    {"name": "Deer",           "glyph": "d", "terrain": ["forest"],           "livestock": 3, "weight": 3},
    "boar":    {"name": "Wild Boar",      "glyph": "b", "terrain": ["forest"],           "livestock": 3, "weight": 2},
    "camel":   {"name": "Camels",         "glyph": "c", "terrain": ["desert"],           "livestock": 5, "weight": 2},
    "horse":   {"name": "Wild Horses",    "glyph": "o", "terrain": ["plains", "desert"], "livestock": 5, "weight": 1},
    "aurochs": {"name": "Aurochs",        "glyph": "a", "terrain": ["plains"],           "livestock": 6, "weight": 1},
    "bison":   {"name": "Bison",          "glyph": "n", "terrain": ["meadow"],           "livestock": 5, "weight": 4},
    "buffalo": {"name": "Water Buffalo",  "glyph": "f", "terrain": ["swamp", "marsh"],   "livestock": 5, "weight": 3},
    "yak":     {"name": "Yaks",           "glyph": "y", "terrain": ["glacier", "mountain", "foothills"], "livestock": 4, "weight": 3},
}


# --------------------------------------------------------------------------
# Terrain / building interactions
# --------------------------------------------------------------------------
# Each modifier takes (area, x, y) and returns (speed multiplier, short label).
# Above 1 makes the building's cycle shorter, below 1 makes it longer.

def _count_adjacent(area, x, y, test):
    return sum(1 for nx, ny in neighbors(area, x, y) if test(area["tiles"][ny][nx]))


def _mod_fertility(area, x, y):
    f = effective_fertility(area, x, y)
    return 0.4 + f / 100, f"fertility {f}%"


def _mod_crop_temperature(area, x, y):
    t = area["tiles"][y][x]["temp"]
    if 10 <= t <= 28:
        return 1.0, f"{t}C ideal"
    off = (10 - t) if t < 10 else (t - 28)
    return max(0.25, 1 - off * 0.05), f"{t}C too {'cold' if t < 10 else 'hot'}"


def _mod_height(area, x, y):
    h = area["tiles"][y][x]["height"]
    return 1 + 0.1 * (h - 4), f"height {h}"


def _mod_adjacent_water(area, x, y):
    if has_adjacent(area, x, y, "fresh"):
        return 1.25, "next to fresh water"
    return 1.0, "no fresh water nearby"


def _mod_fish(area, x, y):
    f = area["tiles"][y][x]["fish"]
    return 0.4 + f / 100, f"fish {f}%"


def _mod_deep_forest(area, x, y):
    n = _count_adjacent(area, x, y, lambda t: terrain_is(t["terrain"], "forest"))
    return 1 + 0.1 * n, f"{n} forest nearby"


def _mod_open_water(area, x, y):
    n = _count_adjacent(area, x, y, lambda t: terrain_is(t["terrain"], "water"))
    return 1 + 0.1 * n, f"{n} water nearby"


def _mod_customers(area, x, y):
    n = _count_adjacent(area, x, y, lambda t: t["building"] and BUILDINGS[t["building"]].get("housing"))
    return 1 + 0.1 * n, f"{n} homes nearby"


def _mod_near_mine(area, x, y):
    if _count_adjacent(area, x, y, lambda t: t["building"] in ("mine", "deep_mine")):
        return 1.25, "next to a mine"
    return 1.0, "no mine nearby"


MODIFIERS = {
    "fertility": _mod_fertility,
    "crop_temperature": _mod_crop_temperature,
    "height": _mod_height,
    "adjacent_water": _mod_adjacent_water,
    "fish": _mod_fish,
    "deep_forest": _mod_deep_forest,
    "open_water": _mod_open_water,
    "customers": _mod_customers,
    "near_mine": _mod_near_mine,
}


# --------------------------------------------------------------------------
# Areas and tiles
# --------------------------------------------------------------------------

def _land_terrain(rng, env, distance):
    """Pick the terrain for a land tile `distance` areas from home."""
    bias = ENVIRONMENTS[env]["terrain"]
    names = [n for n, t in TERRAINS.items() if t.get("weight")]
    terrain = rng.choices(names, weights=[TERRAINS[n]["weight"] * bias.get(n, 1) for n in names])[0]
    for rare, t in TERRAINS.items():
        if t.get("from") == terrain:
            chance = t["chance"] * bias.get(rare, 1) * (RARE_BASE + RARE_PER_DISTANCE * distance)
            if rng.random() < min(RARE_MAX, chance):
                return rare
    return terrain


def _new_tile(climate, rng, env="homeland", distance=0):
    return _make_tile(_land_terrain(rng, env, distance), climate, rng)


def _make_tile(terrain, climate, rng):
    t = TERRAINS[terrain]
    height = rng.randint(*t["height"])
    return {
        "terrain": terrain,
        "height": height,
        "fertility": rng.randint(*t["fertility"]),
        "fish": rng.randint(*t.get("fish", (0, 0))),
        "temp": climate + t["temp"] - DEGREES_PER_HEIGHT * height + rng.randint(-2, 2),
        "building": None,
        "progress": 0,   # seconds of work done on the building's current cycle
        "additions": [],
        "animal": None,  # id from WILDLIFE while a wild animal is here
    }


def _new_area(rx, ry, env, climate, rng):
    area = {
        "rx": rx, "ry": ry,          # position in the world; home is (0, 0)
        "env": env,
        "size": AREA_SIZE,
        "climate": climate,
        "tiles": [[_new_tile(climate, rng, env, abs(rx) + abs(ry)) for _ in range(AREA_SIZE)]
                  for _ in range(AREA_SIZE)],
    }
    _carve_water(area, rng)
    _spread_terrain(area, rng)
    for _ in range(2):
        _spawn_animal(area, rng)
    return area


def _carve_water(area, rng):
    """Lay an ocean, a river and lakes over a freshly made area, as its environment allows."""
    env, n, tiles = ENVIRONMENTS[area["env"]], area["size"], area["tiles"]

    def put(x, y, terrain):
        if 0 <= x < n and 0 <= y < n and not terrain_is(tiles[y][x]["terrain"], "water"):
            tiles[y][x] = _make_tile(terrain, area["climate"], rng)

    if rng.random() < env["ocean"]:        # a ragged band along one side, about half the map
        side, depth = rng.randrange(4), rng.randint(2, 3)
        for i in range(n):
            depth = max(1, min(n - 2, depth + rng.choice((-1, 0, 0, 1))))
            for d in range(depth):
                put(*[(d, i), (n - 1 - d, i), (i, d), (i, n - 1 - d)][side], "ocean")
    if rng.random() < env["river"]:        # a wandering line from one side to the other
        across, pos = rng.random() < 0.5, rng.randrange(n)
        for i in range(n):
            put(*((i, pos) if across else (pos, i)), "river")
            step = rng.choice((-1, 0, 0, 0, 1))
            if 0 <= pos + step < n:
                pos += step
                put(*((i, pos) if across else (pos, i)), "river")
    for _ in range(env.get("lakes", 1)):   # a clump of 2-5 tiles
        if rng.random() < env["lake"]:
            cells = [(rng.randrange(n), rng.randrange(n))]
            for _ in range(rng.randint(2, 6)):
                x, y = rng.choice(cells)
                dx, dy = rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
                if 0 <= x + dx < n and 0 <= y + dy < n:
                    cells.append((x + dx, y + dy))
            for x, y in set(cells):
                put(x, y, "lake")


def _spread_terrain(area, rng, cells=None):
    """Turn some tiles into the terrain that forms beside their neighbours
    (dunes inside deserts, swamp by marshes, ...). `cells` limits it to those
    (x, y) positions; tiles with buildings are never changed."""
    n, tiles = area["size"], area["tiles"]
    for terrain, t in TERRAINS.items():
        if "near" not in t:
            continue
        alike = lambda other: any(terrain_is(other["terrain"], k) for k in t["near"])
        for y in range(n):
            for x in range(n):
                tile = tiles[y][x]
                if (cells is not None and (x, y) not in cells) or tile["building"]:
                    continue
                if (tile["terrain"] in t["spread_from"] and rng.random() < t["chance"]
                        and _count_adjacent(area, x, y, alike) >= t.get("need", 1)):
                    tiles[y][x] = _make_tile(terrain, area["climate"], rng)


def _playable(tiles):
    """A starting map must have somewhere to farm, log, mine and fish."""
    flat = [t for row in tiles for t in row]
    count = lambda name: sum(1 for t in flat if terrain_is(t["terrain"], name))
    farmable = sum(1 for t in flat if terrain_is(t["terrain"], "plains")
                   and t["height"] <= 2 and t["fertility"] >= 40)
    minable = sum(1 for t in flat if terrain_is(t["terrain"], "hill") and t["height"] >= 5)
    return (farmable >= 3 and count("forest") >= 2 and minable >= 1
            and 2 <= count("water") <= len(flat) // 3)


def new_game(name, now, seed=None):
    rng = random.Random(seed)
    while True:
        home = _new_area(0, 0, "homeland", rng.randint(10, 26), rng)
        if _playable(home["tiles"]):
            break
    state = {
        "name": name,
        "seed": rng.randrange(1 << 30),   # decides what lies in each direction
        "founded": now,
        "updated": now,      # game time has been simulated up to here
        "meal": 0,           # seconds since the last meal
        "wild": 0,           # seconds since wildlife last appeared
        "hungry": False,
        "tech": 0,
        "areas": [home],
        "expedition": None,  # {"rx", "ry", "arrive"} while a team is travelling
        "resources": {k: START_RESOURCES.get(k, 0) for k in RESOURCES},
        "population": START_POPULATION,
        "research": [],
        "log": [],
    }
    state["banned"] = []     # cities that may not view this one or propose bills to it
    _remember_seen(state, now)
    log(state, now, f"The tribe of {name} settles a new land.")
    return state


def migrate(state, now):
    """Bring a save from an older version of the game up to date."""
    if "updated" not in state:  # turn-based save
        state.pop("turn", None)
        state.update(founded=now, updated=now, meal=0, hungry=False)
        state["log"] = [{"t": now, "text": str(entry)} for entry in state["log"]]
        for row in state["tiles"]:
            for tile in row:
                tile["progress"] = 0
                if tile["building"] == "market":
                    tile["building"] = "trading_post"
    if "areas" not in state:    # single-map save
        state["areas"] = [{"rx": 0, "ry": 0, "env": "homeland", "size": state.pop("size"),
                           "climate": state.pop("climate"), "tiles": state.pop("tiles")}]
    # Things added since the save was made.
    state.setdefault("seed", random.randrange(1 << 30))
    state.setdefault("research", [])
    state.setdefault("wild", 0)
    state.setdefault("expedition", None)
    state.setdefault("banned", [])
    if "seen" not in state:
        _remember_seen(state, state["updated"])
    for k in RESOURCES:
        state["resources"].setdefault(k, 0)
    for area in state["areas"]:
        for row in area["tiles"]:
            for tile in row:
                tile.setdefault("additions", [])
                tile.setdefault("animal", None)
                if tile["terrain"] == "water":      # from before rivers, lakes and oceans
                    tile.update(terrain="lake", fish=50)
                tile.setdefault("fish", 0)
    return state


def _expand_area(area):
    """Wrap an area in a ring of newly discovered tiles."""
    rng = random.Random()
    pad = MAP_GROWTH_PER_TECH // 2
    old, size = area["tiles"], area["size"] + pad * 2
    tiles = [[None] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            oy, ox = y - pad, x - pad
            if 0 <= oy < area["size"] and 0 <= ox < area["size"]:
                tiles[y][x] = old[oy][ox]
            else:
                tiles[y][x] = _new_tile(area["climate"], rng, area["env"], abs(area["rx"]) + abs(area["ry"]))
    # Rivers and oceans that reached the old edge carry on into the new land.
    for y in range(size):
        for x in range(size):
            ix, iy = min(max(x, pad), size - 1 - pad), min(max(y, pad), size - 1 - pad)
            inner = tiles[iy][ix]["terrain"]
            if (ix, iy) != (x, y) and (inner == "ocean" or (inner == "river" and (ix == x or iy == y))):
                tiles[y][x] = _make_tile(inner, area["climate"], rng)
    area["tiles"], area["size"] = tiles, size
    ring = {(x, y) for y in range(size) for x in range(size)
            if not (pad <= x < size - pad and pad <= y < size - pad)}
    _spread_terrain(area, rng, ring)


def neighbors(area, x, y):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            nx, ny = x + dx, y + dy
            if (dx or dy) and 0 <= nx < area["size"] and 0 <= ny < area["size"]:
                yield nx, ny


def terrain_is(terrain, wanted):
    """True if `terrain` is `wanted` or belongs to the group `wanted`."""
    return terrain == wanted or wanted in TERRAINS[terrain].get("groups", ())


def terrain_label(key):
    return TERRAINS[key]["name"].lower() if key in TERRAINS else GROUP_NAMES.get(key, key)


def has_adjacent(area, x, y, terrain):
    return any(terrain_is(area["tiles"][ny][nx]["terrain"], terrain) for nx, ny in neighbors(area, x, y))


def effective_fertility(area, x, y):
    tile = area["tiles"][y][x]
    if terrain_is(tile["terrain"], "water"):
        return 0
    f = tile["fertility"]
    for nx, ny in neighbors(area, x, y):
        if area["tiles"][ny][nx]["building"]:
            f += tile_stat(area["tiles"][ny][nx], "fertility_aura")
    return min(100, f)


def all_tiles(state):
    return (t for area in state["areas"] for row in area["tiles"] for t in row)


def has_building(state, bid):
    return any(t["building"] == bid for t in all_tiles(state))


def where(rx, ry):
    """Position of an area in words, relative to home."""
    if not (rx or ry):
        return "Home"
    parts = []
    if ry:
        parts.append(f"{abs(ry)} {'north' if ry < 0 else 'south'}")
    if rx:
        parts.append(f"{abs(rx)} {'east' if rx > 0 else 'west'}")
    return ", ".join(parts)


def area_name(area):
    if not (area["rx"] or area["ry"]):
        return "Home"
    return f"{ENVIRONMENTS[area['env']]['name']} ({where(area['rx'], area['ry'])})"


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

def log(state, now, text):
    state["log"].append({"t": now, "text": text})
    del state["log"][:-40]


def fmt_goods(goods):
    return ", ".join(f"{v} {RESOURCES[k]}" for k, v in goods.items())


def _missing(state, cost):
    return {k: v for k, v in cost.items() if state["resources"].get(k, 0) < v}


def _pay(state, cost):
    for k, v in cost.items():
        state["resources"][k] -= v


def _researched(state, field):
    """Values of `field` across everything the city has researched."""
    return [RESEARCH[rid][field] for rid in state["research"] if field in RESEARCH[rid]]


def _need_research(state, field, what):
    """Problem text if nothing researched has `field`, else None."""
    if _researched(state, field):
        return None
    names = [r["name"] for r in RESEARCH.values() if field in r]
    return f"{what} requires research: {names[0]}" if names else f"{what} is not possible"


def tile_cycle(state, area, x, y, bid):
    """Seconds one cycle of `bid` takes on this tile at full staff: (seconds, notes).

    Returns (None, []) for buildings that don't work in cycles (housing etc).
    """
    b = BUILDINGS[bid]
    if "time" not in b:
        return None, []
    factors = [MODIFIERS[m](area, x, y) for m in b.get("modifiers", [])]
    # Neighbouring buildings that help this kind of building (e.g. windmills).
    for nx, ny in neighbors(area, x, y):
        nb = area["tiles"][ny][nx]["building"]
        aura = BUILDINGS[nb].get("speed_aura") if nb else None
        if aura and bid in aura["for"]:
            bonus = aura["bonus"] + tile_stat(area["tiles"][ny][nx], "aura_bonus")
            factors.append((1 + bonus, f"{BUILDINGS[nb]['name']} nearby"))
    # The ground it stands on.
    ground = TERRAINS[area["tiles"][y][x]["terrain"]]
    if bid in ground.get("boost", {}):
        factors.append((ground["boost"][bid], ground["name"]))
    # The size of the city's herd.
    if b.get("livestock_speed"):
        herd = int(state["resources"]["livestock"])
        factors.append((max(0.2, min(2.0, herd / LIVESTOCK_FOR_FULL_SPEED)), f"{herd} livestock owned"))
    # Researched techniques.
    for rid in state["research"]:
        if bid in RESEARCH[rid].get("boost", {}):
            factors.append((RESEARCH[rid]["boost"][bid], RESEARCH[rid]["name"]))
    # Additions attached to the building standing here.
    tile = area["tiles"][y][x]
    if tile["building"] == bid:
        for aid in tile["additions"]:
            if "speed" in ADDITIONS[aid]:
                factors.append((ADDITIONS[aid]["speed"], ADDITIONS[aid]["name"]))
    speed, notes = 1.0, []
    for factor, label in factors:
        speed *= factor
        notes.append(f"{label} x{factor:.2f}")
    return round(b["time"] / speed), notes


def tile_output(tile):
    """What the building on this tile pays out per cycle, additions included."""
    out = dict(BUILDINGS[tile["building"]].get("produces", {}))
    for aid in tile["additions"]:
        for k, v in ADDITIONS[aid].get("produces", {}).items():
            out[k] = out.get(k, 0) + v
    return out


def tile_stat(tile, field):
    """A number the building on this tile has, plus what its additions add to it."""
    return (BUILDINGS[tile["building"]].get(field, 0)
            + sum(ADDITIONS[aid].get(field, 0) for aid in tile["additions"]))


def tile_housing(tile):
    return tile_stat(tile, "housing")


def placement_problem(state, area, x, y, bid):
    """Why `bid` can't stand on this tile (ignoring cost), or None if it can."""
    b = BUILDINGS[bid]
    tile = area["tiles"][y][x]
    if b["tech"] > state["tech"]:
        return f"requires {TECH_LEVELS[b['tech']]['name']} tech"
    if b.get("research") and b["research"] not in state["research"]:
        return f"requires research: {RESEARCH[b['research']]['name']}"
    if not any(terrain_is(tile["terrain"], t) for t in b["terrain"]):
        return "needs " + " or ".join(terrain_label(t) for t in b["terrain"])
    lock = TERRAINS[tile["terrain"]].get("research")
    if lock and lock not in state["research"]:
        return f"this land can't be used until you research {RESEARCH[lock]['name']}"
    if "max_height" in b and tile["height"] > b["max_height"]:
        return f"too steep (height {tile['height']}, max {b['max_height']})"
    if "min_height" in b and tile["height"] < b["min_height"]:
        return f"too low (height {tile['height']}, needs {b['min_height']}+)"
    if "min_fertility" in b and effective_fertility(area, x, y) < b["min_fertility"]:
        return f"not fertile enough ({effective_fertility(area, x, y)}%, needs {b['min_fertility']}%)"
    if "min_temp" in b and tile["temp"] < b["min_temp"]:
        return f"too cold ({tile['temp']}C)"
    if "max_temp" in b and tile["temp"] > b["max_temp"]:
        return f"too hot ({tile['temp']}C)"
    if "adjacent" in b and not has_adjacent(area, x, y, b["adjacent"]):
        return f"must be next to {terrain_label(b['adjacent'])}"
    return None


def work_plan(state):
    """Hand out workers and time every building.

    Workers go to buildings the player marked "first" (tile priority 1), then to
    the rest, each group in map order: home first, then each area top-left
    first. Buildings switched off (priority -1) get nobody.

    Returns (jobs, housing, totals) where jobs is a list of working buildings.
    """
    free = state["population"]
    housing, needed, herd_room, jobs = BASE_HOUSING, 0, 0, []
    for ai, area in enumerate(state["areas"]):
        for y, row in enumerate(area["tiles"]):
            for x, tile in enumerate(row):
                if not tile["building"]:
                    continue
                b = BUILDINGS[tile["building"]]
                housing += tile_housing(tile)
                cycle, notes = tile_cycle(state, area, x, y, tile["building"])
                if cycle is None and "generates" not in b:
                    continue
                need = b.get("workers", 0)
                power_out = tile_stat(tile, "generates")
                for m in b.get("generates_modifiers", []):
                    power_out *= MODIFIERS[m](area, x, y)[0]
                jobs.append({
                    "area": ai, "x": x, "y": y, "tile": tile, "b": b,
                    "cycle": cycle,             # None for a generator that needs no fuel
                    "notes": notes, "need": need, "priority": tile.get("priority", 0),
                    "produces": tile_output(tile),
                    "feeds": "food" in b.get("produces", {}) or "food" in b.get("per_head", {}),
                    "herd": tile_stat(tile, "herd"),
                    "herd_before": herd_room,   # pasture room in the buildings ahead of this one
                    "power_in": b.get("power", 0),
                    "power_out": round(power_out, 1),
                })
                herd_room += tile_stat(tile, "herd")
    for job in sorted(jobs, key=lambda j: -j["priority"]):   # stable: map order within a priority
        off = job["priority"] < 0
        job["staff"] = 0 if off else min(job["need"], free)
        free -= job["staff"]
        needed += 0 if off else job["need"]
        job["ratio"] = 0.0 if off else (job["staff"] / job["need"] if job["need"] else 1.0)
        job["herd_room"] = herd_room
    return jobs, housing, {"jobs": needed, "idle": free, "herd_room": herd_room}


def job_herd(state, job):
    """Livestock kept in this building. Pastures fill up in work order."""
    spare = state["resources"]["livestock"] - job["herd_before"]
    return int(max(0, min(job["herd"], spare)))


def job_output(state, job):
    """What this building pays out when its current cycle finishes."""
    out = dict(job["produces"])
    if "herd" in job["b"]:
        herd = job_herd(state, job)
        for k, v in job["b"].get("per_head", {}).items():
            if int(herd * v):
                out[k] = out.get(k, 0) + int(herd * v)
        if herd >= 2 and state["resources"]["livestock"] < job["herd_room"] and _researched(state, "breeding"):
            out["livestock"] = out.get("livestock", 0) + 1
    return out


def _out_of_inputs(state, job):
    """True if the building has finished a cycle and can't pay for it (e.g. no fuel)."""
    return (job["cycle"] is not None and job["tile"]["progress"] >= job["cycle"]
            and bool(_missing(state, job["b"].get("consumes", {}))))


def power_status(state, jobs):
    """(power supplied, power needed, share of the need that is met) right now."""
    supply = sum(j["power_out"] * j["ratio"] for j in jobs
                 if j["power_out"] and not _out_of_inputs(state, j))
    demand = sum(j["power_in"] for j in jobs if j["power_in"] and j["ratio"])
    return supply, demand, (min(1.0, supply / demand) if demand else 1.0)


def _speed(state, job, power=1.0):
    """Seconds of work this building gets done per second right now."""
    speed = job["ratio"]
    if state["hungry"] and not job["feeds"]:
        speed *= HUNGRY_SPEED
    if job["power_in"]:
        speed *= power
    return speed


def _meal(state, housing, when):
    """Everyone eats. Returns True if the population changed."""
    res, pop = state["resources"], state["population"]
    if res["food"] < pop:
        res["food"] = 0
        if not state["hungry"]:
            state["hungry"] = True
            log(state, when, "The food has run out. Hungry workers are working at half speed.")
        return False
    res["food"] -= pop
    if state["hungry"]:
        state["hungry"] = False
        log(state, when, "Everyone is fed again.")
    arrivals = _arrivals(pop, res["food"], housing, 1 + city_attracts(state))
    state["population"] += arrivals
    return arrivals > 0


def city_stat(state, field):
    """`field` added up over every building (and its additions) in the city."""
    return sum(tile_stat(t, field) for t in all_tiles(state) if t["building"])


def city_attracts(state):
    """Extra people who may arrive at each meal, from taverns and the like."""
    return city_stat(state, "attracts")


def _arrivals(pop, food_left, housing, tries):
    """How many people join after a meal that left `food_left` in store.

    Up to `tries` may come. Each needs a free place to live and a meal already
    in store for everyone including the newcomers before them, so every extra
    arrival takes one more meal's worth of spare food than the last.
    """
    n = 0
    while n < tries and pop + n < housing and food_left >= pop + n:
        n += 1
    return n


def next_arrivals(state, housing):
    """How many people would join at the next meal as things stand."""
    pop, food = state["population"], state["resources"]["food"]
    if food < pop:
        return 0
    return _arrivals(pop, food - pop, housing, 1 + city_attracts(state))


def advance_time(state, now):
    """Simulate everything that happened between the last update and `now`."""
    remaining = now - state["updated"]
    if remaining <= 0:
        return
    state["updated"] = now
    res = state["resources"]
    jobs, housing, _ = work_plan(state)
    wildlife_speed = city_stat(state, "wildlife_speed")
    rng = random.Random()

    while remaining > 0:
        dt = min(SIM_STEP, remaining)
        remaining -= dt
        power = power_status(state, jobs)[2]
        for job in jobs:
            speed = _speed(state, job, power)
            if not speed or job["cycle"] is None:
                continue
            tile, b = job["tile"], job["b"]
            tile["progress"] += dt * speed
            while tile["progress"] >= job["cycle"]:
                if _missing(state, b.get("consumes", {})):
                    tile["progress"] = job["cycle"]   # finished, waiting for inputs
                    break
                _pay(state, b.get("consumes", {}))
                for k, v in job_output(state, job).items():
                    res[k] += v
                tile["progress"] -= job["cycle"]
        state["meal"] += dt
        while state["meal"] >= MEAL_TIME:
            state["meal"] -= MEAL_TIME
            if _meal(state, housing, now - remaining):
                jobs, housing, _ = work_plan(state)
        state["wild"] += dt * (1 + wildlife_speed)
        while state["wild"] >= WILDLIFE_TIME:
            state["wild"] -= WILDLIFE_TIME
            for area in state["areas"]:
                _spawn_animal(area, rng)

    trip = state["expedition"]
    if trip and now >= trip["arrive"]:
        _arrive(state, trip)


def build(state, now, area, x, y, bid):
    if bid not in BUILDINGS:
        return "Unknown building."
    tile = area["tiles"][y][x]
    b = BUILDINGS[bid]
    if tile["building"]:
        return "That tile already has a building."
    problem = placement_problem(state, area, x, y, bid)
    if problem:
        return f"Can't build {b['name']} here: {problem}."
    missing = _missing(state, b["cost"])
    if missing:
        return f"Not enough resources for {b['name']} (need {fmt_goods(missing)})."
    _pay(state, b["cost"])
    scared = tile["animal"]
    tile.update(building=bid, progress=0, additions=[], animal=None, priority=0)
    log(state, now, f"Built {b['name']} at ({x},{y}) in {area_name(area)}."
        + (f" The {WILDLIFE[scared]['name'].lower()} fled." if scared else ""))
    return None


def demolish(state, now, area, x, y):
    tile = area["tiles"][y][x]
    if not tile["building"]:
        return "Nothing to demolish there."
    b = BUILDINGS[tile["building"]]
    for part in [b] + [ADDITIONS[aid] for aid in tile["additions"]]:
        for k, v in part["cost"].items():
            state["resources"][k] += int(v * DEMOLISH_REFUND)
    tile.update(building=None, progress=0, additions=[], priority=0)
    log(state, now, f"Demolished {b['name']} at ({x},{y}) in {area_name(area)}.")
    return None


def set_priority(state, now, area, x, y, priority):
    """Choose how this building is staffed: 1 = first, 0 = normal, -1 = switched off."""
    tile = area["tiles"][y][x]
    if not tile["building"] or not BUILDINGS[tile["building"]].get("workers"):
        return "That building has no workers to assign."
    if priority not in (-1, 0, 1):
        return "Unknown priority."
    tile["priority"] = priority
    return None


def addition_problem(state, area, x, y, aid):
    """Why addition `aid` can't go on the building at this tile (ignoring cost), or None."""
    a, tile = ADDITIONS[aid], area["tiles"][y][x]
    if tile["building"] not in a["for"]:
        return "doesn't fit this building"
    if aid in tile["additions"]:
        return "already attached"
    if len(tile["additions"]) >= MAX_ADDITIONS:
        return f"no room (a building holds {MAX_ADDITIONS} additions)"
    if a.get("tech", 0) > state["tech"]:
        return f"requires {TECH_LEVELS[a['tech']]['name']} tech"
    if a.get("research") and a["research"] not in state["research"]:
        return f"requires research: {RESEARCH[a['research']]['name']}"
    if "adjacent" in a and not has_adjacent(area, x, y, a["adjacent"]):
        return f"building must be next to {terrain_label(a['adjacent'])}"
    return None


def add_addition(state, now, area, x, y, aid):
    if aid not in ADDITIONS:
        return "Unknown addition."
    a, tile = ADDITIONS[aid], area["tiles"][y][x]
    if not tile["building"]:
        return "There is no building there."
    problem = addition_problem(state, area, x, y, aid)
    if problem:
        return f"Can't add {a['name']}: {problem}."
    missing = _missing(state, a["cost"])
    if missing:
        return f"Not enough resources for {a['name']} (need {fmt_goods(missing)})."
    _pay(state, a["cost"])
    tile["additions"].append(aid)
    log(state, now, f"Added {a['name']} to the {BUILDINGS[tile['building']]['name']} at ({x},{y}).")
    return None


def research_problem(state, rid):
    """Why `rid` can't be researched (ignoring cost), or None."""
    r = RESEARCH[rid]
    if rid in state["research"]:
        return "already researched"
    if r["tech"] > state["tech"]:
        return f"requires {TECH_LEVELS[r['tech']]['name']} tech"
    if r.get("building") and not has_building(state, r["building"]):
        return f"needs a {BUILDINGS[r['building']]['name']}"
    return None


def research(state, now, rid):
    if rid not in RESEARCH:
        return "Unknown research."
    r = RESEARCH[rid]
    problem = research_problem(state, rid)
    if problem:
        return f"Can't research {r['name']}: {problem}."
    missing = _missing(state, r["cost"])
    if missing:
        return f"Not enough to research {r['name']} (need {fmt_goods(missing)})."
    _pay(state, r["cost"])
    state["research"].append(rid)
    log(state, now, f"Researched {r['name']}.")
    return None


def advance_checks(state):
    """Everything the next tech level asks for, and whether the city has it yet."""
    if state["tech"] + 1 >= len(TECH_LEVELS):
        return []
    nxt = TECH_LEVELS[state["tech"] + 1]
    checks = [(state["population"], nxt["population"], "population")]
    checks += [(int(state["resources"][k]), v, RESOURCES[k]) for k, v in nxt["cost"].items()]
    if nxt.get("research"):
        checks.append((len(state["research"]), nxt["research"], "things researched"))
    if nxt.get("areas"):
        checks.append((len(state["areas"]), nxt["areas"], "areas owned"))
    return [{"ok": have >= need, "text": f"{have} of {need} {what}"} for have, need, what in checks]


def advance(state, now):
    if state["tech"] + 1 >= len(TECH_LEVELS):
        return "You have reached the highest tech level."
    nxt = TECH_LEVELS[state["tech"] + 1]
    unmet = [c["text"] for c in advance_checks(state) if not c["ok"]]
    if unmet:
        return f"Not ready to become a {nxt['name']} yet: {', '.join(unmet)}."
    _pay(state, nxt["cost"])
    state["tech"] += 1
    _expand_area(state["areas"][0])
    log(state, now, f"*** {state['name']} is now a {nxt['name']}! The home area has grown. ***")
    return None


# ---- Coming back to the city ----

def _remember_seen(state, when):
    state["seen"] = {"t": when, "resources": dict(state["resources"]),
                     "population": state["population"]}


def check_in(state, now):
    """The city's own player is looking at it. If nobody had looked for a while
    (AWAY_TIME), a report of what changed is kept until the player dismisses it.
    Returns the waiting report, or None."""
    seen = state["seen"]
    if now - seen["t"] >= AWAY_TIME and not state.get("report"):
        state["report"] = {
            "since": seen["t"],
            "resources": {k: round(state["resources"][k] - seen["resources"].get(k, 0), 1)
                          for k in RESOURCES},
            "population": state["population"] - seen["population"],
            "hungry": state["hungry"],
            "events": [e for e in state["log"] if e["t"] > seen["t"]],
        }
    _remember_seen(state, now)
    return state.get("report")


def set_ban(state, now, target, banned):
    """Ban (or unban) another city from viewing this one and proposing bills to it."""
    if target == state["name"]:
        return "You can't ban your own city."
    if banned and target not in state["banned"]:
        state["banned"].append(target)
        log(state, now, f"Banned {target} from viewing this city and proposing bills.")
    elif not banned and target in state["banned"]:
        state["banned"].remove(target)
        log(state, now, f"Lifted the ban on {target}.")
    return None


# ---- Wildlife ----

def _spawn_animal(area, rng):
    """A wild animal wanders onto a free tile, if the area has room for more."""
    tiles = [t for row in area["tiles"] for t in row]
    if sum(1 for t in tiles if t["animal"]) >= MAX_WILDLIFE:
        return
    free = [t for t in tiles if not t["building"] and not t["animal"]]
    if not free:
        return
    tile = rng.choice(free)
    species = [s for s, w in WILDLIFE.items() if any(terrain_is(tile["terrain"], t) for t in w["terrain"])]
    if species:
        tile["animal"] = rng.choices(species, weights=[WILDLIFE[s]["weight"] for s in species])[0]


def tame_cost(species):
    return {"food": WILDLIFE[species]["livestock"] * TAME_FOOD_PER_HEAD}


def tame(state, now, area, x, y):
    tile = area["tiles"][y][x]
    if not tile["animal"]:
        return "There are no animals there."
    problem = _need_research(state, "taming", "Taming")
    if problem:
        return problem + "."
    w = WILDLIFE[tile["animal"]]
    missing = _missing(state, tame_cost(tile["animal"]))
    if missing:
        return f"Not enough bait to tame the {w['name'].lower()} (need {fmt_goods(missing)})."
    _pay(state, tame_cost(tile["animal"]))
    state["resources"]["livestock"] += w["livestock"]
    tile["animal"] = None
    log(state, now, f"Tamed {w['name'].lower()} in {area_name(area)}: +{w['livestock']} Livestock.")
    return None


# ---- Exploration ----

def region_env(state, rx, ry):
    """What kind of land lies at this position. Fixed for the life of the city."""
    rng = random.Random(f"{state['seed']}/{rx}/{ry}")
    names = [e for e, d in ENVIRONMENTS.items() if d["weight"]]
    return rng.choices(names, weights=[ENVIRONMENTS[e]["weight"] for e in names])[0]


def destinations(state):
    """Undiscovered positions next to a discovered area."""
    known = {(a["rx"], a["ry"]) for a in state["areas"]}
    out = set()
    for rx, ry in known:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (rx + dx, ry + dy) not in known:
                out.add((rx + dx, ry + dy))
    return sorted(out, key=lambda p: (abs(p[0]) + abs(p[1]), p[1], p[0]))


def expedition_cost(state, rx, ry):
    """Supplies for the team: depends on the land it is heading into and how far it is."""
    distance = abs(rx) + abs(ry)
    discount = min(_researched(state, "explore_discount"), default=1)
    base = ENVIRONMENTS[region_env(state, rx, ry)]["cost"]
    return {k: math.ceil(v * distance * discount) for k, v in base.items()}


def expedition_time(state, rx, ry):
    """Seconds the journey takes. Stables and the like shorten it."""
    speed = 1 + min(MAX_EXPLORE_SPEED, city_stat(state, "explore_speed"))
    return round(EXPEDITION_TIME * (abs(rx) + abs(ry)) / speed)


def expedition_problem(state, rx, ry):
    """Why a team can't be sent to this position (ignoring cost), or None."""
    problem = _need_research(state, "explore_range", "Exploring")
    if problem:
        return problem
    if state["expedition"]:
        return "an expedition is already under way"
    if (rx, ry) not in destinations(state):
        return "you can only explore next to land you already know"
    if abs(rx) + abs(ry) > max(_researched(state, "explore_range")):
        better = [r["name"] for r in RESEARCH.values()
                  if r.get("explore_range", 0) >= abs(rx) + abs(ry)]
        return "too far from home" + (f" (requires research: {better[0]})" if better else "")
    return None


def send_expedition(state, now, rx, ry):
    if not (isinstance(rx, int) and isinstance(ry, int)):
        return "Bad destination."
    problem = expedition_problem(state, rx, ry)
    if problem:
        return f"Can't send an expedition: {problem}."
    cost = expedition_cost(state, rx, ry)
    missing = _missing(state, cost)
    if missing:
        return f"Not enough supplies for the expedition (need {fmt_goods(missing)})."
    _pay(state, cost)
    state["expedition"] = {"rx": rx, "ry": ry, "left": now, "arrive": now + expedition_time(state, rx, ry)}
    log(state, now, f"An expedition set out {where(rx, ry)} of home with {fmt_goods(cost)}.")
    return None


def _arrive(state, trip):
    env = region_env(state, trip["rx"], trip["ry"])
    home = state["areas"][0]
    area = _new_area(trip["rx"], trip["ry"], env, home["climate"] + ENVIRONMENTS[env]["temp"],
                     random.Random())
    state["areas"].append(area)
    state["expedition"] = None
    log(state, trip["arrive"], f"*** The expedition has mapped a new area: {area_name(area)}. ***")


def apply_action(state, now, action, data):
    """Run one player action. Returns an error message, or None on success."""
    if action == "advance":
        return advance(state, now)
    if action == "dismiss_away":
        state["report"] = None
        return None
    if action == "research":
        return research(state, now, data.get("research"))
    if action == "explore":
        return send_expedition(state, now, data.get("rx"), data.get("ry"))
    if action in ("build", "demolish", "add", "tame", "priority"):
        ai, x, y = data.get("area", 0), data.get("x"), data.get("y")
        if not (isinstance(ai, int) and 0 <= ai < len(state["areas"])):
            return "Unknown area."
        area = state["areas"][ai]
        if not (isinstance(x, int) and isinstance(y, int)
                and 0 <= x < area["size"] and 0 <= y < area["size"]):
            return "Bad tile."
        if action == "build":
            return build(state, now, area, x, y, data.get("building"))
        if action == "add":
            return add_addition(state, now, area, x, y, data.get("addition"))
        if action == "tame":
            return tame(state, now, area, x, y)
        if action == "priority":
            return set_priority(state, now, area, x, y, data.get("priority"))
        return demolish(state, now, area, x, y)
    return "Unknown action."


# --------------------------------------------------------------------------
# What the browser sees
# --------------------------------------------------------------------------

def view(state, ai=0):
    """The saved state plus everything the UI needs computed to show area `ai`."""
    if not 0 <= ai < len(state["areas"]):
        ai = 0
    area = state["areas"][ai]
    jobs, housing, totals = work_plan(state)
    rates = {k: 0.0 for k in RESOURCES}   # expected change per hour, whole city
    rates["food"] -= state["population"] * 3600 / MEAL_TIME
    food_made = 0.0
    here = {}
    supply, demand, power = power_status(state, jobs)
    for job in jobs:
        job["speed"] = _speed(state, job, power)
        job["waiting"] = list(_missing(state, job["b"].get("consumes", {})))
        job["output"] = job_output(state, job)
        job["status"] = job_status(state, job, power)
        if job["speed"] and not job["waiting"] and job["cycle"]:
            per_hour = 3600 / job["cycle"] * job["speed"]
            for k, v in job["output"].items():
                rates[k] += v * per_hour
            food_made += job["output"].get("food", 0) * per_hour
            for k, v in job["b"].get("consumes", {}).items():
                rates[k] -= v * per_hour
        if job["area"] == ai:
            here[(job["x"], job["y"])] = job

    tame_problem = _need_research(state, "taming", "Taming")
    tiles = []
    for y in range(area["size"]):
        row = []
        for x in range(area["size"]):
            tile, cell = area["tiles"][y][x], {"fertility": effective_fertility(area, x, y)}
            lock = TERRAINS[tile["terrain"]].get("research")
            if lock and lock not in state["research"]:
                cell["locked"] = RESEARCH[lock]["name"]
            job = here.get((x, y))
            if job:
                cell.update(cycle=job["cycle"], notes=job["notes"], speed=job["speed"],
                            staff=job["staff"], need=job["need"], waiting=job["waiting"],
                            priority=job["priority"], status=job["status"],
                            produces=job["output"],
                            power_in=job["power_in"], power_out=job["power_out"])
                if "herd" in job["b"]:
                    cell["herd"], cell["herd_room"] = job_herd(state, job), job["herd"]
            if tile["animal"]:
                cost = tame_cost(tile["animal"])
                cell["tame"] = {"problem": tame_problem, "cost": cost,
                                "affordable": not _missing(state, cost)}
            if tile["building"]:
                cell["housing"] = tile_housing(tile)
                cell["additions"] = []   # additions that could still be attached
                for aid, a in ADDITIONS.items():
                    if tile["building"] in a["for"] and aid not in tile["additions"]:
                        cell["additions"].append({
                            "id": aid, "problem": addition_problem(state, area, x, y, aid),
                            "affordable": not _missing(state, a["cost"]),
                        })
            else:
                cell["build"] = []
                for bid, b in BUILDINGS.items():
                    if b["tech"] > state["tech"]:
                        continue
                    problem = placement_problem(state, area, x, y, bid)
                    entry = {"id": bid, "problem": problem}
                    if not problem:
                        entry["cycle"], entry["notes"] = tile_cycle(state, area, x, y, bid)
                        entry["affordable"] = not _missing(state, b["cost"])
                    cell["build"].append(entry)
            row.append(cell)
        tiles.append(row)

    explore = []
    for rx, ry in destinations(state):
        cost = expedition_cost(state, rx, ry)
        explore.append({
            "rx": rx, "ry": ry, "where": where(rx, ry), "env": region_env(state, rx, ry),
            "distance": abs(rx) + abs(ry), "cost": cost, "time": expedition_time(state, rx, ry),
            "problem": expedition_problem(state, rx, ry),
            "affordable": not _missing(state, cost),
        })
    trip = state["expedition"]

    return {
        "state": state,
        "area": ai,
        "areas": [{"name": area_name(a), "env": a["env"], "size": a["size"],
                   "buildings": sum(1 for row in a["tiles"] for t in row if t["building"]),
                   "animals": sum(1 for row in a["tiles"] for t in row if t["animal"]),
                   # buildings that are not working properly
                   "problems": sum(1 for j in jobs if j["area"] == i and j["status"] != "working")}
                  for i, a in enumerate(state["areas"])],
        "status": {
            "housing": housing,
            "jobs": totals["jobs"],
            "idle": totals["idle"],
            "herd_room": totals["herd_room"],
            "power": {"supply": round(supply, 1), "demand": demand},
            "rates": {k: round(v, 1) for k, v in rates.items()},
            "meal_time": MEAL_TIME,
            "food_made": round(food_made, 1),
            "food_eaten": round(state["population"] * 3600 / MEAL_TIME, 1),
            "housing_from": housing_sources(state),
            "growth": growth_checks(state, housing),
            "arrivals_max": 1 + city_attracts(state),
            "advance": advance_view(state),
            "arrivals_next": next_arrivals(state, housing),
        },
        "tiles": tiles,
        "research": [{"id": rid, "done": rid in state["research"],
                      "problem": research_problem(state, rid),
                      "affordable": not _missing(state, r["cost"])}
                     for rid, r in RESEARCH.items()],
        "explore": {
            "destinations": explore,
            "expedition": trip and {**trip, "where": where(trip["rx"], trip["ry"]),
                                    "env": region_env(state, trip["rx"], trip["ry"])},
        },
        "defs": {
            "terrains": TERRAINS,
            "resources": RESOURCES,
            "tradeable": [k for k in RESOURCES if k not in UNTRADEABLE],
            "buildings": BUILDINGS,
            "categories": CATEGORIES,
            "tech": TECH_LEVELS,
            "research": RESEARCH,
            "additions": ADDITIONS,
            "max_additions": MAX_ADDITIONS,
            "environments": ENVIRONMENTS,
            "wildlife": WILDLIFE,
        },
    }


def advance_view(state):
    checks = advance_checks(state)
    if not checks:
        return None
    return {"name": TECH_LEVELS[state["tech"] + 1]["name"], "checks": checks,
            "ready": all(c["ok"] for c in checks)}


def job_status(state, job, power):
    """In a few words, how a working building is doing: "working" or what is wrong."""
    if job["priority"] < 0:
        return "switched off"
    if job["need"] and not job["staff"]:
        return "no workers"
    missing = _missing(state, job["b"].get("consumes", {}))
    if missing:
        return "waiting for " + ", ".join(RESOURCES[k] for k in missing)
    if job["power_in"] and power <= 0:
        return "no power"
    slow = []
    if job["staff"] < job["need"]:
        slow.append(f"short of workers ({job['staff']} of {job['need']})")
    if job["power_in"] and power < 1:
        slow.append("short of power")
    if state["hungry"] and not job["feeds"]:
        slow.append("hungry")
    return ", ".join(slow) or "working"


def _clock(seconds):
    return f"{int(seconds) // 60}m {int(seconds) % 60:02d}s"


FIND_LIMIT = 60     # most results the Find box is given


def find(state, kind, what):
    """Search every area of the city. Returns {"results": [...], "total": n} or
    {"locked": research name} if the search needs research the city lacks.

    kind is "buildings" (what = a building id, or "" for all), "problems",
    "wildlife", "sites" (what = a building id: where it could go, fastest
    first) or "terrain" (what = a terrain id).
    """
    if kind in ("sites", "terrain") and not _researched(state, "surveying"):
        return {"locked": next(r["name"] for r in RESEARCH.values() if r.get("surveying"))}
    found = []   # (sort key, result)
    jobs, _, _ = work_plan(state)
    power = power_status(state, jobs)[2]
    by_tile = {(j["area"], j["x"], j["y"]): j for j in jobs}
    for ai, area in enumerate(state["areas"]):
        for y, row in enumerate(area["tiles"]):
            for x, tile in enumerate(row):
                hit = lambda label, note, key=0: found.append(
                    (key, {"area": ai, "x": x, "y": y, "label": label, "note": note}))
                bid, terrain = tile["building"], TERRAINS[tile["terrain"]]
                job = by_tile.get((ai, x, y))
                if kind in ("buildings", "problems") and bid and (not what or bid == what):
                    status = job_status(state, job, power) if job else ""
                    if kind == "buildings" or (job and status != "working"):
                        hit(BUILDINGS[bid]["name"], status)
                elif kind == "wildlife" and tile["animal"]:
                    w = WILDLIFE[tile["animal"]]
                    hit(w["name"], f"worth {w['livestock']} livestock, on {terrain['name'].lower()}", -w["livestock"])
                elif kind == "terrain" and tile["terrain"] == what:
                    fact = (f"fish {tile['fish']}%" if terrain_is(tile["terrain"], "water")
                            else f"fertility {effective_fertility(area, x, y)}%")
                    hit(terrain["name"], f"{fact}, height {tile['height']}, "
                        + (BUILDINGS[bid]["name"] if bid else "nothing built"), 1 if bid else 0)
                elif (kind == "sites" and what in BUILDINGS and not bid
                      and not placement_problem(state, area, x, y, what)):
                    cycle = tile_cycle(state, area, x, y, what)[0]
                    hit(terrain["name"], f"one cycle every {_clock(cycle)}" if cycle else "can be built here",
                        cycle or 0)
    found.sort(key=lambda f: f[0])
    return {"results": [r for _, r in found[:FIND_LIMIT]], "total": len(found)}


def housing_sources(state):
    """Where the city's housing comes from: [[name, places], ...]."""
    out = {"Starting camp": BASE_HOUSING}
    for tile in all_tiles(state):
        if tile["building"] and tile_housing(tile):
            name = BUILDINGS[tile["building"]]["name"]
            out[name] = out.get(name, 0) + tile_housing(tile)
    return [[k, v] for k, v in out.items()]


def growth_checks(state, housing):
    """What _meal needs before it adds a person, and whether each is met right now."""
    pop, food = state["population"], int(state["resources"]["food"])
    return [
        {"ok": food >= 2 * pop,
         "text": f"Food for the next meal with another meal to spare: {2 * pop} needed, {food} in store",
         "fix": "Make more food (farms, fishing docks, hunting lodges, pastures) or buy some on the market."},
        {"ok": pop < housing,
         "text": f"A free place to live: {pop} people, housing for {housing}",
         "fix": "Build more housing (huts, then houses and apartments) or add rooms to the homes you have."},
    ]


def summary(state):
    """One leaderboard row."""
    return {
        "name": state["name"],
        "tech": state["tech"],
        "tech_name": TECH_LEVELS[state["tech"]]["name"],
        "population": state["population"],
        "research": len(state["research"]),
        "areas": len(state["areas"]),
        "buildings": sum(1 for t in all_tiles(state) if t["building"]),
        "resources": {k: int(state["resources"].get(k, 0)) for k in RESOURCES},
    }
