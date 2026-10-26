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
without touching index.html. Player-to-player trading lives in market.py, and
beasts (eggs, missions and the bonuses they give) in beasts.py.
"""

import json
import math
import random
from contextlib import contextmanager
import re

import artifacts
import beasts
import cauldron
import ideology
import moderation
import weather

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
#   sheltered True - underground: day, night and weather make no difference here
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
    "savanna": {"name": "Savanna", "glyph": "'", "color": "#d6c46a", "weight": 3, "groups": ["plains"],
                "height": (1, 2), "fertility": (25, 55), "temp": 8,
                "boost": {"pasture": 1.3, "hunting_lodge": 1.2},
                "desc": "Hot, dry grassland dotted with trees. Thin soil for crops, but fine grazing and good hunting."},
    "steppe": {"name": "Steppe", "glyph": "-", "color": "#b9c48a", "weight": 3, "groups": ["plains"],
               "height": (1, 3), "fertility": (20, 45), "temp": -4,
               "boost": {"pasture": 1.2, "wind_turbine": 1.2},
               "desc": "Cold, windswept grass to the horizon. Poor for crops, good for herds and for wind turbines."},
    "taiga": {"name": "Pine Forest", "glyph": "\u2191", "color": "#4f8f7a", "weight": 2, "groups": ["forest"],
              "height": (1, 4), "fertility": (30, 55), "temp": -6,
              "boost": {"lumber_camp": 1.15, "sawmill": 1.15},
              "desc": "Cold evergreen forest. Straight, even timber that is quick to cut."},
    "jungle": {"name": "Jungle", "glyph": "\u2660", "color": "#2fae5a", "weight": 2, "groups": ["forest"],
               "height": (1, 4), "fertility": (70, 95), "temp": 8,
               "boost": {"hunting_lodge": 1.3, "shaman_hut": 1.2, "lumber_camp": 0.9},
               "desc": "Hot, wet and teeming with life. Hunters and shamans do well; the tangle slows logging."},
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
    "canyon": {"name": "Canyon", "glyph": "\u2261", "color": "#c98a5a",
               "from": "hill", "chance": 0.08, "groups": ["hill"],
               "height": (5, 7), "fertility": (0, 10), "temp": 4,
               "boost": {"quarry": 1.4, "mine": 1.3, "deep_mine": 1.3},
               "desc": "A gorge cut through layered rock. The seams are laid bare, so quarries and mines work much faster."},
    "mesa": {"name": "Mesa", "glyph": "\u2229", "color": "#d9a066",
             "from": "desert", "chance": 0.08, "groups": ["hill", "desert"],
             "height": (5, 8), "fertility": (0, 10), "temp": 8,
             "boost": {"observatory": 1.3, "wind_turbine": 1.3},
             "desc": "A flat-topped rock standing over the desert. High, dry and clear: ideal for observatories and wind turbines."},
    "lava_field": {"name": "Lava Field", "glyph": "\u2591", "color": "#c9584a",
                   "from": "hill", "chance": 0.03, "groups": ["hill"], "research": "volcanology",
                   "height": (4, 9), "fertility": (0, 0), "temp": 15,
                   "boost": {"quarry": 1.5, "mine": 1.4, "deep_mine": 1.4},
                   "desc": "Black rock, still warm underfoot. Rich in stone and ore, and a Geothermal Plant can stand on it."},
    # ---- land that forms beside its own kind (see _spread_terrain) ----
    "beach": {"name": "Beach", "glyph": "`", "color": "#f2e6b0",
              "spread_from": ["plains", "desert", "forest", "savanna"], "near": ["ocean"], "need": 1, "chance": 0.3,
              "groups": ["desert"],
              "height": (1, 1), "fertility": (0, 15), "temp": 3,
              "boost": {"glassworks": 1.2},
              "desc": "Sand where the land meets the ocean. Desert buildings can stand here, and later a Resort."},
    "mangrove": {"name": "Mangrove", "glyph": "\u00a5", "color": "#3f9f8a",
                 "spread_from": ["forest", "jungle", "swamp", "plains"], "near": ["ocean"], "need": 1, "chance": 0.2,
                 "groups": ["forest"],
                 "height": (1, 1), "fertility": (50, 80), "temp": 4,
                 "boost": {"hunting_lodge": 1.2, "lumber_camp": 0.85},
                 "desc": "Trees standing in the tide at the ocean's edge. Good hunting among the roots; awkward to log."},
    "coral_reef": {"name": "Coral Reef", "glyph": "\u00a4", "color": "#ff9fb0",
                   "spread_from": ["ocean"], "near": ["ocean"], "need": 3, "chance": 0.1,
                   "groups": ["water"],
                   "height": (0, 0), "fertility": (0, 0), "fish": (85, 100), "temp": 2,
                   "boost": {"fishing_dock": 1.2, "fishery": 1.2},
                   "desc": "Shallow sea crowded with fish: the best fishing water there is."},
    "bamboo": {"name": "Bamboo Grove", "glyph": "|", "color": "#a6d96a",
               "spread_from": ["forest", "jungle"], "near": ["river", "lake", "marsh"], "need": 1, "chance": 0.15,
               "groups": ["forest"],
               "height": (1, 2), "fertility": (60, 85), "temp": 3,
               "boost": {"lumber_camp": 1.5, "sawmill": 1.3},
               "desc": "Fast-growing cane by the water. It grows back as quickly as it is cut, so timber buildings are much faster."},
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
                    "desc": "Steaming pools heated from below. Only here: a Bath House and Spring Shrine early on, then a Thermal Fountain, heated greenhouses and fish farms, a Drying House and Spa Hotel, and at last a Deep Geothermal Well."},
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
               "boost": {"pasture": 1.4, "dairy": 1.3, "breeding_pen": 1.3},
               "desc": "Open flowering grassland. The best grazing there is: pastures and dairies work faster here."},
    # ---- added with the wider world: tundra, moors, caves, reefs, cliffs ----
    "tundra": {"name": "Tundra", "glyph": "°", "color": "#c8d8c8", "weight": 1, "groups": ["plains"],
               "height": (1, 3), "fertility": (5, 25), "temp": -10,
               "boost": {"hunting_lodge": 1.2, "forager_camp": 1.2, "shepherds_hut": 1.2},
               "desc": "Frozen ground under moss and lichen. Crops barely grow, but foragers, hunters and herders get by."},
    "scrubland": {"name": "Scrubland", "glyph": "¨", "color": "#c4b07a", "weight": 2, "groups": ["desert"],
                  "height": (1, 3), "fertility": (5, 30), "temp": 6,
                  "boost": {"forager_camp": 1.3, "ranch": 1.25},
                  "desc": "Dry bush and red earth. Desert buildings stand here; foragers and ranchers do well."},
    "cave": {"name": "Cave", "glyph": "◙", "color": "#8a7a6a",
             "from": "hill", "chance": 0.08, "groups": ["hill"], "sheltered": True,
             "height": (4, 7), "fertility": (0, 5), "temp": -4,
             "boost": {"mine": 1.2, "quarry": 1.1},
             "desc": "A cave mouth in the hillside. Day, night and weather never reach inside. Cave Dwellings and Mushroom Caves can be built here, and hill buildings too."},
    "heath": {"name": "Heath", "glyph": "∴", "color": "#b48ab0",
              "spread_from": ["plains", "foothills", "steppe"], "near": ["hill", "foothills"], "need": 1, "chance": 0.2,
              "groups": ["plains"],
              "height": (2, 4), "fertility": (15, 40), "temp": -2,
              "boost": {"pasture": 1.2, "apiary": 1.4, "shepherds_hut": 1.3},
              "desc": "Heather and gorse on high open ground. Poor for crops, loved by bees and sheep."},
    "floodplain": {"name": "Floodplain", "glyph": "÷", "color": "#7fb86a",
                   "spread_from": ["plains", "meadow", "marsh"], "near": ["river"], "need": 1, "chance": 0.35,
                   "groups": ["plains", "fresh"],
                   "height": (1, 1), "fertility": (85, 100), "temp": 1,
                   "boost": {"farm": 1.2, "irrigated_farm": 1.2, "rice_paddy": 1.2},
                   "desc": "Flat land the river floods each year, leaving rich silt behind. Superb farmland that waters the land around it."},
    "kelp_forest": {"name": "Kelp Forest", "glyph": "∫", "color": "#3f8f6f",
                    "spread_from": ["ocean"], "near": ["ocean"], "need": 2, "chance": 0.15,
                    "groups": ["water"],
                    "height": (0, 0), "fertility": (0, 0), "fish": (70, 95), "temp": -2,
                    "boost": {"fishery": 1.1, "fishing_dock": 1.1},
                    "desc": "Tall swaying weed under the waves, full of fish. Kelp can be gathered here for food."},
    "cliffs": {"name": "Sea Cliffs", "glyph": "¦", "color": "#a89a8a",
               "spread_from": ["hill", "foothills", "mountain"], "near": ["ocean"], "need": 1, "chance": 0.4,
               "groups": ["hill"],
               "height": (6, 9), "fertility": (0, 10), "temp": -2,
               "boost": {"wind_turbine": 1.3},
               "desc": "Rock walls over the sea, windy and high. Good for wind turbines, lookouts and weather stations."},
    "crystal_cavern": {"name": "Crystal Cavern", "glyph": "◊", "color": "#c08af0",
                       "spread_from": ["cave", "mountain"], "near": ["cave", "mountain"], "need": 1, "chance": 0.12,
                       "groups": ["hill"], "research": "crystallography", "sheltered": True,
                       "height": (8, 11), "fertility": (0, 0), "temp": -6,
                       "boost": {"deep_mine": 1.3},
                       "desc": "A hollow in the deep rock lined with crystal. Sheltered from all weather. A Crystal Mine can work it."},
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
    "electronics": "Electronics",
    "livestock": "Livestock",
    "knowledge": "Knowledge",
}
UNTRADEABLE = {"knowledge"}   # cannot be offered or asked for on the market

START_RESOURCES = {"food": 200, "wood": 100, "stone": 25, "livestock": 3}   # food for 5 hours of the 10 starting people
START_POPULATION = 10
BASE_HOUSING = 10           # people who can live in the starting camp
AREA_SIZE = 5
MAP_GROWTH_PER_TECH = 2     # the home area gains a ring of new land on each advance
DEGREES_PER_HEIGHT = 2      # temperature drop per height level
DEMOLISH_REFUND = 0.5
MAX_ADDITIONS = 2           # additions one building can carry

MEAL_TIME = 15 * MIN        # everyone eats 1 food this often; a fed city also gains 1 person
HUNGRY_SPEED = 0.5          # work speed of non-food buildings while the city is hungry
SIM_STEP = 60               # seconds of game time simulated per step when catching up...
LONG_STEP = 300             # ...or this, while more than LONG_CATCH_UP is still to go (a week away is then quick)
LONG_CATCH_UP = 6 * 3600

EXPEDITION_TIME = 20 * MIN  # travel time per step of distance from home
MAX_EXPEDITION_QUEUE = 5    # most expeditions that can wait for the one under way to come back
# Room in the queue comes from research and buildings with "exp_queue" (each adds that many places).
# What an expedition may bring back besides its map: (resource, least, most), per step of distance.
EXPEDITION_LOOT = [("food", 15, 40), ("wood", 15, 40), ("stone", 10, 30), ("gold", 5, 15),
                   ("livestock", 2, 5), ("knowledge", 3, 8)]
# What an expedition's supplies come to (see expedition_cost): the land's own food and wood, times
#   distance ** EXPEDITION_DISTANCE_POWER          further out costs more than in proportion,
#   1 + EXPEDITION_AREA_STEP * areas held           every area held or being explored makes the next one dearer,
#   1 + EXPEDITION_TECH_STEP * tech level           a bigger city sends a bigger team;
# plus pack animals (livestock), tools from Town on and gold from City on.
EXPEDITION_DISTANCE_POWER = 1.4
EXPEDITION_AREA_STEP = 0.25
EXPEDITION_TECH_STEP = 0.3
EXPEDITION_LIVESTOCK = (1.0, 0.3)  # pack animals per step of distance: this, and this more for every area held
EXPEDITION_TOOLS = 0.15            # tools, as a share of the food, from Town on
EXPEDITION_GOLD = 0.1              # gold, as a share of the food, from City on
EXPEDITION_LOOT_CHANCE = 0.7
FULL_EXPLORE_SPEED = 1.0    # buildings' expedition speed counts in full up to this (1.0 = twice as fast)...
EXPLORE_SPEED_STEP = 0.3    # ...and past it this much more for every doubling: see explore_speed()
EXPLORE_COST_WEIGHT = 1.5   # how hard the ideology's explore_cost cuts supplies: see explore_discount()
LIVESTOCK_FOR_FULL_SPEED = 10   # herd size at which "livestock_speed" buildings run at normal speed
WILDLIFE_TIME = 45 * MIN    # how often a new animal wanders into each area
MAX_WILDLIFE = 4            # wild animals an area holds at once
TAME_FOOD_PER_HEAD = 3      # food used as bait, per livestock the animal is worth
SLAUGHTER_FOOD = 6          # food from slaughtering one livestock by hand (a Butcher gets more)
AWAY_TIME = 5 * MIN         # unwatched for this long -> the player gets a "while you were away" report

# Index 0 is the starting level. The other entries say what it takes to advance
# *into* that level:
#   population  people the city must have
#   cost        resources paid
#   research    how many things the city must have researched (of any level)
#   areas       how many areas the city must own, counting home
# What each level asks for. Set in October 2026 from the leaderboard: a little below what cities a level lower
# already had (so no one settled there is stuck), with resources in step with what each level's research costs.
# Each level's cost includes livestock: the feast that marks the city's new standing.
TECH_LEVELS = [
    {"name": "Tribe"},
    {"name": "Village", "population": 18, "research": 4,
     "cost": {"food": 300, "wood": 500, "stone": 300, "knowledge": 150, "livestock": 4}},
    {"name": "Town", "population": 70, "research": 15, "areas": 3,
     "cost": {"wood": 1500, "stone": 1500, "ore": 500, "gold": 500, "knowledge": 600, "livestock": 15}},
    {"name": "City", "population": 250, "research": 30, "areas": 5,
     "cost": {"stone": 8000, "ore": 3000, "tools": 1500, "gold": 5000, "knowledge": 4000, "livestock": 50}},
    {"name": "Metropolis", "population": 700, "research": 50, "areas": 8,
     "cost": {"stone": 25000, "ore": 8000, "tools": 8000, "gold": 30000, "knowledge": 15000, "livestock": 150}},
    {"name": "Megacity", "population": 1600, "research": 70, "areas": 14,
     "cost": {"food": 50000, "tools": 25000, "electronics": 8000, "gold": 120000, "knowledge": 60000, "livestock": 400}},
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
#   unique         True - a city can only have one
#   beast_xp / beast_power / hatch_speed / egg_chance / mission_speed / nest   see beasts.py
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
#   sheltered      True - day, night and weather make no difference to it (indoors)
#   weather_groups extra groups it belongs to for day, night and weather (see weather.py)
#   night_shelter / weather_shelter   0.5 = night's (or the weather's) slowdowns halved
#                  across the whole city; 1.0 = gone
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
        "herd": 10, "per_head": {"food": 0.6}, "fertility_aura": 8,
        "modifiers": ["fertility"],
        "desc": "Keeps up to 10 of your livestock and farms them for food. Faster on fertile grass. Its manure adds +8 fertility to the 8 surrounding tiles.",
    },
    "salt_lick": {
        "name": "Salt Lick", "glyph": "l", "tech": 0, "category": "support",
        "terrain": ["plains", "forest"],
        "cost": {"wood": 5, "food": 20}, "wildlife_speed": 0.5,
        "desc": "Draws animals in from the wild: wildlife appears 50% more often in all your areas.",
    },
    "butcher": {
        "name": "Butcher", "glyph": "2", "tech": 0, "category": "food", "research": "animal_husbandry",
        "terrain": ["plains", "forest", "desert", "hill"],
        "cost": {"wood": 15}, "workers": 1, "time": 15 * MIN,
        "consumes": {"livestock": 1}, "produces": {"food": 14},
        "desc": "Turns livestock into meat: 14 food from each animal, more than twice what slaughtering by hand gives. Stops when the herd is gone.",
    },
    "beast_den": {
        "name": "Beast Den", "glyph": "d", "tech": 0, "category": "support", "research": "beast_lore", "unique": True,
        "terrain": ["plains", "forest", "hill", "desert"],
        "cost": {"wood": 25, "food": 20}, "beast_xp": 0.5,
        "desc": "A proper home for your beast. Missions give it 50% more experience. A city can have one.",
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
        "terrain": ["river", "lake", "marsh", "swamp"],
        "cost": {"wood": 8}, "workers": 1, "time": 12 * MIN, "produces": {"wood": 2},
        "modifiers": ["open_water"],
        "desc": "Cuts reeds and driftwood from fresh water, marsh or swamp: a source of wood without a forest.",
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
    # ---- wetland: marsh and swamp, something for every tech level ----
    "eel_traps": {
        "name": "Eel Traps", "glyph": "\u00f0", "tech": 0, "category": "food",
        "terrain": ["marsh", "swamp"],
        "cost": {"wood": 10}, "workers": 1, "time": 12 * MIN, "produces": {"food": 5},
        "desc": "Wicker traps sunk in the reeds. Eels, frogs and crayfish from land too wet to farm.",
    },
    "herb_fen": {
        "name": "Herb Fen", "glyph": "\u00f1", "tech": 2, "category": "knowledge",
        "terrain": ["marsh", "swamp"],
        "cost": {"wood": 60, "stone": 30, "gold": 20}, "workers": 2, "time": 20 * MIN, "produces": {"knowledge": 6, "gold": 4},
        "desc": "Healers gather and study the fen's herbs: knowledge, and remedies to sell.",
    },
    "bog_iron": {
        "name": "Bog Iron Works", "glyph": "\u00f8", "tech": 3, "category": "materials", "research": "metallurgy",
        "terrain": ["swamp", "marsh"],
        "cost": {"wood": 80, "stone": 100, "tools": 20}, "workers": 3, "time": 20 * MIN, "produces": {"ore": 7, "tools": 1},
        "desc": "Iron that settles in the bog, dredged up and smelted on the spot: ore, and a few tools.",
    },
    "cranberry_bog": {
        "name": "Cranberry Bog", "glyph": "\u00a2", "tech": 3, "category": "food", "research": "botany",
        "terrain": ["marsh"],
        "cost": {"wood": 100, "stone": 60, "tools": 15}, "workers": 3, "time": 12 * MIN, "produces": {"food": 18, "gold": 4},
        "modifiers": ["crop_temperature"],
        "desc": "Flooded at harvest so the berries float to the top: food, and a little gold from the jam.",
    },
    "biogas_plant": {
        "name": "Biogas Plant", "glyph": "\u00b1", "tech": 4, "category": "power", "research": "recycling",
        "terrain": ["marsh", "swamp"],
        "cost": {"stone": 200, "tools": 60, "gold": 80}, "workers": 2, "generates": 12,
        "desc": "Domes over the rotting reeds catch the marsh gas and burn it: power with no fuel to buy.",
    },
    "wetland_reserve": {
        "name": "Wetland Reserve", "glyph": "\u00e6", "tech": 4, "category": "trade",
        "terrain": ["marsh", "swamp"],
        "cost": {"wood": 200, "stone": 150, "gold": 250}, "workers": 3, "time": 20 * MIN,
        "produces": {"gold": 26, "knowledge": 6}, "attracts": 1, "wildlife_speed": 0.3,
        "desc": "Boardwalks, hides and a visitor centre: gold and knowledge, one more arrival per meal, and wild animals come more often.",
    },
    "algae_bioreactor": {
        "name": "Algae Bioreactor", "glyph": "\u00fe", "tech": 5, "category": "food", "power": 4, "research": "hydroponics",
        "terrain": ["marsh", "swamp"],
        "cost": {"stone": 400, "tools": 150, "electronics": 80, "gold": 400}, "workers": 4, "time": 12 * MIN,
        "produces": {"food": 48, "gold": 16},
        "desc": "Clear tubes of green algae fed by the marsh water: a great deal of food, and gold from what is sold on.",
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
    "chicken_coop": {
        "name": "Chicken Coop", "glyph": "\u00e7", "tech": 0, "category": "food", "research": "animal_taming",
        "terrain": ["plains", "forest", "savanna", "meadow"],
        "cost": {"wood": 25}, "workers": 1, "time": 45 * MIN,
        "consumes": {"food": 5}, "produces": {"livestock": 1},
        "desc": "Hens and a fence: 1 head of livestock from 5 food, slowly. The first steady supply before Selective Breeding.",
    },
    "breeding_pen": {
        "name": "Breeding Pen", "glyph": "{", "tech": 1, "category": "food", "research": "selective_breeding",
        "terrain": ["plains"],
        "cost": {"wood": 35}, "workers": 1, "time": 30 * MIN,
        "consumes": {"food": 6}, "produces": {"livestock": 1},
        "modifiers": ["fertility"],
        "desc": "Raises new livestock on feed: 1 animal from 6 food. A steady supply that does not depend on finding wildlife. Faster on fertile grass.",
    },
    "incubator": {
        "name": "Incubator", "glyph": "o", "tech": 1, "category": "support", "research": "incubation", "unique": True,
        "terrain": ["plains", "forest", "hill", "desert"],
        "cost": {"wood": 30, "stone": 30}, "hatch_speed": 1.0, "egg_chance": 0.05,
        "desc": "Warm, turned and watched: eggs hatch twice as fast, and expedition teams who know what to look for are 5 points likelier to bring one home. A city can have one.",
    },
    "nesting_ground": {
        "name": "Nesting Ground", "glyph": "\u03b7", "tech": 1, "category": "support", "research": "incubation", "unique": True,
        "terrain": ["plains", "forest", "hill"],
        "cost": {"wood": 60, "food": 80, "livestock": 2}, "nest": 1,
        "desc": "Sheltered ground where wild beasts come to lay. Every 2 days an egg is left here, usually a common one, unless the city already has 3 eggs waiting to hatch. A city can have one.",
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
    "leatherworks": {
        "name": "Leatherworks", "glyph": "\u00a3", "tech": 2, "category": "trade", "research": "tanning",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"wood": 60, "stone": 40, "ore": 10}, "workers": 2, "time": 25 * MIN,
        "consumes": {"livestock": 2}, "produces": {"tools": 3, "gold": 12},
        "modifiers": ["adjacent_water"],
        "desc": "Saddles, belts and harness from your herd: 2 livestock become tools and gold. Faster next to fresh water.",
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
    "cattle_market": {
        "name": "Cattle Market", "glyph": "]", "tech": 2, "category": "trade", "research": "bookkeeping",
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"wood": 60, "stone": 40}, "workers": 2, "time": 20 * MIN, "produces": {"gold": 12},
        "livestock_speed": True,
        "desc": "Shows, auctions and stud fees: gold from owning a fine herd, without selling it. Works faster the more livestock the city owns: normal speed at 10. Needs flat ground.",
    },
    "training_ground": {
        "name": "Training Ground", "glyph": "g", "tech": 2, "category": "support", "research": "beast_training", "unique": True,
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"wood": 80, "stone": 60, "gold": 40}, "beast_power": 0.25,
        "desc": "Where a beast learns to work with the city: its bonus is 25% stronger. Needs flat ground. A city can have one.",
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
        "terrain": ["hot_springs", "volcanic", "lava_field"],
        "cost": {"stone": 120, "tools": 25}, "workers": 2, "generates": 14,
        "desc": "Power from the heat underground, with no fuel. Only on hot springs or a volcanic plain.",
    },
    "zoo": {
        "name": "Zoo", "glyph": "[", "tech": 3, "category": "trade", "power": 2,
        "terrain": ["plains", "forest"],
        "cost": {"stone": 120, "gold": 80, "livestock": 8}, "workers": 3, "time": 20 * MIN, "produces": {"gold": 20},
        "livestock_speed": True, "attracts": 1,
        "desc": "People come from far away to see the animals: gold, and one extra arrival per meal. Works faster the more livestock the city owns: normal speed at 10. Costs 8 livestock to stock.",
    },
    "resort": {
        "name": "Resort", "glyph": "}", "tech": 3, "category": "trade", "power": 3,
        "terrain": ["beach"],
        "cost": {"wood": 80, "stone": 120, "gold": 100}, "workers": 4, "time": 20 * MIN, "produces": {"gold": 26},
        "housing": 4, "attracts": 1,
        "desc": "Hotels along a beach. Earns gold, has rooms for 4, and brings one extra arrival per meal.",
    },
    "beast_sanctuary": {
        "name": "Beast Sanctuary", "glyph": "a", "tech": 3, "category": "support", "research": "beast_bonding", "unique": True,
        "terrain": ["plains", "forest"],
        "cost": {"stone": 150, "tools": 30, "gold": 150}, "mission_speed": 0.5, "beast_xp": 0.25,
        "desc": "Quiet ground set aside for your beast. Missions come 50% more often and give 25% more experience. A city can have one.",
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
        "sheltered": True,
        "desc": "Heated glass houses that grow food anywhere, whatever the soil, weather or time of day.",
    },
    "laboratory": {
        "name": "Laboratory", "glyph": "J", "tech": 3, "category": "knowledge", "power": 5, "research": "scientific_method",
        "terrain": ["plains", "desert"],
        "cost": {"stone": 100, "tools": 25, "gold": 80}, "workers": 4, "time": 20 * MIN,
        "produces": {"knowledge": 30},
        "desc": "Experiments on an industrial scale.",
    },
    "townhouses": {
        "name": "Townhouses", "glyph": "b", "tech": 3, "category": "housing",
        "terrain": ["plains", "forest", "hill", "desert"],
        "cost": {"wood": 60, "stone": 80, "tools": 10}, "housing": 10,
        "desc": "Tall narrow homes in a row. Fewer rooms than apartments, but they fit on hills and in forest.",
    },
    "city_hall": {
        "name": "City Hall", "glyph": "c", "tech": 3, "category": "support", "research": "civil_service", "unique": True,
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 300, "tools": 40, "gold": 300}, "housing": 2, "attracts": 2,
        "speed_aura": {"for": ["trading_post", "department_store", "museum", "school", "university"], "bonus": 0.15},
        "desc": "A well-run city draws people: two extra arrivals per meal, and shops and places of learning on the 8 surrounding tiles work 15% faster. A city can have one.",
    },
    "train_station": {
        "name": "Train Station", "glyph": "e", "tech": 3, "category": "support", "research": "railways",
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 250, "ore": 120, "tools": 60, "gold": 150}, "explore_speed": 0.3, "attracts": 1,
        "speed_aura": {"for": ["factory", "steel_mill", "cement_works", "timber_yard", "cannery", "deep_mine", "mine"], "bonus": 0.15},
        "desc": "Expeditions travel 30% faster, one extra person arrives per meal, and industry on the 8 surrounding tiles works 15% faster with goods wagons at the door. Needs flat ground.",
    },
    "ferry_terminal": {
        "name": "Ferry Terminal", "glyph": "k", "tech": 3, "category": "support", "research": "railways",
        "terrain": ["river", "lake", "ocean"], "min_temp": 1,
        "cost": {"wood": 120, "stone": 80, "tools": 30}, "explore_speed": 0.15, "attracts": 1,
        "desc": "Regular boats on a river, lake or ocean. Expeditions travel 15% faster and one extra person arrives per meal.",
    },
    "waterworks": {
        "name": "Waterworks", "glyph": "r", "tech": 3, "category": "support", "research": "sanitation",
        "terrain": ["plains", "desert", "hill"], "adjacent": "fresh",
        "cost": {"stone": 180, "ore": 40, "tools": 30}, "fertility_aura": 30,
        "desc": "Pumps and pipes beside fresh water. Adds +30 fertility to the 8 surrounding tiles.",
    },
    "steel_mill": {
        "name": "Steel Mill", "glyph": "(", "tech": 3, "category": "materials", "power": 6, "research": "steelmaking",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 200, "ore": 80, "tools": 30, "gold": 80}, "workers": 5, "time": 20 * MIN,
        "consumes": {"ore": 12}, "produces": {"tools": 10}, "modifiers": ["near_mine"],
        "desc": "Turns ore straight into tools, with no wood. Faster next to a mine.",
    },
    "cement_works": {
        "name": "Cement Works", "glyph": "σ", "tech": 3, "category": "materials", "power": 4, "research": "concrete",
        "terrain": ["hill"],
        "cost": {"stone": 100, "tools": 25, "gold": 40}, "workers": 4, "time": 15 * MIN,
        "produces": {"stone": 16}, "modifiers": ["height"],
        "desc": "Burns and crushes rock into building stone on a scale no quarry can match. Faster on higher hills.",
    },
    "timber_yard": {
        "name": "Timber Yard", "glyph": "α", "tech": 3, "category": "materials", "power": 4, "research": "forestry",
        "terrain": ["forest"],
        "cost": {"wood": 80, "stone": 60, "tools": 25}, "workers": 4, "time": 12 * MIN,
        "produces": {"wood": 20}, "modifiers": ["deep_forest"],
        "desc": "Powered saws and managed woodland. Faster with more forest around it.",
    },
    "cannery": {
        "name": "Cannery", "glyph": "β", "tech": 3, "category": "food", "power": 3, "research": "canning",
        "terrain": ["plains", "desert"],
        "cost": {"stone": 100, "ore": 40, "tools": 20}, "workers": 3, "time": 15 * MIN,
        "consumes": {"livestock": 2}, "produces": {"food": 34, "gold": 6},
        "desc": "Tins meat so none of it spoils: 2 livestock become far more food than a butcher gets, with gold from what is sold on.",
    },
    "stockyard": {
        "name": "Stockyard", "glyph": "\u00a5", "tech": 3, "category": "food", "research": "selective_breeding",
        "terrain": ["plains", "savanna", "meadow", "scrubland"],
        "cost": {"wood": 80, "stone": 120, "gold": 60}, "workers": 3, "time": 30 * MIN,
        "consumes": {"food": 20}, "produces": {"livestock": 4},
        "modifiers": ["fertility"],
        "desc": "Pens and feed lots on a large scale: 4 livestock from 20 food. Faster on fertile grass.",
    },
    "coal_plant": {
        "name": "Coal Power Station", "glyph": "δ", "tech": 3, "category": "power", "research": "steam_turbines",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 200, "ore": 80, "tools": 40}, "workers": 4, "generates": 32,
        "time": 15 * MIN, "consumes": {"ore": 5},
        "desc": "Burns ore from the mines for more power than a wood-fired plant, and can stand on hills.",
    },
    "tidal_generator": {
        "name": "Tidal Generator", "glyph": "λ", "tech": 3, "category": "power", "research": "steam_turbines",
        "terrain": ["ocean"],
        "cost": {"stone": 150, "ore": 40, "tools": 30}, "workers": 1, "generates": 9,
        "desc": "Power from the tide, with no fuel. Only on the ocean.",
    },
    "department_store": {
        "name": "Department Store", "glyph": "μ", "tech": 3, "category": "trade", "power": 3,
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 150, "tools": 30, "gold": 120}, "workers": 4, "time": 20 * MIN,
        "produces": {"gold": 22}, "modifiers": ["customers"],
        "desc": "Several floors of shopping. Needs flat ground; faster with homes next to it.",
    },
    "stadium": {
        "name": "Stadium", "glyph": "π", "tech": 3, "category": "trade", "power": 4, "unique": True,
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 400, "tools": 60, "gold": 250}, "workers": 5, "time": 20 * MIN,
        "produces": {"gold": 34}, "attracts": 1, "modifiers": ["customers"],
        "desc": "Match days fill the tills and the city's name travels: gold, and one extra arrival per meal. Faster with homes next to it. A city can have one.",
    },
    "museum": {
        "name": "Museum", "glyph": "ω", "tech": 3, "category": "knowledge", "power": 2, "research": "public_education",
        "terrain": ["plains", "desert"],
        "cost": {"stone": 180, "tools": 20, "gold": 150}, "workers": 3, "time": 20 * MIN,
        "produces": {"knowledge": 12, "gold": 8}, "modifiers": ["customers"],
        "desc": "What the city has learned, on show. Knowledge and gold; faster with homes next to it.",
    },
    # ---- Metropolis ----
    "high_rise": {
        "name": "High-Rise", "glyph": "\u03a0", "tech": 4, "category": "housing",
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 300, "tools": 60, "gold": 150}, "housing": 30,
        "desc": "A steel and glass tower of flats. Needs flat ground.",
    },
    "livestock_complex": {
        "name": "Livestock Complex", "glyph": "\u00a7", "tech": 4, "category": "food", "power": 4, "research": "mechanised_farming",
        "terrain": ["plains", "savanna", "meadow", "scrubland", "desert"],
        "cost": {"stone": 300, "tools": 100, "gold": 200}, "workers": 4, "time": 30 * MIN,
        "consumes": {"food": 45, "electronics": 1}, "produces": {"livestock": 10},
        "desc": "Climate-controlled barns and automatic feeders: 10 livestock from 45 food and a little electronics.",
    },
    "meat_packing": {
        "name": "Meat Packing Plant", "glyph": "\u00b5", "tech": 4, "category": "food", "power": 4, "research": "canning",
        "terrain": ["plains", "desert"],
        "cost": {"stone": 300, "ore": 100, "tools": 80}, "workers": 4, "time": 20 * MIN,
        "consumes": {"livestock": 4}, "produces": {"food": 110, "gold": 20},
        "desc": "Cuts, packs and chills on an industrial line: 4 livestock become a great deal of food, and gold from what is sold on.",
    },
    "hospital": {
        "name": "Hospital", "glyph": "8", "tech": 4, "category": "support", "research": "modern_medicine",
        "terrain": ["plains", "desert"],
        "cost": {"stone": 250, "tools": 80, "gold": 300}, "housing": 4, "attracts": 2,
        "desc": "People move to where they will be looked after: two extra arrivals per meal.",
    },
    "industrial_farm": {
        "name": "Industrial Farm", "glyph": "\u0393", "tech": 4, "category": "food", "power": 5, "research": "mechanised_farming",
        "terrain": ["plains"], "max_height": 2, "min_fertility": 40,
        "cost": {"stone": 100, "tools": 80, "gold": 100}, "workers": 3, "time": 12 * MIN, "produces": {"food": 34},
        "modifiers": ["fertility", "crop_temperature", "adjacent_water"],
        "desc": "Tractors, combines and fertiliser: a farm that feeds a district with three workers.",
    },
    "open_pit_mine": {
        "name": "Open-Pit Mine", "glyph": "\u00df", "tech": 4, "category": "materials", "power": 6,
        "terrain": ["hill", "mountain", "mesa", "canyon", "foothills", "desert"],
        "cost": {"stone": 400, "tools": 150, "gold": 200}, "workers": 5, "time": 20 * MIN,
        "produces": {"ore": 30, "stone": 10},
        "desc": "Giant diggers working a whole hillside at once: a great deal of ore, and stone as it comes out.",
    },
    "aggregate_plant": {
        "name": "Aggregate Plant", "glyph": "\u00a9", "tech": 4, "category": "materials", "power": 5,
        "terrain": ["hill", "mountain", "cliffs", "canyon", "foothills", "desert"],
        "cost": {"stone": 300, "tools": 120, "gold": 150}, "workers": 4, "time": 15 * MIN,
        "produces": {"stone": 36},
        "desc": "Crushes rock into building stone by the trainload.",
    },
    "precision_works": {
        "name": "Precision Works", "glyph": "\u00ae", "tech": 4, "category": "materials", "power": 8,
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 300, "tools": 150, "gold": 300}, "workers": 4, "time": 20 * MIN,
        "consumes": {"ore": 10}, "produces": {"tools": 20},
        "desc": "Machines that make machine parts: many more tools from the same ore.",
    },
    "deep_core_drill": {
        "name": "Deep Core Drill", "glyph": "\u00b6", "tech": 5, "category": "materials", "power": 25,
        "terrain": ["hill", "mountain", "mesa", "canyon", "foothills", "desert", "plains"],
        "cost": {"stone": 800, "tools": 400, "electronics": 150, "gold": 800}, "workers": 4, "time": 20 * MIN,
        "produces": {"ore": 60, "stone": 30},
        "desc": "Drills miles down, to where the ore is purest: ore and stone in great amounts.",
    },
    "electronics_plant": {
        "name": "Electronics Plant", "glyph": "\u039e", "tech": 4, "category": "materials", "power": 8, "research": "semiconductors",
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 250, "tools": 120, "gold": 250}, "workers": 6, "time": 20 * MIN,
        "consumes": {"ore": 8, "tools": 2}, "produces": {"electronics": 8},
        "desc": "Makes electronics from ore and tools. Everything in a Megacity is built with them.",
    },
    "recycling_centre": {
        "name": "Recycling Centre", "glyph": "3", "tech": 4, "category": "materials", "power": 4, "research": "recycling",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 150, "tools": 60}, "workers": 4, "time": 15 * MIN,
        "produces": {"ore": 6, "wood": 6, "stone": 6},
        "modifiers": ["customers"],
        "desc": "Recovers ore, wood and stone from what the city throws away. Faster with homes next to it.",
    },
    "shopping_mall": {
        "name": "Shopping Mall", "glyph": "\u03a3", "tech": 4, "category": "trade", "power": 6,
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 300, "tools": 80, "gold": 200}, "workers": 6, "time": 20 * MIN, "produces": {"gold": 36},
        "modifiers": ["customers"],
        "desc": "Shops under one roof. Needs flat ground; faster with homes next to it.",
    },
    "container_port": {
        "name": "Container Port", "glyph": "\u0394", "tech": 4, "category": "trade", "power": 8, "research": "container_shipping",
        "terrain": ["ocean", "lake"], "min_temp": 1,
        "cost": {"stone": 400, "tools": 150, "gold": 300}, "workers": 6, "time": 20 * MIN,
        "produces": {"gold": 45, "food": 12},
        "modifiers": ["open_water"],
        "desc": "Cranes and container ships on a lake or ocean. Faster on bigger water.",
    },
    "research_institute": {
        "name": "Research Institute", "glyph": "\u03a6", "tech": 4, "category": "knowledge", "power": 8, "research": "computing",
        "terrain": ["plains", "desert"],
        "cost": {"stone": 300, "tools": 120, "gold": 400}, "workers": 6, "time": 20 * MIN,
        "produces": {"knowledge": 70},
        "desc": "Computers and specialists. Needed for Megacity research.",
    },
    "solar_farm": {
        "name": "Solar Farm", "glyph": "\u0398", "tech": 4, "category": "power", "research": "photovoltaics",
        "terrain": ["plains", "desert"],
        "cost": {"stone": 150, "tools": 100, "gold": 150}, "workers": 1, "generates": 20,
        "generates_modifiers": ["sunlight"],
        "desc": "Fields of panels with no fuel. Gives more the hotter the tile: best in deserts, poor in the cold.",
    },
    "nuclear_plant": {
        "name": "Nuclear Plant", "glyph": "\u03a8", "tech": 4, "category": "power", "research": "nuclear_fission",
        "terrain": ["plains", "desert"], "max_height": 2, "adjacent": "water",
        "cost": {"stone": 800, "tools": 300, "gold": 600}, "workers": 6, "generates": 80,
        "time": 30 * MIN, "consumes": {"ore": 5},
        "desc": "A great deal of power from a little ore. Must be on flat ground next to water for cooling.",
    },
    "airport": {
        "name": "Airport", "glyph": "\u039b", "tech": 4, "category": "support", "research": "aviation",
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 500, "tools": 150, "gold": 400}, "explore_speed": 0.5, "attracts": 1,
        "desc": "Expeditions travel 50% faster, and one extra person arrives per meal. Needs flat ground.",
    },
    # ---- Megacity ----
    "arcology": {
        "name": "Arcology", "glyph": "\u03a9", "tech": 5, "category": "housing",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 800, "tools": 200, "electronics": 120, "gold": 600}, "housing": 90,
        "desc": "A whole neighbourhood in one building, with its own streets, parks and shops.",
    },
    "vertical_farm": {
        "name": "Vertical Farm", "glyph": "4", "tech": 5, "category": "food", "power": 12, "research": "hydroponics",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 300, "tools": 100, "electronics": 60}, "workers": 3, "time": 12 * MIN, "produces": {"food": 70},
        "sheltered": True,
        "desc": "Floor upon floor of crops under lamps, anywhere, whatever the soil, weather or time of day.",
    },
    "robotics_factory": {
        "name": "Robotics Factory", "glyph": "7", "tech": 5, "category": "materials", "power": 20, "research": "robotics",
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 500, "tools": 200, "electronics": 100, "gold": 500}, "workers": 3, "time": 20 * MIN,
        "consumes": {"ore": 14}, "produces": {"tools": 20, "electronics": 6},
        "desc": "Machines building machines: tools and electronics from ore, with hardly any workers.",
    },
    "drone_port": {
        "name": "Drone Port", "glyph": "<", "tech": 5, "category": "trade", "power": 12, "research": "autonomous_logistics",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 300, "tools": 100, "electronics": 80}, "workers": 3, "time": 20 * MIN, "produces": {"gold": 80},
        "modifiers": ["customers"],
        "desc": "Deliveries by air to every door. Faster with homes next to it.",
    },
    "data_centre": {
        "name": "Data Centre", "glyph": "9", "tech": 5, "category": "knowledge", "power": 25, "research": "machine_learning",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 400, "tools": 150, "electronics": 150, "gold": 500}, "workers": 3, "time": 20 * MIN,
        "produces": {"knowledge": 180},
        "modifiers": ["cooling"],
        "desc": "Racks of machines that learn. Runs faster on a cold tile, slower on a hot one.",
    },
    "tidal_array": {
        "name": "Tidal Array", "glyph": ">", "tech": 5, "category": "power", "research": "offshore_energy",
        "terrain": ["ocean"],
        "cost": {"stone": 300, "tools": 150, "electronics": 60}, "workers": 1, "generates": 45,
        "desc": "Turbines on the sea bed, turned by the tide. No fuel.",
    },
    "fusion_plant": {
        "name": "Fusion Plant", "glyph": "5", "tech": 5, "category": "power", "research": "fusion_power",
        "terrain": ["plains", "desert"], "max_height": 2, "adjacent": "water",
        "cost": {"stone": 1500, "tools": 500, "electronics": 400, "gold": 2000}, "workers": 6, "generates": 250,
        "desc": "The power of the sun, from water. No fuel. Must be on flat ground next to water.",
    },
    "desalination_plant": {
        "name": "Desalination Plant", "glyph": "?", "tech": 5, "category": "support", "research": "desalination",
        "terrain": ["plains", "desert"], "adjacent": "ocean",
        "cost": {"stone": 300, "tools": 100, "electronics": 50}, "fertility_aura": 35,
        "desc": "Turns sea water fresh. Built on land beside the ocean; adds +35 fertility to the 8 surrounding tiles.",
    },
    "maglev_hub": {
        "name": "Maglev Hub", "glyph": "1", "tech": 5, "category": "support", "research": "maglev",
        "terrain": ["plains", "desert"], "max_height": 2,
        "cost": {"stone": 600, "tools": 200, "electronics": 150, "gold": 800}, "explore_speed": 0.5, "attracts": 2,
        "speed_aura": {"for": ["shopping_mall", "drone_port", "trading_post", "research_institute", "data_centre"], "bonus": 0.2},
        "desc": "Floating trains. Expeditions travel 50% faster, two extra people arrive per meal, and shops and research on the 8 surrounding tiles work 20% faster.",
    },
    # ---- the wider world: caves, moors, reefs, ice, and shelter from the weather ----
    "cave_dwelling": {
        "name": "Cave Dwelling", "glyph": "κ", "tech": 0, "category": "housing",
        "terrain": ["cave"],
        "cost": {"wood": 10}, "housing": 5,
        "desc": "A dry cave with a fire at the back. Houses 5, and costs almost nothing.",
    },
    "forager_camp": {
        "name": "Forager's Camp", "glyph": "ε", "tech": 0, "category": "food",
        "terrain": ["heath", "scrubland", "tundra", "meadow", "savanna", "steppe"],
        "cost": {"wood": 10}, "workers": 1, "time": 10 * MIN, "produces": {"food": 3, "wood": 1},
        "weather_groups": ["crops"],
        "desc": "Gathers berries, roots and kindling from open land where farms do poorly. Works by daylight.",
    },
    "apiary": {
        "name": "Apiary", "glyph": "ζ", "tech": 1, "category": "food", "research": "beekeeping",
        "terrain": ["meadow", "heath", "plains", "forest"],
        "cost": {"wood": 25}, "workers": 1, "time": 15 * MIN, "produces": {"food": 4, "gold": 2},
        "speed_aura": {"for": ["farm", "orchard", "irrigated_farm", "terrace_farm"], "bonus": 0.1},
        "weather_groups": ["crops"],
        "desc": "Hives of bees: honey and wax to sell, and the farms and orchards on the 8 tiles around it work 10% faster. Bees only fly by day.",
    },
    "mushroom_cave": {
        "name": "Mushroom Cave", "glyph": "ν", "tech": 1, "category": "food", "research": "caving",
        "terrain": ["cave"],
        "cost": {"wood": 30, "stone": 10}, "workers": 2, "time": 12 * MIN, "produces": {"food": 8},
        "desc": "Beds of mushrooms in the dark. Never troubled by night or weather.",
    },
    "kelp_gatherers": {
        "name": "Kelp Gatherers", "glyph": "ψ", "tech": 1, "category": "food",
        "terrain": ["kelp_forest"],
        "cost": {"wood": 25}, "workers": 1, "time": 12 * MIN, "produces": {"food": 5},
        "modifiers": ["fish"],
        "desc": "Small boats cutting kelp and netting the fish that live in it. Faster with more fish.",
    },
    "lookout_tower": {
        "name": "Lookout Tower", "glyph": "ι", "tech": 1, "category": "support",
        "terrain": ["cliffs", "mountain", "mesa", "hill"], "min_height": 6,
        "cost": {"wood": 40, "stone": 30}, "explore_speed": 0.1, "wildlife_speed": 0.15,
        "desc": "A tall tower on high ground. Expeditions travel 10% faster and wild animals are spotted 15% more often.",
    },
    "shepherds_hut": {
        "name": "Shepherd's Hut", "glyph": "χ", "tech": 1, "category": "food", "research": "animal_husbandry",
        "terrain": ["heath", "steppe", "tundra", "foothills"],
        "cost": {"wood": 25, "stone": 10}, "workers": 1, "time": 15 * MIN, "housing": 2,
        "herd": 6, "per_head": {"food": 0.5},
        "desc": "A hut on rough grazing. Houses 2, keeps up to 6 of your livestock and farms them for food.",
    },
    "weather_station": {
        "name": "Weather Station", "glyph": "τ", "tech": 2, "category": "knowledge", "research": "meteorology",
        "terrain": ["hill", "mountain", "cliffs", "mesa", "tundra", "plains"],
        "cost": {"wood": 40, "stone": 40, "ore": 15}, "workers": 2, "time": 20 * MIN, "produces": {"knowledge": 8},
        "modifiers": ["height"], "weather_groups": ["weather_watch"],
        "desc": "Gauges, vanes and a log book. Learns fastest in wild weather, and higher up.",
    },
    "night_market": {
        "name": "Night Market", "glyph": "ρ", "tech": 2, "category": "trade", "research": "street_lighting",
        "terrain": ["plains", "desert", "scrubland"],
        "cost": {"wood": 60, "stone": 30, "gold": 30}, "workers": 3, "time": 15 * MIN, "produces": {"gold": 11},
        "modifiers": ["customers"], "weather_groups": ["after_dark"],
        "desc": "Lantern-lit stalls that open at dusk: slow by day, very busy at night. Faster with homes next to it.",
    },
    "pearl_divers": {
        "name": "Pearl Divers", "glyph": "φ", "tech": 2, "category": "trade", "research": "pearl_diving",
        "terrain": ["coral_reef", "kelp_forest"],
        "cost": {"wood": 50, "stone": 20, "gold": 20}, "workers": 2, "time": 20 * MIN, "produces": {"gold": 14},
        "modifiers": ["fish"],
        "desc": "Divers bring up pearls from the reef. Faster in richer water.",
    },
    "bamboo_workshop": {
        "name": "Bamboo Workshop", "glyph": "θ", "tech": 2, "category": "materials",
        "terrain": ["bamboo"],
        "cost": {"wood": 40, "stone": 20}, "workers": 2, "time": 15 * MIN, "produces": {"wood": 6, "tools": 2},
        "desc": "Cuts and splits cane into poles, mats and simple tools.",
    },
    "ice_works": {
        "name": "Ice Works", "glyph": "υ", "tech": 2, "category": "trade",
        "terrain": ["glacier", "tundra"],
        "cost": {"wood": 50, "stone": 40}, "workers": 2, "time": 20 * MIN, "produces": {"gold": 8, "food": 4},
        "weather_groups": ["ice"],
        "desc": "Cuts ice to sell and to keep food fresh. Sells best in a heatwave.",
    },
    "ranch": {
        "name": "Ranch", "glyph": "γ", "tech": 2, "category": "food", "research": "selective_breeding",
        "terrain": ["scrubland", "savanna", "steppe"],
        "cost": {"wood": 60, "stone": 20}, "workers": 2, "time": 15 * MIN,
        "herd": 20, "per_head": {"food": 0.5, "gold": 0.1},
        "desc": "Wide open range for a big herd: keeps up to 20 of your livestock, for food and a little gold.",
    },
    "crystal_mine": {
        "name": "Crystal Mine", "glyph": "ξ", "tech": 3, "category": "materials", "power": 3, "research": "crystallography",
        "terrain": ["crystal_cavern"],
        "cost": {"stone": 150, "tools": 40, "gold": 60}, "workers": 4, "time": 25 * MIN,
        "produces": {"gold": 18, "knowledge": 5},
        "desc": "Cuts crystal for jewellers and lens makers. Sheltered from all weather.",
    },
    "ski_resort": {
        "name": "Ski Resort", "glyph": "♦", "tech": 3, "category": "trade", "power": 2, "research": "alpine_sports",
        "terrain": ["glacier", "mountain"],
        "cost": {"wood": 150, "stone": 150, "gold": 120}, "workers": 4, "time": 20 * MIN,
        "produces": {"gold": 24}, "attracts": 1, "weather_groups": ["snow_sports"],
        "desc": "Lifts, lodges and slopes: gold, and one extra arrival per meal. Busiest in fresh snow; closed in a blizzard.",
    },
    "aquarium": {
        "name": "Aquarium", "glyph": "@", "tech": 3, "category": "trade", "power": 2, "research": "marine_biology",
        "terrain": ["beach", "plains"], "adjacent": "ocean",
        "cost": {"stone": 160, "tools": 30, "gold": 120}, "workers": 3, "time": 20 * MIN,
        "produces": {"gold": 18, "knowledge": 4}, "attracts": 1, "sheltered": True,
        "desc": "Tanks of reef fish by the sea: gold, a little knowledge and one extra arrival per meal. Indoors, so the weather does not matter.",
    },
    "kelp_farm": {
        "name": "Kelp Farm", "glyph": "/", "tech": 3, "category": "food", "power": 1, "research": "marine_biology",
        "terrain": ["kelp_forest", "ocean"],
        "cost": {"wood": 80, "stone": 40, "tools": 15}, "workers": 3, "time": 12 * MIN, "produces": {"food": 18},
        "modifiers": ["fish"],
        "desc": "Lines of kelp grown and harvested at sea. Faster in rich water.",
    },
    "biodome": {
        "name": "Biodome", "glyph": "%", "tech": 4, "category": "food", "power": 6, "research": "climate_engineering",
        "terrain": ["tundra", "glacier", "desert", "scrubland", "sand_dunes", "salt_flat"],
        "cost": {"stone": 300, "tools": 100, "gold": 150}, "workers": 3, "time": 15 * MIN, "produces": {"food": 34},
        "sheltered": True,
        "desc": "A sealed dome with its own climate, for land nothing else will grow on. Weather and night make no difference.",
    },
    "storm_barrier": {
        "name": "Storm Barrier", "glyph": "#", "tech": 4, "category": "support", "research": "climate_engineering", "unique": True,
        "terrain": ["plains", "hill", "cliffs", "beach"],
        "cost": {"stone": 1200, "tools": 300, "gold": 600}, "weather_shelter": 0.5,
        "desc": "Walls, drains and wind breaks around the whole city: every slowdown the weather causes is halved. A city can have one.",
    },
    "planetarium": {
        "name": "Planetarium", "glyph": "^", "tech": 4, "category": "knowledge", "power": 5, "research": "astrophysics",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 300, "tools": 100, "gold": 250}, "workers": 4, "time": 20 * MIN,
        "produces": {"knowledge": 40}, "attracts": 1, "weather_groups": ["stargazing"],
        "desc": "A dome of stars: knowledge, and one extra arrival per meal. Busiest at night and under a sky full of wonders.",
    },
    "theme_park": {
        "name": "Theme Park", "glyph": "~", "tech": 4, "category": "trade", "power": 8, "unique": True,
        "terrain": ["plains", "beach"],
        "cost": {"stone": 600, "tools": 200, "gold": 800}, "workers": 6, "time": 20 * MIN,
        "produces": {"gold": 70}, "attracts": 2, "modifiers": ["customers"],
        "desc": "Rides, shows and fireworks after dark: gold, and two extra arrivals per meal. A city can have one.",
    },
    "offshore_wind": {
        "name": "Offshore Wind Farm", "glyph": "|", "tech": 4, "category": "power", "research": "smart_grid",
        "terrain": ["ocean"],
        "cost": {"stone": 200, "tools": 120, "gold": 100}, "workers": 1, "generates": 28,
        "desc": "Turbines out at sea, where the wind never stops. Gives most in windy weather.",
    },
    "polar_station": {
        "name": "Polar Station", "glyph": ":", "tech": 4, "category": "knowledge", "power": 6, "research": "climate_engineering",
        "terrain": ["glacier", "tundra"],
        "cost": {"stone": 250, "tools": 120, "gold": 200}, "workers": 4, "time": 20 * MIN,
        "produces": {"knowledge": 45}, "modifiers": ["cooling"],
        "desc": "Scientists drilling ice cores and watching the sky. Faster the colder it is.",
    },
    "spaceport": {
        "name": "Spaceport", "glyph": ";", "tech": 5, "category": "support", "power": 30, "research": "orbital_mechanics", "unique": True,
        "terrain": ["plains", "desert", "scrubland"], "max_height": 2,
        "cost": {"stone": 2000, "tools": 800, "electronics": 600, "gold": 3000}, "workers": 6, "time": 30 * MIN,
        "produces": {"knowledge": 120, "gold": 100}, "attracts": 2, "explore_speed": 0.3,
        "desc": "Rockets to orbit and back: knowledge, gold, two extra arrivals per meal, and expeditions 30% faster. Needs flat ground. A city can have one.",
    },
    "orbital_mirror": {
        "name": "Orbital Mirror Array", "glyph": "-", "tech": 5, "category": "support", "research": "orbital_mechanics", "unique": True,
        "terrain": ["plains", "desert", "hill"],
        "cost": {"tools": 600, "electronics": 500, "gold": 2500}, "night_shelter": 0.75,
        "desc": "Mirrors in orbit that light the city by night: three quarters of every slowdown the night causes is gone, solar farms included. A city can have one.",
    },
    "weather_control": {
        "name": "Weather Control Tower", "glyph": "_", "tech": 5, "category": "support", "research": "weather_control", "unique": True,
        "terrain": ["plains", "hill", "mountain"],
        "cost": {"stone": 1500, "tools": 600, "electronics": 800, "gold": 4000}, "weather_shelter": 1.0,
        "desc": "Seeds the clouds and turns the storms: the weather never slows anything in the city, not even a blizzard. Its good effects still count. A city can have one.",
    },
    "ocean_habitat": {
        "name": "Ocean Habitat", "glyph": "○", "tech": 5, "category": "housing", "research": "marine_habitats",
        "terrain": ["ocean", "coral_reef", "kelp_forest"],
        "cost": {"stone": 600, "tools": 200, "electronics": 150, "gold": 500}, "housing": 60,
        "desc": "A town of glass domes on the sea bed. Houses 60.",
    },
    "quantum_lab": {
        "name": "Quantum Lab", "glyph": "∞", "tech": 5, "category": "knowledge", "power": 30, "research": "quantum_computing",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 500, "tools": 200, "electronics": 300, "gold": 800}, "workers": 4, "time": 20 * MIN,
        "produces": {"knowledge": 260}, "modifiers": ["cooling"],
        "desc": "Machines that think in many directions at once. Runs best on a cold tile.",
    },
    # ---- electronics, from City on: each step makes more than the one before, and the Electronics Plant is not the best
    "electronics_workshop": {
        "name": "Electronics Workshop", "glyph": "\u00ac", "tech": 3, "category": "materials", "power": 3, "research": "electricity",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 120, "ore": 60, "tools": 40}, "workers": 2, "time": 20 * MIN,
        "consumes": {"ore": 4, "tools": 1}, "produces": {"electronics": 4},
        "desc": "Wires, valves and radios built by hand: a first trickle of electronics, before a city can make chips.",
    },
    "ewaste_recycler": {
        "name": "E-Waste Recycler", "glyph": "\u00f7", "tech": 4, "category": "materials", "power": 6, "research": "semiconductors",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 200, "tools": 100, "gold": 150}, "workers": 2, "time": 20 * MIN,
        "consumes": {"tools": 6}, "produces": {"electronics": 7},
        "desc": "Strips old machines for their boards and chips: worn-out tools turned into electronics, no ore needed.",
    },
    "chip_fab": {
        "name": "Chip Fab", "glyph": "\u00d7", "tech": 4, "category": "materials", "power": 12, "research": "semiconductors",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 400, "tools": 200, "gold": 300}, "workers": 4, "time": 20 * MIN,
        "consumes": {"ore": 10, "gold": 10}, "produces": {"electronics": 14},
        "desc": "Prints circuits onto silicon wafers in spotless halls: far more electronics than an Electronics Plant, from fewer workers.",
    },
    "nano_assembler": {
        "name": "Nano Assembler", "glyph": "\u00be", "tech": 5, "category": "materials", "power": 25, "research": "robotics",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 600, "tools": 300, "electronics": 100, "gold": 800}, "workers": 4, "time": 15 * MIN,
        "consumes": {"ore": 12}, "produces": {"electronics": 24},
        "desc": "Machines too small to see build circuits atom by atom: the most electronics of any building.",
    },
    # ---- wood for a Metropolis and a Megacity, whose buildings take it by the thousand ----
    "tree_plantation": {
        "name": "Tree Plantation", "glyph": "\u00b0", "tech": 4, "category": "materials", "research": "forestry",
        "terrain": ["plains"], "min_fertility": 30,
        "cost": {"stone": 150, "tools": 80, "gold": 120}, "workers": 4, "time": 15 * MIN,
        "produces": {"wood": 70}, "modifiers": ["fertility"],
        "desc": "Rows of fast-growing trees, cut in turn and planted again: a great deal of wood from open land. Faster on richer soil.",
    },
    "harvester_fleet": {
        "name": "Harvester Fleet", "glyph": "\u00b7", "tech": 4, "category": "materials", "power": 4, "research": "forestry",
        "terrain": ["forest"],
        "cost": {"stone": 150, "tools": 120, "gold": 150}, "workers": 3, "time": 15 * MIN,
        "produces": {"wood": 60}, "modifiers": ["deep_forest"],
        "desc": "Machines that fell, strip and stack a tree in a minute. Faster deeper in the woods.",
    },
    "bio_timber_vats": {
        "name": "Bio-Timber Vats", "glyph": "\u00a1", "tech": 5, "category": "materials", "power": 15, "research": "hydroponics",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 500, "tools": 200, "electronics": 80, "gold": 500}, "workers": 4, "time": 15 * MIN,
        "produces": {"wood": 160}, "sheltered": True,
        "desc": "Wood grown from cells in warm tanks, no tree needed: more wood than any forest, anywhere, in any weather or time of day.",
    },
    # ---- rivers, lakes and the ocean: something for every stage of the game ----
    "river_fish_weir": {
        "name": "Fish Weir", "glyph": "\u0152", "tech": 1, "category": "food",
        "terrain": ["river"], "cost": {"wood": 40, "stone": 20}, "workers": 2, "time": 15 * MIN,
        "produces": {"food": 13}, "modifiers": ["fish"],
        "desc": "A fence of stakes across the river that steers the fish into traps. Faster with more fish.",
    },
    "river_barge_port": {
        "name": "River Barge Port", "glyph": "\u0153", "tech": 4, "category": "trade", "power": 3,
        "terrain": ["river"], "cost": {"stone": 250, "tools": 100, "gold": 200}, "workers": 3, "time": 20 * MIN,
        "produces": {"gold": 45}, "explore_speed": 0.1,
        "desc": "Long barges carry goods up and down the river: gold, and expeditions are 10% faster.",
    },
    "run_of_river_turbines": {
        "name": "Run-of-River Turbines", "glyph": "\u0160", "tech": 5, "category": "power",
        "terrain": ["river"], "cost": {"stone": 500, "tools": 200, "electronics": 60, "gold": 400}, "workers": 1, "generates": 60,
        "desc": "Turbines set in the current itself, with no dam: steady power with no fuel.",
    },
    "duck_farm": {
        "name": "Duck Farm", "glyph": "\u017d", "tech": 1, "category": "food",
        "terrain": ["lake"], "cost": {"wood": 40}, "workers": 2, "time": 15 * MIN,
        "produces": {"food": 11, "livestock": 0.05},
        "desc": "Ducks and geese on the shallows: food, and now and then a bird to keep.",
    },
    "aquaculture_pens": {
        "name": "Aquaculture Pens", "glyph": "\u00d6", "tech": 4, "category": "food", "power": 2,
        "terrain": ["lake"], "cost": {"stone": 200, "tools": 100, "gold": 150}, "workers": 4, "time": 15 * MIN,
        "produces": {"food": 66}, "modifiers": ["fish"],
        "desc": "Floating net pens raising fish by the thousand: a great deal of food. Faster in richer water.",
    },
    "floating_solar": {
        "name": "Floating Solar", "glyph": "\u0110", "tech": 5, "category": "power",
        "terrain": ["lake"], "cost": {"stone": 300, "tools": 150, "electronics": 60, "gold": 300}, "workers": 1, "generates": 55,
        "generates_modifiers": ["sunlight"],
        "desc": "Panels floating on the lake, kept cool by the water: more power than a solar farm. Less at night and under cloud.",
    },
    "sea_salt_pans": {
        "name": "Sea Salt Pans", "glyph": "\u0111", "tech": 1, "category": "trade",
        "terrain": ["ocean"], "cost": {"wood": 30, "stone": 20}, "workers": 2, "time": 15 * MIN,
        "produces": {"gold": 8},
        "desc": "Shallow pans the sea fills and the sun dries: salt to sell.",
    },
    "marina": {
        "name": "Marina", "glyph": "\u0126", "tech": 3, "category": "trade", "power": 1,
        "terrain": ["river", "lake", "ocean"], "cost": {"wood": 120, "stone": 100, "gold": 80}, "workers": 3, "time": 20 * MIN,
        "produces": {"gold": 24}, "housing": 4, "attracts": 1,
        "desc": "Moorings for pleasure boats, with a clubhouse: gold, rooms for 4, and one extra arrival per meal.",
    },
    "deep_sea_trawlers": {
        "name": "Deep-Sea Trawlers", "glyph": "\u0127", "tech": 4, "category": "food", "power": 3,
        "terrain": ["ocean"], "cost": {"stone": 200, "tools": 150, "gold": 200}, "workers": 4, "time": 15 * MIN,
        "produces": {"food": 80}, "modifiers": ["fish", "open_water"],
        "desc": "Big ships that stay out for weeks: a great deal of food. Faster with more fish and bigger water.",
    },
    "ocean_mining_rig": {
        "name": "Ocean Mining Rig", "glyph": "\u0141", "tech": 5, "category": "materials", "power": 15,
        "terrain": ["ocean"], "cost": {"stone": 600, "tools": 300, "electronics": 120, "gold": 600}, "workers": 4, "time": 15 * MIN,
        "produces": {"ore": 60, "electronics": 4},
        "desc": "Robot dredgers lift metal-rich nodules from the deep sea floor: a great deal of ore, and rare metals for electronics.",
    },
    # ---- turning surplus tools and electronics into gold ----
    "tinkers_stall": {
        "name": "Tinker's Stall", "glyph": "\u0174", "tech": 2, "category": "trade",
        "terrain": ["plains", "desert", "hill"], "cost": {"wood": 60, "stone": 40}, "workers": 2, "time": 15 * MIN,
        "consumes": {"tools": 4}, "produces": {"gold": 19},
        "desc": "Mends and sells pots, locks and little gadgets: tools turned into gold.",
    },
    "hardware_store": {
        "name": "Hardware Store", "glyph": "\u0176", "tech": 3, "category": "trade", "power": 1,
        "terrain": ["plains", "desert", "hill"], "cost": {"stone": 120, "tools": 30, "gold": 60}, "workers": 3, "time": 20 * MIN,
        "consumes": {"tools": 10}, "produces": {"gold": 50},
        "desc": "Shelves of nails, saws and spanners for every builder in the land: tools turned into gold.",
    },
    "electronics_store": {
        "name": "Electronics Store", "glyph": "\u0164", "tech": 4, "category": "trade", "power": 3,
        "terrain": ["plains", "desert", "hill"], "cost": {"stone": 200, "tools": 80, "gold": 200}, "workers": 3, "time": 20 * MIN,
        "consumes": {"electronics": 8}, "produces": {"gold": 100},
        "desc": "Radios, phones and games for the whole region: electronics turned into gold.",
    },
    "export_terminal": {
        "name": "Export Terminal", "glyph": "\u015e", "tech": 4, "category": "trade", "power": 4,
        "terrain": ["plains", "desert", "hill"], "cost": {"stone": 300, "tools": 120, "gold": 250}, "workers": 4, "time": 20 * MIN,
        "consumes": {"tools": 20, "electronics": 5}, "produces": {"gold": 140},
        "desc": "Crates finished goods for buyers far away: tools and electronics turned into a great deal of gold.",
    },
    "smart_device_factory": {
        "name": "Smart Device Factory", "glyph": "\u0158", "tech": 5, "category": "trade", "power": 10,
        "terrain": ["plains", "desert", "hill"], "cost": {"stone": 500, "tools": 250, "electronics": 100, "gold": 600}, "workers": 4, "time": 15 * MIN,
        "consumes": {"electronics": 20, "tools": 10}, "produces": {"gold": 260},
        "desc": "Builds the gadgets everyone wants this year: electronics and tools turned into gold by the cartload.",
    },
    # ---- stone for a Megacity, whose buildings take it by the thousand ----
    "autonomous_quarry": {
        "name": "Autonomous Quarry", "glyph": "\u0147", "tech": 5, "category": "materials", "power": 12, "research": "robotics",
        "terrain": ["hill", "mountain", "cliffs", "canyon", "foothills"],
        "cost": {"stone": 400, "tools": 250, "electronics": 80, "gold": 400}, "workers": 3, "time": 15 * MIN,
        "produces": {"stone": 120},
        "desc": "Robot diggers and cutters that work a whole hillside day and night: more stone than any quarry.",
    },
    "geopolymer_plant": {
        "name": "Geopolymer Plant", "glyph": "\u010c", "tech": 5, "category": "materials", "power": 15, "research": "robotics",
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 300, "tools": 250, "electronics": 100, "gold": 500}, "workers": 4, "time": 15 * MIN,
        "produces": {"stone": 100}, "sheltered": True,
        "desc": "Binds ash and clay into blocks as hard as granite, on any flat ground: a great deal of stone without a hill to quarry.",
    },
    # ---- knowledge on the water ----
    "tide_watchers": {
        "name": "Tide Watchers", "glyph": "\u0106", "tech": 2, "category": "knowledge",
        "terrain": ["ocean"], "cost": {"wood": 60, "stone": 40}, "workers": 2, "time": 20 * MIN,
        "produces": {"knowledge": 10},
        "desc": "Keep a record of the tides, the currents and the stars over the sea: knowledge.",
    },
    "freshwater_lab": {
        "name": "Freshwater Lab", "glyph": "\u0179", "tech": 3, "category": "knowledge", "power": 2,
        "terrain": ["river", "lake"], "cost": {"stone": 120, "tools": 30, "gold": 60}, "workers": 3, "time": 20 * MIN,
        "produces": {"knowledge": 22},
        "desc": "Studies the life of rivers and lakes, from fish to the smallest water bugs: knowledge.",
    },
    "limnology_station": {
        "name": "Limnology Station", "glyph": "\u0143", "tech": 4, "category": "knowledge", "power": 3,
        "terrain": ["lake"], "cost": {"stone": 250, "tools": 100, "gold": 200}, "workers": 3, "time": 20 * MIN,
        "produces": {"knowledge": 30, "food": 10},
        "desc": "Floating labs that study the whole lake, and breed better fish while they are at it: knowledge and some food.",
    },
    "oceanographic_institute": {
        "name": "Oceanographic Institute", "glyph": "\u015a", "tech": 4, "category": "knowledge", "power": 4,
        "terrain": ["ocean"], "cost": {"stone": 300, "tools": 120, "gold": 250}, "workers": 3, "time": 20 * MIN,
        "produces": {"knowledge": 35},
        "desc": "Research ships and a harbour full of instruments, mapping the seas: a great deal of knowledge.",
    },
    "deep_sea_lab": {
        "name": "Deep Sea Lab", "glyph": "\u0102", "tech": 5, "category": "knowledge", "power": 12,
        "terrain": ["ocean"], "cost": {"stone": 500, "tools": 200, "electronics": 150, "gold": 600}, "workers": 4, "time": 20 * MIN,
        "produces": {"knowledge": 100},
        "desc": "A station on the sea floor, studying life no one has seen before: more knowledge than any lab on land.",
    },
    # ---- for the Cauldron: cheaper and stronger brews. A city can have one of each ----
    "witchs_garden": {
        "name": "Witch's Garden", "glyph": "\u0118", "tech": 1, "category": "support", "unique": True,
        "terrain": ["plains", "forest", "hill", "marsh", "swamp"], "cost": {"wood": 60, "food": 40, "stone": 20},
        "cauldron_cost": 0.1,
        "desc": "Herbs, roots and mushrooms grown for the pot: Cauldron brews take fewer ingredients. A city can have one.",
    },
    "alchemists_workshop": {
        "name": "Alchemist's Workshop", "glyph": "\u011a", "tech": 3, "category": "support", "unique": True, "power": 2,
        "terrain": ["plains", "desert", "hill"], "cost": {"stone": 150, "tools": 40, "gold": 120},
        "cauldron_power": 0.15,
        "desc": "Flasks, furnaces and a great deal of careful notes: Cauldron brews are stronger. A city can have one.",
    },
    "grand_apothecary": {
        "name": "Grand Apothecary", "glyph": "\u010e", "tech": 4, "category": "support", "unique": True, "power": 3,
        "terrain": ["plains", "desert", "hill"], "cost": {"stone": 300, "tools": 100, "gold": 300},
        "cauldron_cost": 0.15, "cauldron_power": 0.1,
        "desc": "A great hall of jars and drawers, with every ingredient known: brews take less and are stronger. A city can have one.",
    },
    "arcane_distillery": {
        "name": "Arcane Distillery", "glyph": "\u0139", "tech": 5, "category": "support", "unique": True, "power": 10,
        "terrain": ["plains", "desert", "hill"], "cost": {"stone": 500, "tools": 250, "electronics": 100, "gold": 800},
        "cauldron_power": 0.3,
        "desc": "Towers of glass coils that wring every last drop of power from a brew: Cauldron brews are much stronger. A city can have one.",
    },
    # ---- rare tiles: buildings found nowhere else, at every stage of the game ----
    # Each is a little better than the best ordinary building of its tech level, as the reward for finding the tile.
    # Hot springs
    "spring_shrine": {
        "name": "Spring Shrine", "glyph": "\u00c5", "tech": 1, "category": "knowledge", "research": "masonry",
        "terrain": ["hot_springs"], "cost": {"wood": 40, "stone": 40}, "workers": 1, "time": 20 * MIN,
        "produces": {"knowledge": 3, "gold": 2},
        "speed_aura": {"for": ["bath_house", "thermal_spa_hotel", "geothermal_greenhouse", "thermal_fish_farm"], "bonus": 0.25},
        "desc": "A shrine to the spirits of the spring, honoured since the first bathers came. Knowledge and gold, and the bath houses, greenhouses, fish farms and spa hotels around it work 25% faster.",
    },
    "thermal_fountain": {
        "name": "Thermal Fountain", "glyph": "\u00ba", "tech": 2, "category": "support",
        "terrain": ["hot_springs"], "cost": {"stone": 120, "gold": 60}, "attracts": 1, "fertility_aura": 15,
        "desc": "A carved fountain and public footbaths of hot mineral water in the town square. One extra arrival per meal, and the mineral water makes the 8 tiles around it richer. No workers needed.",
    },
    "geothermal_greenhouse": {
        "name": "Geothermal Greenhouse", "glyph": "\u00db", "tech": 3, "category": "food", "research": "botany",
        "terrain": ["hot_springs"], "cost": {"stone": 120, "tools": 30, "gold": 60}, "workers": 3, "time": 12 * MIN,
        "produces": {"food": 26, "gold": 3}, "sheltered": True,
        "desc": "Glass houses heated by spring water piped under the floor: tropical fruit and flowers all year, whatever the weather or hour, and no power needed.",
    },
    "thermal_fish_farm": {
        "name": "Thermal Fish Farm", "glyph": "\u00c6", "tech": 3, "category": "food", "research": "marine_biology",
        "terrain": ["hot_springs"], "cost": {"wood": 80, "stone": 100, "tools": 20}, "workers": 3, "time": 10 * MIN,
        "produces": {"food": 22}, "sheltered": True,
        "desc": "Warm raceways and pools fed by the spring, raising prawns and tilapia that grow fast in the heat. Never troubled by night, cold or weather.",
    },
    "drying_house": {
        "name": "Drying House", "glyph": "\u00d0", "tech": 4, "category": "trade",
        "terrain": ["hot_springs"], "cost": {"stone": 250, "tools": 80, "gold": 150}, "workers": 3, "time": 15 * MIN,
        "consumes": {"food": 40, "wood": 20}, "produces": {"gold": 60, "tools": 8},
        "desc": "Dries timber, fruit and milk powder with the spring's dry heat: spare food and wood become gold and tools, with no fuel and no power.",
    },
    "thermal_spa_hotel": {
        "name": "Thermal Spa Hotel", "glyph": "\u00d5", "tech": 4, "category": "housing", "power": 3,
        "terrain": ["hot_springs"], "cost": {"stone": 300, "tools": 80, "gold": 250}, "workers": 4, "time": 20 * MIN,
        "produces": {"gold": 30}, "housing": 12, "attracts": 2,
        "desc": "A grand hotel built round healing pools. Earns gold, has rooms for 12, and its fame brings two extra arrivals per meal.",
    },
    "deep_geothermal_well": {
        "name": "Deep Geothermal Well", "glyph": "\u00d8", "tech": 5, "category": "power",
        "terrain": ["hot_springs"], "cost": {"stone": 600, "tools": 250, "electronics": 100, "gold": 600}, "workers": 2, "generates": 90,
        "desc": "Bored miles down beneath the springs to rock hotter than any furnace: a great deal of power, with no fuel.",
    },
    # Coral reef
    "reef_fishers": {
        "name": "Reef Fishers", "glyph": "\u00aa", "tech": 0, "category": "food",
        "terrain": ["coral_reef"], "cost": {"wood": 15}, "workers": 1, "time": 12 * MIN,
        "produces": {"food": 4}, "modifiers": ["fish"],
        "desc": "Canoes and spears over the reef, where the fish are thick. Faster with more fish.",
    },
    "reef_research_station": {
        "name": "Reef Research Station", "glyph": "\u00d2", "tech": 3, "category": "knowledge", "power": 2, "research": "marine_biology",
        "terrain": ["coral_reef"], "cost": {"stone": 120, "tools": 30, "gold": 60}, "workers": 3, "time": 20 * MIN,
        "produces": {"knowledge": 22, "gold": 5},
        "desc": "Divers and scientists studying the reef, the richest life in the sea: knowledge, and gold from what they find.",
    },
    "dive_resort": {
        "name": "Dive Resort", "glyph": "\u00f5", "tech": 4, "category": "trade", "power": 3,
        "terrain": ["coral_reef"], "cost": {"stone": 250, "tools": 60, "gold": 250}, "workers": 4, "time": 20 * MIN,
        "produces": {"gold": 50}, "housing": 6, "attracts": 1,
        "desc": "Cabins on stilts over the reef and boats out to the best dives. Earns gold, has rooms for 6, and brings one extra arrival per meal.",
    },
    "reef_biolab": {
        "name": "Reef Biolab", "glyph": "\u00d3", "tech": 5, "category": "knowledge", "power": 12,
        "terrain": ["coral_reef"], "cost": {"stone": 500, "tools": 200, "electronics": 200, "gold": 700}, "workers": 4, "time": 20 * MIN,
        "produces": {"knowledge": 90, "electronics": 3},
        "desc": "Finds medicines and new materials in the reef's corals and sponges: a great deal of knowledge, and electronics from reef-grown materials.",
    },
    # Crystal cavern
    "crystal_grotto": {
        "name": "Crystal Grotto", "glyph": "\u00c3", "tech": 1, "category": "knowledge", "research": "caving",
        "terrain": ["crystal_cavern"], "cost": {"wood": 30, "stone": 20}, "workers": 1, "time": 20 * MIN,
        "produces": {"knowledge": 4, "gold": 1}, "sheltered": True,
        "desc": "Seers meditate among glowing crystals. Knowledge, and a little gold from pilgrims. Sheltered from all weather.",
    },
    "lens_grinders": {
        "name": "Lens Grinders", "glyph": "\u00d4", "tech": 2, "category": "knowledge", "research": "glassmaking",
        "terrain": ["crystal_cavern"], "cost": {"wood": 40, "stone": 60, "gold": 30}, "workers": 2, "time": 20 * MIN,
        "produces": {"knowledge": 8, "gold": 6}, "sheltered": True,
        "desc": "Grinds clear crystal into lenses for spectacles and telescopes: knowledge, and gold from the lenses sold.",
    },
    "resonance_lab": {
        "name": "Resonance Lab", "glyph": "\u00de", "tech": 4, "category": "materials", "power": 6, "research": "semiconductors",
        "terrain": ["crystal_cavern"], "cost": {"stone": 250, "tools": 100, "gold": 200}, "workers": 3, "time": 20 * MIN,
        "produces": {"electronics": 5, "knowledge": 15}, "sheltered": True,
        "desc": "Cuts natural crystal into oscillators that keep every circuit in time: electronics without ore or tools, and knowledge.",
    },
    "crystal_lattice_core": {
        "name": "Crystal Lattice Core", "glyph": "\u00c4", "tech": 5, "category": "knowledge", "power": 20, "research": "quantum_computing",
        "terrain": ["crystal_cavern"], "cost": {"stone": 500, "tools": 200, "electronics": 300, "gold": 800}, "workers": 4, "time": 20 * MIN,
        "produces": {"knowledge": 300}, "sheltered": True,
        "desc": "A quantum computer grown inside a flawless crystal, cold and still in the cavern: more knowledge than any lab on open ground.",
    },
    # Volcanic plain and lava field
    "ash_vineyard": {
        "name": "Ash Vineyard", "glyph": "\u00e0", "tech": 1, "category": "food",
        "terrain": ["volcanic"], "cost": {"wood": 30}, "workers": 2, "time": 15 * MIN,
        "produces": {"food": 7, "gold": 4},
        "desc": "Vines in rich volcanic ash: food, and wine to sell.",
    },
    "basalt_quarry": {
        "name": "Basalt Quarry", "glyph": "\u00e1", "tech": 1, "category": "materials",
        "terrain": ["volcanic", "lava_field"], "cost": {"wood": 30}, "workers": 2, "time": 12 * MIN,
        "produces": {"stone": 9},
        "desc": "Splits old lava into neat columns of hard black stone.",
    },
    "obsidian_workshop": {
        "name": "Obsidian Workshop", "glyph": "\u00e2", "tech": 2, "category": "materials",
        "terrain": ["volcanic", "lava_field"], "cost": {"wood": 50, "stone": 40}, "workers": 2, "time": 15 * MIN,
        "consumes": {"stone": 6}, "produces": {"tools": 6, "gold": 4},
        "desc": "Knaps volcanic glass into blades sharper than steel: tools, and gold from the finest pieces.",
    },
    "volcano_observatory": {
        "name": "Volcano Observatory", "glyph": "\u00e3", "tech": 3, "category": "knowledge", "power": 2,
        "terrain": ["volcanic", "lava_field"], "cost": {"stone": 150, "tools": 30, "gold": 60}, "workers": 3, "time": 20 * MIN,
        "produces": {"knowledge": 20, "gold": 4},
        "desc": "Watches the mountain breathe: knowledge, and gold from the visitors who come to see.",
    },
    "sulphur_works": {
        "name": "Sulphur Works", "glyph": "\u00e4", "tech": 3, "category": "materials", "research": "metallurgy",
        "terrain": ["volcanic", "lava_field"], "cost": {"stone": 150, "tools": 30}, "workers": 3, "time": 20 * MIN,
        "produces": {"ore": 12, "gold": 16},
        "desc": "Gathers the yellow sulphur round the vents, and the metals that come up with it: ore and gold.",
    },
    "magma_forge": {
        "name": "Magma Forge", "glyph": "\u00e5", "tech": 4, "category": "materials", "research": "steelmaking",
        "terrain": ["volcanic", "lava_field"], "cost": {"stone": 300, "tools": 100, "gold": 150}, "workers": 3, "time": 15 * MIN,
        "consumes": {"ore": 12}, "produces": {"tools": 24},
        "desc": "Smelts ore in the heat of the earth itself: a great many tools, with no fuel and no power.",
    },
    "magma_tap": {
        "name": "Magma Tap", "glyph": "\u00c0", "tech": 5, "category": "power",
        "terrain": ["lava_field"], "cost": {"stone": 800, "tools": 300, "electronics": 150, "gold": 1000}, "workers": 3, "generates": 160,
        "desc": "Draws heat straight from the magma under a lava field: more power than anything but a fusion plant.",
    },
    # Cave
    "cheese_cave": {
        "name": "Cheese Cave", "glyph": "\u00e8", "tech": 2, "category": "trade", "research": "dairying",
        "terrain": ["cave"], "cost": {"wood": 50, "stone": 30}, "workers": 2, "time": 20 * MIN,
        "consumes": {"food": 8}, "produces": {"gold": 22}, "sheltered": True,
        "desc": "Wheels of cheese ripening in the cool, steady dark: food turned into gold.",
    },
    "cave_archive": {
        "name": "Cave Archive", "glyph": "\u00e9", "tech": 3, "category": "knowledge", "research": "public_education",
        "terrain": ["cave"], "cost": {"stone": 120, "tools": 20, "gold": 50}, "workers": 2, "time": 20 * MIN,
        "produces": {"knowledge": 14}, "sheltered": True,
        "desc": "Books and records kept safe from fire, flood and damp deep underground.",
    },
    "cave_data_vault": {
        "name": "Cave Data Vault", "glyph": "\u00ea", "tech": 4, "category": "knowledge", "power": 8, "research": "computing",
        "terrain": ["cave"], "cost": {"stone": 250, "tools": 100, "electronics": 40, "gold": 200}, "workers": 3, "time": 20 * MIN,
        "produces": {"knowledge": 40}, "modifiers": ["cooling"], "sheltered": True,
        "desc": "Racks of computers kept cool by the rock. Runs best where the cave is cold.",
    },
    "undercity": {
        "name": "Undercity", "glyph": "\u00eb", "tech": 5, "category": "housing",
        "terrain": ["cave"], "cost": {"stone": 900, "tools": 250, "gold": 500}, "housing": 70,
        "desc": "Streets and homes carved out of the cave: houses 70, and needs no electronics to build.",
    },
    # Oasis
    "date_palm_grove": {
        "name": "Date Palm Grove", "glyph": "\u00ec", "tech": 1, "category": "food",
        "terrain": ["oasis"], "cost": {"wood": 30}, "workers": 2, "time": 15 * MIN,
        "produces": {"food": 9, "gold": 3},
        "desc": "Palms heavy with dates round the water: food, and dates to sell.",
    },
    "oasis_bazaar": {
        "name": "Oasis Bazaar", "glyph": "\u00ed", "tech": 2, "category": "trade", "research": "bookkeeping",
        "terrain": ["oasis"], "cost": {"wood": 60, "stone": 40, "gold": 20}, "workers": 3, "time": 20 * MIN,
        "produces": {"gold": 20}, "attracts": 1,
        "desc": "Every caravan in the desert stops to water here, and trade. Gold, and one extra arrival per meal.",
    },
    "desert_botanic_garden": {
        "name": "Desert Botanic Garden", "glyph": "\u00ee", "tech": 4, "category": "knowledge", "power": 3,
        "terrain": ["oasis"], "cost": {"stone": 250, "tools": 80, "gold": 200}, "workers": 4, "time": 20 * MIN,
        "produces": {"knowledge": 25, "food": 20, "gold": 10},
        "desc": "Plants from every dry land on earth, grown and studied round the spring: knowledge, food and gold.",
    },
    "oasis_waterworks": {
        "name": "Oasis Waterworks", "glyph": "\u00ef", "tech": 5, "category": "food", "power": 6, "research": "desalination",
        "terrain": ["oasis"], "cost": {"stone": 500, "tools": 200, "electronics": 60, "gold": 400}, "workers": 3, "time": 12 * MIN,
        "produces": {"food": 80}, "fertility_aura": 40,
        "desc": "Pumps and pipes that spread the oasis far into the sand: a great deal of food, and the 8 tiles around it much richer.",
    },
    # Glacier
    "cryo_vault": {
        "name": "Cryo Vault", "glyph": "\u00f2", "tech": 5, "category": "knowledge", "power": 15, "research": "machine_learning",
        "terrain": ["glacier"], "cost": {"stone": 500, "tools": 200, "electronics": 200, "gold": 600}, "workers": 3, "time": 20 * MIN,
        "produces": {"knowledge": 120}, "modifiers": ["cooling"],
        "desc": "Computers buried in the ice, which keeps them colder than any machine could: a great deal of knowledge. Faster the colder it is.",
    },
    # Ancient grove
    "druid_circle": {
        "name": "Druid Circle", "glyph": "\u00f3", "tech": 1, "category": "knowledge", "research": "pathfinding",
        "terrain": ["ancient_grove"], "cost": {"wood": 20, "stone": 30}, "workers": 1, "time": 20 * MIN,
        "produces": {"knowledge": 4, "gold": 1}, "wildlife_speed": 0.1,
        "desc": "A ring of stones among the oldest trees. Knowledge, and wild animals come 10% more often.",
    },
    "heartwood_loggers": {
        "name": "Heartwood Loggers", "glyph": "\u00f4", "tech": 3, "category": "materials", "research": "forestry",
        "terrain": ["ancient_grove"], "cost": {"wood": 80, "stone": 60, "tools": 30}, "workers": 3, "time": 15 * MIN,
        "produces": {"wood": 36}, "modifiers": ["deep_forest"],
        "desc": "Takes only fallen giants and single great trees, each worth a forest of saplings. Faster deeper in the woods.",
    },
    "elder_tree_sanctuary": {
        "name": "Elder Tree Sanctuary", "glyph": "\u00f6", "tech": 4, "category": "support", "research": "beast_training", "unique": True,
        "terrain": ["ancient_grove"], "cost": {"wood": 300, "stone": 200, "gold": 300}, "workers": 2, "time": 20 * MIN,
        "produces": {"knowledge": 20}, "mission_speed": 0.25, "beast_xp": 0.15,
        "desc": "Beasts rest and train beneath the oldest tree in the land: missions go 25% faster, beasts grow 15% faster, and the keepers gather knowledge. A city can have one.",
    },
    "living_spire": {
        "name": "Living Spire", "glyph": "\u00f9", "tech": 5, "category": "housing", "research": "hydroponics",
        "terrain": ["ancient_grove"], "cost": {"wood": 1200, "stone": 400, "tools": 200, "gold": 600}, "housing": 55, "attracts": 1,
        "desc": "Homes grown into and around a living giant tree. Houses 55, and so many come to see it that one extra arrives per meal.",
    },
    # Dense forest
    "charcoal_kilns": {
        "name": "Charcoal Kilns", "glyph": "\u00fa", "tech": 1, "category": "materials",
        "terrain": ["dense_forest"], "cost": {"wood": 30, "stone": 20}, "workers": 2, "time": 15 * MIN,
        "consumes": {"wood": 10}, "produces": {"tools": 5, "gold": 5},
        "desc": "Slow-burns wood into charcoal for the smiths: tools, and gold from the charcoal sold.",
    },
    "canopy_walkway": {
        "name": "Canopy Walkway", "glyph": "\u00fb", "tech": 3, "category": "trade", "power": 1,
        "terrain": ["dense_forest"], "cost": {"wood": 200, "tools": 30, "gold": 80}, "workers": 3, "time": 20 * MIN,
        "produces": {"gold": 24}, "attracts": 1,
        "desc": "Rope bridges high in the treetops. Earns gold, and brings one extra arrival per meal.",
    },
    "biomass_plant": {
        "name": "Biomass Plant", "glyph": "\u00fc", "tech": 4, "category": "power", "research": "recycling",
        "terrain": ["dense_forest"], "cost": {"stone": 200, "tools": 80, "gold": 100}, "workers": 2, "time": 15 * MIN,
        "consumes": {"wood": 8}, "generates": 36,
        "desc": "Burns the forest's deadwood and brush for power, a little wood at a time.",
    },
    # Mangrove
    "crab_traps": {
        "name": "Crab Traps", "glyph": "\u00fd", "tech": 0, "category": "food",
        "terrain": ["mangrove"], "cost": {"wood": 12}, "workers": 1, "time": 12 * MIN,
        "produces": {"food": 4}, "modifiers": ["fish"],
        "desc": "Pots set among the mangrove roots, where crabs and shrimp hide. Faster with more fish.",
    },
    "mangrove_nursery": {
        "name": "Mangrove Nursery", "glyph": "\u00ff", "tech": 2, "category": "food",
        "terrain": ["mangrove"], "cost": {"wood": 40, "stone": 20}, "workers": 2, "time": 20 * MIN,
        "produces": {"wood": 10, "food": 6}, "fertility_aura": 10,
        "desc": "Grows new mangroves, which feed the fish and build up the mud: wood and food, and the 8 tiles around it a little richer.",
    },
    "blue_carbon_reserve": {
        "name": "Blue Carbon Reserve", "glyph": "\u00c1", "tech": 4, "category": "trade",
        "terrain": ["mangrove"], "cost": {"wood": 300, "stone": 100, "gold": 200}, "workers": 3, "time": 20 * MIN,
        "produces": {"gold": 30, "knowledge": 12}, "wildlife_speed": 0.15,
        "desc": "Protected mangrove that locks away carbon, paid for by the world: gold and knowledge, and wild animals come 15% more often.",
    },
    # Kelp forest
    "kelp_biorefinery": {
        "name": "Kelp Biorefinery", "glyph": "\u00c2", "tech": 4, "category": "power", "research": "recycling",
        "terrain": ["kelp_forest"], "cost": {"stone": 200, "tools": 100, "gold": 100}, "workers": 2, "generates": 30,
        "desc": "Turns fast-growing kelp into fuel as quickly as it grows back: steady power with nothing to feed it.",
    },
    # Beach
    "beachcombers": {
        "name": "Beachcombers", "glyph": "\u00c7", "tech": 0, "category": "food",
        "terrain": ["beach"], "cost": {"wood": 10}, "workers": 1, "time": 15 * MIN,
        "produces": {"wood": 3, "food": 2, "gold": 1},
        "desc": "Walks the tide line for driftwood, shellfish and whatever the sea brings in.",
    },
    "boatyard": {
        "name": "Boatyard", "glyph": "\u00c8", "tech": 2, "category": "trade", "research": "navigation",
        "terrain": ["beach"], "cost": {"wood": 60, "stone": 30}, "workers": 2, "time": 20 * MIN,
        "consumes": {"wood": 12}, "produces": {"gold": 22}, "explore_speed": 0.05,
        "desc": "Builds boats on the open sand: wood turned into gold, and expeditions are 5% faster.",
    },
    # Salt flat
    "salt_curing_house": {
        "name": "Salt Curing House", "glyph": "\u00c9", "tech": 3, "category": "trade", "research": "canning",
        "terrain": ["salt_flat"], "cost": {"wood": 80, "stone": 80, "tools": 20}, "workers": 2, "time": 20 * MIN,
        "consumes": {"food": 20}, "produces": {"gold": 36},
        "desc": "Salts fish and meat to keep for years: food turned into gold.",
    },
    "speed_trials_track": {
        "name": "Speed Trials Track", "glyph": "\u00ca", "tech": 4, "category": "trade", "power": 2,
        "terrain": ["salt_flat"], "cost": {"stone": 200, "tools": 80, "gold": 200}, "workers": 3, "time": 20 * MIN,
        "produces": {"gold": 44}, "attracts": 1,
        "desc": "The flattest ground on earth, where record-breaking cars race. Gold, and one extra arrival per meal.",
    },
    "lithium_brine_works": {
        "name": "Lithium Brine Works", "glyph": "\u00cb", "tech": 5, "category": "materials", "power": 8,
        "terrain": ["salt_flat"], "cost": {"stone": 400, "tools": 200, "gold": 500}, "workers": 3, "time": 20 * MIN,
        "produces": {"electronics": 12, "gold": 20},
        "desc": "Draws lithium from the brine under the salt for batteries: electronics without ore or tools, and gold.",
    },
    # Canyon
    "cliff_dwellings": {
        "name": "Cliff Dwellings", "glyph": "\u00cc", "tech": 1, "category": "housing", "research": "masonry",
        "terrain": ["canyon"], "cost": {"wood": 20, "stone": 30}, "housing": 7,
        "desc": "Rooms built into the canyon walls, cool in summer and safe all year. Houses 7.",
    },
    "fossil_dig": {
        "name": "Fossil Dig", "glyph": "\u00cd", "tech": 3, "category": "knowledge",
        "terrain": ["canyon"], "cost": {"wood": 60, "stone": 60, "tools": 20}, "workers": 3, "time": 20 * MIN,
        "produces": {"knowledge": 18, "gold": 6},
        "desc": "Digs ancient bones out of the canyon's layers of rock: knowledge, and gold from museums.",
    },
    "canyon_skywalk": {
        "name": "Canyon Skywalk", "glyph": "\u00ce", "tech": 4, "category": "trade", "power": 2,
        "terrain": ["canyon"], "cost": {"stone": 200, "tools": 100, "gold": 200}, "workers": 3, "time": 20 * MIN,
        "produces": {"gold": 44}, "attracts": 1,
        "desc": "A glass walkway out over the drop. Gold, and one extra arrival per meal.",
    },
    # Mesa
    "mesa_pueblo": {
        "name": "Mesa Pueblo", "glyph": "\u00cf", "tech": 2, "category": "housing",
        "terrain": ["mesa"], "cost": {"wood": 40, "stone": 80}, "housing": 12,
        "desc": "Terraced adobe homes on the flat top of a mesa. Houses 12.",
    },
    "mesa_solar_array": {
        "name": "Mesa Solar Array", "glyph": "\u00d1", "tech": 4, "category": "power", "research": "photovoltaics",
        "terrain": ["mesa"], "cost": {"stone": 150, "tools": 100, "gold": 150}, "workers": 1, "generates": 36,
        "generates_modifiers": ["sunlight"],
        "desc": "Panels on the high, clear top of a mesa, above the dust and the haze: more power than a solar farm. Less at night and under cloud.",
    },
    # Bamboo grove
    "bamboo_cutters": {
        "name": "Bamboo Cutters", "glyph": "\u00d9", "tech": 0, "category": "materials",
        "terrain": ["bamboo"], "cost": {"wood": 8}, "workers": 1, "time": 12 * MIN,
        "produces": {"wood": 5},
        "desc": "Bamboo grows back almost as fast as it is cut.",
    },
    "bamboo_scaffolders": {
        "name": "Bamboo Scaffolders", "glyph": "\u00da", "tech": 3, "category": "materials",
        "terrain": ["bamboo"], "cost": {"wood": 100, "stone": 40, "tools": 20}, "workers": 3, "time": 15 * MIN,
        "produces": {"wood": 18, "tools": 5},
        "desc": "Lashes bamboo into scaffolds and frames: wood, and tools.",
    },
    "bamboo_towers": {
        "name": "Bamboo Towers", "glyph": "\u00dc", "tech": 5, "category": "housing",
        "terrain": ["bamboo"], "cost": {"wood": 900, "stone": 300, "tools": 150, "gold": 400}, "housing": 45,
        "desc": "Light, strong towers of engineered bamboo. Houses 45, and needs no electronics to build.",
    },
    # Sand dunes
    "dune_caravan_camp": {
        "name": "Dune Caravan Camp", "glyph": "\u00dd", "tech": 1, "category": "trade",
        "terrain": ["sand_dunes"], "cost": {"wood": 30}, "workers": 2, "time": 20 * MIN,
        "produces": {"gold": 8}, "explore_speed": 0.05,
        "desc": "Camels and guides who know the dunes: gold from the caravans, and expeditions are 5% faster.",
    },
    "sand_glassworks": {
        "name": "Sand Glassworks", "glyph": "\u00b2", "tech": 3, "category": "trade", "power": 2, "research": "glassmaking",
        "terrain": ["sand_dunes"], "cost": {"stone": 120, "tools": 30, "gold": 40}, "workers": 3, "time": 20 * MIN,
        "produces": {"gold": 22, "knowledge": 3},
        "desc": "The finest glass sand there is, melted into windows and bottles: gold.",
    },
    "dune_solar_field": {
        "name": "Dune Solar Field", "glyph": "\u00b3", "tech": 5, "category": "power", "research": "photovoltaics",
        "terrain": ["sand_dunes"], "cost": {"stone": 300, "tools": 150, "electronics": 60, "gold": 300}, "workers": 1, "generates": 70,
        "generates_modifiers": ["sunlight"],
        "desc": "Miles of panels across the sand, under the strongest sun on earth. Less at night and under cloud.",
    },
    # Floodplain
    "silt_farm": {
        "name": "Silt Farm", "glyph": "\u00b9", "tech": 1, "category": "food", "research": "drainage",
        "terrain": ["floodplain"], "cost": {"wood": 20}, "workers": 2, "time": 12 * MIN,
        "produces": {"food": 10}, "modifiers": ["fertility"],
        "desc": "Fields renewed by every flood's fresh silt: more food than any farm. Faster on richer soil.",
    },
    "silt_brickworks": {
        "name": "Silt Brickworks", "glyph": "\u00a4", "tech": 2, "category": "materials",
        "terrain": ["floodplain"], "cost": {"wood": 40, "stone": 20}, "workers": 2, "time": 15 * MIN,
        "produces": {"stone": 12},
        "desc": "Fires the river's mud into bricks, as good as stone.",
    },
    # Sea cliffs
    "seabird_egg_gatherers": {
        "name": "Seabird Egg Gatherers", "glyph": "\u00a6", "tech": 0, "category": "food",
        "terrain": ["cliffs"], "cost": {"wood": 10}, "workers": 1, "time": 15 * MIN,
        "produces": {"food": 5},
        "desc": "Climbs the cliffs on ropes for the eggs of the seabirds nesting there.",
    },
    "cliffside_hotel": {
        "name": "Cliffside Hotel", "glyph": "\u00ab", "tech": 3, "category": "trade", "power": 2,
        "terrain": ["cliffs"], "cost": {"stone": 150, "tools": 30, "gold": 100}, "workers": 3, "time": 20 * MIN,
        "produces": {"gold": 28}, "housing": 4, "attracts": 1,
        "desc": "Rooms with a view over the sea. Earns gold, has rooms for 4, and brings one extra arrival per meal.",
    },
    # Heath and foothills
    "heather_distillery": {
        "name": "Heather Distillery", "glyph": "\u00bb", "tech": 2, "category": "trade",
        "terrain": ["heath"], "cost": {"wood": 50, "stone": 40}, "workers": 2, "time": 20 * MIN,
        "produces": {"gold": 14},
        "desc": "Heather honey and spirits made on the open moor, sold far and wide.",
    },
    "hillside_vineyard": {
        "name": "Hillside Vineyard", "glyph": "\u00bf", "tech": 2, "category": "food", "research": "grafting",
        "terrain": ["foothills"], "cost": {"wood": 50, "stone": 30}, "workers": 2, "time": 20 * MIN,
        "produces": {"food": 8, "gold": 8},
        "desc": "Terraced vines on sunny slopes: food, and wine to sell.",
    },
    # ---- the expedition queue ----
    "expedition_camp": {
        "name": "Expedition Camp", "glyph": "⚐", "tech": 1, "category": "support", "research": "expedition_planning", "unique": True,
        "terrain": ["plains", "forest", "desert", "hill"],
        "cost": {"wood": 120, "stone": 60, "food": 50}, "exp_queue": 1, "explore_speed": 0.05,
        "desc": "Tents, mules and stores for the next team: one more expedition can wait in the queue, and expeditions are 5% faster. A city can have one.",
    },
    "explorers_guild": {
        "name": "Explorers' Guild", "glyph": "⚑", "tech": 3, "category": "support", "research": "grand_survey", "unique": True,
        "terrain": ["plains", "desert", "hill"],
        "cost": {"stone": 400, "tools": 80, "gold": 300}, "exp_queue": 1, "explore_speed": 0.1,
        "desc": "A hall of maps and veteran guides: one more expedition can wait in the queue, and expeditions are 10% faster. A city can have one.",
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
    "beast_lore": {
        "name": "Beast Lore", "tech": 0, "building": "shaman_hut", "cost": {"knowledge": 10},
        "desc": "What the old stories say about the great beasts, and what they like.",
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
    "incubation": {
        "name": "Incubation", "tech": 1, "building": "school", "cost": {"knowledge": 25},
        "desc": "How warm, how often to turn, and when to leave well alone.",
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
    "volcanology": {
        "name": "Volcanology", "tech": 2, "building": "university", "cost": {"knowledge": 60},
        "effect": "lava fields can be built on",
        "desc": "Knowing when the ground is safe to stand on.",
    },
    "beast_training": {
        "name": "Beast Training", "tech": 2, "building": "university", "cost": {"knowledge": 55},
        "desc": "Patience, routine and a pocketful of treats.",
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
    "beast_bonding": {
        "name": "Beast Bonding", "tech": 3, "building": "university", "cost": {"knowledge": 110},
        "desc": "A beast that trusts its city asks more of it, and gives more back.",
    },
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
    "civil_service": {
        "name": "Civil Service", "tech": 3, "building": "university", "cost": {"knowledge": 120},
        "desc": "Clerks, records and someone whose job it is.",
    },
    "sanitation": {
        "name": "Sanitation", "tech": 3, "building": "university", "cost": {"knowledge": 110},
        "desc": "Clean water in, dirty water out.",
    },
    "forestry": {
        "name": "Forestry", "tech": 3, "building": "university", "cost": {"knowledge": 110},
        "boost": {"lumber_camp": 1.2, "sawmill": 1.15},
        "desc": "Plant as much as you fell.",
    },
    "canning": {
        "name": "Canning", "tech": 3, "building": "university", "cost": {"knowledge": 120},
        "boost": {"fishery": 1.15, "butcher": 1.15},
        "desc": "Food sealed in tin keeps for years.",
    },
    "concrete": {
        "name": "Concrete", "tech": 3, "building": "university", "cost": {"knowledge": 130},
        "boost": {"quarry": 1.25},
        "desc": "Stone you can pour.",
    },
    "public_education": {
        "name": "Public Education", "tech": 3, "building": "university", "cost": {"knowledge": 140},
        "boost": {"school": 1.25, "university": 1.15},
        "desc": "Every child at a desk.",
    },
    "steelmaking": {
        "name": "Steelmaking", "tech": 3, "building": "university", "cost": {"knowledge": 150},
        "boost": {"smithy": 1.2},
        "desc": "Blow air through molten iron and it comes out stronger.",
    },
    "steam_turbines": {
        "name": "Steam Turbines", "tech": 3, "building": "university", "cost": {"knowledge": 160},
        "desc": "Anything that spins a shaft can light a street.",
    },
    "railways": {
        "name": "Railways", "tech": 3, "building": "university", "cost": {"knowledge": 170},
        "desc": "Iron roads, and timetables to go with them.",
    },
    "telegraph": {
        "name": "Telegraph", "tech": 3, "building": "university", "cost": {"knowledge": 180},
        "explore_discount": 0.6, "effect": "expeditions cost 40% less instead of 25% less",
        "desc": "News that outruns the fastest horse: expeditions carry only what they will need.",
    },
    # ---- Metropolis ----
    "modern_medicine": {
        "name": "Modern Medicine", "tech": 4, "building": "laboratory", "cost": {"knowledge": 200},
        "desc": "Antibiotics, surgery and clean wards.",
    },
    "mechanised_farming": {
        "name": "Mechanised Farming", "tech": 4, "building": "laboratory", "cost": {"knowledge": 220},
        "boost": {"farm": 1.2, "irrigated_farm": 1.2, "orchard": 1.2, "terrace_farm": 1.2, "rice_paddy": 1.2},
        "desc": "Engines in the fields.",
    },
    "recycling": {
        "name": "Recycling", "tech": 4, "building": "laboratory", "cost": {"knowledge": 200},
        "desc": "Nothing is rubbish twice.",
    },
    "photovoltaics": {
        "name": "Photovoltaics", "tech": 4, "building": "laboratory", "cost": {"knowledge": 250},
        "desc": "Electricity straight from sunlight.",
    },
    "container_shipping": {
        "name": "Container Shipping", "tech": 4, "building": "laboratory", "cost": {"knowledge": 250},
        "boost": {"harbor": 1.25},
        "desc": "The same steel box on ship, train and lorry.",
    },
    "aviation": {
        "name": "Aviation", "tech": 4, "building": "laboratory", "cost": {"knowledge": 280},
        "desc": "Powered flight.",
    },
    "semiconductors": {
        "name": "Semiconductors", "tech": 4, "building": "laboratory", "cost": {"knowledge": 300},
        "desc": "Circuits etched in silicon.",
    },
    "computing": {
        "name": "Computing", "tech": 4, "building": "laboratory", "cost": {"knowledge": 350},
        "boost": {"laboratory": 1.25, "university": 1.25},
        "desc": "Machines that calculate.",
    },
    "nuclear_fission": {
        "name": "Nuclear Fission", "tech": 4, "building": "laboratory", "cost": {"knowledge": 400},
        "desc": "Splitting the atom, carefully.",
    },
    "smart_grid": {
        "name": "Smart Grid", "tech": 4, "building": "laboratory", "cost": {"knowledge": 300},
        "desc": "Storing power and sending it where it is needed.",
    },
    # ---- Megacity ----
    "hydroponics": {
        "name": "Hydroponics", "tech": 5, "building": "research_institute", "cost": {"knowledge": 700},
        "boost": {"greenhouse": 1.3},
        "desc": "Crops without soil.",
    },
    "robotics": {
        "name": "Robotics", "tech": 5, "building": "research_institute", "cost": {"knowledge": 900},
        "boost": {"factory": 1.3, "electronics_plant": 1.3, "deep_mine": 1.2},
        "desc": "Tireless hands.",
    },
    "autonomous_logistics": {
        "name": "Autonomous Logistics", "tech": 5, "building": "research_institute", "cost": {"knowledge": 800},
        "boost": {"container_port": 1.25, "shopping_mall": 1.2},
        "desc": "Goods that find their own way.",
    },
    "machine_learning": {
        "name": "Machine Learning", "tech": 5, "building": "research_institute", "cost": {"knowledge": 1000},
        "boost": {"research_institute": 1.25},
        "desc": "Programs that improve with practice.",
    },
    "offshore_energy": {
        "name": "Offshore Energy", "tech": 5, "building": "research_institute", "cost": {"knowledge": 700},
        "desc": "Power from tide and swell.",
    },
    "desalination": {
        "name": "Desalination", "tech": 5, "building": "research_institute", "cost": {"knowledge": 600},
        "desc": "Fresh water from the sea.",
    },
    "maglev": {
        "name": "Maglev", "tech": 5, "building": "research_institute", "cost": {"knowledge": 900},
        "desc": "Trains that float on magnets.",
    },
    "fusion_power": {
        "name": "Fusion Power", "tech": 5, "building": "research_institute", "cost": {"knowledge": 1500},
        "desc": "A star in a bottle.",
    },
    # ---- the wider world ----
    "caving": {
        "name": "Caving", "tech": 0, "building": "shaman_hut", "cost": {"knowledge": 12},
        "desc": "Torches, ropes, and knowing which way is out.",
    },
    "beekeeping": {
        "name": "Beekeeping", "tech": 1, "building": "school", "cost": {"knowledge": 25},
        "desc": "Smoke, patience and a veil.",
    },
    "weather_lore": {
        "name": "Weather Lore", "tech": 1, "building": "school", "cost": {"knowledge": 30},
        "forecast": 2, "effect": "the weather can be seen two meals ahead in every area",
        "desc": "Red sky at night, and the old sayings that are mostly right.",
    },
    "meteorology": {
        "name": "Meteorology", "tech": 2, "building": "university", "cost": {"knowledge": 60},
        "forecast": 4, "effect": "the weather can be seen four meals ahead in every area",
        "desc": "Barometers, wind vanes and careful notes.",
    },
    "street_lighting": {
        "name": "Street Lighting", "tech": 2, "building": "university", "cost": {"knowledge": 55},
        "desc": "Lamps on poles, and someone to light them every evening.",
    },
    "pearl_diving": {
        "name": "Pearl Diving", "tech": 2, "building": "university", "cost": {"knowledge": 50},
        "desc": "Holding your breath, and knowing which shells to open.",
    },
    "crystallography": {
        "name": "Crystallography", "tech": 3, "building": "university", "cost": {"knowledge": 140},
        "effect": "crystal caverns can be built on",
        "desc": "How crystals grow, and how to cut them without shattering them.",
    },
    "alpine_sports": {
        "name": "Alpine Sports", "tech": 3, "building": "university", "cost": {"knowledge": 110},
        "desc": "Skis, sledges and a great deal of hot chocolate.",
    },
    "marine_biology": {
        "name": "Marine Biology", "tech": 3, "building": "university", "cost": {"knowledge": 120},
        "boost": {"kelp_gatherers": 1.2, "pearl_divers": 1.2},
        "desc": "What lives under the waves, and how to look after it.",
    },
    "climate_engineering": {
        "name": "Climate Engineering", "tech": 4, "building": "laboratory", "cost": {"knowledge": 320},
        "desc": "Domes, barriers and drains that keep the weather where it belongs.",
    },
    "astrophysics": {
        "name": "Astrophysics", "tech": 4, "building": "laboratory", "cost": {"knowledge": 280},
        "boost": {"observatory": 1.3},
        "desc": "What the stars are made of, and how far away they are.",
    },
    "orbital_mechanics": {
        "name": "Orbital Mechanics", "tech": 5, "building": "research_institute", "cost": {"knowledge": 1200},
        "desc": "Getting up there, staying up there, and coming back down.",
    },
    "weather_control": {
        "name": "Weather Control", "tech": 5, "building": "research_institute", "cost": {"knowledge": 1400},
        "desc": "Telling the clouds where to rain.",
    },
    "marine_habitats": {
        "name": "Marine Habitats", "tech": 5, "building": "research_institute", "cost": {"knowledge": 800},
        "desc": "Living under the sea, with the air on the inside.",
    },
    "quantum_computing": {
        "name": "Quantum Computing", "tech": 5, "building": "research_institute", "cost": {"knowledge": 1300},
        "boost": {"data_centre": 1.2, "research_institute": 1.2},
        "desc": "Bits that are both at once, until someone looks.",
    },
    # ---- rituals (see ideology.py): one very expensive rank per tech level from Village up ----
    "sacred_calendar": {
        "name": "Sacred Calendar", "tech": 1, "building": "school", "cost": {"knowledge": 300, "gold": 300},
        "ritual": 1, "effect": "your ideology's first ritual can be held",
        "desc": "A calendar of holy days and feast days, and someone to keep it.",
    },
    "ceremonial_halls": {
        "name": "Ceremonial Halls", "tech": 2, "building": "university", "cost": {"knowledge": 900, "gold": 1500},
        "ritual": 2, "effect": "opens your ideology's ritual number 2, and every ritual is stronger and lasts longer",
        "desc": "Great halls built for nothing but ceremony.",
    },
    "grand_rituals": {
        "name": "Grand Rituals", "tech": 3, "building": "university", "cost": {"knowledge": 3000, "gold": 6000},
        "ritual": 3, "effect": "opens your ideology's ritual number 3, and every ritual is stronger and lasts longer",
        "desc": "Ceremonies big enough to move a whole city.",
    },
    "rituals_of_state": {
        "name": "Rituals of State", "tech": 4, "building": "laboratory", "cost": {"knowledge": 8000, "gold": 20000},
        "ritual": 4, "effect": "opens your ideology's ritual number 4, and every ritual is stronger and lasts longer",
        "desc": "The state itself takes part: holidays, parades and broadcasts.",
    },
    "eternal_rituals": {
        "name": "Eternal Rituals", "tech": 5, "building": "research_institute", "cost": {"knowledge": 20000, "gold": 60000},
        "ritual": 5, "effect": "opens your ideology's ritual number 5, and every ritual is stronger and lasts longer",
        "desc": "Ceremony perfected over a thousand years, and then improved.",
    },
    # ---- expedition queue: each adds a place for a trip waiting behind the one under way ----
    "expedition_planning": {
        "name": "Expedition Planning", "tech": 1, "building": "school", "cost": {"knowledge": 60},
        "exp_queue": 1, "effect": "one expedition can wait for the one under way, and sets off when it comes back",
        "desc": "Maps, lists and a second team packed and ready.",
    },
    "supply_lines": {
        "name": "Supply Lines", "tech": 2, "building": "university", "cost": {"knowledge": 180},
        "exp_queue": 1, "effect": "one more expedition can wait in the queue",
        "desc": "Depots along the roads, so the next team never waits for food.",
    },
    "grand_survey": {
        "name": "The Grand Survey", "tech": 3, "building": "university", "cost": {"knowledge": 500},
        "exp_queue": 1, "effect": "one more expedition can wait in the queue",
        "desc": "A plan to map everything, one team after another.",
    },
}

# The costs above are the base; every research but the ritual ranks (already priced on their own) costs:
#   its knowledge times RESEARCH_SCALE[its tech level];
#   if it is important (opens a building, or is one of IMPORTANT_EFFECTS), materials of its era as well:
#     RESEARCH_MATERIALS[tech level], each a share of that knowledge, but never one the buildings it opens make;
#   if it is about animals (ANIMAL_RESEARCH), livestock: RESEARCH_LIVESTOCK[tech level].
RESEARCH_SCALE = [2, 3, 4, 5, 6, 8]
IMPORTANT_EFFECTS = ("explore_range", "explore_discount", "exp_queue", "taming", "surveying", "breeding", "forecast")
RESEARCH_MATERIALS = [{"wood": 1.0, "stone": 0.5},
                      {"wood": 0.8, "stone": 0.8},
                      {"stone": 0.6, "ore": 0.6, "tools": 0.2},
                      {"ore": 0.5, "tools": 0.5, "gold": 0.5},
                      {"tools": 0.6, "electronics": 0.2, "gold": 0.6},
                      {"tools": 0.4, "electronics": 0.25, "gold": 0.8}]
ANIMAL_RESEARCH = {"animal_husbandry", "dairying", "beast_lore", "selective_breeding", "draft_animals", "incubation",
                   "tanning", "beast_training", "beast_bonding", "canning", "mechanised_farming"}
RESEARCH_LIVESTOCK = [2, 5, 10, 20, 40, 80]


def _nice(x):
    """A cost rounded to a number that reads well: 5s under 100, 10s under 1,000, then 50s."""
    step = 5 if x < 100 else 10 if x < 1000 else 50
    return max(step, int(round(x / step)) * step)


def _price_research():
    opens = {b["research"] for b in BUILDINGS.values() if b.get("research")}
    # what the buildings each research opens make: that research never costs it (Semiconductors opens the
    # Electronics Plant, so asking for electronics to research it would leave a city no way to start)
    makes = {}
    for b in BUILDINGS.values():
        if b.get("research"):
            makes.setdefault(b["research"], set()).update(b.get("produces", {}), b.get("per_head", {}))
    for rid, r in RESEARCH.items():
        if r.get("ritual"):
            continue
        tech = r["tech"]
        knowledge = _nice(r["cost"]["knowledge"] * RESEARCH_SCALE[tech])
        cost = {"knowledge": knowledge}
        if rid in opens or any(r.get(k) for k in IMPORTANT_EFFECTS):
            for k, share in RESEARCH_MATERIALS[tech].items():
                if k not in makes.get(rid, ()):
                    cost[k] = _nice(knowledge * share)
        if rid in ANIMAL_RESEARCH:
            cost["livestock"] = RESEARCH_LIVESTOCK[tech]
        r["cost"] = cost


_price_research()

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
#   explore_speed / wildlife_speed / attracts   added to the building's own
#   workers   change to the workers the building needs, e.g. -1 (never below 1)
#   power     change to the power the building needs, e.g. -2 (never below 0)
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
        "name": "Market Stalls", "for": ["trading_post", "caravanserai", "bath_house", "salt_works", "cattle_market"], "research": "bookkeeping",
        "cost": {"wood": 40, "gold": 15}, "produces": {"gold": 2},
        "desc": "+2 Gold per cycle.",
    },
    "water_wheel": {
        "name": "Water Wheel", "for": ["sawmill", "smithy", "glassworks"], "research": "water_wheels",
        "adjacent": "fresh", "cost": {"wood": 50, "ore": 15}, "speed": 1.4,
        "desc": "40% faster. The building must be next to fresh water.",
    },
    "plumbing": {
        "name": "Plumbing", "for": ["house", "apartments", "townhouses"], "research": "plumbing",
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
        "name": "Smokehouse", "for": ["fishing_dock", "hunting_lodge", "fishery", "butcher"], "research": "smoking",
        "cost": {"wood": 20}, "produces": {"food": 1},
        "desc": "+1 Food per cycle.",
    },
    "feeding_trough": {
        "name": "Feeding Trough", "for": ["pasture", "dairy", "breeding_pen"],
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
        "name": "Library", "for": ["school", "university", "observatory", "laboratory", "research_institute"], "research": "masonry",
        "cost": {"wood": 30, "stone": 30}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "irrigation_pipes": {
        "name": "Irrigation Pipes", "for": ["irrigated_farm", "orchard", "greenhouse", "rice_paddy", "industrial_farm", "vertical_farm"], "research": "water_wheels",
        "cost": {"stone": 20, "ore": 15}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "flywheel": {
        "name": "Flywheel", "for": ["water_mill", "steam_engine"], "research": "mechanics",
        "cost": {"ore": 30}, "generates": 2,
        "desc": "+2 power.",
    },
    "crane": {
        "name": "Loading Crane", "for": ["harbor", "fishery", "container_port"], "research": "mechanics",
        "cost": {"wood": 40, "ore": 20}, "speed": 1.25,
        "desc": "25% faster.",
    },
    "transformer": {
        "name": "Transformer", "for": ["wind_turbine", "hydro_dam", "power_plant", "geothermal_plant", "nuclear_plant", "fusion_plant", "coal_plant", "tidal_generator"], "research": "electricity",
        "cost": {"ore": 30, "tools": 10}, "generates": 4,
        "desc": "+4 power.",
    },
    "assembly_line": {
        "name": "Assembly Line", "for": ["factory", "glassworks", "smithy", "electronics_plant", "recycling_centre", "steel_mill", "cannery"], "research": "mass_production",
        "cost": {"tools": 20, "gold": 30}, "speed": 1.3,
        "desc": "30% faster.",
    },
    "penthouses": {
        "name": "Penthouses", "for": ["high_rise", "arcology"],
        "cost": {"stone": 100, "gold": 150}, "housing": 10,
        "desc": "Houses 10 more people.",
    },
    "emergency_wing": {
        "name": "Emergency Wing", "for": ["hospital"],
        "cost": {"stone": 150, "tools": 50, "gold": 200}, "attracts": 1,
        "desc": "One more extra arrival per meal.",
    },
    "food_court": {
        "name": "Food Court", "for": ["shopping_mall", "airport", "maglev_hub", "resort"],
        "cost": {"stone": 80, "gold": 100}, "housing": 4,
        "desc": "Room for 4 more people.",
    },
    "advertising": {
        "name": "Advertising", "for": ["shopping_mall", "drone_port", "container_port", "zoo", "resort"],
        "cost": {"gold": 200}, "produces": {"gold": 10},
        "desc": "+10 Gold per cycle.",
    },
    "battery_bank": {
        "name": "Battery Bank", "for": ["solar_farm", "wind_turbine", "tidal_array", "offshore_wind"], "research": "smart_grid",
        "cost": {"ore": 80, "tools": 40}, "generates": 8, "night_proof": 0.5,
        "desc": "+8 power, and it stores the day's power: a solar farm keeps half its power at night.",
    },
    "express_link": {
        "name": "Express Link", "for": ["airport", "maglev_hub"],
        "cost": {"stone": 200, "tools": 80, "gold": 200}, "explore_speed": 0.25,
        "desc": "Expeditions travel a further 25% faster.",
    },
    "clean_room": {
        "name": "Clean Room", "for": ["electronics_plant", "robotics_factory", "research_institute", "data_centre"],
        "cost": {"stone": 100, "tools": 60, "gold": 150}, "speed": 1.25,
        "desc": "25% faster.",
    },
    "grow_lamps": {
        "name": "Grow Lamps", "for": ["vertical_farm", "greenhouse"], "research": "hydroponics",
        "cost": {"tools": 40, "electronics": 30}, "produces": {"food": 15},
        "desc": "+15 Food per cycle.",
    },
    "delivery_swarm": {
        "name": "Delivery Swarm", "for": ["drone_port", "robotics_factory"], "research": "autonomous_logistics",
        "cost": {"electronics": 60}, "speed": 1.3,
        "desc": "30% faster.",
    },
    "supercomputer": {
        "name": "Supercomputer", "for": ["data_centre", "research_institute"], "research": "machine_learning",
        "cost": {"electronics": 120, "gold": 300}, "produces": {"knowledge": 40},
        "desc": "+40 Knowledge per cycle.",
    },
    "extra_pumps": {
        "name": "Extra Pumps", "for": ["desalination_plant"],
        "cost": {"tools": 60, "electronics": 30}, "fertility_aura": 15,
        "desc": "+15 more fertility to the surrounding tiles.",
    },
    "superconductors": {
        "name": "Superconductors", "for": ["fusion_plant", "nuclear_plant", "tidal_array"], "research": "fusion_power",
        "cost": {"tools": 100, "electronics": 100}, "generates": 30,
        "desc": "+30 power.",
    },
    # ---- a second and third choice for most buildings ----
    "loft": {
        "name": "Sleeping Loft", "for": ["hut", "tavern", "stilt_house"],
        "cost": {"wood": 12}, "housing": 1,
        "desc": "Houses 1 more person.",
    },
    "guest_rooms": {
        "name": "Guest Rooms", "for": ["tavern", "bath_house", "caravanserai", "resort"], "research": "masonry",
        "cost": {"wood": 30, "stone": 20}, "housing": 3,
        "desc": "Houses 3 more people.",
    },
    "kitchen_garden": {
        "name": "Kitchen Garden", "for": ["house", "stilt_house"],
        "cost": {"wood": 10, "food": 15}, "housing": 1,
        "desc": "Room for 1 more person.",
    },
    "lifts": {
        "name": "Lifts", "for": ["apartments", "high_rise"], "research": "engineering",
        "cost": {"tools": 30, "gold": 60}, "housing": 8,
        "desc": "Houses 8 more people.",
    },
    "rooftop_gardens": {
        "name": "Rooftop Gardens", "for": ["apartments", "high_rise", "arcology"], "research": "botany",
        "cost": {"stone": 60, "gold": 40}, "housing": 6,
        "desc": "Houses 6 more people.",
    },
    "sky_bridges": {
        "name": "Sky Bridges", "for": ["arcology"],
        "cost": {"stone": 300, "electronics": 60}, "housing": 25,
        "desc": "Houses 25 more people.",
    },
    "maternity_ward": {
        "name": "Maternity Ward", "for": ["hospital"],
        "cost": {"stone": 120, "gold": 150}, "housing": 8,
        "desc": "Room for 8 more people.",
    },
    "compost_heap": {
        "name": "Compost Heap", "for": ["farm", "orchard", "terrace_farm", "rice_paddy"],
        "cost": {"food": 15}, "produces": {"food": 1},
        "desc": "+1 Food per cycle.",
    },
    "fishing_nets": {
        "name": "Fishing Nets", "for": ["fishing_dock", "fishery"],
        "cost": {"wood": 15}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "ice_house": {
        "name": "Ice House", "for": ["fishing_dock", "fishery", "hunting_lodge", "dairy", "butcher"], "research": "masonry",
        "cost": {"stone": 25}, "produces": {"food": 2},
        "desc": "+2 Food per cycle.",
    },
    "hunting_dogs": {
        "name": "Hunting Dogs", "for": ["hunting_lodge"], "research": "animal_taming",
        "cost": {"food": 10, "livestock": 1}, "speed": 1.25,
        "desc": "25% faster. Costs 1 livestock.",
    },
    "sheepdogs": {
        "name": "Sheepdogs", "for": ["pasture", "shepherds_hut", "ranch"], "research": "animal_taming",
        "cost": {"food": 10, "livestock": 1}, "speed": 1.15, "herd": 2,
        "desc": "15% faster and holds 2 more livestock. Costs 1 livestock.",
    },
    "grain_silo": {
        "name": "Grain Silo", "for": ["irrigated_farm", "industrial_farm"], "research": "engineering",
        "cost": {"stone": 60, "tools": 20}, "produces": {"food": 5},
        "desc": "+5 Food per cycle.",
    },
    "dry_dock": {
        "name": "Dry Dock", "for": ["harbor"], "research": "engineering",
        "cost": {"wood": 80, "stone": 60}, "produces": {"food": 3, "gold": 3},
        "desc": "+3 Food and +3 Gold per cycle.",
    },
    "saw_pit": {
        "name": "Saw Pit", "for": ["lumber_camp"],
        "cost": {"wood": 15}, "produces": {"wood": 1},
        "desc": "+1 Wood per cycle.",
    },
    "ox_cart": {
        "name": "Ox Cart", "for": ["lumber_camp", "quarry", "mine", "peat_cutter", "reed_cutter"], "research": "draft_animals",
        "cost": {"wood": 20, "livestock": 1}, "speed": 1.15,
        "desc": "15% faster. Costs 1 livestock.",
    },
    "stone_saw": {
        "name": "Stone Saw", "for": ["quarry"], "research": "masonry",
        "cost": {"wood": 25, "stone": 10}, "produces": {"stone": 1},
        "desc": "+1 Stone per cycle.",
    },
    "ore_carts": {
        "name": "Ore Carts", "for": ["mine", "deep_mine"], "research": "mechanics",
        "cost": {"wood": 40, "ore": 20}, "produces": {"ore": 2},
        "desc": "+2 Ore per cycle.",
    },
    "seasoning_shed": {
        "name": "Seasoning Shed", "for": ["sawmill"],
        "cost": {"wood": 40, "stone": 20}, "produces": {"wood": 3},
        "desc": "+3 Wood per cycle.",
    },
    "blast_furnace": {
        "name": "Blast Furnace", "for": ["smithy", "factory"], "research": "metallurgy",
        "cost": {"stone": 60, "ore": 30}, "produces": {"tools": 1},
        "desc": "+1 Tools per cycle.",
    },
    "tanning_pits": {
        "name": "Tanning Pits", "for": ["tannery"],
        "cost": {"wood": 20, "stone": 20}, "produces": {"gold": 2},
        "desc": "+2 Gold per cycle.",
    },
    "night_shift": {
        "name": "Night Shift", "for": ["factory", "recycling_centre", "electronics_plant", "container_port"],
        "cost": {"gold": 150}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "labour_saving": {
        "name": "Labour-Saving Machines", "for": ["sawmill", "smithy", "mine", "deep_mine", "factory", "fishery", "harbor", "steel_mill", "cement_works", "timber_yard"], "research": "mechanics",
        "cost": {"ore": 30, "tools": 10}, "workers": -1,
        "desc": "Needs 1 fewer worker.",
    },
    "automation": {
        "name": "Automation", "for": ["industrial_farm", "electronics_plant", "shopping_mall", "container_port", "recycling_centre", "research_institute", "vertical_farm", "nuclear_plant", "fusion_plant"], "research": "robotics",
        "cost": {"tools": 60, "electronics": 60}, "workers": -2,
        "desc": "Needs 2 fewer workers.",
    },
    "counting_house": {
        "name": "Counting House", "for": ["trading_post", "caravanserai", "salt_works", "weaver", "cattle_market", "zoo"],
        "cost": {"wood": 20, "stone": 20}, "produces": {"gold": 1},
        "desc": "+1 Gold per cycle.",
    },
    "caravan_yard": {
        "name": "Caravan Yard", "for": ["caravanserai", "trading_post", "stable"], "research": "draft_animals",
        "cost": {"wood": 40, "livestock": 1}, "explore_speed": 0.1,
        "desc": "Expeditions travel 10% faster. Costs 1 livestock.",
    },
    "steam_rooms": {
        "name": "Steam Rooms", "for": ["bath_house"],
        "cost": {"stone": 40}, "speed": 1.25,
        "desc": "25% faster.",
    },
    "annealing_oven": {
        "name": "Annealing Oven", "for": ["glassworks"],
        "cost": {"stone": 50, "ore": 20}, "produces": {"gold": 4},
        "desc": "+4 Gold per cycle.",
    },
    "herb_garden": {
        "name": "Herb Garden", "for": ["shaman_hut"],
        "cost": {"food": 15}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "apprentices": {
        "name": "Apprentices' Lodge", "for": ["shaman_hut", "school"],
        "cost": {"wood": 25, "food": 20}, "produces": {"knowledge": 1},
        "desc": "+1 Knowledge per cycle.",
    },
    "scriptorium": {
        "name": "Scriptorium", "for": ["school", "university"], "research": "bookkeeping",
        "cost": {"wood": 30, "stone": 30}, "produces": {"knowledge": 2},
        "desc": "+2 Knowledge per cycle.",
    },
    "lecture_hall": {
        "name": "Lecture Hall", "for": ["university", "laboratory"],
        "cost": {"stone": 80, "gold": 40}, "speed": 1.15,
        "desc": "15% faster.",
    },
    "telescope_dome": {
        "name": "Telescope Dome", "for": ["observatory"],
        "cost": {"stone": 50, "gold": 40}, "produces": {"knowledge": 4},
        "desc": "+4 Knowledge per cycle.",
    },
    "specialist_equipment": {
        "name": "Specialist Equipment", "for": ["laboratory"],
        "cost": {"tools": 30, "gold": 80}, "produces": {"knowledge": 10},
        "desc": "+10 Knowledge per cycle.",
    },
    "mill_race": {
        "name": "Mill Race", "for": ["water_mill", "hydro_dam"],
        "cost": {"stone": 30}, "generates": 2,
        "desc": "+2 power.",
    },
    "bigger_boiler": {
        "name": "Bigger Boiler", "for": ["steam_engine", "power_plant"], "research": "mechanics",
        "cost": {"ore": 40, "tools": 10}, "generates": 4,
        "desc": "+4 power.",
    },
    "taller_mast": {
        "name": "Taller Mast", "for": ["wind_turbine", "offshore_wind"],
        "cost": {"stone": 40, "tools": 15}, "generates": 3,
        "desc": "+3 power.",
    },
    "deep_bore": {
        "name": "Deep Bore", "for": ["geothermal_plant"],
        "cost": {"stone": 80, "tools": 30}, "generates": 6,
        "desc": "+6 power.",
    },
    "sun_trackers": {
        "name": "Sun Trackers", "for": ["solar_farm"],
        "cost": {"tools": 60, "gold": 80}, "generates": 6,
        "desc": "+6 power.",
    },
    "efficient_motors": {
        "name": "Efficient Motors", "for": ["sawmill", "smithy", "university", "fishery", "glassworks", "observatory", "harbor", "deep_mine"], "research": "mechanics",
        "cost": {"ore": 25, "tools": 10}, "power": -1,
        "desc": "Needs 1 less power.",
    },
    "smart_meters": {
        "name": "Smart Meters", "for": ["shopping_mall", "greenhouse", "vertical_farm", "data_centre", "research_institute", "drone_port", "factory", "laboratory", "steel_mill", "department_store", "stadium"], "research": "smart_grid",
        "cost": {"tools": 40, "gold": 100}, "power": -3,
        "desc": "Needs 3 less power.",
    },
    "cistern": {
        "name": "Cistern", "for": ["well", "desalination_plant"],
        "cost": {"stone": 25}, "fertility_aura": 5,
        "desc": "+5 more fertility to the surrounding tiles.",
    },
    "grindstones": {
        "name": "Extra Grindstones", "for": ["windmill"],
        "cost": {"stone": 30}, "aura_bonus": 0.05,
        "desc": "Surrounding farms get a further 5% faster.",
    },
    "fog_bell": {
        "name": "Fog Bell", "for": ["lighthouse"],
        "cost": {"ore": 15}, "aura_bonus": 0.05,
        "desc": "Surrounding water buildings get a further 5% faster.",
    },
    "hunters_hide": {
        "name": "Hunters' Hide", "for": ["salt_lick"],
        "cost": {"wood": 20}, "wildlife_speed": 0.25,
        "desc": "Wildlife appears a further 25% more often.",
    },
    "paddock": {
        "name": "Paddock", "for": ["stable"],
        "cost": {"wood": 30, "livestock": 2}, "explore_speed": 0.1,
        "desc": "Expeditions travel a further 10% faster. Costs 2 livestock.",
    },
    # ---- livestock ----
    "ox_plough": {
        "name": "Ox Plough", "for": ["farm", "terrace_farm", "irrigated_farm", "rice_paddy"], "research": "draft_animals",
        "cost": {"wood": 15, "livestock": 2}, "speed": 1.25,
        "desc": "25% faster. Costs 2 livestock.",
    },
    "stud_book": {
        "name": "Stud Book", "for": ["breeding_pen", "cattle_market"],
        "cost": {"wood": 20, "gold": 20}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "petting_corner": {
        "name": "Petting Corner", "for": ["zoo"],
        "cost": {"wood": 40, "livestock": 4}, "attracts": 1,
        "desc": "One more extra arrival per meal. Costs 4 livestock.",
    },
    "guard_dogs": {
        "name": "Guard Dogs", "for": ["trading_post", "caravanserai", "cattle_market", "salt_works"], "research": "animal_taming",
        "cost": {"food": 20, "livestock": 1}, "produces": {"gold": 1},
        "desc": "+1 Gold per cycle: less goes missing. Costs 1 livestock.",
    },
    "pack_mules": {
        "name": "Pack Mules", "for": ["mine", "quarry", "salt_works", "peat_cutter"], "research": "draft_animals",
        "cost": {"wood": 15, "livestock": 2}, "speed": 1.2,
        "desc": "20% faster. Costs 2 livestock.",
    },
    # ---- beasts ----
    "warm_bedding": {
        "name": "Warm Bedding", "for": ["beast_den"],
        "cost": {"wood": 20, "food": 20}, "beast_xp": 0.25,
        "desc": "Missions give a further 25% more experience.",
    },
    "trophy_wall": {
        "name": "Trophy Wall", "for": ["beast_den", "training_ground"],
        "cost": {"wood": 30, "gold": 10}, "beast_power": 0.05,
        "desc": "Your beast's bonus is a further 5% stronger.",
    },
    "heat_stones": {
        "name": "Heat Stones", "for": ["incubator"],
        "cost": {"stone": 25}, "hatch_speed": 0.5,
        "desc": "Eggs hatch faster still.",
    },
    "nest_boxes": {
        "name": "Nest Boxes", "for": ["incubator", "beast_den"],
        "cost": {"wood": 25}, "egg_chance": 0.03,
        "desc": "Expeditions are 3 points likelier to find an egg.",
    },
    "obstacle_course": {
        "name": "Obstacle Course", "for": ["training_ground"],
        "cost": {"wood": 60, "stone": 40}, "beast_power": 0.1,
        "desc": "Your beast's bonus is a further 10% stronger.",
    },
    "handlers_lodge": {
        "name": "Handlers' Lodge", "for": ["training_ground", "beast_sanctuary"],
        "cost": {"wood": 50, "stone": 30}, "beast_xp": 0.25,
        "desc": "Missions give a further 25% more experience.",
    },
    "quiet_grove": {
        "name": "Quiet Grove", "for": ["beast_sanctuary", "incubator"],
        "cost": {"wood": 80, "gold": 60}, "mission_speed": 0.25,
        "desc": "Missions come a further 25% more often.",
    },
    # ---- City ----
    "attic_rooms": {
        "name": "Attic Rooms", "for": ["townhouses"],
        "cost": {"wood": 60, "tools": 10}, "housing": 3,
        "desc": "Houses 3 more people.",
    },
    "sewers": {
        "name": "Sewers", "for": ["townhouses", "apartments", "house"], "research": "sanitation",
        "cost": {"stone": 80, "tools": 15}, "housing": 5,
        "desc": "Houses 5 more people.",
    },
    "public_square": {
        "name": "Public Square", "for": ["city_hall"],
        "cost": {"stone": 200, "gold": 100}, "attracts": 1,
        "desc": "One more extra arrival per meal.",
    },
    "records_office": {
        "name": "Records Office", "for": ["city_hall"],
        "cost": {"stone": 120, "tools": 30}, "aura_bonus": 0.1,
        "desc": "Surrounding shops and places of learning get a further 10% faster.",
    },
    "clock_tower": {
        "name": "Clock Tower", "for": ["city_hall", "train_station"],
        "cost": {"stone": 100, "tools": 40, "gold": 60}, "aura_bonus": 0.05,
        "desc": "Everyone is on time: the buildings it speeds up get a further 5% faster.",
    },
    "goods_yard": {
        "name": "Goods Yard", "for": ["train_station"],
        "cost": {"stone": 120, "ore": 60, "tools": 30}, "aura_bonus": 0.1,
        "desc": "Surrounding industry gets a further 10% faster.",
    },
    "sleeper_cars": {
        "name": "Sleeper Cars", "for": ["train_station"],
        "cost": {"wood": 80, "tools": 30, "gold": 80}, "explore_speed": 0.1,
        "desc": "Expeditions travel a further 10% faster.",
    },
    "second_berth": {
        "name": "Second Berth", "for": ["ferry_terminal"],
        "cost": {"wood": 100, "stone": 60}, "attracts": 1,
        "desc": "One more extra arrival per meal.",
    },
    "night_crossings": {
        "name": "Night Crossings", "for": ["ferry_terminal"],
        "cost": {"tools": 20, "gold": 60}, "explore_speed": 0.1,
        "desc": "Expeditions travel a further 10% faster.",
    },
    "filter_beds": {
        "name": "Filter Beds", "for": ["waterworks"],
        "cost": {"stone": 100, "tools": 15}, "fertility_aura": 10,
        "desc": "A further +10 fertility for the surrounding tiles.",
    },
    "water_tower": {
        "name": "Water Tower", "for": ["waterworks"],
        "cost": {"stone": 80, "ore": 40, "tools": 20}, "fertility_aura": 15,
        "desc": "A further +15 fertility for the surrounding tiles.",
    },
    "blast_furnace": {
        "name": "Blast Furnace", "for": ["steel_mill"],
        "cost": {"stone": 150, "ore": 60, "tools": 30}, "speed": 1.3,
        "desc": "30% faster.",
    },
    "rolling_mill": {
        "name": "Rolling Mill", "for": ["steel_mill"],
        "cost": {"ore": 80, "tools": 40, "gold": 60}, "produces": {"tools": 3},
        "desc": "+3 Tools per cycle.",
    },
    "rotary_kiln": {
        "name": "Rotary Kiln", "for": ["cement_works"],
        "cost": {"ore": 60, "tools": 30}, "speed": 1.25,
        "desc": "25% faster.",
    },
    "aggregate_pit": {
        "name": "Aggregate Pit", "for": ["cement_works"],
        "cost": {"wood": 60, "tools": 20}, "produces": {"stone": 5},
        "desc": "+5 Stone per cycle.",
    },
    "band_saws": {
        "name": "Band Saws", "for": ["timber_yard", "sawmill"], "research": "forestry",
        "cost": {"ore": 40, "tools": 25}, "speed": 1.25,
        "desc": "25% faster.",
    },
    "replanting": {
        "name": "Replanting", "for": ["timber_yard"],
        "cost": {"food": 100, "wood": 60}, "produces": {"wood": 5},
        "desc": "+5 Wood per cycle.",
    },
    "cold_store": {
        "name": "Cold Store", "for": ["cannery", "harbor"], "research": "canning",
        "cost": {"stone": 80, "tools": 25}, "produces": {"food": 6},
        "desc": "+6 Food per cycle.",
    },
    "labelling_line": {
        "name": "Labelling Line", "for": ["cannery"],
        "cost": {"tools": 25, "gold": 50}, "produces": {"gold": 5},
        "desc": "+5 Gold per cycle.",
    },
    "tall_chimney": {
        "name": "Tall Chimney", "for": ["coal_plant", "power_plant"], "research": "steam_turbines",
        "cost": {"stone": 150, "tools": 20}, "generates": 6,
        "desc": "+6 power.",
    },
    "sea_wall": {
        "name": "Sea Wall", "for": ["tidal_generator"],
        "cost": {"stone": 200, "tools": 20}, "generates": 4,
        "desc": "+4 power.",
    },
    "window_displays": {
        "name": "Window Displays", "for": ["department_store"],
        "cost": {"wood": 40, "gold": 80}, "produces": {"gold": 6},
        "desc": "+6 Gold per cycle.",
    },
    "delivery_vans": {
        "name": "Delivery Vans", "for": ["department_store"], "research": "mass_production",
        "cost": {"tools": 40, "gold": 60}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "extra_stands": {
        "name": "Extra Stands", "for": ["stadium"],
        "cost": {"stone": 250, "tools": 40}, "attracts": 1,
        "desc": "One more extra arrival per meal.",
    },
    "floodlights": {
        "name": "Floodlights", "for": ["stadium"], "research": "electricity",
        "cost": {"ore": 60, "tools": 40, "gold": 100}, "produces": {"gold": 10}, "power": 2,
        "desc": "Evening matches: +10 Gold per cycle, for 2 more power.",
    },
    "special_exhibits": {
        "name": "Special Exhibits", "for": ["museum"],
        "cost": {"gold": 150}, "produces": {"gold": 8},
        "desc": "+8 Gold per cycle.",
    },
    "archive": {
        "name": "Archive", "for": ["museum"],
        "cost": {"stone": 100, "tools": 20, "gold": 60}, "produces": {"knowledge": 6},
        "desc": "+6 Knowledge per cycle.",
    },
    # ---- shelter from the night and the weather ----
    # night_proof / weather_proof: share of the slowdowns night (or the weather) causes this building that it no longer has
    "lanterns": {
        "name": "Lanterns", "research": "street_lighting",
        "for": ["lumber_camp", "quarry", "mine", "sawmill", "smithy", "trading_post", "caravanserai", "weaver",
                "tannery", "glassworks", "salt_works", "peat_cutter", "reed_cutter", "bamboo_workshop", "cattle_market"],
        "cost": {"wood": 20, "ore": 5, "gold": 10}, "night_proof": 1.0,
        "desc": "Work goes on after dark: night no longer slows it.",
    },
    "work_lights": {
        "name": "Work Lights", "research": "electricity",
        "for": ["factory", "steel_mill", "deep_mine", "cement_works", "timber_yard", "electronics_plant", "recycling_centre",
                "robotics_factory", "container_port", "harbor", "department_store", "shopping_mall", "crystal_mine"],
        "cost": {"ore": 30, "tools": 20}, "night_proof": 1.0, "power": 1,
        "desc": "Floodlit night shifts: night no longer slows it. Uses 1 more power.",
    },
    "cold_frames": {
        "name": "Cold Frames", "research": "glassmaking",
        "for": ["farm", "orchard", "terrace_farm", "irrigated_farm", "rice_paddy", "industrial_farm", "apiary", "forager_camp"],
        "cost": {"wood": 30, "gold": 20}, "weather_proof": 1.0,
        "desc": "Glass covers over the beds: bad weather no longer slows it.",
    },
    "field_lights": {
        "name": "Field Lights", "research": "electricity",
        "for": ["farm", "orchard", "terrace_farm", "irrigated_farm", "rice_paddy", "industrial_farm"],
        "cost": {"ore": 30, "tools": 20}, "night_proof": 0.7, "power": 2,
        "desc": "Lamps over the crops: most of night's slowdown is gone. Uses 2 power.",
    },
    "storm_hulls": {
        "name": "Storm Hulls", "research": "navigation",
        "for": ["fishing_dock", "fishery", "harbor", "pearl_divers", "kelp_gatherers", "kelp_farm"],
        "cost": {"wood": 40, "ore": 10}, "weather_proof": 1.0,
        "desc": "Boats built for rough water: bad weather no longer slows it.",
    },
    "covered_pens": {
        "name": "Covered Pens", "research": "masonry",
        "for": ["pasture", "dairy", "breeding_pen", "shepherds_hut", "ranch", "cattle_market"],
        "cost": {"wood": 30, "stone": 20}, "weather_proof": 1.0,
        "desc": "Shelter for the animals: bad weather no longer slows it.",
    },
    "snow_cannons": {
        "name": "Snow Cannons", "for": ["ski_resort"], "research": "electricity",
        "cost": {"tools": 40, "gold": 60}, "weather_proof": 1.0, "power": 2,
        "desc": "Makes its own snow: bad weather no longer slows it (a blizzard still shuts it).",
    },
    # ---- for the buildings of the wider world ----
    "carved_rooms": {
        "name": "Carved Rooms", "for": ["cave_dwelling"], "research": "caving",
        "cost": {"wood": 15, "stone": 10}, "housing": 3,
        "desc": "Houses 3 more people.",
    },
    "foraging_baskets": {
        "name": "Foraging Baskets", "for": ["forager_camp"],
        "cost": {"wood": 10}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "more_hives": {
        "name": "More Hives", "for": ["apiary"],
        "cost": {"wood": 25}, "produces": {"food": 2, "gold": 2}, "aura_bonus": 0.05,
        "desc": "+2 Food and +2 Gold per cycle, and the farms around it get a further 5% faster.",
    },
    "spore_beds": {
        "name": "Spore Beds", "for": ["mushroom_cave"],
        "cost": {"wood": 20, "food": 10}, "speed": 1.3,
        "desc": "30% faster.",
    },
    "drying_lines": {
        "name": "Drying Lines", "for": ["kelp_gatherers", "kelp_farm"],
        "cost": {"wood": 20}, "produces": {"food": 3},
        "desc": "+3 Food per cycle.",
    },
    "signal_fire": {
        "name": "Signal Fire", "for": ["lookout_tower"],
        "cost": {"wood": 30}, "explore_speed": 0.05,
        "desc": "Expeditions a further 5% faster.",
    },
    "rain_gauges": {
        "name": "Rain Gauges", "for": ["weather_station"],
        "cost": {"ore": 10, "gold": 10}, "produces": {"knowledge": 3},
        "desc": "+3 Knowledge per cycle.",
    },
    "radar_dish": {
        "name": "Radar Dish", "for": ["weather_station"], "research": "electricity",
        "cost": {"tools": 30, "gold": 40}, "speed": 1.3, "power": 2,
        "desc": "30% faster, for 2 power.",
    },
    "lantern_alley": {
        "name": "Lantern Alley", "for": ["night_market"],
        "cost": {"wood": 30, "gold": 20}, "produces": {"gold": 4},
        "desc": "+4 Gold per cycle.",
    },
    "diving_bells": {
        "name": "Diving Bells", "for": ["pearl_divers"], "research": "engineering",
        "cost": {"ore": 30, "tools": 10}, "speed": 1.3,
        "desc": "30% faster.",
    },
    "bamboo_scaffolds": {
        "name": "Bamboo Scaffolds", "for": ["bamboo_workshop"],
        "cost": {"wood": 20}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "ice_cellar": {
        "name": "Ice Cellar", "for": ["ice_works"],
        "cost": {"stone": 30}, "produces": {"food": 3},
        "desc": "+3 Food per cycle.",
    },
    "crystal_oscillators": {
        "name": "Crystal Oscillators", "for": ["crystal_mine"], "research": "semiconductors",
        "cost": {"tools": 60, "gold": 80}, "produces": {"electronics": 3},
        "desc": "+3 Electronics per cycle.",
    },
    "chalets": {
        "name": "Chalets", "for": ["ski_resort"],
        "cost": {"wood": 80, "gold": 40}, "housing": 6,
        "desc": "Houses 6 people.",
    },
    "shark_tunnel": {
        "name": "Shark Tunnel", "for": ["aquarium"],
        "cost": {"stone": 80, "tools": 20, "gold": 60}, "produces": {"gold": 6},
        "desc": "+6 Gold per cycle.",
    },
    "climate_control": {
        "name": "Climate Control", "for": ["biodome", "polar_station"], "research": "smart_grid",
        "cost": {"tools": 60, "electronics": 20}, "speed": 1.2,
        "desc": "20% faster.",
    },
    "star_shows": {
        "name": "Star Shows", "for": ["planetarium", "observatory"],
        "cost": {"gold": 80}, "produces": {"gold": 8},
        "desc": "+8 Gold per cycle.",
    },
    "roller_coaster": {
        "name": "Roller Coaster", "for": ["theme_park"],
        "cost": {"tools": 150, "gold": 300}, "attracts": 1,
        "desc": "One more extra arrival per meal.",
    },
    "night_parade": {
        "name": "Night Parade", "for": ["theme_park", "night_market", "stadium"],
        "cost": {"gold": 120}, "produces": {"gold": 10},
        "desc": "+10 Gold per cycle.",
    },
    "ice_cores": {
        "name": "Ice Core Store", "for": ["polar_station"],
        "cost": {"tools": 40}, "produces": {"knowledge": 8},
        "desc": "+8 Knowledge per cycle.",
    },
    "launch_pad": {
        "name": "Second Launch Pad", "for": ["spaceport"],
        "cost": {"tools": 300, "electronics": 200}, "produces": {"gold": 40}, "explore_speed": 0.1,
        "desc": "+40 Gold per cycle, and expeditions a further 10% faster.",
    },
    "pressure_domes": {
        "name": "Pressure Domes", "for": ["ocean_habitat"],
        "cost": {"tools": 100, "electronics": 60}, "housing": 20,
        "desc": "Houses 20 more people.",
    },
    "cryo_cooling": {
        "name": "Cryo Cooling", "for": ["quantum_lab", "data_centre"],
        "cost": {"tools": 80, "electronics": 60}, "speed": 1.25, "power": 4,
        "desc": "25% faster, for 4 more power.",
    },
    # ---- for buildings whose work is a city-wide effect ----
    "map_room": {
        "name": "Map Room", "for": ["expedition_camp", "explorers_guild", "lookout_tower"], "research": "cartography",
        "cost": {"wood": 80, "stone": 40, "gold": 40}, "exp_queue": 1,
        "desc": "Charts pinned to every wall: one more expedition can wait in the queue.",
    },
    "supply_depot": {
        "name": "Supply Depot", "for": ["expedition_camp", "explorers_guild", "ferry_terminal", "airport"],
        "cost": {"wood": 60, "stone": 30}, "explore_speed": 0.1,
        "desc": "Packs ready to go: expeditions travel 10% faster.",
    },
    "satellite_mapping": {
        "name": "Satellite Mapping", "for": ["orbital_mirror", "weather_control", "spaceport", "airport", "planetarium"],
        "research": "aviation", "cost": {"tools": 40, "electronics": 40, "gold": 200}, "explore_speed": 0.15,
        "desc": "Pictures of the land from far above: expeditions travel 15% faster.",
    },
    "reinforced_walls": {
        "name": "Reinforced Walls", "for": ["storm_barrier", "desalination_plant", "tidal_array"],
        "cost": {"stone": 300, "tools": 60}, "weather_shelter": 0.15,
        "desc": "Thicker sea walls: bad weather slows the whole city 15% less.",
    },
    "aurora_lamps": {
        "name": "Aurora Lamps", "for": ["weather_control", "orbital_mirror", "storm_barrier"], "research": "electricity",
        "cost": {"tools": 40, "electronics": 20, "gold": 100}, "night_shelter": 0.1,
        "desc": "Soft light over the streets all night: night slows the whole city 10% less.",
    },
    "focused_beam": {
        "name": "Focused Beam", "for": ["orbital_mirror"],
        "cost": {"electronics": 100, "gold": 500}, "night_shelter": 0.15,
        "desc": "The mirrors turned to light the city alone: night slows it a further 15% less.",
    },
    "cloud_seeding": {
        "name": "Cloud Seeding", "for": ["weather_control", "orbital_mirror", "waterworks", "well", "desalination_plant"],
        "research": "meteorology", "cost": {"stone": 80, "tools": 20, "gold": 40}, "fertility_aura": 15,
        "desc": "Rain where it is wanted: +15 fertility on the 8 tiles around it.",
    },
    "promenade": {
        "name": "Promenade", "for": ["storm_barrier", "ferry_terminal", "lighthouse", "desalination_plant"],
        "cost": {"stone": 120, "gold": 60}, "attracts": 1,
        "desc": "A walk along the water, with benches and stalls: one more arrival per meal.",
    },
    "bird_hides": {
        "name": "Bird Hides", "for": ["wetland_reserve", "lookout_tower", "salt_lick", "zoo"],
        "cost": {"wood": 40, "stone": 10}, "wildlife_speed": 0.25,
        "desc": "Quiet hides at the water's edge: wild animals appear 25% more often.",
    },
    "digester_tanks": {
        "name": "Digester Tanks", "for": ["biogas_plant"], "research": "recycling",
        "cost": {"stone": 120, "tools": 40}, "generates": 6,
        "desc": "More tanks to catch the marsh gas: 6 more power.",
    },
    "spore_beds": {
        "name": "Spore Beds", "for": ["mushroom_cave", "herb_fen"],
        "cost": {"wood": 30, "food": 20}, "speed": 1.25,
        "desc": "Racks of rich, damp beds: 25% faster.",
    },
    "kelp_gardens": {
        "name": "Kelp Gardens", "for": ["ocean_habitat"], "research": "marine_habitats",
        "cost": {"stone": 400, "electronics": 60}, "housing": 10,
        "desc": "Gardens grown in the water around the domes: houses 10 more people.",
    },
    "lean_to": {
        "name": "Lean-To", "for": ["hut", "cave_dwelling", "shepherds_hut"],
        "cost": {"wood": 12}, "housing": 1,
        "desc": "A sloping roof against one wall: houses 1 more person.",
    },
    "extra_sails": {
        "name": "Extra Sails", "for": ["windmill"], "research": "mechanics",
        "cost": {"wood": 60, "tools": 10}, "aura_bonus": 0.1,
        "desc": "Longer sails catch more wind: the farms around it get a further 10% faster.",
    },
    "brighter_lamp": {
        "name": "Brighter Lamp", "for": ["lighthouse"], "research": "glassmaking",
        "cost": {"stone": 40, "ore": 10, "gold": 30}, "aura_bonus": 0.1,
        "desc": "A bigger lens: the fishing and harbours around it get a further 10% faster.",
    },
    "pressure_locks": {
        "name": "Pressure Locks", "for": ["ocean_habitat"],
        "cost": {"stone": 300, "tools": 100}, "housing": 8,
        "desc": "More doors to the sea, so more domes can join on: houses 8 more people.",
    },
}

# Existing additions that also fit these buildings (the newer ones, and those that had few to choose from).
ADDITIONS_MORE = {
    "lanterns": ["eel_traps", "herb_fen", "leatherworks", "bog_iron", "chicken_coop", "forager_camp", "butcher", "kelp_gatherers"],
    "work_lights": ["meat_packing", "livestock_complex", "stockyard", "bog_iron", "crystal_mine", "algae_bioreactor"],
    "cold_frames": ["cranberry_bog", "herb_fen"],
    "covered_pens": ["chicken_coop", "stockyard", "livestock_complex"],
    "feeding_trough": ["chicken_coop", "stockyard", "livestock_complex", "ranch", "shepherds_hut"],
    "sheepdogs": ["stockyard"],
    "drying_racks": ["leatherworks", "herb_fen"],
    "smokehouse": ["eel_traps"],
    "ice_house": ["eel_traps", "meat_packing", "cranberry_bog"],
    "tool_shed": ["eel_traps", "forager_camp"],
    "support_beams": ["bog_iron", "crystal_mine"],
    "compost_heap": ["cranberry_bog"],
    "field_lights": ["cranberry_bog"],
    "assembly_line": ["meat_packing", "leatherworks"],
    "smart_meters": ["algae_bioreactor", "livestock_complex", "meat_packing", "biodome", "planetarium", "aquarium",
                     "crystal_mine", "quantum_lab", "polar_station", "museum"],
    "automation": ["meat_packing", "livestock_complex", "algae_bioreactor", "spaceport"],
    "labour_saving": ["bog_iron", "leatherworks", "stockyard", "crystal_mine", "kelp_farm", "mushroom_cave", "ice_works", "biogas_plant"],
    "transformer": ["biogas_plant", "water_mill", "steam_engine", "solar_farm", "offshore_wind", "tidal_array"],
    "counting_house": ["leatherworks", "herb_fen", "pearl_divers", "night_market", "ice_works"],
    "market_stalls": ["herb_fen", "cranberry_bog", "leatherworks", "ice_works", "night_market", "museum", "wetland_reserve"],
    "advertising": ["wetland_reserve", "aquarium", "museum", "ski_resort", "spaceport"],
    "food_court": ["museum", "aquarium", "spaceport", "ocean_habitat"],
    "guest_rooms": ["ski_resort"],
    "library": ["herb_fen", "museum", "planetarium", "weather_station", "polar_station"],
    "clean_room": ["quantum_lab", "algae_bioreactor", "biodome", "polar_station", "crystal_mine"],
    "extra_room": ["cave_dwelling", "shepherds_hut"],
    "loft": ["cave_dwelling"],
    "plumbing": ["hospital"],
    "warm_bedding": ["nesting_ground"],
    "heat_stones": ["nesting_ground"],
    "nest_boxes": ["nesting_ground"],
    "caravan_yard": ["expedition_camp", "explorers_guild", "ferry_terminal", "lookout_tower"],
}
# Additions for the rare-tile buildings and the electronics buildings that nothing else fitted.
ADDITIONS.update({
    "wafer_line": {"name": "Wafer Line", "research": "semiconductors", "for": [],
                   "cost": {"tools": 150, "electronics": 40, "gold": 200}, "speed": 1.3, "desc": "30% faster."},
    "yield_testing": {"name": "Yield Testing", "research": "computing", "for": [],
                      "cost": {"tools": 80, "gold": 150}, "produces": {"electronics": 2}, "desc": "2 more electronics each cycle: fewer chips thrown away."},
    "sorting_robots": {"name": "Sorting Robots", "research": "robotics", "for": [],
                       "cost": {"tools": 120, "electronics": 60}, "speed": 1.4, "desc": "40% faster."},
    "heated_floors": {"name": "Heated Floors", "for": [],
                      "cost": {"stone": 60, "tools": 20}, "speed": 1.25, "desc": "Spring water piped under the floor: 25% faster."},
    "mineral_baths": {"name": "Mineral Baths", "for": [],
                      "cost": {"stone": 80, "gold": 60}, "produces": {"gold": 6}, "desc": "6 more gold each cycle from bathers."},
    "deep_casing": {"name": "Deep Casing", "research": "engineering", "for": [],
                    "cost": {"stone": 300, "tools": 120}, "generates": 20, "desc": "A deeper, lined bore: 20 more power."},
    "glass_bottom_boats": {"name": "Glass-Bottom Boats", "for": [],
                           "cost": {"wood": 80, "gold": 80}, "produces": {"gold": 10}, "desc": "10 more gold each cycle from sightseers."},
    "polishing_wheels": {"name": "Polishing Wheels", "for": [],
                         "cost": {"stone": 60, "tools": 30}, "produces": {"gold": 3}, "desc": "3 more gold each cycle from polished crystal."},
    "resonance_chamber": {"name": "Resonance Chamber", "research": "semiconductors", "for": [],
                          "cost": {"stone": 200, "tools": 100, "gold": 150}, "speed": 1.25, "desc": "Crystal tuned to ring true: 25% faster."},
    "lava_channels": {"name": "Lava Channels", "for": [],
                      "cost": {"stone": 120, "tools": 40}, "speed": 1.3, "desc": "Molten rock led right to the work: 30% faster."},
    "heat_exchangers": {"name": "Heat Exchangers", "research": "engineering", "for": [],
                        "cost": {"stone": 400, "tools": 200, "electronics": 50}, "generates": 40, "desc": "40 more power from the same heat."},
    "gift_shop": {"name": "Gift Shop", "for": [],
                  "cost": {"wood": 60, "gold": 60}, "produces": {"gold": 6}, "desc": "6 more gold each cycle from visitors."},
    "more_floors": {"name": "More Floors", "research": "engineering", "for": [],
                    "cost": {"stone": 200, "tools": 60, "gold": 100}, "housing": 15, "desc": "Houses 15 more."},
})
# A third choice for the buildings that had two.
for _aid, _more in {"market_stalls": ["apiary"], "drying_racks": ["bamboo_workshop"], "warm_bedding": ["beast_sanctuary"],
                    "nest_boxes": ["beast_sanctuary"], "ice_house": ["mushroom_cave"], "advertising": ["maglev_hub"],
                    "guest_rooms": ["theme_park"], "food_court": ["theme_park"],
                    "labour_saving": ["coal_plant", "geothermal_plant", "hydro_dam", "tidal_generator", "bamboo_workshop",
                                      "open_pit_mine", "aggregate_plant", "precision_works"],
                    "support_beams": ["open_pit_mine", "deep_core_drill"],
                    "work_lights": ["open_pit_mine", "aggregate_plant", "precision_works", "deep_core_drill"],
                    "smart_meters": ["precision_works", "deep_core_drill", "aggregate_plant"],
                    "automation": ["deep_core_drill", "precision_works"],
                    "assembly_line": ["precision_works"], "clean_room": ["precision_works"]}.items():
    ADDITIONS_MORE[_aid] = ADDITIONS_MORE.get(_aid, []) + _more
for _aid, _more in ADDITIONS_MORE.items():
    ADDITIONS[_aid]["for"] += [b for b in _more if b not in ADDITIONS[_aid]["for"]]
# Additions for the rare-tile buildings (each has at least three to choose two from) and the electronics buildings.
for _aid, _more in {
    "heated_floors": ["geothermal_greenhouse", "thermal_fish_farm", "thermal_spa_hotel"],
    "mineral_baths": ["thermal_spa_hotel", "bath_house", "thermal_fountain"],
    "deep_casing": ["deep_geothermal_well", "magma_tap"],
    "glass_bottom_boats": ["dive_resort", "reef_research_station"],
    "polishing_wheels": ["crystal_grotto", "lens_grinders", "crystal_mine"],
    "resonance_chamber": ["resonance_lab", "crystal_lattice_core"],
    "lava_channels": ["magma_forge", "obsidian_workshop", "basalt_quarry"],
    "heat_exchangers": ["magma_tap", "deep_geothermal_well"],
    "gift_shop": ["canopy_walkway", "canyon_skywalk", "speed_trials_track", "cliffside_hotel", "oasis_bazaar", "spring_shrine",
                  "druid_circle", "fossil_dig", "elder_tree_sanctuary", "heather_distillery"],
    "more_floors": ["undercity", "living_spire", "bamboo_towers"],
    "wafer_line": ["electronics_plant", "chip_fab", "nano_assembler", "electronics_workshop"],
    "yield_testing": ["electronics_plant", "chip_fab", "nano_assembler", "electronics_workshop", "ewaste_recycler", "lithium_brine_works"],
    "sorting_robots": ["ewaste_recycler"],
    "labour_saving": ["geothermal_greenhouse", "thermal_fish_farm", "drying_house", "sulphur_works", "magma_forge", "heartwood_loggers",
                      "bamboo_scaffolders", "volcano_observatory", "reef_research_station", "electronics_workshop", "ewaste_recycler"],
    "automation": ["reef_biolab", "crystal_lattice_core", "desert_botanic_garden", "thermal_spa_hotel", "dive_resort", "chip_fab",
                   "nano_assembler", "lithium_brine_works", "cryo_vault"],
    "assembly_line": ["drying_house", "magma_forge", "obsidian_workshop", "bamboo_scaffolders", "salt_curing_house", "electronics_workshop",
                      "chip_fab", "ewaste_recycler"],
    "clean_room": ["resonance_lab", "crystal_lattice_core", "reef_biolab", "lens_grinders", "chip_fab", "nano_assembler", "cave_data_vault"],
    "smart_meters": ["reef_biolab", "crystal_lattice_core", "resonance_lab", "cave_data_vault", "cryo_vault", "lithium_brine_works",
                     "oasis_waterworks", "chip_fab", "nano_assembler", "ewaste_recycler"],
    "work_lights": ["basalt_quarry", "sulphur_works", "heartwood_loggers", "silt_farm", "hillside_vineyard", "ash_vineyard",
                    "date_palm_grove", "bamboo_cutters", "charcoal_kilns", "silt_brickworks", "salt_curing_house"],
    "lanterns": ["oasis_bazaar", "canopy_walkway", "heather_distillery", "cliffside_hotel", "crab_traps", "reef_fishers",
                 "seabird_egg_gatherers", "boatyard", "beachcombers", "dune_caravan_camp"],
    "market_stalls": ["ash_vineyard", "date_palm_grove", "hillside_vineyard", "heather_distillery", "beachcombers", "oasis_bazaar"],
    "advertising": ["canyon_skywalk", "speed_trials_track", "dive_resort", "thermal_spa_hotel", "sand_glassworks"],
    "promenade": ["thermal_fountain"],
    "library": ["spring_shrine", "crystal_grotto", "druid_circle", "cave_archive", "fossil_dig", "lens_grinders"],
    "scriptorium": ["spring_shrine", "crystal_grotto", "druid_circle", "cave_archive"],
    "supercomputer": ["cave_data_vault", "cryo_vault", "crystal_lattice_core", "reef_biolab"],
    "specialist_equipment": ["reef_research_station", "volcano_observatory", "fossil_dig", "desert_botanic_garden", "cave_archive"],
    "drying_lines": ["seabird_egg_gatherers"],
    "transformer": ["deep_geothermal_well", "magma_tap", "biomass_plant", "kelp_biorefinery", "mesa_solar_array", "dune_solar_field"],
    "sun_trackers": ["mesa_solar_array", "dune_solar_field"],
    "battery_bank": ["mesa_solar_array", "dune_solar_field", "kelp_biorefinery"],
    "tall_chimney": ["biomass_plant"],
    "digester_tanks": ["biomass_plant", "kelp_biorefinery"],
    "fishing_nets": ["reef_fishers", "crab_traps", "thermal_fish_farm"],
    "storm_hulls": ["reef_fishers", "crab_traps", "boatyard"],
    "support_beams": ["basalt_quarry", "sulphur_works"],
    "ore_carts": ["sulphur_works"],
    "stone_saw": ["basalt_quarry", "silt_brickworks"],
    "irrigation_pipes": ["silt_farm", "date_palm_grove", "ash_vineyard", "hillside_vineyard", "mangrove_nursery", "oasis_waterworks"],
    "scarecrow": ["silt_farm", "hillside_vineyard", "ash_vineyard"],
    "cold_frames": ["ash_vineyard", "date_palm_grove", "hillside_vineyard", "silt_farm"],
    "drying_racks": ["drying_house", "mangrove_nursery"],
    "cold_store": ["thermal_fish_farm", "geothermal_greenhouse", "salt_curing_house"],
    "grow_lamps": ["geothermal_greenhouse", "oasis_waterworks"],
    "climate_control": ["geothermal_greenhouse", "cave_data_vault", "thermal_spa_hotel", "desert_botanic_garden"],
    "penthouses": ["undercity", "living_spire", "bamboo_towers"],
    "lifts": ["undercity", "living_spire", "bamboo_towers"],
    "rooftop_gardens": ["living_spire", "bamboo_towers", "mesa_pueblo"],
    "carved_rooms": ["cliff_dwellings", "undercity"],
    "guest_rooms": ["cliff_dwellings", "mesa_pueblo", "cliffside_hotel", "dive_resort"],
    "sewers": ["undercity", "mesa_pueblo", "cliff_dwellings"],
    "bird_hides": ["druid_circle", "blue_carbon_reserve", "canopy_walkway"],
    "quiet_grove": ["elder_tree_sanctuary"],
    "warm_bedding": ["elder_tree_sanctuary"],
    "caravan_yard": ["dune_caravan_camp", "oasis_bazaar"],
    "supply_depot": ["boatyard", "dune_caravan_camp"],
    "crystal_oscillators": ["resonance_lab", "crystal_lattice_core"],
    "diving_bells": ["reef_research_station", "reef_biolab"],
    "blast_furnace": ["magma_forge"],
    "annealing_oven": ["obsidian_workshop", "sand_glassworks"],
    "rotary_kiln": ["sand_glassworks"],
    "night_parade": ["canyon_skywalk", "speed_trials_track"],
    "steam_rooms": ["thermal_spa_hotel", "drying_house"],
    "spore_beds": ["cheese_cave"],
    "ice_cellar": ["cheese_cave"],
    "labelling_line": ["salt_curing_house", "heather_distillery", "cheese_cave"],
    "totem": ["spring_shrine", "druid_circle"],
    "extra_pumps": ["oasis_waterworks", "thermal_fountain"],
    "cistern": ["thermal_fountain"],
    "deep_bore": ["deep_geothermal_well", "magma_tap"],
    "band_saws": ["heartwood_loggers", "bamboo_cutters", "bamboo_scaffolders"],
    "replanting": ["heartwood_loggers", "mangrove_nursery", "bamboo_cutters"],
    "seasoning_shed": ["bamboo_cutters", "charcoal_kilns"],
    "special_exhibits": ["fossil_dig"],
    "shark_tunnel": ["dive_resort"],
    "star_shows": ["volcano_observatory"],
    "tool_shed": ["charcoal_kilns", "silt_brickworks", "beachcombers", "seabird_egg_gatherers", "crab_traps", "reef_fishers",
                  "bamboo_cutters", "ash_vineyard", "date_palm_grove", "silt_farm"],
    "counting_house": ["dune_caravan_camp", "boatyard", "salt_curing_house", "lithium_brine_works", "blue_carbon_reserve"],
    "hunters_hide": ["blue_carbon_reserve"],
}.items():
    if _aid in ADDITIONS:
        ADDITIONS[_aid]["for"] += [b for b in _more if b not in ADDITIONS[_aid]["for"]]


# Wood for a Metropolis and a Megacity: additions of their own.
ADDITIONS.update({
    "fast_clones": {"name": "Fast-Growing Clones", "research": "botany", "for": [],
                    "cost": {"wood": 200, "gold": 150}, "speed": 1.3, "desc": "Trees bred to grow quickly: 30% faster."},
    "log_loader": {"name": "Log Loader", "research": "mechanics", "for": [],
                   "cost": {"stone": 80, "tools": 60}, "produces": {"wood": 15}, "desc": "15 more wood each cycle: nothing left lying in the woods."},
    "nutrient_feed": {"name": "Nutrient Feed", "research": "hydroponics", "for": [],
                      "cost": {"tools": 100, "electronics": 40, "gold": 150}, "speed": 1.3, "desc": "Richer broth in the tanks: 30% faster."},
})
for _aid, _more in {
    "fast_clones": ["tree_plantation", "timber_yard", "harvester_fleet"],
    "log_loader": ["tree_plantation", "harvester_fleet", "timber_yard"],
    "nutrient_feed": ["bio_timber_vats"],
    "band_saws": ["tree_plantation", "harvester_fleet", "bio_timber_vats"],
    "replanting": ["tree_plantation", "harvester_fleet"],
    "labour_saving": ["tree_plantation", "harvester_fleet"],
    "automation": ["bio_timber_vats", "harvester_fleet"],
    "smart_meters": ["bio_timber_vats", "harvester_fleet"],
    "work_lights": ["tree_plantation", "harvester_fleet"],
    "irrigation_pipes": ["tree_plantation"],
    "clean_room": ["bio_timber_vats"],
}.items():
    ADDITIONS[_aid]["for"] += [b for b in _more if b not in ADDITIONS[_aid]["for"]]

# More water buildings: additions of their own, and old ones that fit them.
ADDITIONS.update({
    "fish_ladder": {"name": "Fish Ladder", "for": [],
                    "cost": {"wood": 60, "stone": 60}, "produces": {"food": 4}, "desc": "Fish swim up past it all year: 4 more food each cycle."},
    "feed_barge": {"name": "Feed Barge", "for": [],
                   "cost": {"wood": 100, "tools": 40}, "speed": 1.3, "desc": "Feed taken out to the pens and the birds every day: 30% faster."},
    "sonar_fish_finder": {"name": "Sonar Fish Finder", "research": "electricity", "for": [],
                          "cost": {"tools": 60, "gold": 80}, "speed": 1.3, "power": 1, "desc": "Finds the shoals first: 30% faster. Uses 1 more power."},
    "mooring_buoys": {"name": "Mooring Buoys", "for": [],
                      "cost": {"wood": 60, "gold": 60}, "produces": {"gold": 8}, "desc": "Room for visiting boats: 8 more gold each cycle."},
    "riser_pipes": {"name": "Riser Pipes", "research": "engineering", "for": [],
                    "cost": {"stone": 200, "tools": 150, "electronics": 40}, "speed": 1.25, "desc": "Wider pipes from the sea floor: 25% faster."},
})
for _aid, _more in {
    "fish_ladder": ["river_fish_weir", "run_of_river_turbines", "water_mill"],
    "feed_barge": ["aquaculture_pens", "duck_farm"],
    "sonar_fish_finder": ["deep_sea_trawlers", "fishery", "aquaculture_pens", "river_fish_weir"],
    "mooring_buoys": ["marina", "river_barge_port"],
    "riser_pipes": ["ocean_mining_rig"],
    "fishing_nets": ["river_fish_weir", "deep_sea_trawlers", "aquaculture_pens"],
    "storm_hulls": ["deep_sea_trawlers", "river_barge_port", "marina"],
    "lanterns": ["river_fish_weir", "duck_farm", "sea_salt_pans", "marina"],
    "tool_shed": ["river_fish_weir", "duck_farm", "sea_salt_pans"],
    "market_stalls": ["sea_salt_pans", "duck_farm", "marina"],
    "drying_racks": ["sea_salt_pans"],
    "cold_store": ["deep_sea_trawlers", "aquaculture_pens"],
    "ice_house": ["river_fish_weir", "duck_farm"],
    "labour_saving": ["deep_sea_trawlers", "aquaculture_pens", "river_barge_port"],
    "automation": ["ocean_mining_rig", "deep_sea_trawlers"],
    "smart_meters": ["ocean_mining_rig"],
    "work_lights": ["sea_salt_pans", "aquaculture_pens"],
    "crane": ["river_barge_port"],
    "advertising": ["marina", "river_barge_port"],
    "guest_rooms": ["marina"],
    "promenade": ["marina"],
    "transformer": ["run_of_river_turbines", "floating_solar"],
    "sun_trackers": ["floating_solar"],
    "battery_bank": ["floating_solar", "run_of_river_turbines"],
    "sea_wall": ["run_of_river_turbines"],
    "clean_room": ["ocean_mining_rig"],
}.items():
    ADDITIONS[_aid]["for"] += [b for b in _more if b not in ADDITIONS[_aid]["for"]]

# Shops that turn tools and electronics into gold: additions of their own, and old ones that fit them.
ADDITIONS.update({
    "showroom": {"name": "Showroom", "for": [],
                 "cost": {"stone": 100, "tools": 40, "gold": 100}, "produces": {"gold": 15}, "desc": "Goods on show where buyers pass: 15 more gold each cycle."},
    "online_shop": {"name": "Online Shop", "research": "computing", "for": [],
                    "cost": {"tools": 60, "electronics": 30, "gold": 150}, "speed": 1.3, "desc": "Sells to the whole world at once: 30% faster."},
    "bulk_contracts": {"name": "Bulk Contracts", "research": "bookkeeping", "for": [],
                       "cost": {"gold": 120}, "speed": 1.2, "desc": "Big buyers who take all you make: 20% faster."},
})
for _aid, _more in {
    "showroom": ["hardware_store", "electronics_store", "smart_device_factory"],
    "online_shop": ["electronics_store", "export_terminal", "smart_device_factory", "hardware_store"],
    "bulk_contracts": ["tinkers_stall", "hardware_store", "export_terminal", "electronics_store"],
    "market_stalls": ["tinkers_stall", "hardware_store"],
    "counting_house": ["tinkers_stall", "export_terminal"],
    "window_displays": ["tinkers_stall", "hardware_store", "electronics_store"],
    "advertising": ["hardware_store", "electronics_store", "smart_device_factory"],
    "lanterns": ["tinkers_stall"],
    "labour_saving": ["hardware_store", "export_terminal"],
    "automation": ["smart_device_factory", "export_terminal"],
    "smart_meters": ["smart_device_factory"],
    "assembly_line": ["smart_device_factory", "export_terminal"],
    "crane": ["export_terminal"],
    "delivery_vans": ["hardware_store", "electronics_store"],
    "clean_room": ["smart_device_factory"],
}.items():
    ADDITIONS[_aid]["for"] += [b for b in _more if b not in ADDITIONS[_aid]["for"]]

# Stone for a Megacity: additions of their own, and old ones that fit.
ADDITIONS.update({
    "rock_crushers": {"name": "Rock Crushers", "for": [],
                      "cost": {"stone": 200, "tools": 120}, "produces": {"stone": 20}, "desc": "Nothing goes to waste: 20 more stone each cycle."},
    "diamond_wire_saws": {"name": "Diamond Wire Saws", "research": "robotics", "for": [],
                          "cost": {"tools": 200, "electronics": 50, "gold": 200}, "speed": 1.3, "desc": "Cut through rock like butter: 30% faster."},
})
for _aid, _more in {
    "rock_crushers": ["autonomous_quarry", "geopolymer_plant", "aggregate_plant"],
    "diamond_wire_saws": ["autonomous_quarry", "aggregate_plant", "cement_works"],
    "automation": ["autonomous_quarry", "geopolymer_plant"],
    "smart_meters": ["autonomous_quarry", "geopolymer_plant"],
    "labour_saving": ["geopolymer_plant"],
    "work_lights": ["autonomous_quarry"],
    "support_beams": ["autonomous_quarry"],
    "aggregate_pit": ["autonomous_quarry"],
    "rotary_kiln": ["geopolymer_plant"],
}.items():
    ADDITIONS[_aid]["for"] += [b for b in _more if b not in ADDITIONS[_aid]["for"]]

# Knowledge on the water: additions of their own, and old ones that fit.
ADDITIONS.update({
    "research_submarine": {"name": "Research Submarine", "research": "marine_biology", "for": [],
                           "cost": {"tools": 120, "gold": 150}, "speed": 1.3, "desc": "Goes where divers can't: 30% faster."},
    "sample_archive": {"name": "Sample Archive", "for": [],
                       "cost": {"stone": 100, "gold": 80}, "produces": {"knowledge": 6}, "desc": "Every sample kept and studied again: 6 more knowledge each cycle."},
})
for _aid, _more in {
    "research_submarine": ["oceanographic_institute", "deep_sea_lab", "limnology_station"],
    "sample_archive": ["tide_watchers", "freshwater_lab", "limnology_station", "oceanographic_institute", "deep_sea_lab"],
    "library": ["tide_watchers", "freshwater_lab"],
    "scriptorium": ["tide_watchers"],
    "lanterns": ["tide_watchers"],
    "specialist_equipment": ["freshwater_lab", "limnology_station", "oceanographic_institute"],
    "diving_bells": ["freshwater_lab", "oceanographic_institute"],
    "supercomputer": ["deep_sea_lab", "oceanographic_institute"],
    "clean_room": ["deep_sea_lab"],
    "smart_meters": ["deep_sea_lab", "oceanographic_institute"],
    "automation": ["deep_sea_lab"],
    "storm_hulls": ["oceanographic_institute", "tide_watchers"],
    "fishing_nets": ["limnology_station"],
}.items():
    ADDITIONS[_aid]["for"] += [b for b in _more if b not in ADDITIONS[_aid]["for"]]

# Additions for the Cauldron buildings.
ADDITIONS.update({
    "copper_stills": {"name": "Copper Stills", "for": [], "cost": {"ore": 60, "tools": 40, "gold": 60},
                      "cauldron_power": 0.05, "desc": "Cauldron brews 5% stronger."},
    "spice_cellar": {"name": "Spice Cellar", "for": [], "cost": {"stone": 80, "wood": 60, "gold": 40},
                     "cauldron_cost": 0.05, "desc": "Cauldron brews take a little fewer ingredients."},
    "rare_reagents": {"name": "Rare Reagents", "research": "botany", "for": [], "cost": {"gold": 200, "knowledge": 100},
                      "cauldron_power": 0.08, "desc": "Cauldron brews 8% stronger."},
})
for _aid, _more in {
    "copper_stills": ["alchemists_workshop", "grand_apothecary", "arcane_distillery"],
    "spice_cellar": ["witchs_garden", "grand_apothecary", "alchemists_workshop"],
    "rare_reagents": ["grand_apothecary", "arcane_distillery", "witchs_garden"],
}.items():
    ADDITIONS[_aid]["for"] += [b for b in _more if b not in ADDITIONS[_aid]["for"]]

# Kinds of area an expedition can find. Fields:
#   weight   how common it is (0 = never found by exploring)
#   terrain  multipliers on how common each terrain is (ordinary or rare)
#   river / lake / ocean   chance the area has one; rivers / lakes / oceans = how many tries
#   temp     added to the home climate
#   cost     what an expedition there needs, per step of distance from home
#   loot     extra (resource, least, most) an expedition there may bring back, per step of distance
#   The terrain multipliers also make land that forms beside its own kind (heath, kelp, ...) likelier.
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
    "tundra":    {"name": "Tundra",    "weight": 1, "terrain": {"desert": 0, "hill": 1.5, "tundra": 40, "plains": 0.3}, "temp": -16,
                  "river": 0.4, "lake": 0.5, "ocean": 0.04,
                  "cost": {"food": 60, "wood": 50}},
    "coast":     {"name": "Coast",     "weight": 1, "terrain": {}, "temp": 0,
                  "river": 0.5, "lake": 0.1, "ocean": 1,
                  "cost": {"food": 30, "wood": 40}},
    "jungle":    {"name": "Jungle",    "weight": 2, "terrain": {"jungle": 25, "forest": 1.5, "dense_forest": 1.5}, "temp": 8,
                  "river": 0.7, "lake": 0.3, "ocean": 0.02,
                  "cost": {"food": 50, "wood": 30}},
    "savanna":   {"name": "Savanna",   "weight": 2, "terrain": {"savanna": 14, "plains": 1.5}, "temp": 8,
                  "river": 0.3, "lake": 0.2, "ocean": 0.02,
                  "cost": {"food": 40, "wood": 15}},
    "steppe":    {"name": "Steppe",    "weight": 2, "terrain": {"steppe": 14, "hill": 1.2}, "temp": -4,
                  "river": 0.3, "lake": 0.2, "ocean": 0,
                  "cost": {"food": 45, "wood": 20}},
    "taiga":     {"name": "Taiga",     "weight": 2, "terrain": {"desert": 0, "taiga": 20, "forest": 1.5}, "temp": -8,
                  "river": 0.5, "lake": 0.5, "ocean": 0.02,
                  "cost": {"food": 50, "wood": 30}},
    "badlands":  {"name": "Badlands",  "weight": 1, "terrain": {"desert": 3, "hill": 2.5, "canyon": 5, "mesa": 5}, "temp": 5,
                  "river": 0.25, "lake": 0, "ocean": 0,
                  "cost": {"food": 70, "wood": 30}},
    "volcanic":  {"name": "Volcanic Fields", "weight": 1,
                  "terrain": {"hill": 2.5, "volcanic": 6, "lava_field": 30, "mountain": 0.6}, "temp": 4,
                  "river": 0.2, "lake": 0.2, "ocean": 0.05,
                  "cost": {"food": 60, "wood": 40}},
    "delta":     {"name": "River Delta", "weight": 1, "terrain": {"marsh": 6, "plains": 1.5}, "temp": 2,
                  "river": 1, "rivers": 2, "lake": 0.5, "ocean": 0.6,
                  "cost": {"food": 35, "wood": 40}},
    "islands":   {"name": "Islands",   "weight": 1, "terrain": {"jungle": 4}, "temp": 4,
                  "river": 0.2, "lake": 0.1, "ocean": 1, "oceans": 2,
                  "cost": {"food": 40, "wood": 70}},
    "moorland":  {"name": "Moorland",  "weight": 2, "terrain": {"desert": 0, "hill": 2, "plains": 1.2, "heath": 3, "foothills": 2},
                  "temp": -3, "river": 0.5, "lake": 0.4, "ocean": 0,
                  "cost": {"food": 40, "wood": 25}, "loot": [("livestock", 1, 3)]},
    "karst":     {"name": "Cave Country", "weight": 1, "terrain": {"desert": 0.3, "hill": 3, "plains": 0.6, "cave": 8, "canyon": 2, "crystal_cavern": 3},
                  "temp": -1, "river": 0.4, "lake": 0.2, "ocean": 0,
                  "cost": {"food": 50, "wood": 40}, "loot": [("ore", 10, 30), ("stone", 20, 40)]},
    "floodplains": {"name": "Floodplains", "weight": 2, "terrain": {"plains": 2, "floodplain": 3, "marsh": 2, "meadow": 1.5},
                    "temp": 1, "river": 1, "rivers": 2, "lake": 0.3, "ocean": 0,
                    "cost": {"food": 30, "wood": 30}, "loot": [("food", 30, 60)]},
    "reef":      {"name": "Reef Shallows", "weight": 1, "terrain": {"beach": 3, "coral_reef": 4, "kelp_forest": 3, "mangrove": 2},
                  "temp": 5, "river": 0.1, "lake": 0, "ocean": 1, "oceans": 2,
                  "cost": {"food": 40, "wood": 70}, "loot": [("gold", 10, 25)]},
    "sea_cliffs": {"name": "Sea Cliffs", "weight": 1, "terrain": {"desert": 0, "hill": 3, "cliffs": 3, "foothills": 1.5, "mountain": 1.5},
                   "temp": -2, "river": 0.3, "lake": 0.1, "ocean": 1,
                   "cost": {"food": 40, "wood": 50}, "loot": [("food", 20, 40)]},
    "outback":   {"name": "Outback",   "weight": 2, "terrain": {"scrubland": 25, "plains": 0.4, "forest": 0.2, "desert": 2, "savanna": 3, "mesa": 2},
                  "temp": 7, "river": 0.15, "lake": 0.05, "ocean": 0,
                  "cost": {"food": 70, "wood": 20}, "loot": [("gold", 10, 20)]},
    "icefields": {"name": "Icefields", "weight": 1, "terrain": {"desert": 0, "tundra": 45, "plains": 0.2, "forest": 0.2, "hill": 1.5, "mountain": 2, "glacier": 3},
                  "temp": -20, "river": 0.2, "lake": 0.4, "ocean": 0.1,
                  "cost": {"food": 80, "wood": 60}, "loot": [("knowledge", 8, 15)]},
    "bamboo_valley": {"name": "Bamboo Valley", "weight": 1, "terrain": {"desert": 0, "forest": 2, "bamboo": 4, "jungle": 2, "foothills": 1.5},
                      "temp": 5, "river": 0.9, "lake": 0.4, "ocean": 0,
                      "cost": {"food": 40, "wood": 20}, "loot": [("wood", 30, 60)]},
}

# Wild animals. terrain is where they appear; livestock is what one is worth
# once tamed (the species is not remembered after that). night: True - mostly
# seen at night (and rarely by day); False - rarely seen at night.
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
    "pheasant": {"name": "Pheasants",     "glyph": "p", "terrain": ["meadow", "plains", "foothills"], "livestock": 1, "weight": 3},
    "bees":    {"name": "Wild Bees",      "glyph": "x", "terrain": ["meadow", "ancient_grove", "forest"], "livestock": 1, "weight": 2},
    "turkey":  {"name": "Wild Turkeys",   "glyph": "t", "terrain": ["forest", "foothills"], "livestock": 2, "weight": 3},
    "geese":   {"name": "Geese",          "glyph": "u", "terrain": ["river", "lake", "marsh"], "livestock": 2, "weight": 3},
    "beaver":  {"name": "Beavers",        "glyph": "v", "terrain": ["river", "lake", "swamp"], "livestock": 2, "weight": 2},
    "turtle":  {"name": "Sea Turtles",    "glyph": "w", "terrain": ["ocean", "coral_reef"], "livestock": 2, "weight": 3},
    "seal":    {"name": "Seals",          "glyph": "q", "terrain": ["ocean", "coral_reef"], "livestock": 3, "weight": 2},
    "ostrich": {"name": "Ostriches",      "glyph": "s", "terrain": ["desert", "salt_flat"], "livestock": 3, "weight": 2},
    "ibex":    {"name": "Ibex",           "glyph": "i", "terrain": ["mountain", "glacier", "hot_springs"], "livestock": 3, "weight": 3},
    "donkey":  {"name": "Wild Asses",     "glyph": "j", "terrain": ["desert", "foothills"], "livestock": 4, "weight": 2},
    "llama":   {"name": "Llamas",         "glyph": "l", "terrain": ["hill", "foothills"],  "livestock": 4, "weight": 2},
    "elk":     {"name": "Elk",            "glyph": "m", "terrain": ["dense_forest", "ancient_grove", "swamp"], "livestock": 5, "weight": 2},
    "muskox":  {"name": "Musk Oxen",      "glyph": "z", "terrain": ["glacier", "mountain"], "livestock": 6, "weight": 1},
    "elephant": {"name": "Elephants",     "glyph": "h", "terrain": ["plains", "swamp"],    "livestock": 10, "weight": 0.4},
    "crab":     {"name": "Crabs",         "glyph": "C", "terrain": ["beach", "mangrove"],  "livestock": 1, "weight": 4},
    "flamingo": {"name": "Flamingos",     "glyph": "F", "terrain": ["salt_flat", "beach", "marsh"], "livestock": 2, "weight": 2},
    "tapir":    {"name": "Tapirs",        "glyph": "T", "terrain": ["jungle", "bamboo", "mangrove"], "livestock": 3, "weight": 3},
    "zebra":    {"name": "Zebras",        "glyph": "Z", "terrain": ["savanna"],            "livestock": 4, "weight": 4},
    "reindeer": {"name": "Reindeer",      "glyph": "R", "terrain": ["taiga", "steppe"],    "livestock": 4, "weight": 4},
    "saiga":    {"name": "Saiga Antelope", "glyph": "S", "terrain": ["steppe", "savanna"], "livestock": 3, "weight": 3},
    "arctic_fox": {"name": "Arctic Foxes", "glyph": "A", "terrain": ["tundra", "glacier"], "livestock": 2, "weight": 3, "night": True},
    "snowy_owl":  {"name": "Snowy Owls",   "glyph": "N", "terrain": ["tundra", "heath"],   "livestock": 1, "weight": 2, "night": True},
    "grouse":     {"name": "Red Grouse",   "glyph": "G", "terrain": ["heath", "foothills"], "livestock": 1, "weight": 4},
    "kangaroo":   {"name": "Kangaroos",    "glyph": "K", "terrain": ["scrubland", "savanna"], "livestock": 4, "weight": 4},
    "emu":        {"name": "Emus",         "glyph": "E", "terrain": ["scrubland", "desert"], "livestock": 3, "weight": 3},
    "otter":      {"name": "Sea Otters",   "glyph": "O", "terrain": ["kelp_forest", "river"], "livestock": 2, "weight": 3},
    "bats":       {"name": "Cave Bats",    "glyph": "B", "terrain": ["cave", "crystal_cavern", "canyon"], "livestock": 1, "weight": 4, "night": True},
    "puffin":     {"name": "Puffins",      "glyph": "P", "terrain": ["cliffs", "beach"],    "livestock": 1, "weight": 4, "night": False},
    "walrus":     {"name": "Walruses",     "glyph": "W", "terrain": ["kelp_forest", "glacier"], "livestock": 6, "weight": 1},
    "hedgehog":   {"name": "Hedgehogs",    "glyph": "H", "terrain": ["meadow", "plains", "floodplain"], "livestock": 1, "weight": 2, "night": True},
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


def _mod_sunlight(area, x, y):
    t = area["tiles"][y][x]["temp"]
    return max(0.5, min(1.5, 0.7 + t / 50)), f"{t}C sun"


def _mod_cooling(area, x, y):
    t = area["tiles"][y][x]["temp"]
    return max(0.6, min(1.4, 1.2 - t / 50)), f"{t}C air"


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
    "sunlight": _mod_sunlight,
    "cooling": _mod_cooling,
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
    """Lay oceans, rivers and lakes over a freshly made area, as its environment allows."""
    env, n, tiles = ENVIRONMENTS[area["env"]], area["size"], area["tiles"]

    def put(x, y, terrain):
        if 0 <= x < n and 0 <= y < n and not terrain_is(tiles[y][x]["terrain"], "water"):
            tiles[y][x] = _make_tile(terrain, area["climate"], rng)

    sides = [0, 1, 2, 3]
    rng.shuffle(sides)
    for side in sides[:env.get("oceans", 1)]:   # a ragged band along one side
        if rng.random() < env["ocean"]:
            depth = rng.randint(2, 3) if env.get("oceans", 1) == 1 else rng.randint(1, 2)
            for i in range(n):
                depth = max(1, min(n - 2, depth + rng.choice((-1, 0, 0, 1))))
                for d in range(depth):
                    put(*[(d, i), (n - 1 - d, i), (i, d), (i, n - 1 - d)][side], "ocean")
    for _ in range(env.get("rivers", 1)):       # a wandering line from one side to the other
        if rng.random() < env["river"]:
            across, pos = rng.random() < 0.5, rng.randrange(n)
            for i in range(n):
                put(*((i, pos) if across else (pos, i)), "river")
                step = rng.choice((-1, 0, 0, 0, 1))
                if 0 <= pos + step < n:
                    pos += step
                    put(*((i, pos) if across else (pos, i)), "river")
    for _ in range(env.get("lakes", 1)):        # a clump of 2-5 tiles
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
    bias = ENVIRONMENTS[area["env"]]["terrain"]
    for terrain, t in TERRAINS.items():
        if "near" not in t:
            continue
        alike = lambda other: any(terrain_is(other["terrain"], k) for k in t["near"])
        for y in range(n):
            for x in range(n):
                tile = tiles[y][x]
                if (cells is not None and (x, y) not in cells) or tile["building"]:
                    continue
                if (tile["terrain"] in t["spread_from"] and rng.random() < min(0.9, t["chance"] * bias.get(terrain, 1))
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


# ---- the tutorial: every city is taken through the game one step at a time (see TUTOR in index.html, whose
# steps these are, in the same order). New cities must finish it; cities from before it can skip it. ----
TUTORIAL_STEPS = ("welcome", "stores", "select", "food", "house", "knowledge", "priority", "addition",
                  "people", "people_read", "research_open", "research", "explore", "explore_read", "beast", "beast_read",
                  "market", "market_read", "cauldron", "cauldron_read", "ideology", "ideology_read",
                  "back_to_city", "advance_read", "finish")
TUTORIAL_GIFTS = {"research": {"knowledge": 30}}     # handed over when the tutorial reaches that step, once


def tutorial_reach(state, now, step):
    """The tutorial moves on to `step` (never back), or ends ("done")."""
    tut = state.setdefault("tutorial", {"at": TUTORIAL_STEPS[0], "done": False, "skippable": True, "gifts": []})
    if step == "done":
        tut["done"] = True
        return None
    if step not in TUTORIAL_STEPS:
        return "Unknown tutorial step."
    here = TUTORIAL_STEPS.index(tut["at"]) if tut["at"] in TUTORIAL_STEPS else 0
    there = TUTORIAL_STEPS.index(step)
    if there <= here:
        return None
    for s in TUTORIAL_STEPS[here + 1:there + 1]:
        gift = TUTORIAL_GIFTS.get(s)
        if gift and s not in tut.setdefault("gifts", []):
            for k, v in gift.items():
                state["resources"][k] += v
            tut["gifts"].append(s)
            log(state, now, f"The tutorial gave you {fmt_goods(gift)} to try it out.")
    tut["at"] = step
    return None


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
        "exp_queue": [],     # [{"rx", "ry", "cost", "queued"}]: teams waiting to set off, supplies already paid
        "resources": {k: START_RESOURCES.get(k, 0) for k in RESOURCES},
        "population": START_POPULATION,
        "research": [],
        "log": [],
    }
    state["banned"] = []     # cities that may not view this one or propose bills to it
    state["priorities"] = PRIORITY_VERSION
    state["tutorial"] = {"at": TUTORIAL_STEPS[0], "done": False, "skippable": False, "gifts": []}   # a new city takes it all
    beasts.setup(state, now, rng)
    ideology.setup(state)
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
    state.setdefault("totals", {})
    state.setdefault("totals_since", state.get("updated", now))    # counted from here, catching up included
    state.setdefault("research", [])
    state.setdefault("wild", 0)
    state.setdefault("expedition", None)
    state.setdefault("exp_queue", [])
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
    if state.get("priorities", 1) < PRIORITY_VERSION:     # "first" was 1 before "high" came in; it is 2 now
        for area in state["areas"]:
            for row in area["tiles"]:
                for tile in row:
                    if tile.get("priority") == 1:
                        tile["priority"] = 2
        state["priorities"] = PRIORITY_VERSION
    beasts.migrate(state, now)
    ideology.setup(state)
    # a city from before the tutorial goes through it too, but may skip it
    state.setdefault("tutorial", {"at": TUTORIAL_STEPS[0], "done": False, "skippable": True, "gifts": []})
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


def default_area_name(area):
    if not (area["rx"] or area["ry"]):
        return "Home"
    return f"{ENVIRONMENTS[area['env']]['name']} ({where(area['rx'], area['ry'])})"


def area_name(area):
    """What the player calls the area: the name they gave it, or the default."""
    return area.get("label") or default_area_name(area)


AREA_NAME = re.compile(r"^[\w '.,!&()\-]{1,24}$")


def rename_area(state, now, area, name):
    """Give an area a name of the player's choosing; an empty name puts the default back.
    Only the label changes: nothing about how the area works depends on it."""
    name = " ".join(name.split()) if isinstance(name, str) else None
    if name is None or (name and not AREA_NAME.match(name)):
        return "Area names are up to 24 letters, digits, spaces and simple punctuation."
    if name and moderation.check_name(name):
        return moderation.check_name(name)
    old = area_name(area)
    area["label"] = name
    if area_name(area) != old:
        log(state, now, f"{old} is now called {area_name(area)}.")
    return None


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

def tally(state, key, n=1):
    """Add to one of the city's lifetime counters (see TALLIES), shown on the Stats tab."""
    totals = state.setdefault("totals", {})
    totals[key] = totals.get(key, 0) + n


def log(state, now, text):
    state["log"].append({"t": now, "text": text})
    del state["log"][:-40]


def fmt_goods(goods):
    return ", ".join(f"{v:,} {RESOURCES[k]}" for k, v in goods.items())


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
    # The city's active beast.
    favour = beasts.speed_bonus(state, b.get("category"))
    if favour:
        factors.append(favour)
    # The city's ideology and the perks it has taken.
    belief = ideology.speed_bonus(state, b.get("category"))
    if belief:
        factors.append(belief)
    # Brews from the Cauldron, and enshrined artifacts.
    for extra in (cauldron.speed_bonus(state, b.get("category")), artifacts.speed_bonus(state, b.get("category"))):
        if extra:
            factors.append(extra)
    # Hexes, sabotage and the like other cities have done to this one.
    hexed = ideology.curse_speed(state, b.get("category"))
    if hexed:
        factors.append(hexed)
    # Workers trained by newcomers sent to training (see training_bonus).
    if b.get("workers") and state.get("training", {}).get("trained"):
        factors.append((1 + training_bonus(state), "Trained workers"))
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
    if b.get("unique") and has_building(state, bid):
        return "a city can only have one"
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

    Workers go to buildings the player marked "first" (tile priority 2), then
    "high" (1), then the rest (0), each group in map order: home first, then
    each area top-left first. Buildings switched off (priority -1) get nobody.

    Returns (jobs, housing, totals) where jobs is a list of working buildings.
    Inside reading() it is worked out once per city and handed out again (as copies) after that.
    """
    if _PLAN_CACHE is not None:
        key = id(state)
        if key not in _PLAN_CACHE:
            _PLAN_CACHE[key] = _remembered_plan(state)
        jobs, housing, totals = _PLAN_CACHE[key]
        return [dict(j) for j in jobs], housing, dict(totals)
    jobs, housing, totals = _remembered_plan(state)
    return [dict(j) for j in jobs], housing, dict(totals)


_PLAN_CACHE = None     # inside reading(): id(state) -> its work plan
# The last work plan of each city, kept between requests: a big city's plan took a tenth of a second, and every
# update a player's page asks for worked it out twice (catching up, then the reply), though it rarely changes.
# It is used again only while everything it depends on is the same (_plan_key), and for at most PLAN_KEEP seconds
# of game time, so anything the key misses can only be out of date that long.
_PLAN_MEMO = {}        # id(state) -> (key, made at, plan)
PLAN_KEEP = 120


def _plan_key(state):
    """Everything a work plan depends on: the buildings (with additions and priorities), the people to staff them,
    research, the effects in force at the moment being worked out (ideology, rituals, the Cauldron, artifacts,
    hexes), the active beast and the size of the herd."""
    tiles = tuple((ai, x, y, t["building"], t.get("priority", 0), tuple(t["additions"]))
                  for ai, area in enumerate(state["areas"]) for y, row in enumerate(area["tiles"])
                  for x, t in enumerate(row) if t["building"])
    beast = beasts.active(state)
    return (tiles, len(state["areas"]), state["population"], state["tech"], len(state["research"]),
            json.dumps(ideology.effects(state), sort_keys=True, default=str),
            tuple((c["ideology"], c["curse"], c["scale"]) for _, c in ideology.active_curses(state)),
            (beast["id"], beast["species"], beast["level"], beast["stage"], beast.get("cap")) if beast else None,
            min(2.0, max(0.2, int(state["resources"]["livestock"]) / LIVESTOCK_FOR_FULL_SPEED)),
            state.get("training", {}).get("trained", 0))


def _remembered_plan(state):
    with _stats_cached():
        key = _plan_key(state)
        old = _PLAN_MEMO.get(id(state))
        if old and old[0] == key and 0 <= state["updated"] - old[1] <= PLAN_KEEP:
            jobs = old[2][0]
            # the same tiles, not copies of them (a city brought back from its save is a new set of tiles)
            if all(j["tile"] is state["areas"][j["area"]]["tiles"][j["y"]][j["x"]] for j in jobs):
                return old[2]
        plan = _work_plan(state)
    if len(_PLAN_MEMO) > 1000:
        _PLAN_MEMO.clear()
    _PLAN_MEMO[id(state)] = (key, state["updated"], plan)
    return plan


@contextmanager
def reading():
    """For a reply that only looks at cities (a view, a Find, the Stats tab) and changes nothing in them: each
    city's work plan and city_stat values are worked out once, however many parts of the reply ask for them."""
    global _PLAN_CACHE
    if _PLAN_CACHE is not None:      # already inside one
        yield
        return
    _PLAN_CACHE = {}
    try:
        with _stats_cached():
            yield
    finally:
        _PLAN_CACHE = None


def _work_plan(state):
    housing = BASE_HOUSING + int(beasts.bonus(state, "housing")) + int(ideology.value(state, "housing"))
    herd_room, jobs = 0, []
    beast_power = (1 + beasts.bonus(state, "power") + ideology.value(state, "power")) * ideology.curse_factor(state, "power")     # generators give more (or less, cursed)
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
                # Additions can save labour and power, but a staffed building keeps at least one worker.
                need = max(1, tile_stat(tile, "workers")) if b.get("workers") else 0
                power_out = tile_stat(tile, "generates")
                for m in b.get("generates_modifiers", []):
                    power_out *= MODIFIERS[m](area, x, y)[0]
                power_out *= beast_power
                jobs.append({
                    "area": ai, "x": x, "y": y, "tile": tile, "b": b,
                    "cycle": cycle,             # None for a generator that needs no fuel
                    "notes": notes, "need": need, "priority": tile.get("priority", 0),
                    "produces": tile_output(tile),
                    "feeds": "food" in b.get("produces", {}) or "food" in b.get("per_head", {}),
                    "herd": tile_stat(tile, "herd"),
                    "herd_before": herd_room,   # pasture room in the buildings ahead of this one
                    "power_in": max(0, tile_stat(tile, "power")) if b.get("power") else 0,
                    "power_out": round(power_out, 1),
                })
                herd_room += tile_stat(tile, "herd")
    return jobs, housing, _staff(jobs, state["population"], herd_room)


def _staff(jobs, free, herd_room):
    """Hand `free` workers out to the jobs: "first" buildings first, switched-off ones none. Returns the totals."""
    needed = 0
    for job in sorted(jobs, key=lambda j: -j["priority"]):   # stable: map order within a priority
        off = job["priority"] < 0
        job["staff"] = 0 if off else min(job["need"], free)
        free -= job["staff"]
        needed += 0 if off else job["need"]
        job["ratio"] = 0.0 if off else (job["staff"] / job["need"] if job["need"] else 1.0)
        job["herd_room"] = herd_room
    return {"jobs": needed, "idle": free, "herd_room": herd_room}


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
    if state.get("mastery"):        # a Megacity's mastery: more of each resource it has mastered
        out = {k: round(v * (1 + mastery_bonus(state, k)), 2) for k, v in out.items()}
    return out


def _out_of_inputs(state, job):
    """True if the building has finished a cycle and can't pay for it (e.g. no fuel)."""
    return (job["cycle"] is not None and job["tile"]["progress"] >= job["cycle"]
            and bool(_missing(state, job["b"].get("consumes", {}))))


def power_status(state, jobs, env=None):
    """(power supplied, power needed, share of the need that is met) right now.
    env: weather.job_factors() for the jobs, if day, night and weather count."""
    supply = sum(j["power_out"] * j["ratio"] * (env[i][1] if env else 1) for i, j in enumerate(jobs)
                 if j["power_out"] and not _out_of_inputs(state, j))
    demand = sum(j["power_in"] for j in jobs if j["power_in"] and j["ratio"])
    return supply, demand, (min(1.0, supply / demand) if demand else 1.0)


def _speed(state, job, power=1.0, env=1.0):
    """Seconds of work this building gets done per second right now. env: what day or night and the weather do."""
    speed = job["ratio"] * env
    if state["hungry"] and not job["feeds"]:
        speed *= HUNGRY_SPEED
    if job["power_in"]:
        speed *= power
    return speed


# ---- training: newcomers sent to train instead of joining the city make every worker better ----
# A city can send a share of each meal's newcomers (TRAINING_SHARES) to training. They don't join the city (so they
# don't eat or need a home): each one adds to the city's trained count, and every building with workers is faster by
# TRAINING_STEP for each doubling of it (in TRAINING_UNIT steps): 30 trained +4%, 90 +8%, 210 +12%, 450 +16%...
# Only people who would really have come are trained, so a city whose homes are all full trains nobody. At most 90%
# can be sent: the rest join and fill the homes, so training stops unless the city keeps building homes.
TRAINING_SHARES = (0, 0.25, 0.5, 0.75, 0.9)
TRAINING_MAX = 0.9
TRAINING_STEP = 0.04
TRAINING_UNIT = 30


def training_bonus(state, trained=None):
    """How much faster trained workers make every building: TRAINING_STEP per doubling."""
    n = state.get("training", {}).get("trained", 0) if trained is None else trained
    return TRAINING_STEP * math.log2(1 + n / TRAINING_UNIT) if n > 0 else 0.0


def set_training(state, now, share):
    if share not in TRAINING_SHARES:
        return "Pick how many newcomers to send to training."
    t = state.setdefault("training", {"share": 0, "trained": 0, "carry": 0.0})
    t["share"] = share
    log(state, now, "Newcomers now all join the city." if not share else
                    f"{'All' if share == 1 else f'{round(share * 100)}% of'} newcomers now go to training instead of joining the city.")
    return None


def _train(state, arrivals):
    """Of this meal's `arrivals`, how many go to training (the rest join the city)."""
    t = state.get("training")
    if not t or not t.get("share") or not arrivals:
        return 0
    t["carry"] = t.get("carry", 0.0) + arrivals * min(t["share"], TRAINING_MAX)     # (a city that chose "all" before the cap: 90%)
    sent = min(arrivals, int(t["carry"]))
    t["carry"] -= sent
    t["trained"] = t.get("trained", 0) + sent
    return sent


def training_view(state):
    t = state.get("training", {})
    trained = t.get("trained", 0)
    next_at = TRAINING_UNIT * (2 ** (math.floor(math.log2(1 + trained / TRAINING_UNIT)) + 1) - 1)
    return {"share": min(t.get("share", 0), TRAINING_MAX), "trained": trained, "bonus": round(training_bonus(state), 4), "shares": list(TRAINING_SHARES),
            "step": TRAINING_STEP, "unit": TRAINING_UNIT,
            "next_at": int(next_at), "next_bonus": round(training_bonus(state, next_at), 4)}


def _meal(state, housing, when):
    """Everyone eats. Returns True if the population changed."""
    res, pop = state["resources"], state["population"]
    tally(state, "meals")
    if res["food"] < pop:
        tally(state, "hungry_meals")
        tally(state, "eaten", int(res["food"]))
        res["food"] = 0
        if not state["hungry"]:
            state["hungry"] = True
            log(state, when, "The food has run out. Hungry workers are working at half speed.")
        return False
    res["food"] -= pop
    tally(state, "eaten", pop)
    if state["hungry"]:
        state["hungry"] = False
        log(state, when, "Everyone is fed again.")
    arrivals = _arrivals(pop, res["food"], housing, 1 + city_attracts(state, when))
    trained = _train(state, arrivals)          # some go to training instead of joining the city
    arrivals -= trained
    state["population"] += arrivals
    if arrivals:
        tally(state, "arrivals", arrivals)
        beasts.note(state, when, "arrival", arrivals)
    if trained:
        tally(state, "trained", trained)
    return arrivals > 0 or trained > 0


_STAT_CACHE = None     # while view() or work_plan() runs (they change nothing) each city_stat is worked out once, not per tile


@contextmanager
def _stats_cached():
    """Keep city_stat results for the length of a calculation that changes nothing in the city."""
    global _STAT_CACHE
    if _STAT_CACHE is not None:      # already inside one
        yield
        return
    _STAT_CACHE = {}
    try:
        yield
    finally:
        _STAT_CACHE = None


def city_stat(state, field):
    """`field` added up over every building (and its additions) in the city."""
    if _STAT_CACHE is not None:
        key = (id(state), field)
        if key not in _STAT_CACHE:
            # every building's numbers added up in one pass, the first time any is asked for (a big city has
            # thousands of buildings, and a reply asks for twenty or so of these)
            totals = _STAT_CACHE.get((id(state), None))
            if totals is None:
                totals = _STAT_CACHE[(id(state), None)] = _tile_totals(state)
            _STAT_CACHE[key] = totals.get(field, 0) + ideology.value(state, field)
        return _STAT_CACHE[key]
    return sum(tile_stat(t, field) for t in all_tiles(state) if t["building"]) + ideology.value(state, field)


def building_stat(state, field):
    """`field` added up over the city's buildings and their additions alone, without the ideology's (city_stat adds
    that): for the Cauldron, whose bonuses ideology.effects itself takes in."""
    if _STAT_CACHE is not None:
        totals = _STAT_CACHE.get((id(state), None))
        if totals is None:
            totals = _STAT_CACHE[(id(state), None)] = _tile_totals(state)
        return totals.get(field, 0)
    return sum(tile_stat(t, field) for t in all_tiles(state) if t["building"])


_NUMBERS = {}      # ("b" or "a", id) -> that building's or addition's number fields


def _numbers(kind, key):
    if (kind, key) not in _NUMBERS:
        d = (BUILDINGS if kind == "b" else ADDITIONS)[key]
        _NUMBERS[(kind, key)] = {f: v for f, v in d.items() if isinstance(v, (int, float)) and not isinstance(v, str)}
    return _NUMBERS[(kind, key)]


def _tile_totals(state):
    """tile_stat added up over every building in the city, for every field at once."""
    out = {}
    for t in all_tiles(state):
        if not t["building"]:
            continue
        for f, v in _numbers("b", t["building"]).items():
            out[f] = out.get(f, 0) + v
        for aid in t["additions"]:
            for f, v in _numbers("a", aid).items():
                out[f] = out.get(f, 0) + v
    return out


def city_attracts(state, when=None):
    """Extra people who may arrive at each meal, from taverns and the like (more at night, at time `when`)."""
    return (city_stat(state, "attracts") + int(beasts.bonus(state, "attracts"))
            + weather.night_attracts(state, state["updated"] if when is None else when))


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
    return _arrivals(pop, food - pop, housing, 1 + city_attracts(state, state["updated"] + MEAL_TIME - state["meal"]))


def advance_time(state, now, coarse=False):
    """Simulate everything that happened between the last update and `now`. `coarse`: in LONG_STEP steps all the
    way (the server catching up a city nobody is playing, a slice at a time), not SIM_STEP for the last hours."""
    remaining = now - state["updated"]
    if remaining <= 0:
        return
    start = now - remaining
    state["wphase"] = weather.phase(state)     # before the clock moves on: the weather changes at meals
    state["updated"] = now
    # Caught up in stretches that end where a ritual, hex or the Cauldron's hour ends, so each counts for exactly as
    # long as it ran. At the end of each hour the Cauldron brews the next one (which sets the next stop), so the
    # stops are found one at a time.
    while True:
        end = min([t for t in [r["until"] for r in list(state.get("rituals", {}).values()) + state.get("curses", [])]
                   + cauldron.ends(state) if start < t < now], default=now)
        state["ritual_now"] = start
        with _stats_cached():     # buildings and ideology don't change within a stretch
            _advance(state, end, end - start, coarse)
        start = end
        if end >= now:
            break
        state["ritual_now"] = end
        cauldron.renew(state, end)
    state.pop("ritual_now", None)
    ideology.tidy_rituals(state)
    cauldron.tidy(state)
    trip = state["expedition"]
    while trip and now >= trip["arrive"]:
        _arrive(state, trip)
        if state.get("exp_queue"):          # the next team was waiting: it leaves the moment this one is back
            nxt = state["exp_queue"].pop(0)
            _depart(state, trip["arrive"], nxt["rx"], nxt["ry"])
            log(state, trip["arrive"], f"The next expedition set out {where(nxt['rx'], nxt['ry'])} of home.")
        trip = state["expedition"]
    beasts.tick(state, now)


def _advance(state, now, remaining, coarse=False):
    res = state["resources"]
    totals = state.setdefault("totals", {})
    jobs, housing, _ = work_plan(state)
    wildlife_speed = city_stat(state, "wildlife_speed") + beasts.bonus(state, "wildlife_speed")
    rng = random.Random()

    while remaining > 0:
        dt = min(LONG_STEP if coarse or remaining > LONG_CATCH_UP else SIM_STEP, remaining)
        env = weather.job_factors(state, jobs, now - remaining)    # day or night and the weather as this step starts
        remaining -= dt
        power = power_status(state, jobs, env)[2]
        for i, job in enumerate(jobs):
            speed = _speed(state, job, power, env[i][0])
            if not speed or job["cycle"] is None:
                continue
            tile, b = job["tile"], job["b"]
            tile["progress"] += dt * speed
            while tile["progress"] >= job["cycle"]:
                if _missing(state, b.get("consumes", {})):
                    tile["progress"] = job["cycle"]   # finished, waiting for inputs
                    break
                _pay(state, b.get("consumes", {}))
                for k, v in b.get("consumes", {}).items():
                    totals["used:" + k] = totals.get("used:" + k, 0) + v
                for k, v in job_output(state, job).items():
                    res[k] += v
                    totals["made:" + k] = totals.get("made:" + k, 0) + v
                tile["progress"] -= job["cycle"]
        state["meal"] += dt
        while state["meal"] >= MEAL_TIME:
            state["meal"] -= MEAL_TIME
            when = now - remaining
            if _meal(state, housing, when):
                jobs, housing, _ = work_plan(state)
            # a new spell of weather starts in every area: rare weather is worth watching
            rare = [i for i in range(len(state["areas"])) if weather.WEATHER[weather.weather_at(state, i, when + 1)].get("rare")]
            if rare:
                tally(state, "rare_weather", len(rare))
                beasts.note(state, when, "weather")
                beasts.weather_egg(state, when, rare, rng)
        state["wild"] += dt * (1 + wildlife_speed) * ideology.curse_factor(state, "wildlife")
        while state["wild"] >= WILDLIFE_TIME:
            state["wild"] -= WILDLIFE_TIME
            night = weather.is_night(state, now - remaining)
            for area in state["areas"]:
                _spawn_animal(area, rng, night)


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
    tally(state, "built")
    beasts.note(state, now, "build")
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
    tally(state, "demolished")
    log(state, now, f"Demolished {b['name']} at ({x},{y}) in {area_name(area)}.")
    return None


PRIORITIES = {2: "first", 1: "high", 0: "normal", -1: "off"}   # who gets workers first; see work_plan
PRIORITY_VERSION = 2          # saves from before "high" had first as 1: migrate() moves it to 2


def set_priority(state, now, area, x, y, priority):
    """Choose how this building is staffed: 1 = first, 0 = normal, -1 = switched off."""
    tile = area["tiles"][y][x]
    if not tile["building"] or not BUILDINGS[tile["building"]].get("workers"):
        return "That building has no workers to assign."
    if priority not in PRIORITIES or isinstance(priority, bool):
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
    tally(state, "additions")
    beasts.note(state, now, "addition")
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
    if r.get("ritual"):
        if not ideology.chosen(state):
            return "choose an ideology first"
        earlier = next((k for k, x in RESEARCH.items() if x.get("ritual") == r["ritual"] - 1), None)
        if earlier and earlier not in state["research"]:
            return f"research {RESEARCH[earlier]['name']} first"
    return None


# ---- Mastery: endless research for a Megacity ----
# Once a city is a Megacity it can keep studying each resource for ever. Every level of a resource's mastery makes
# everything the city's buildings make of it MASTERY_STEP more (+3%, +6%, ...), with no top. A level costs Knowledge
# and the resource itself (Knowledge's own mastery costs Knowledge alone), MASTERY_GROWTH times as much as the level
# before: it is where a Megacity's surplus goes, and the further it goes the slower it gets.
MASTERY_TECH = 5
MASTERY_STEP = 0.03
MASTERY_GROWTH = 1.3
MASTERY_COST = {      # level 1: (knowledge, the resource itself)
    "food": (25_000, 150_000), "wood": (25_000, 60_000), "stone": (25_000, 60_000), "ore": (25_000, 40_000),
    "tools": (25_000, 15_000), "gold": (25_000, 100_000), "electronics": (25_000, 4_000), "livestock": (25_000, 1_500),
    "knowledge": (60_000, 0),
}


def mastery_level(state, res):
    return state.get("mastery", {}).get(res, 0)


def mastery_bonus(state, res):
    """How much more of `res` the city's buildings make: 0.03 per level."""
    return MASTERY_STEP * mastery_level(state, res)


def mastery_cost(state, res):
    """What the next level of this resource's mastery costs."""
    know, own = MASTERY_COST[res]
    f = MASTERY_GROWTH ** mastery_level(state, res)
    cost = {"knowledge": int(round(know * f, -2))}
    if own:
        cost[res] = cost.get(res, 0) + int(round(own * f, -2 if own * f >= 1000 else 0))
    return cost


def master(state, now, res):
    if res not in MASTERY_COST:
        return "Pick a resource to master."
    if state["tech"] < MASTERY_TECH:
        return f"Mastery opens when your city is a {TECH_LEVELS[MASTERY_TECH]['name']}."
    cost = mastery_cost(state, res)
    short = _missing(state, cost)
    if short:
        return f"Not enough to master {RESOURCES[res]} further (need {fmt_goods(short)})."
    _pay(state, cost)
    state.setdefault("mastery", {})[res] = mastery_level(state, res) + 1
    tally(state, "masteries")
    log(state, now, f"Mastery of {RESOURCES[res]} is now level {mastery_level(state, res)}: buildings make "
                    f"{round(mastery_bonus(state, res) * 100)}% more {RESOURCES[res]}. It cost {fmt_goods(cost)}.")
    return None


def mastery_view(state):
    return {"open": state["tech"] >= MASTERY_TECH, "tech": TECH_LEVELS[MASTERY_TECH]["name"], "step": MASTERY_STEP,
            "growth": MASTERY_GROWTH,
            "tracks": {res: {"level": mastery_level(state, res), "bonus": round(mastery_bonus(state, res), 3),
                             "cost": mastery_cost(state, res), "affordable": not _missing(state, mastery_cost(state, res))}
                       for res in MASTERY_COST}}


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
    tally(state, "researched")
    beasts.note(state, now, "research")
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
    tally(state, "tech_ups")
    _expand_area(state["areas"][0])
    log(state, now, f"*** {state['name']} is now a {nxt['name']}! The home area has grown. ***")
    beasts.tech_egg(state, now, state["tech"])
    return None


# ---- Presents ----
# The admin sends these from the console (see server.py --present). A present
# waits in the city, wrapped, until its player opens it; only then are the
# goods added.

MAX_PRESENT_MESSAGE = 300
MAX_SOCIAL_LIST = 200       # cities one city can mark as ally or enemy (the lists do nothing in the game)


def give_present(state, now, message, gifts, egg=None, people=0):
    """Leave a wrapped present in the city. `gifts` is {resource: amount}; `egg` a rarity or None;
    `people` new arrivals (they move in even if every bed is taken)."""
    state["present_count"] = state.get("present_count", 0) + 1
    state.setdefault("presents", []).append({
        "id": state["present_count"], "t": now, "message": str(message or "")[:MAX_PRESENT_MESSAGE],
        "gifts": {k: v for k, v in gifts.items() if k in RESOURCES and v > 0},
        "egg": egg if egg in beasts.RARITIES else None, "people": max(0, int(people or 0)), "opened": False})
    log(state, now, "A present has arrived for the city.")


def open_present(state, now, present_id):
    present = next((p for p in state.get("presents", []) if p["id"] == present_id), None)
    if not present:
        return "That present is no longer here."
    if present["opened"]:
        return None
    present["opened"] = True
    tally(state, "presents")
    for k, v in present["gifts"].items():
        state["resources"][k] += v
    got = [fmt_goods(present["gifts"])] if present["gifts"] else []
    if present.get("people"):
        state["population"] += present["people"]
        tally(state, "arrivals", present["people"])
        got.append(f"{present['people']} new {'person' if present['people'] == 1 else 'people'}")
    if present["egg"]:
        beasts.new_egg(state, now, beasts.random_species(random.Random(), rarity=present["egg"]))
        got.append(f"a {beasts.RARITIES[present['egg']]['name'].lower()} beast egg")
    log(state, now, f"Opened a present: {' and '.join(got) or 'nothing inside'}.")
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

def _spawn_animal(area, rng, night=None):
    """A wild animal wanders onto a free tile, if the area has room for more.
    night: True or False if it is night or day in the city (None: either)."""
    tiles = [t for row in area["tiles"] for t in row]
    if sum(1 for t in tiles if t["animal"]) >= MAX_WILDLIFE:
        return
    free = [t for t in tiles if not t["building"] and not t["animal"]]
    if not free:
        return
    tile = rng.choice(free)
    species = [s for s, w in WILDLIFE.items() if any(terrain_is(tile["terrain"], t) for t in w["terrain"])]
    if species:
        when = lambda s: 1 if night is None or "night" not in WILDLIFE[s] else (3 if WILDLIFE[s]["night"] == night else 0.2)
        tile["animal"] = rng.choices(species, weights=[WILDLIFE[s]["weight"] * when(s) for s in species])[0]


def tame_cost(species):
    return {"food": WILDLIFE[species]["livestock"] * TAME_FOOD_PER_HEAD}


def tame(state, now, area, x, y, quiet=False):
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
    tally(state, "tamed")
    tally(state, "tamed_livestock", w["livestock"])
    beasts.note(state, now, "tame")
    beasts.tame_egg(state, now, random.Random())
    tile["animal"] = None
    if not quiet:
        log(state, now, f"Tamed {w['name'].lower()} in {area_name(area)}: +{w['livestock']} Livestock.")
    return None


def tame_all(state, now, areas):
    """Tame every wild animal in these areas that there is bait for, in map order. One line in the log."""
    problem = _need_research(state, "taming", "Taming")
    if problem:
        return problem + "."
    spots = [(area, x, y) for area in areas for y, row in enumerate(area["tiles"]) for x, t in enumerate(row) if t["animal"]]
    if not spots:
        return "There are no wild animals there to tame."
    tamed, livestock, food, left = 0, 0, 0, 0
    for area, x, y in spots:
        species = area["tiles"][y][x]["animal"]
        if _missing(state, tame_cost(species)):
            left += 1
            continue
        tame(state, now, area, x, y, quiet=True)
        tamed += 1
        livestock += WILDLIFE[species]["livestock"]
        food += tame_cost(species)["food"]
    if not tamed:
        return f"Not enough Food to tame any of them (the cheapest needs {min(tame_cost(a['tiles'][y][x]['animal'])['food'] for a, x, y in spots)})."
    where = area_name(areas[0]) if len(areas) == 1 else "every area"
    log(state, now, f"Tamed {tamed} wild {'animal' if tamed == 1 else 'animals'} in {where} for {food} Food: +{livestock} Livestock."
        + (f" {left} more could not be tamed: not enough Food." if left else ""))
    return None


def slaughter(state, now, count):
    """Kill livestock by hand for food: quick, but a Butcher gets far more from each animal."""
    if not (isinstance(count, int) and not isinstance(count, bool) and count >= 1):
        return "Choose how many livestock to slaughter."
    if state["resources"]["livestock"] < count:
        return f"You only have {int(state['resources']['livestock'])} livestock."
    state["resources"]["livestock"] -= count
    state["resources"]["food"] += count * SLAUGHTER_FOOD
    tally(state, "slaughtered", count)
    log(state, now, f"Slaughtered {count} livestock for {count * SLAUGHTER_FOOD} Food.")
    return None


# ---- Exploration ----

def region_env(state, rx, ry):
    """What kind of land lies at this position. Fixed for the life of the city."""
    rng = random.Random(f"{state['seed']}/{rx}/{ry}")
    names = [e for e, d in ENVIRONMENTS.items() if d["weight"]]
    return rng.choices(names, weights=[ENVIRONMENTS[e]["weight"] for e in names])[0]


def planned(state):
    """Positions an expedition is heading for or waiting to head for."""
    trip = state.get("expedition")
    return ([(trip["rx"], trip["ry"])] if trip else []) + [(q["rx"], q["ry"]) for q in state.get("exp_queue", [])]


def queue_room(state):
    """How many expeditions can wait behind the one under way: from research and buildings, at most MAX_EXPEDITION_QUEUE."""
    return min(MAX_EXPEDITION_QUEUE, int(sum(_researched(state, "exp_queue")) + city_stat(state, "exp_queue")))


def destinations(state, with_planned=False):
    """Undiscovered positions next to an area already mapped, leaving out those an expedition is heading for (or
    keeping them, with_planned, for the Explore tab to show where they stand). New land opens up only when an
    expedition has mapped the land next to it, not when one sets out: a queue can't run on ahead in one direction,
    and the list of places to go doesn't change with every team sent."""
    known = {(a["rx"], a["ry"]) for a in state["areas"]}
    skip = set() if with_planned else set(planned(state))
    out = set()
    for rx, ry in known:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p = (rx + dx, ry + dy)
            if p not in known and p not in skip:
                out.add(p)
    return sorted(out, key=lambda p: (abs(p[0]) + abs(p[1]), p[1], p[0]))


def explore_speed(state):
    """What buildings add to expedition speed: in full up to FULL_EXPLORE_SPEED, then a step per doubling."""
    x = city_stat(state, "explore_speed")
    return x if x <= FULL_EXPLORE_SPEED else FULL_EXPLORE_SPEED + EXPLORE_SPEED_STEP * math.log2(x / FULL_EXPLORE_SPEED)


def explore_discount(state):
    """The share of an expedition's supplies still needed: research's discount, then the ideology's, which
    comes ever closer to free but never reaches it (0.15 of explore_cost is 18% off, 0.6 is 47% off, 1.0 is 60% off)."""
    cut = max(0, ideology.value(state, "explore_cost"))
    return min(_researched(state, "explore_discount"), default=1) / (1 + EXPLORE_COST_WEIGHT * cut)


def expedition_cost(state, rx, ry):
    """Supplies for the team: the land it is heading into, how far it is, how much land the city holds already
    (counting expeditions on their way or queued) and its tech level. See EXPEDITION_DISTANCE_POWER."""
    distance = abs(rx) + abs(ry)
    held = len(state["areas"]) + len(planned(state))
    scale = (distance ** EXPEDITION_DISTANCE_POWER * (1 + EXPEDITION_AREA_STEP * (held - 1))
             * (1 + EXPEDITION_TECH_STEP * state["tech"]))
    cost = {k: v * scale for k, v in ENVIRONMENTS[region_env(state, rx, ry)]["cost"].items()}
    cost["livestock"] = distance * (EXPEDITION_LIVESTOCK[0] + EXPEDITION_LIVESTOCK[1] * held)
    food = cost.get("food", 0)
    if state["tech"] >= 2:
        cost["tools"] = food * EXPEDITION_TOOLS
    if state["tech"] >= 3:
        cost["gold"] = food * EXPEDITION_GOLD
    discount = explore_discount(state)
    return {k: max(1, math.ceil(v * discount)) for k, v in cost.items()}


def expedition_time(state, rx, ry):
    """Seconds the journey takes. Stables and the like shorten it."""
    speed = (1 + explore_speed(state) + beasts.bonus(state, "explore_speed")) * ideology.curse_factor(state, "explore")
    return round(EXPEDITION_TIME * (abs(rx) + abs(ry)) / speed)


def expedition_problem(state, rx, ry):
    """Why a team can't be sent to this position (ignoring cost), or None."""
    problem = _need_research(state, "explore_range", "Exploring")
    if problem:
        return problem
    if (rx, ry) in planned(state):
        return "an expedition is already heading there"
    if state["expedition"] and len(state.get("exp_queue", [])) >= queue_room(state):
        if not queue_room(state):
            better = next((r["name"] for r in RESEARCH.values() if r.get("exp_queue")), None)
            return "an expedition is already under way" + (f" (research {better} to queue more)" if better else "")
        return f"the queue is full ({queue_room(state)} waiting)"
    if (rx, ry) not in destinations(state):
        return "you can only explore next to land an expedition has already mapped"
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
    for k, v in cost.items():
        tally(state, "supplies:" + k, v)
    if state["expedition"]:      # one is under way: this one waits its turn, its supplies set aside
        state["exp_queue"].append({"rx": rx, "ry": ry, "cost": cost, "queued": now})
        log(state, now, f"An expedition {where(rx, ry)} of home is packed and waiting its turn ({len(state['exp_queue'])} in the queue), "
                        f"with {fmt_goods(cost)}.")
        return None
    _depart(state, now, rx, ry)
    log(state, now, f"An expedition set out {where(rx, ry)} of home with {fmt_goods(cost)}.")
    return None


def _depart(state, when, rx, ry):
    state["expedition"] = {"rx": rx, "ry": ry, "left": when, "arrive": when + expedition_time(state, rx, ry)}


def cancel_queued(state, now, index):
    """Call off a waiting expedition (not the one under way): its supplies come back."""
    queue = state.get("exp_queue", [])
    if not (isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(queue)):
        return "There is no such expedition waiting."
    if any(_depends(state, q, queue[index]) for q in queue[index + 1:]):
        return "A later expedition in the queue can only get there through that land. Call that one off first."
    trip = queue.pop(index)
    for k, v in trip["cost"].items():
        state["resources"][k] += v
    log(state, now, f"Called off the expedition waiting to go {where(trip['rx'], trip['ry'])} of home; "
                    f"its {fmt_goods(trip['cost'])} went back into store.")
    return None


def _depends(state, later, earlier):
    """True if the land `later` is heading for can only be reached through the land `earlier` will map."""
    step = lambda a, b: abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1
    goal, via = (later["rx"], later["ry"]), (earlier["rx"], earlier["ry"])
    others = {(a["rx"], a["ry"]) for a in state["areas"]} | (set(planned(state)) - {goal, via})
    return step(goal, via) and not any(step(goal, o) for o in others)


def _arrive(state, trip):
    """The expedition reaches its goal: map the area, and note what else it found
    in a report the player is shown."""
    when, rng = trip["arrive"], random.Random()
    env = region_env(state, trip["rx"], trip["ry"])
    home = state["areas"][0]
    area = _new_area(trip["rx"], trip["ry"], env, home["climate"] + ENVIRONMENTS[env]["temp"], rng)
    state["areas"].append(area)
    state["expedition"] = None
    log(state, when, f"*** The expedition has mapped a new area: {area_name(area)}. ***")
    tally(state, "expeditions")

    distance = abs(trip["rx"]) + abs(trip["ry"])
    loot = {}
    if rng.random() < EXPEDITION_LOOT_CHANCE:
        res, least, most = rng.choice(EXPEDITION_LOOT + ENVIRONMENTS[env].get("loot", []) * 2)
        loot[res] = rng.randint(least, most) * distance
        state["resources"][res] += loot[res]
    egg = beasts.expedition_egg(state, when, distance, rng, env)
    if egg:
        log(state, when, "*** The expedition brought back a beast egg! See the Beast tab. ***")
    tiles = [t for row in area["tiles"] for t in row]
    land = {}
    for t in tiles:
        land[TERRAINS[t["terrain"]]["name"]] = land.get(TERRAINS[t["terrain"]]["name"], 0) + 1
    state["reports"].append({
        "t": when, "area": area_name(area), "land": ENVIRONMENTS[env]["name"], "where": where(trip["rx"], trip["ry"]),
        "terrain": sorted(land.items(), key=lambda kv: -kv[1])[:5],
        "animals": sorted({WILDLIFE[t["animal"]]["name"] for t in tiles if t["animal"]}),
        "loot": loot,
        "egg": beasts.RARITIES[beasts.SPECIES[egg["species"]]["rarity"]]["name"] if egg else None,
    })
    del state["reports"][:-50]       # kept until read in the Explore tab's summary
    beasts.note(state, when, "explore")


def apply_action(state, now, action, data):
    """Run one player action. Returns an error message, or None on success."""
    if action == "advance":
        return advance(state, now)
    if action == "ideology_choose":
        return ideology.choose(state, now, data.get("ideology"))
    if action == "perk_take":
        return ideology.take(state, now, data.get("perk"))
    if action == "ritual_start":
        return ideology.start_ritual(state, now, data.get("ritual"), data.get("gold"))
    if action == "cauldron_set":
        return cauldron.set_recipe(state, now, data.get("recipe"), data.get("times", 1))
    if action == "cauldron_stop":
        return cauldron.stop(state, now)
    if action == "artifact_craft":
        return artifacts.craft(state, now, data.get("kind"), data.get("times", 1))
    if action == "artifact_enshrine":
        return artifacts.enshrine(state, now, data.get("artifact"))
    if action == "artifact_unenshrine":
        return artifacts.unenshrine(state, now, data.get("artifact"))
    if action == "artifact_break":
        return artifacts.break_up(state, now, data.get("artifact"))
    if action == "beast_active":
        return beasts.set_active(state, now, data.get("beast"))
    if action == "breed_set":
        return beasts.breed_set(state, now, data.get("male"), data.get("female"), data.get("count"))
    if action == "breed_queue":
        return beasts.breed_queue(state, now, data.get("male"), data.get("female"), data.get("count"))
    if action == "breed_unqueue":
        return beasts.breed_unqueue(state, now, data.get("index"))
    if action == "breed_stop":
        return beasts.breed_stop(state, now)
    if action == "breed_collect":
        return beasts.breed_collect(state, now)
    if action == "mission_deliver":
        return beasts.deliver(state, now)
    if action == "egg_deliver":
        return beasts.deliver(state, now, data.get("beast"))
    if action == "training_set":
        return set_training(state, now, data.get("share"))
    if action == "tree_take":
        return ideology.tree_take(state, now, data.get("node"))
    if action == "quest_give":
        return ideology.quest_give(state, now, data.get("res") or None, data.get("amount"))
    if action == "tutorial":
        return tutorial_reach(state, now, data.get("reach"))
    if action == "tutorial_skip":
        tut = state.get("tutorial") or {}
        if not tut.get("skippable"):
            return "A new city goes through the tutorial to the end."
        tut["done"] = True
        return None
    if action == "report_seen":     # the player has read the oldest expedition report
        since = data.get("since")
        if isinstance(since, (int, float)) and not isinstance(since, bool):
            # ...or every report from since the player went away: the "while you were away" summary covers them
            state["reports"] = [r for r in state["reports"] if r["t"] <= since]
        else:
            del state["reports"][:1]
        return None
    if action == "slaughter":
        return slaughter(state, now, data.get("count"))
    if action == "dismiss_away":
        state["report"] = None
        return None
    if action == "social_list":     # put another city on the ally or enemy list, or take it off both
        target, tag = data.get("target"), data.get("list")
        if not isinstance(target, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", target) or target == state["name"]:
            return "Pick another city."
        lists = state.setdefault("social", {"lists": {}, "history": []})["lists"]
        if tag not in ("ally", "enemy"):
            lists.pop(target, None)
        elif target not in lists and len(lists) >= MAX_SOCIAL_LIST:
            return f"You can keep at most {MAX_SOCIAL_LIST} cities on your lists."
        else:
            lists[target] = tag
        return None
    if action == "present_open":
        return open_present(state, now, data.get("present"))
    if action == "present_close":
        state["presents"] = [p for p in state.get("presents", []) if p["id"] != data.get("present")]
        return None
    if action == "mastery":
        return master(state, now, data.get("resource"))
    if action == "research":
        return research(state, now, data.get("research"))
    if action == "explore":
        return send_expedition(state, now, data.get("rx"), data.get("ry"))
    if action == "explore_cancel":
        return cancel_queued(state, now, data.get("index"))
    if action == "rename_area":
        target = data.get("target")
        if not (isinstance(target, int) and 0 <= target < len(state["areas"])):
            return "Unknown area."
        return rename_area(state, now, state["areas"][target], data.get("name"))
    if action == "tame_all":     # "area": an area's index, or "all" for every area
        target = data.get("area")
        if target == "all":
            return tame_all(state, now, state["areas"])
        if not (isinstance(target, int) and 0 <= target < len(state["areas"])):
            return "Unknown area."
        return tame_all(state, now, [state["areas"][target]])
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

def view(state, ai=0, detail=None):
    """The saved state plus everything the UI needs computed to show area `ai`.

    What could be built or added on a tile is only worked out for `detail`, the
    (x, y) of the tile the player has selected: doing it for every tile was most
    of the work and most of the size of each reply.
    """
    with _stats_cached():
        return _view(state, ai, detail)


DEFS = None       # the content tables the page needs, the same for every city; see defs()


def defs():
    global DEFS
    if DEFS is None:
        DEFS = {
            "terrains": TERRAINS,
            "resources": RESOURCES,
            "tradeable": [k for k in RESOURCES if k not in UNTRADEABLE],
            "buildings": BUILDINGS,
            "categories": CATEGORIES,
            "tech": TECH_LEVELS,
            "research": RESEARCH,
            "additions": ADDITIONS,
            "max_additions": MAX_ADDITIONS,
            "slaughter_food": SLAUGHTER_FOOD,
            "tame_food": TAME_FOOD_PER_HEAD,
            "environments": ENVIRONMENTS,
            "wildlife": WILDLIFE,
            "ideologies": ideology.defs(),
            "cauldron": cauldron.defs(),
            "artifacts": artifacts.defs(),
            "weather": weather.defs(),
        }
    return DEFS


def _queue_view(state):
    """The waiting expeditions, each with when it should set off and be back (if nothing changes)."""
    out, t = [], (state["expedition"] or {}).get("arrive", state["updated"])
    for q in state.get("exp_queue", []):
        took = expedition_time(state, q["rx"], q["ry"])
        out.append({"rx": q["rx"], "ry": q["ry"], "where": where(q["rx"], q["ry"]), "env": region_env(state, q["rx"], q["ry"]),
                    "cost": q["cost"], "leaves": t, "arrive": t + took})
        t += took
    return out


def unpaused_projection(state, plan=None, env=None):
    """Net rates at full housing with paused buildings enabled; never edits the city.
    plan / env: the city's work_plan() and weather.job_factors() if the caller has them already. What each
    building is and how fast it runs do not depend on who works where, so only the workers are handed out again."""
    with _stats_cached():
        jobs, housing, totals = plan or work_plan(state)
        jobs = [dict(j, priority=max(0, j["priority"])) for j in jobs]
        _staff(jobs, housing, totals["herd_room"])
        if env is None:
            env = weather.job_factors(state, jobs, state["updated"])
        supply, demand, power = power_status(state, jobs, env)
        rates = {k: 0.0 for k in RESOURCES}
        rates["food"] = -housing * 3600 / MEAL_TIME
        for i, job in enumerate(jobs):
            if not job["cycle"] or _missing(state, job["b"].get("consumes", {})):
                continue
            per_hour = 3600 / job["cycle"] * _speed(state, job, power, env[i][0])
            for k, v in job_output(state, job).items():
                rates[k] += v * per_hour
            for k, v in job["b"].get("consumes", {}).items():
                rates[k] -= v * per_hour
        return {"rates": {k: round(v, 1) for k, v in rates.items()},
                "power": {"supply": round(supply, 1), "demand": demand}}


def unpaused_rates(state):
    return unpaused_projection(state)["rates"]


def _view(state, ai, detail):
    if not 0 <= ai < len(state["areas"]):
        ai = 0
    area = state["areas"][ai]
    jobs, housing, totals = work_plan(state)
    rates = {k: 0.0 for k in RESOURCES}   # expected change per hour, whole city
    rates["food"] -= state["population"] * 3600 / MEAL_TIME
    food_made = 0.0
    food_potential = 0.0
    here = {}
    env = weather.job_factors(state, jobs, state["updated"])
    supply, demand, power = power_status(state, jobs, env)
    projected = unpaused_projection(state, (jobs, housing, totals), env)
    # The Cauldron's ingredients, taken every hour while it brews (its effect is in the buildings' speed already).
    for k, v in cauldron.hourly(state).items():
        rates[k] -= v
        projected["rates"][k] = round(projected["rates"][k] - v, 1)
    for i, job in enumerate(jobs):
        job["env"], job["power_env"] = env[i][0], env[i][1]
        job["notes"] = job["notes"] + env[i][2]
        job["env_notes"] = env[i][2]
        job["speed"] = _speed(state, job, power, env[i][0])
        job["waiting"] = list(_missing(state, job["b"].get("consumes", {})))
        job["output"] = job_output(state, job)
        if job["cycle"]:
            food_potential += job["output"].get("food", 0) * 3600 / job["cycle"] * env[i][0]
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
                            power_in=job["power_in"], power_out=round(job["power_out"] * job.get("power_env", 1), 1))
                if "herd" in job["b"]:
                    cell["herd"], cell["herd_room"] = job_herd(state, job), job["herd"]
            if tile["animal"]:
                cost = tame_cost(tile["animal"])
                cell["tame"] = {"problem": tame_problem, "cost": cost,
                                "affordable": not _missing(state, cost)}
            if tile["building"]:
                cell["housing"] = tile_housing(tile)
            if (x, y) != detail:
                pass                     # build and addition choices only for the selected tile
            elif tile["building"]:
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
    plan = planned(state)
    for rx, ry in destinations(state, with_planned=True):
        if (rx, ry) in plan:        # kept in the list where it was: "on its way" (0) or its place in the queue
            explore.append({"rx": rx, "ry": ry, "where": where(rx, ry), "env": region_env(state, rx, ry),
                            "distance": abs(rx) + abs(ry), "planned": plan.index((rx, ry))})
            continue
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
                   "renamed": bool(a.get("label")), "default_name": default_area_name(a),
                   "where": where(a["rx"], a["ry"]), "distance": abs(a["rx"]) + abs(a["ry"]),
                   "buildings": sum(1 for row in a["tiles"] for t in row if t["building"]),
                   "animals": sum(1 for row in a["tiles"] for t in row if t["animal"]),
                   # buildings that are not working properly
                   "problems": sum(1 for j in jobs if j["area"] == i and j["status"] != "working"
                                   and not j["status"].startswith("stopped:"))}
                  for i, a in enumerate(state["areas"])],
        "status": {
            "housing": housing,
            "jobs": totals["jobs"],
            "idle": totals["idle"],
            "herd_room": totals["herd_room"],
            "power": {"supply": round(supply, 1), "demand": demand},
            "rates": {k: round(v, 1) for k, v in rates.items()},
            "unpaused_rates": projected["rates"],
            "unpaused_power": projected["power"],
            "meal_time": MEAL_TIME,
            # expedition speed: what buildings add before and after the step past FULL_EXPLORE_SPEED, and in all
            "explore": {"raw": round(city_stat(state, "explore_speed"), 3), "counted": round(explore_speed(state), 3),
                        "full": FULL_EXPLORE_SPEED, "step": EXPLORE_SPEED_STEP,
                        "times": round((1 + explore_speed(state) + beasts.bonus(state, "explore_speed"))
                                       * ideology.curse_factor(state, "explore"), 3)},
            "food_made": round(food_made, 1),
            "food_potential": round(food_potential, 1),
            "food_eaten": round(state["population"] * 3600 / MEAL_TIME, 1),
            "housing_from": housing_sources(state),
            "growth": growth_checks(state, housing),
            # whole people: _arrivals lets one more in while fewer than this have come, so a fraction counts as one more
            "arrivals_max": math.ceil(1 + city_attracts(state, state["updated"] + MEAL_TIME - state["meal"]) - 1e-9),
            "advance": advance_view(state),
            "arrivals_next": next_arrivals(state, housing),
        },
        "tiles": tiles,
        "environment": weather.view(state, state["updated"]),
        "research": [{"id": rid, "done": rid in state["research"],
                      "problem": research_problem(state, rid),
                      "affordable": not _missing(state, r["cost"])}
                     for rid, r in RESEARCH.items()],
        "beast": beasts.view(state, state["updated"]),
        "ideology": ideology.view(state),
        "cauldron": cauldron.view(state),
        "artifacts": artifacts.view(state),
        "mastery": mastery_view(state),
        "training": training_view(state),
        "reports": state["reports"],
        "explore": {
            "destinations": explore,
            "expedition": trip and {**trip, "where": where(trip["rx"], trip["ry"]),
                                    "env": region_env(state, trip["rx"], trip["ry"])},
            "queue": _queue_view(state), "queue_room": queue_room(state), "queue_max": MAX_EXPEDITION_QUEUE,
        },
        "defs": defs(),
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
    stopped = [n.rsplit(" x", 1)[0] for n in job.get("env_notes", []) if n.endswith(" x0.00")]
    if stopped:
        return "stopped: " + ", ".join(stopped).lower()
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


def find(state, kind, what, here=None):
    """Search every area of the city. Returns {"results": [...], "total": n, "areas": {area: n},
    "here": [...]} or {"locked": research name} if the search needs research the city lacks. "results" is the
    first FIND_LIMIT over the whole city; "here" is every match in area `here` (the one on screen), for the map.

    kind is "buildings" (what = a building id, or "" for all), "problems",
    "wildlife", "sites" (what = a building id: where it could go, fastest
    first) or "terrain" (what = a terrain id).
    """
    if kind in ("sites", "terrain") and not _researched(state, "surveying"):
        return {"locked": next(r["name"] for r in RESEARCH.values() if r.get("surveying"))}
    found = []   # (sort key, result)
    jobs, _, _ = work_plan(state)
    env = weather.job_factors(state, jobs, state["updated"])
    power = power_status(state, jobs, env)[2]
    for i, job in enumerate(jobs):
        job["env"], job["power_env"], job["env_notes"] = env[i][0], env[i][1], env[i][2]
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
                    if kind == "buildings" or (job and status != "working" and not status.startswith("stopped:")):
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
    per_area = {}       # every match counts here, including those past FIND_LIMIT
    for _, r in found:
        per_area[r["area"]] = per_area.get(r["area"], 0) + 1
    # the best in each area: the quickest sites, the most livestock (the lowest sort key there, when keys differ)
    best = {}
    for key, r in found:
        best.setdefault(r["area"], key)
    keys = {}
    for key, r in found:
        keys.setdefault(r["area"], set()).add(key)
    for key, r in found:
        r["best"] = kind in ("sites", "wildlife") and len(keys[r["area"]]) > 1 and key == best[r["area"]]
    return {"query": f"{kind}:{what}", "results": [r for _, r in found[:FIND_LIMIT]], "total": len(found),
            "areas": per_area, "here": [r for _, r in found if r["area"] == here]}


def housing_sources(state):
    """Where the city's housing comes from: [[name, places], ...]."""
    out = {"Starting camp": BASE_HOUSING}
    if int(beasts.bonus(state, "housing")):
        out[beasts.title(beasts.active(state))] = int(beasts.bonus(state, "housing"))
    if int(ideology.value(state, "housing")):
        out[ideology.chosen(state)["name"]] = int(ideology.value(state, "housing"))
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


# The city's lifetime counters (state["totals"]), counted from when the city first had them.
# "made:<resource>" / "used:<resource>" / "supplies:<resource>" are kept per resource.
TALLIES = [
    ("meals", "Meals eaten"), ("hungry_meals", "Meals with too little food"), ("eaten", "Food eaten"),
    ("arrivals", "People who have arrived"), ("built", "Buildings built"), ("demolished", "Buildings demolished"),
    ("additions", "Additions attached"), ("researched", "Research done"), ("masteries", "Mastery levels gained"), ("tech_ups", "Tech levels gained"),
    ("expeditions", "Expeditions completed"), ("tamed", "Wild animals tamed"), ("tamed_livestock", "Livestock from taming"),
    ("slaughtered", "Livestock slaughtered by hand"), ("rare_weather", "Spells of rare weather seen (area x meal)"),
    ("eggs", "Eggs found"), ("bred", "Eggs bred"), ("hatched", "Eggs hatched"), ("egg_missions", "Egg missions done"),
    ("missions", "Beast missions done"), ("beast_levels", "Beast levels gained"),
    ("bought", "Market purchases made"), ("sold", "Market sales to other cities"),
    ("beast_trades", "Beast trades"), ("duels_won", "Duels won"), ("duels_lost", "Duels lost"),
    ("rituals", "Rituals held"), ("brews", "Brews from the Cauldron"), ("artifacts_crafted", "Artifacts crafted"), ("artifact_trades", "Artifacts traded"), ("curses_cast", "Hexes, sabotage and the like done to other cities"), ("curses_taken", "Hexes, sabotage and the like done to your city"), ("messages_sent", "Messages sent"), ("messages_received", "Messages received"), ("presents", "Presents opened"),
]


def city_stats(state, now, rates):
    """Everything there is to know about the city, in sections for the Stats tab.

    Each section is {"id", "title", "blocks": [{"title"?, "head"?, "rows"}]}: rows are
    [label, value, note] (a block with "head" is a table, each row one cell per heading).
    A value is a number, text, {"time": t}, {"dur": seconds} or {"pct": share}.
    `rates` is the change per hour of every resource (from view(), with bills).
    """
    with _stats_cached():
        return _city_stats(state, now, rates)


def _city_stats(state, now, rates):
    jobs, housing, totals = work_plan(state)
    env = weather.job_factors(state, jobs, state["updated"])
    supply, demand, power = power_status(state, jobs, env)
    tiles = [(ai, t) for ai, area in enumerate(state["areas"]) for row in area["tiles"] for t in row]
    built = [t for _, t in tiles if t["building"]]
    pct = lambda x: {"pct": x}
    sections = []

    def section(sid, title, *blocks):
        sections.append({"id": sid, "title": title, "blocks": [b for b in blocks if b and b["rows"]]})

    # ---- overview
    tech = TECH_LEVELS[state["tech"]]
    ideo = ideology.chosen(state)
    checks = advance_checks(state)
    section("overview", "Overview", {"rows": [
        ["City", state["name"], ""],
        ["Tech level", f"{tech['name']} ({state['tech'] + 1} of {len(TECH_LEVELS)})", ""],
        ["Next tech level", TECH_LEVELS[state["tech"] + 1]["name"] if checks else "none: the highest reached",
         f"{sum(c['ok'] for c in checks)} of {len(checks)} requirements met" if checks else ""],
        ["Founded", {"time": state["founded"]}, ""],
        ["Age", {"dur": now - state["founded"]}, ""],
        ["Ideology", ideo["name"] if ideo else "not chosen yet", f"{len(state.get('perks', []))} perks taken, {ideology.points(state)} points to spend" if ideo else ""],
        ["Population", state["population"], ""],
        ["Buildings", len(built), ""],
        ["Areas", len(state["areas"]), ""],
        ["Research done", len(state["research"]), f"of {len(RESEARCH)}"],
        ["Beasts", sum(1 for b in state["beasts"] if b["stage"] != "egg"), f"{sum(1 for b in state['beasts'] if b['stage'] == 'egg')} eggs"],
    ]})

    # ---- people
    workers = state["population"] - totals["idle"]
    section("people", "People", {"rows": [
        ["Population", state["population"], ""],
        ["Housing", housing, f"{max(0, housing - state['population'])} beds free"],
        ["Jobs", totals["jobs"], f"{max(0, totals['jobs'] - workers)} unfilled"],
        ["Working", workers, pct(workers / state["population"]) if state["population"] else ""],
        ["Idle", totals["idle"], ""],
        ["Hungry", "yes: buildings that don't make food work at half speed" if state["hungry"] else "no", ""],
        ["Food eaten per meal", state["population"], f"every {MEAL_TIME // 60} minutes"],
        ["Food eaten per hour", round(state["population"] * 3600 / MEAL_TIME), ""],
        ["Food in store lasts", {"dur": state["resources"]["food"] / state["population"] * MEAL_TIME} if state["population"] else "", "with nothing more made"],
        ["Next meal in", {"dur": MEAL_TIME - state["meal"]}, ""],
        ["Most arrivals per meal", 1 + city_attracts(state, state["updated"] + MEAL_TIME - state["meal"]), ""],
        ["Arrivals at the next meal", next_arrivals(state, housing), ""],
        ["Extra arrivals from buildings", city_stat(state, "attracts"), ""],
        ["Extra arrivals at night", weather.night_attracts(state, state["updated"] + 12 * 3600) if not weather.is_night(state, state["updated"])
         else weather.night_attracts(state, state["updated"]), "from taverns, bath houses and resorts"],
        ["Housing from buildings", sum(tile_housing(t) for t in built), ""],
        ["Housing from the starting camp", BASE_HOUSING, ""],
    ]}, {"title": "Housing by building", "head": ["Building", "Built", "Houses"],
         "rows": sorted(([BUILDINGS[bid]["name"], n, h] for bid, (n, h) in _group(built, tile_housing).items() if h),
                        key=lambda r: -r[2])})

    # ---- resources
    made, used = {k: 0.0 for k in RESOURCES}, {k: 0.0 for k in RESOURCES}
    by_building = {}
    for i, job in enumerate(jobs):
        speed = _speed(state, job, power, env[i][0])
        if not speed or not job["cycle"] or _missing(state, job["b"].get("consumes", {})):
            continue
        per_hour = 3600 / job["cycle"] * speed
        for k, v in job_output(state, job).items():
            made[k] += v * per_hour
            key = (k, job["tile"]["building"])
            by_building[key] = by_building.get(key, 0) + v * per_hour
        for k, v in job["b"].get("consumes", {}).items():
            used[k] += v * per_hour
    used["food"] += state["population"] * 3600 / MEAL_TIME
    section("resources", "Resources", {"head": ["Resource", "In store", "Made per hour", "Used per hour", "Change per hour", "Runs out in"],
        "rows": [[RESOURCES[k], int(state["resources"][k]), round(made[k], 1), round(used[k], 1), rates.get(k, 0),
                  {"dur": state["resources"][k] / -rates[k] * 3600} if rates.get(k, 0) < 0 and state["resources"][k] > 0 else ""]
                 for k in RESOURCES]},
        *[{"title": f"{RESOURCES[k]}: what makes it", "head": ["Building", "Per hour", "Share"],
           "rows": [[BUILDINGS[bid]["name"], round(v, 1), pct(v / made[k])]
                    for (res, bid), v in sorted(by_building.items(), key=lambda kv: -kv[1]) if res == k][:12]}
          for k in RESOURCES if made[k]])

    # ---- buildings
    working = sum(1 for j in jobs if job_status(state, j, power) == "working")
    off = sum(1 for t in built if t.get("priority", 0) < 0)
    first = sum(1 for t in built if t.get("priority", 0) >= 2)
    high = sum(1 for t in built if t.get("priority", 0) == 1)
    slots = len(built) * MAX_ADDITIONS
    attached = sum(len(t["additions"]) for t in built)
    kinds = {t["building"] for t in built}
    available = [bid for bid, b in BUILDINGS.items() if b["tech"] <= state["tech"]]
    section("buildings", "Buildings", {"rows": [
        ["Buildings", len(built), ""],
        ["Kinds built", len(kinds), f"of {len(available)} open to your tech level, {len(BUILDINGS)} in the game"],
        ["Working buildings", len(jobs), "that need workers or make something"],
        ["Working properly", working, pct(working / len(jobs)) if jobs else ""],
        ["Not working properly", len(jobs) - working, ""],
        ["Switched off", off, ""],
        ["Staffed first", first, ""],
        ["Staffed high", high, "after First, before Normal"],
        ["Additions attached", attached, f"of {slots} slots ({MAX_ADDITIONS} per building)"],
        ["Kinds of addition used", len({a for t in built for a in t["additions"]}), f"of {len(ADDITIONS)} in the game"],
        ["One-of-a-kind buildings", sum(1 for k in kinds if BUILDINGS[k].get("unique")), ""],
        ["Sheltered from day, night and weather", sum(1 for _, t in tiles if t["building"] and (BUILDINGS[t["building"]].get("sheltered") or TERRAINS[t["terrain"]].get("sheltered"))), ""],
    ]}, {"title": "By kind", "head": ["Kind", "Built"],
         "rows": [[name, sum(1 for t in built if BUILDINGS[t["building"]].get("category") == cat)] for cat, name in CATEGORIES.items()]},
        {"title": "By tech level", "head": ["Tech level", "Built", "Kinds built"],
         "rows": [[lvl["name"], sum(1 for t in built if BUILDINGS[t["building"]]["tech"] == i),
                   f"{sum(1 for k in kinds if BUILDINGS[k]['tech'] == i)} of {sum(1 for b in BUILDINGS.values() if b['tech'] == i)}"]
                  for i, lvl in enumerate(TECH_LEVELS)]},
        {"title": "Every building", "head": ["Building", "Built", "Additions"],
         "rows": sorted(([BUILDINGS[bid]["name"], n, a] for bid, (n, a) in _group(built, lambda t: len(t["additions"])).items()),
                        key=lambda r: (-r[1], r[0]))})

    # ---- power
    gens = [j for j in jobs if j["power_out"]]
    section("power", "Power", {"rows": [
        ["Supplied", round(supply, 1), ""],
        ["Needed", demand, ""],
        ["Share of the need met", pct(power), "powered buildings slow down in proportion when it is short"],
        ["Spare", round(supply - demand, 1), ""],
        ["Generators", len(gens), ""],
        ["Buildings that need power", sum(1 for j in jobs if j["power_in"]), ""],
        ["Generator bonus", pct(1 + beasts.bonus(state, "power") + ideology.value(state, "power")), "from your beast and ideology"],
    ]}, {"title": "Where the power comes from", "head": ["Generator", "Built", "Power now"],
         "rows": sorted(([BUILDINGS[bid]["name"], n, round(p, 1)] for bid, (n, p) in _group(
             [j for j in gens], lambda j: j["power_out"] * j["ratio"] * env[jobs.index(j)][1], key=lambda j: j["tile"]["building"]).items()),
             key=lambda r: -r[2])})

    # ---- land
    n_tiles = len(tiles)
    land = [t for _, t in tiles if not terrain_is(t["terrain"], "water")]
    hi = max(tiles, key=lambda p: p[1]["height"])
    hot = max(tiles, key=lambda p: p[1]["temp"])
    cold = min(tiles, key=lambda p: p[1]["temp"])
    far = max(state["areas"], key=lambda a: abs(a["rx"]) + abs(a["ry"]))
    section("land", "Land", {"rows": [
        ["Areas", len(state["areas"]), ""],
        ["Tiles", n_tiles, ""],
        ["Tiles built on", len(built), pct(len(built) / n_tiles)],
        ["Free tiles", n_tiles - len(built), ""],
        ["Land tiles", len(land), ""],
        ["Water tiles", n_tiles - len(land), ""],
        ["Home area size", f"{state['areas'][0]['size']} x {state['areas'][0]['size']}", ""],
        ["Farthest area", area_name(far), f"{abs(far['rx']) + abs(far['ry'])} steps from home"],
        ["Average fertility of land", round(sum(t["fertility"] for t in land) / max(1, len(land))), "%"],
        ["Average temperature", round(sum(t["temp"] for _, t in tiles) / n_tiles, 1), "C"],
        ["Highest tile", hi[1]["height"], area_name(state["areas"][hi[0]])],
        ["Hottest tile", hot[1]["temp"], f"C, {area_name(state['areas'][hot[0]])}"],
        ["Coldest tile", cold[1]["temp"], f"C, {area_name(state['areas'][cold[0]])}"],
        ["Kinds of terrain owned", len({t["terrain"] for _, t in tiles}), f"of {len(TERRAINS)} in the game"],
        ["Kinds of land owned", len({a["env"] for a in state["areas"]}), f"of {len(ENVIRONMENTS)} in the game"],
        ["Wild animals on your land", sum(1 for _, t in tiles if t["animal"]), ""],
    ]}, {"title": "Terrain", "head": ["Terrain", "Tiles", "Built on"],
         "rows": sorted(([TERRAINS[k]["name"], n, b] for k, (n, b) in _group([t for _, t in tiles], lambda t: 1 if t["building"] else 0,
                                                                              key=lambda t: t["terrain"]).items()), key=lambda r: -r[1])},
        {"title": "Kinds of land", "head": ["Land", "Areas"],
         "rows": sorted(([ENVIRONMENTS[k]["name"], n] for k, (n, _) in _group(state["areas"], lambda a: 0, key=lambda a: a["env"]).items()),
                        key=lambda r: -r[1])},
        {"title": "Wild animals here now", "head": ["Animal", "Here", "Worth"],
         "rows": sorted(([WILDLIFE[k]["name"], n, f"{WILDLIFE[k]['livestock']} livestock each"] for k, (n, _) in _group(
             [t for _, t in tiles if t["animal"]], lambda t: 0, key=lambda t: t["animal"]).items()), key=lambda r: -r[1])})

    # ---- research
    open_now = [rid for rid in RESEARCH if not research_problem(state, rid)]
    section("research", "Research", {"rows": [
        ["Done", len(state["research"]), f"of {len(RESEARCH)} in the game"],
        ["Can be researched now", len(open_now), f"{sum(1 for rid in open_now if not _missing(state, RESEARCH[rid]['cost']))} affordable"],
        ["Knowledge in store", int(state["resources"]["knowledge"]), ""],
        ["Knowledge per hour", rates.get("knowledge", 0), ""],
        ["Knowledge spent on research", sum(RESEARCH[r]["cost"].get("knowledge", 0) for r in state["research"]), ""],
        ["Cheapest left", min((RESEARCH[r]["cost"].get("knowledge", 0) for r in open_now), default=""), "knowledge"],
    ]}, {"title": "By tech level", "head": ["Tech level", "Done", "In the game"],
         "rows": [[lvl["name"], sum(1 for r in state["research"] if RESEARCH[r]["tech"] == i),
                   sum(1 for r in RESEARCH.values() if r["tech"] == i)] for i, lvl in enumerate(TECH_LEVELS)]})

    # ---- bonuses
    def factor(cat):
        out = 1.0
        for bonus in (beasts.speed_bonus(state, cat), ideology.speed_bonus(state, cat), cauldron.speed_bonus(state, cat),
                      artifacts.speed_bonus(state, cat)):
            if bonus:
                out *= bonus[0]
        return out
    night, weather_cover = weather.shelter(state)
    section("bonuses", "Bonuses", {"rows": [
        ["Expedition speed", pct(1 + explore_speed(state) + beasts.bonus(state, "explore_speed")), "of normal"],
        ["Expedition supplies", pct(explore_discount(state)), "of the full cost"],
        ["Expedition range", (lambda r: "any distance" if r >= 99 else f"{r} areas" if r else "none yet")(max(_researched(state, "explore_range"), default=0)), ""],
        ["Wildlife appears", pct(1 + city_stat(state, "wildlife_speed") + beasts.bonus(state, "wildlife_speed")), "of normal"],
        ["Generators give", pct(1 + beasts.bonus(state, "power") + ideology.value(state, "power")), "of normal"],
        ["Night's slowdowns spared", pct(night), ""],
        ["Bad weather's slowdowns spared", pct(weather_cover), ""],
        ["Beast mission experience", pct(1 + city_stat(state, "beast_xp")), "of normal"],
        ["Beast bonus strength", pct(1 + city_stat(state, "beast_power")), "of normal"],
        ["Egg hatching speed", pct(1 + city_stat(state, "hatch_speed")), "of normal"],
        ["Beast missions come", pct(1 + city_stat(state, "mission_speed")), "as often as normal"],
        ["Extra chance of an egg on an expedition", pct(city_stat(state, "egg_chance")), ""],
        ["Weather forecast", f"{weather.forecast_length(state)} meal{'s' if weather.forecast_length(state) > 1 else ''} ahead", ""],
    ]}, {"title": "Speed of each kind of building, from your beast and ideology", "head": ["Kind", "Speed"],
         "rows": [[name, pct(factor(cat))] for cat, name in CATEGORIES.items()]})

    # ---- time and weather
    wv = weather.view(state, state["updated"])
    skies = {}
    for a in wv["areas"]:
        skies[a["now"]] = skies.get(a["now"], 0) + 1
    section("weather", "Time and weather", {"rows": [
        ["Time of day", f"{'Night' if wv['night'] else 'Day'}, {wv['clock']}", "on the player's own clock"],
        [f"{'Day' if wv['night'] else 'Night'} comes in", {"dur": wv["switch_in"]}, ""],
        ["Weather changes in", {"dur": wv["change_in"]}, "at the next meal"],
        ["Areas with rare weather now", sum(n for w, n in skies.items() if weather.WEATHER[w].get("rare")), ""],
        ["Areas the weather is slowing", len({j["area"] for j, e in zip(jobs, env) if e[0] < 1 and any("Night" not in n and "Day" not in n for n in e[2])}), ""],
    ]}, {"title": "Weather in your areas now", "head": ["Weather", "Areas"],
         "rows": sorted(([weather.WEATHER[w]["name"] + (" (rare)" if weather.WEATHER[w].get("rare") else ""), n] for w, n in skies.items()),
                        key=lambda r: -r[1])})

    # ---- beasts
    hatched = [b for b in state["beasts"] if b["stage"] != "egg"]
    act = beasts.active(state)
    section("beasts", "Beasts", {"rows": [
        ["Hatched beasts", len(hatched), ""],
        ["Eggs", len(state["beasts"]) - len(hatched), ""],
        ["Species owned", len({b["species"] for b in hatched}), f"of {len(beasts.SPECIES)} in the game"],
        ["Active beast", f"{beasts.title(act)}, level {act['level']} (fully grown at {beasts.max_level(act)})" if act and act["stage"] != "egg" else "none yet", ""],
        ["Highest level", max((b["level"] for b in hatched), default=0), ""],
        ["Levels in all", sum(b["level"] for b in hatched), ""],
        ["Strongest (stats added up)", max((sum(b["stats"].values()) for b in hatched), default=0), ""],
        ["Mission", (state.get("mission") or {}).get("text", "none"), "done" if (state.get("mission") or {}).get("complete") else ""],
        ["Next mission in", {"dur": max(0, state["mission_at"] - now)} if hatched else "", ""],
    ]}, {"title": "By rarity", "head": ["Rarity", "Beasts", "Eggs"],
         "rows": [[r["name"], sum(1 for b in hatched if beasts.SPECIES[b["species"]]["rarity"] == k),
                   sum(1 for b in state["beasts"] if b["stage"] == "egg" and beasts.SPECIES[b["species"]]["rarity"] == k)]
                  for k, r in beasts.RARITIES.items()]})

    # ---- lifetime
    t = state.get("totals", {})
    since = state.get("totals_since", state["founded"])
    section("lifetime", "All time", {"rows": [["Counted since", {"time": since}, ""]] + [[label, t.get(key, 0), ""] for key, label in TALLIES]},
            {"title": "Made, used and sent on expeditions", "head": ["Resource", "Made", "Used by buildings", "Sent with expeditions"],
             "rows": [[RESOURCES[k], int(t.get("made:" + k, 0)), int(t.get("used:" + k, 0)), int(t.get("supplies:" + k, 0))] for k in RESOURCES]})
    # A few words for each section's button, so the player can see how things stand without opening it.
    falling = [RESOURCES[k] for k in RESOURCES if rates.get(k, 0) < 0]
    act = beasts.active(state)
    heads = {
        "overview": tech["name"],
        "people": f"{state['population']} of {housing} beds" + (", hungry" if state["hungry"] else ""),
        "resources": f"{len(falling)} falling" if falling else "all rising",
        "buildings": f"{len(built)}" + (f", {len(jobs) - working} not working" if len(jobs) - working else ""),
        "power": f"{round(power * 100)}% met" if demand else "none needed",
        "land": f"{len(state['areas'])} areas, {n_tiles - len(built)} free tiles",
        "research": f"{len(state['research'])} of {len(RESEARCH)}",
        "bonuses": "",
        "weather": f"{'Night' if wv['night'] else 'Day'}, {wv['clock']}",
        "beasts": f"level {act['level']} {beasts.title(act)}" if act and act["stage"] != "egg" else f"{len(state['beasts'])} eggs",
        "lifetime": "",
    }
    for s in sections:
        s["headline"] = heads.get(s["id"], "")
    return sections


def _group(items, value, key=lambda t: t["building"]):
    """{key: (how many, value added up)} over items."""
    out = {}
    for it in items:
        n, v = out.get(key(it), (0, 0))
        out[key(it)] = (n + 1, v + value(it))
    return out


def summary(state):
    """One leaderboard row."""
    return {
        "name": state["name"],
        "tech": state["tech"],
        "tech_name": TECH_LEVELS[state["tech"]]["name"],
        "ideology": ideology.chosen(state)["name"] if ideology.chosen(state) else None,
        "population": state["population"],
        # research done, and every Mastery level a Megacity has studied since (each is research too)
        "research": len(state["research"]) + sum(state.get("mastery", {}).values()),
        "researched": len(state["research"]),
        "mastery": sum(state.get("mastery", {}).values()),
        "quests": state.get("quests", {}).get("done", 0),       # ideology quests done
        "beast": max((b["level"] for b in state["beasts"]), default=0),
        "areas": len(state["areas"]),
        "buildings": sum(1 for t in all_tiles(state) if t["building"]),
        "resources": {k: int(state["resources"].get(k, 0)) for k in RESOURCES},
    }
