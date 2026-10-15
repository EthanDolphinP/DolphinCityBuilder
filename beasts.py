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

More eggs come from expeditions (rarer species are likelier far from home,
and a species is likelier in the kinds of land it lives in, its "home"), from
rare weather (now and then an egg turns up where it is passing),
from taming wild animals (a small chance of a nest), from reaching a new tech
level, from a beast reaching level 5 and level 10, and from a Nesting Ground
building, which lays one every few days. Presents and trades can bring them too.

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

import math
import random

import game

HOUR = 3600
MISSION_TIME = 24 * HOUR    # a new mission this often
MAX_LEVEL = 20              # the highest level any beast can reach (see each rarity's max_level)
FULL_LEVELS = 10            # levels past this add half as much to a beast's bonus
MISSION_XP = 10             # experience for a completed mission, before bonuses (times the rarity's xp)
TECH_PAY = [1, 2, 4, 8, 15, 25]   # "bring me" missions ask for this many times more at each tech level
INCOME_HOURS = 1.5          # ...and at least this many hours of what the city makes of it (more for rarer and higher beasts)
TECH_EVENTS = 0.25          # "do something" missions marked "scales" ask for 25% more per tech level
EGG_CHANCE = 0.15           # chance an expedition finds an egg...
EGG_CHANCE_PER_STEP = 0.05  # ...plus this for every step of distance from home
EGG_CHANCE_MAX = 0.6
RARER_PER_STEP = 0.25       # how much each step of distance favours the rarer species
TAME_EGG_CHANCE = 0.06      # chance that taming a wild animal turns up an egg
TECH_EGGS = ["common", "uncommon", "rare", "epic", "legendary"]   # the egg for reaching Village, Town, ...
EGG_LEVELS = {5: 0, 10: 1, 15: 1, 20: 2}   # a beast reaching this level brings home an egg this many rarities above its own
NEST_TIME = 48 * HOUR       # a Nesting Ground lays an egg this often...
NEST_FULL = 3               # ...unless the city already has this many unhatched eggs
NEST_WEIGHTS = {"common": 70, "uncommon": 25, "rare": 5}
HOME_WEIGHT = 4             # a species is this many times likelier on an expedition into land it calls home
WEATHER_EGG_CHANCE = 0.004  # chance, at each meal, that rare weather in an area turns up an egg there

# weight     how often an egg found by an expedition is of this rarity
# hatch      hours an egg must be kept warm
# egg_tasks  missions an egg needs done, one after another, before it hatches
# max_level  the highest level the beast can reach
# pay        "bring me" missions ask for this many times more
# events     "do something" missions ask for this many times more
# xp         a completed mission gives this many times MISSION_XP
RARITIES = {
    "common":    {"name": "Common",    "weight": 60, "color": "#cfd8d3", "hatch": 2,  "egg_tasks": 1, "max_level": 10,
                  "pay": 1.0, "events": 1.0, "xp": 1.0},
    "uncommon":  {"name": "Uncommon",  "weight": 25, "color": "#7fc97f", "hatch": 4,  "egg_tasks": 1, "max_level": 12,
                  "pay": 1.6, "events": 1.25, "xp": 1.2},
    "rare":      {"name": "Rare",      "weight": 10, "color": "#5aa7d8", "hatch": 8,  "egg_tasks": 2, "max_level": 15,
                  "pay": 2.5, "events": 1.6, "xp": 1.5},
    "epic":      {"name": "Epic",      "weight": 4,  "color": "#c58fe5", "hatch": 16, "egg_tasks": 2, "max_level": 18,
                  "pay": 4.0, "events": 2.0, "xp": 1.8},
    "legendary": {"name": "Legendary", "weight": 1,  "color": "#e6c35c", "hatch": 24, "egg_tasks": 3, "max_level": 20,
                  "pay": 6.0, "events": 2.5, "xp": 2.2},
}

# bonus: what the beast gives per level while it is the active beast.
#   speed           {building category, or "all": 0.02} = those buildings 2% faster per level
#   explore_speed   expeditions faster (0.06 = 6% per level)
#   wildlife_speed  wildlife appears more often
#   power           generators give more
#   housing         people housed, per level
#   attracts        extra arrivals per meal, per level (rounded down in total)
#   night_shelter / weather_shelter   share of night's (or the weather's) slowdowns the city is spared, per level
# home: kinds of land (game.ENVIRONMENTS) where its eggs are likelier to be found.
SPECIES = {
    "mossback":    {"name": "Mossback Tortoise", "rarity": "common", "nature": "Patient grower",
                    "home": ["grassland", "floodplains"],
                    "bonus": {"speed": {"food": 0.02}},
                    "desc": "A slow, green-backed tortoise. Crops seem to like having it around."},
    "stonehorn":   {"name": "Stonehorn", "rarity": "common", "nature": "Tireless digger",
                    "home": ["highlands", "karst"],
                    "bonus": {"speed": {"materials": 0.02}},
                    "desc": "A stocky, horned burrower that cannot leave a rock unturned."},
    "glimmerwing": {"name": "Glimmerwing", "rarity": "common", "nature": "Curious",
                    "home": ["woodland", "moorland"],
                    "bonus": {"speed": {"knowledge": 0.02}},
                    "desc": "A moth the size of a cat, drawn to lamplight and open books."},
    "magpie_drake": {"name": "Magpie Drake", "rarity": "common", "nature": "Hoarder",
                     "home": ["badlands", "outback"],
                     "bonus": {"speed": {"trade": 0.02}},
                     "desc": "A small drake with an eye for anything that glitters."},
    "trailhound":  {"name": "Trailhound", "rarity": "uncommon", "nature": "Pathfinder",
                    "home": ["steppe", "savanna"],
                    "bonus": {"explore_speed": 0.06},
                    "desc": "A long-legged hound that always knows the way back."},
    "herdmother":  {"name": "Herdmother", "rarity": "uncommon", "nature": "Shepherd",
                    "home": ["grassland", "steppe"],
                    "bonus": {"wildlife_speed": 0.1, "speed": {"food": 0.01}},
                    "desc": "A shaggy giant that other animals follow without being asked."},
    "sunscale":    {"name": "Sunscale Lizard", "rarity": "uncommon", "nature": "Basks in power",
                    "home": ["desert", "outback"],
                    "bonus": {"power": 0.03},
                    "desc": "Its scales hum faintly near anything that turns or burns."},
    "hearth_lynx": {"name": "Hearth Lynx", "rarity": "rare", "nature": "Homely",
                    "home": ["taiga", "woodland"],
                    "bonus": {"housing": 2, "attracts": 0.2},
                    "desc": "A great soft cat. People settle where it sleeps."},
    "stormcrest":  {"name": "Stormcrest Eagle", "rarity": "rare", "nature": "Inspiring",
                    "home": ["highlands", "sea_cliffs"],
                    "bonus": {"speed": {"all": 0.015}},
                    "desc": "It circles the city at dawn, and everyone works a little harder."},
    "goldmaw":     {"name": "Goldmaw Toad", "rarity": "rare", "nature": "Lucky",
                    "home": ["lakeland", "delta"],
                    "bonus": {"speed": {"trade": 0.05}},
                    "desc": "Merchants rub its head for luck. It seems to work."},
    "world_turtle": {"name": "World Turtle", "rarity": "epic", "nature": "Carries a village",
                     "home": ["islands", "reef"],
                     "bonus": {"housing": 4, "speed": {"food": 0.02}},
                     "desc": "Big enough to build on, and it does not seem to mind."},
    "frost_wyrm":  {"name": "Frost Wyrm", "rarity": "epic", "nature": "Ancient mind",
                    "home": ["tundra", "icefields"],
                    "bonus": {"speed": {"knowledge": 0.06}, "explore_speed": 0.03},
                    "desc": "Older than the hills, and willing to share some of what it remembers."},
    "sky_serpent": {"name": "Sky Serpent", "rarity": "legendary", "nature": "Sovereign",
                    "home": ["sea_cliffs", "highlands"],
                    "bonus": {"speed": {"all": 0.03}, "explore_speed": 0.06, "attracts": 0.2},
                    "desc": "A ribbon of cloud and scale. Cities it favours are spoken of far away."},
    "burrow_hare": {"name": "Burrow Hare", "rarity": "common", "nature": "Skittish forager",
                    "home": ["grassland", "moorland"],
                    "bonus": {"wildlife_speed": 0.08, "speed": {"food": 0.01}},
                    "desc": "Never still, and it knows where every wild thing in the valley sleeps."},
    "pebble_crab": {"name": "Pebble Crab", "rarity": "common", "nature": "Shore-comber",
                    "home": ["coast", "reef"],
                    "bonus": {"speed": {"materials": 0.015, "trade": 0.01}},
                    "desc": "It carries home anything it can lift, and sorts it into neat piles."},
    "ember_newt":  {"name": "Ember Newt", "rarity": "common", "nature": "Warm-blooded",
                    "home": ["volcanic"],
                    "bonus": {"power": 0.02},
                    "desc": "Warm to the touch. It sleeps wherever the city is hottest."},
    "reed_heron":  {"name": "Reed Heron", "rarity": "common", "nature": "Far-sighted",
                    "home": ["delta", "lakeland", "floodplains"],
                    "bonus": {"explore_speed": 0.04},
                    "desc": "It stands very still for hours, then leaves in exactly the right direction."},
    "ironback_boar": {"name": "Ironback Boar", "rarity": "uncommon", "nature": "Rooter",
                      "home": ["woodland", "jungle"],
                      "bonus": {"speed": {"materials": 0.035}},
                      "desc": "Its tusks turn up ore the miners walked straight past."},
    "lantern_owl": {"name": "Lantern Owl", "rarity": "uncommon", "nature": "Night scholar",
                    "home": ["woodland", "karst"],
                    "bonus": {"speed": {"knowledge": 0.035}},
                    "desc": "Its eyes glow bright enough to read by, and it does not like being ignored."},
    "marsh_otter": {"name": "Marsh Otter", "rarity": "uncommon", "nature": "Playful dealer",
                    "home": ["lakeland", "delta"],
                    "bonus": {"speed": {"trade": 0.03, "food": 0.01}},
                    "desc": "It trades shiny stones with anyone who will play along, and usually comes out ahead."},
    "thunder_ram": {"name": "Thunder Ram", "rarity": "rare", "nature": "Charged",
                    "home": ["highlands", "moorland"],
                    "bonus": {"power": 0.05, "speed": {"materials": 0.02}},
                    "desc": "Its fleece crackles. Stand well back when it shakes itself dry."},
    "moon_stag":   {"name": "Moon Stag", "rarity": "rare", "nature": "Wayfinder",
                    "home": ["taiga", "woodland"],
                    "bonus": {"explore_speed": 0.08, "wildlife_speed": 0.1},
                    "desc": "Other animals follow it, and so do travellers who have lost the road."},
    "amber_bear":  {"name": "Amber Bear", "rarity": "rare", "nature": "Provider",
                    "home": ["taiga", "bamboo_valley"],
                    "bonus": {"speed": {"food": 0.05}, "housing": 1},
                    "desc": "Enormous, gentle, and never once seen hungry."},
    "coral_leviathan": {"name": "Coral Leviathan", "rarity": "epic", "nature": "Tide-bringer",
                        "home": ["reef", "islands", "coast"],
                        "bonus": {"speed": {"food": 0.04, "trade": 0.04}},
                        "desc": "Shoals of fish and whole fleets of traders follow in its wake."},
    "ember_phoenix": {"name": "Ember Phoenix", "rarity": "epic", "nature": "Ever-burning",
                      "home": ["volcanic", "desert"],
                      "bonus": {"power": 0.08, "speed": {"all": 0.01}},
                      "desc": "It has burned out and come back more times than the city has had rulers."},
    "elder_dragon": {"name": "Elder Dragon", "rarity": "legendary", "nature": "Hoard-keeper",
                     "home": ["badlands", "karst"],
                     "bonus": {"speed": {"trade": 0.08, "all": 0.02}, "housing": 3},
                     "desc": "It has decided that this city is part of its hoard, and guards it accordingly."},
    "dusk_moth":   {"name": "Dusk Moth", "rarity": "common", "nature": "Night-flier", "home": ["moorland", "woodland"],
                    "bonus": {"night_shelter": 0.025, "speed": {"knowledge": 0.01}},
                    "desc": "Grey by day, silver by night. Wherever it settles, people stay up late working."},
    "rain_frog":   {"name": "Rain Frog", "rarity": "common", "nature": "Rain-caller", "home": ["floodplains", "delta", "bamboo_valley"],
                    "bonus": {"weather_shelter": 0.025, "speed": {"food": 0.01}},
                    "desc": "It sings before every shower, and the worst of the weather seems to pass the city by."},
    "echo_bat":    {"name": "Echo Bat", "rarity": "uncommon", "nature": "Cave-dweller", "home": ["karst"],
                    "bonus": {"speed": {"materials": 0.025}, "night_shelter": 0.02},
                    "desc": "It hears the ore in the rock, and leads the night shift to it."},
    "snow_lion":   {"name": "Snow Lion", "rarity": "rare", "nature": "Storm-walker", "home": ["icefields", "tundra", "highlands"],
                    "bonus": {"weather_shelter": 0.05, "explore_speed": 0.03},
                    "desc": "A great white cat that walks through blizzards as if they were spring rain."},
    "crystal_drake": {"name": "Crystal Drake", "rarity": "epic", "nature": "Prism-hearted", "home": ["karst"],
                      "bonus": {"speed": {"knowledge": 0.04}, "power": 0.04},
                      "desc": "Light bends through its scales. Scholars and engineers both come to watch."},
    "aurora_whale": {"name": "Aurora Whale", "rarity": "legendary", "nature": "Sky-swimmer", "home": ["icefields", "reef", "sea_cliffs"],
                     "bonus": {"night_shelter": 0.05, "weather_shelter": 0.05, "speed": {"all": 0.02}},
                     "desc": "It swims through the night sky trailing green light. Under it, night is never quite dark and storms never quite break."},
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
    "burrow_hare":  (40, 9, 7, 20),
    "pebble_crab":  (55, 10, 20, 5),
    "ember_newt":   (45, 14, 9, 12),
    "reed_heron":   (42, 12, 8, 16),
    "ironback_boar": (85, 17, 18, 9),
    "lantern_owl":  (50, 15, 10, 22),
    "marsh_otter":  (58, 14, 11, 19),
    "thunder_ram":  (80, 25, 18, 16),
    "moon_stag":    (72, 20, 15, 26),
    "amber_bear":   (105, 24, 20, 9),
    "coral_leviathan": (150, 30, 30, 10),
    "ember_phoenix": (95, 40, 18, 30),
    "elder_dragon": (170, 44, 34, 24),
    "dusk_moth":    (38, 10, 6, 21),
    "rain_frog":    (48, 11, 10, 15),
    "echo_bat":     (52, 16, 9, 24),
    "snow_lion":    (100, 28, 18, 24),
    "crystal_drake": (120, 36, 36, 20),
    "aurora_whale": (190, 38, 34, 22),
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
    "burrow_hare": [
        r"   (\ /)",
        r"   ( . .)",
        r"  c(_)(_)",
    ],
    "pebble_crab": [
        r" (\/)    (\/)",
        r"   \_o__o_/",
        r"   /|____|\ ",
        r"  ^ ^    ^ ^",
    ],
    "ember_newt": [
        r"     __  ^^",
        r"  ~~/ o\_____",
        r"    \__  __  \~~~",
        r"      ^^   ^^",
    ],
    "reed_heron": [
        r"      _",
        r"     (o>",
        r"  \\_// \ ",
        r"   \___/ )",
        r"     | |",
    ],
    "ironback_boar": [
        r"    _^^^^^_",
        r"  <(o      )~",
        r"   ^(__  __)",
        r"     ||  ||",
    ],
    "lantern_owl": [
        r"   ,___,",
        r"   (O,O)",
        r"   /)_)",
        r"   -^-^-",
    ],
    "marsh_otter": [
        r"    .--.",
        r"   ( oo )____",
        r"    \__/     \~",
        r"   ~~ ~~~~~ ~~",
    ],
    "thunder_ram": [
        r"  @)  (@    /",
        r"  (o__o)  _/",
        r"  /    \ /_",
        r"  |_||_|  /",
    ],
    "moon_stag": [
        r"  \|/ \|/",
        r"   (o o)    )",
        r"    \_/____/",
        r"     ||  ||",
    ],
    "amber_bear": [
        r"  (\___/)",
        r"  ( o o )",
        r"  (  v  )___",
        r"  (___)____)",
    ],
    "coral_leviathan": [
        r"        __/\__",
        r"  ~~~~~/ o    \~~~",
        r"  ~~~ <__  ____>~~",
        r"  ~~~~~~ \/ ~~~~~~",
    ],
    "ember_phoenix": [
        r"    \ ^ /",
        r"  ---(o>---",
        r"   /// \\\ ",
        r"    // \\ ",
    ],
    "elder_dragon": [
        r"   /\_/\    /|",
        r"  ( o o )__/ |__",
        r"   \ v /   ___  \>",
        r"    VVV___/   \__\ ",
    ],
    "dusk_moth": [
        r"  \  .  /",
        r" (\(oo)/)",
        r"  \_||_/",
        r"    /  \ ",
    ],
    "rain_frog": [
        r"   ' ' '",
        r"   (o)(o)",
        r"  (  __  )",
        r"  /_/  \_\ ",
    ],
    "echo_bat": [
        r" /\  ^^  /\ ",
        r"/  \(oo)/  \ ",
        r"\_/\ \/ /\_/",
        r"      vv",
    ],
    "snow_lion": [
        r"  *  ,/|_  *",
        r"   (=o.o=)___",
        r"  * (  W   ) *~",
        r"     |_|--|_|",
    ],
    "crystal_drake": [
        r"   /\ <>  /\ ",
        r"  <(o o)><//  >",
        r"   \ v /<>___/",
        r"    /\/\  /\ ",
    ],
    "aurora_whale": [
        r" ~*~*~*~*~*~*~",
        r"   ___________ \ ",
        r"  (  o        >==",
        r"   ~~~~~~~~~~~ /",
    ],
}

# ---- Duels ----
# One city challenges another; each bets goods on one of its beasts, unseen by
# the other, and the beasts fight. The winner's city takes both bets and the
# winning beast gains DUEL_XP (see "Duels" in market.py). A beast does not
# fight better for being a higher level. It fights better the more is bet on
# it, and far better when the bet is the material its species likes.
LIKES = {
    "mossback": "food", "stonehorn": "stone", "glimmerwing": "wood", "magpie_drake": "gold",
    "trailhound": "food", "herdmother": "livestock", "sunscale": "ore",
    "hearth_lynx": "wood", "stormcrest": "livestock", "goldmaw": "gold",
    "world_turtle": "stone", "frost_wyrm": "tools", "sky_serpent": "electronics",
    "burrow_hare": "food", "pebble_crab": "stone", "ember_newt": "ore", "reed_heron": "livestock",
    "ironback_boar": "wood", "lantern_owl": "tools", "marsh_otter": "gold",
    "thunder_ram": "ore", "moon_stag": "wood", "amber_bear": "food",
    "coral_leviathan": "livestock", "ember_phoenix": "tools", "elder_dragon": "gold",
    "dusk_moth": "wood", "rain_frog": "food", "echo_bat": "ore", "snow_lion": "livestock",
    "crystal_drake": "electronics", "aurora_whale": "food",
}
DUEL = {
    "per": 50,       # every doubling past this much of the liked material...
    "step": 0.25,    # ...adds this much to all four stats (0.25 = 25%)
    "other": 0.2,    # a material it does not care for counts for this share of the amount
    "max": 3.0,      # the most a bet can multiply the stats by
}
DUEL_ROUNDS = 40
DUEL_RESULTS_KEPT = 6
DUEL_XP = 3                 # experience the winning beast gains (a mission gives MISSION_XP)


def duel_boost(species, res, qty):
    """What a bet of `qty` of `res` multiplies this species' stats by in a duel."""
    amount = qty if res == LIKES[species] else qty * DUEL["other"]
    return round(min(DUEL["max"], 1 + DUEL["step"] * math.log2(1 + amount / DUEL["per"])), 2)


def fight(one, two, rng):
    """Fight two sets of stats ({"hp", "atk", "def", "spd"}). Returns (index of the winner, rounds).
    The faster beast strikes first and is harder to hit. Each round is {"by", "dmg", "left"};
    dmg 0 is a miss, and "left" is the health the one struck has left."""
    sides, hp, rounds = (one, two), [one["hp"], two["hp"]], []
    first = 0 if one["spd"] > two["spd"] or (one["spd"] == two["spd"] and rng.random() < 0.5) else 1
    for _ in range(DUEL_ROUNDS):
        for i in (first, 1 - first):
            j = 1 - i
            dodge = max(0, min(0.35, (sides[j]["spd"] - sides[i]["spd"]) / (sides[j]["spd"] + sides[i]["spd"])))
            dmg = 0 if rng.random() < dodge else max(1, round(sides[i]["atk"] * rng.uniform(0.8, 1.2) - sides[j]["def"] * 0.5))
            hp[j] = max(0, hp[j] - dmg)
            rounds.append({"by": i, "dmg": dmg, "left": hp[j]})
            if hp[j] <= 0:
                return i, rounds
    # Nobody fell: whoever has the larger share of their health left wins.
    return (0 if hp[0] / one["hp"] >= hp[1] / two["hp"] else 1), rounds

# kind of mission -> how it is asked for.
#   pay        a resource the city hands over with the Deliver button: it asks for
#              base x (1 + grow x level) x the rarity's pay x TECH_PAY[tech level] ** tech,
#              or, if more, INCOME_HOURS x (1 + 0.15 x level) x the square root of the
#              rarity's pay hours' worth of what the city makes of it (see _income)
#   event      something the city does (see note()): it asks for
#              (base + per_level x level) x the rarity's events, at most cap; with
#              "scales" also x (1 + TECH_EVENTS x tech level), as bigger cities do more
#   min_level  the beast's level before it asks for this (eggs are level 0)
#   min_tech   the city's tech level before it is asked for
# A mission is only ever set if the city can do it (see _possible), and one that
# becomes impossible (the last research done, say) is replaced straight away.
MISSIONS = {
    "feed":      {"text": "Bring it {n} Food", "pay": "food", "base": 20, "grow": 0.5, "tech": 1, "min_level": 0},
    "nest":      {"text": "Bring {n} Wood for its nest", "pay": "wood", "base": 15, "grow": 0.5, "tech": 1, "min_level": 0},
    "claws":     {"text": "Bring {n} Stone to sharpen its claws on", "pay": "stone", "base": 12, "grow": 0.5, "tech": 1, "min_level": 0},
    "treat":     {"text": "Bring it {n} Livestock as a treat", "pay": "livestock", "base": 1, "grow": 0.4, "tech": 0.5, "min_level": 1},
    "lore":      {"text": "Share {n} Knowledge with it", "pay": "knowledge", "base": 8, "grow": 0.5, "tech": 1, "min_level": 1},
    "shiny":     {"text": "Bring it {n} Gold to sleep on", "pay": "gold", "base": 10, "grow": 0.5, "tech": 1, "min_level": 2, "min_tech": 1},
    "gnaw":      {"text": "Bring it {n} Ore to gnaw", "pay": "ore", "base": 8, "grow": 0.5, "tech": 1, "min_level": 2, "min_tech": 1},
    "den":       {"text": "Bring {n} Tools to fit out its den", "pay": "tools", "base": 6, "grow": 0.5, "tech": 1, "min_level": 3, "min_tech": 2},
    "glow":      {"text": "Bring it {n} Electronics: it likes the glow", "pay": "electronics", "base": 4, "grow": 0.4, "tech": 0.7, "min_level": 5, "min_tech": 4},
    "build":     {"text": "Build {n} new building{s} for it to inspect", "event": "build", "base": 1, "per_level": 0.4, "cap": 25, "scales": True, "min_level": 0},
    "addition":  {"text": "Attach {n} addition{s} to your buildings", "event": "addition", "base": 1, "per_level": 0.3, "cap": 12, "scales": True, "min_level": 1},
    "grow":      {"text": "Welcome {n} new arrival{s} to the city", "event": "arrival", "base": 2, "per_level": 0.6, "cap": 40, "scales": True, "min_level": 1},
    "tame":      {"text": "Tame {n} wild animal{s} for it to meet", "event": "tame", "base": 1, "per_level": 0.4, "cap": 12, "scales": True, "min_level": 1},
    "research":  {"text": "Research {n} new thing{s} to show it", "event": "research", "base": 1, "per_level": 0.15, "cap": 6, "min_level": 2},
    "explore":   {"text": "Complete {n} expedition{s} and tell it what you saw", "event": "explore", "base": 1, "per_level": 0.1, "cap": 4, "min_level": 3},
    "weather":   {"text": "Watch {n} spell{s} of rare weather with it (any area, at a meal)", "event": "weather", "base": 1, "per_level": 0.15, "cap": 5, "min_level": 4},
}


def _research_left(state):
    """Research the city could do at its tech level and has not done yet."""
    return sum(1 for rid, r in game.RESEARCH.items() if rid not in state["research"] and r["tech"] <= state["tech"])


def _possible(state, kind):
    """How many of this kind of mission the city could still do (None = no limit), or 0 if it can't be done."""
    m = MISSIONS[kind]
    if state["tech"] < m.get("min_tech", 0):
        return 0
    if kind == "research":
        return _research_left(state)
    if kind == "tame" and not game._researched(state, "taming"):
        return 0
    if kind == "explore" and not game._researched(state, "explore_range"):
        return 0
    return None


def _income(state, res):
    """How much of `res` the city's buildings make in an hour, as staffed now."""
    jobs, _, _ = game.work_plan(state)
    return sum(game.job_output(state, j).get(res, 0) * 3600 / j["cycle"] * j["ratio"]
               for j in jobs if j["cycle"] and j["ratio"])


def _make_mission(state, kind, level, rarity):
    """A mission of this kind for a beast of this level and rarity (an egg is level 0)."""
    m, r = MISSIONS[kind], RARITIES[rarity]
    if m.get("pay"):
        need = m["base"] * (1 + m["grow"] * level) * r["pay"] * TECH_PAY[min(state["tech"], len(TECH_PAY) - 1)] ** m["tech"]
        need = max(need, INCOME_HOURS * (1 + 0.15 * level) * r["pay"] ** 0.5 * _income(state, m["pay"]))
        need = max(1, int(round(need, -1) if need >= 100 else round(need)))
    else:
        scale = 1 + TECH_EVENTS * state["tech"] if m.get("scales") else 1
        need = max(1, min(m["cap"], round((m["base"] + m["per_level"] * level) * r["events"] * scale)))
        left = _possible(state, kind)
        if left:
            need = min(need, left)
    return {"kind": kind, "need": need, "done": 0, "complete": False, "pay": m.get("pay"),
            "text": m["text"].format(n=need, s="" if need == 1 else "s")}


def _pick_kind(state, rng, level, avoid=None):
    """A kind of mission the city can do, for a beast of this level."""
    kinds = [k for k, m in MISSIONS.items() if m["min_level"] <= level and _possible(state, k) != 0
             and (m.get("pay") != "livestock" or state["resources"]["livestock"] or level >= 3)]
    if len(kinds) > 1 and avoid in kinds:
        kinds.remove(avoid)      # not the same thing twice in a row
    return rng.choice(kinds)


# ----------------------------------------------------------------- beasts --

def new_egg(state, now, species):
    state["beast_count"] = state.get("beast_count", 0) + 1
    beast = {"id": state["beast_count"], "species": species, "stage": "egg", "level": 0, "xp": 0,
             "obtained": now, "missions": 0, "tasks_needed": rarity_of(species)["egg_tasks"]}
    beast["task"] = _egg_task(state, species, random.Random())
    beast["stats"] = roll_stats(species, random.Random())
    state["beasts"].append(beast)
    game.tally(state, "eggs")
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
    if beast.get("duel"):
        return None, "That beast is waiting for a duel. Withdraw the duel first."
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
            "color": rarity["color"], "level": beast["level"], "stats": beast["stats"], "nature": species["nature"],
            "likes": LIKES[beast["species"]]}


def _egg_task(state, species, rng, avoid=None):
    """One of the missions an egg needs done before it will hatch: harder for rarer eggs."""
    return _make_mission(state, _pick_kind(state, rng, 0, avoid), 0, SPECIES[species]["rarity"])


def rarity_of(species):
    return RARITIES[SPECIES[species]["rarity"]]


def max_level(beast):
    """The highest level this beast can reach."""
    return rarity_of(beast["species"])["max_level"]


def tasks_needed(beast):
    return beast.get("tasks_needed", 1)     # eggs from before rarities mattered needed one


def random_species(rng, distance=0, rarity=None, env=None):
    """Pick a species: of the given rarity, or weighted by rarity (rarer ones likelier far from home).
    In land of kind `env`, the species that call it home are likelier."""
    names = list(RARITIES)
    if rarity is None:
        weights = [RARITIES[r]["weight"] * (1 + RARER_PER_STEP * distance * i) for i, r in enumerate(names)]
        rarity = rng.choices(names, weights=weights)[0]
    kinds = [s for s, d in SPECIES.items() if d["rarity"] == rarity]
    return rng.choices(kinds, weights=[HOME_WEIGHT if env in SPECIES[s].get("home", []) else 1 for s in kinds])[0]


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
    # Eggs from before rarity mattered: as many missions as their rarity asks, and a fresh one that fits.
    for beast in state["beasts"]:
        if beast["stage"] == "egg" and "tasks_needed" not in beast:
            beast["tasks_needed"] = rarity_of(beast["species"])["egg_tasks"]
            if beast.get("task") and not beast["task"]["complete"]:
                beast["task"] = _egg_task(state, beast["species"], random.Random())
            elif beast["missions"] < beast["tasks_needed"]:
                beast["task"] = _egg_task(state, beast["species"], random.Random())
    # Eggs used to share the daily mission; now each has a mission of its own.
    for beast in state["beasts"]:
        if beast["stage"] == "egg" and beast["missions"] < 1 and "task" not in beast:
            old = state.get("mission")
            if old and not old["complete"] and old.get("beast") == beast["id"]:
                beast["task"] = {k: old[k] for k in ("kind", "need", "done", "complete", "pay", "text")}
                state["mission"] = None
            else:
                beast["task"] = _egg_task(state, beast["species"], random.Random())
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


def bonus_level(level):
    """How many levels' worth of bonus a beast of this level gives: levels past FULL_LEVELS count half."""
    return min(level, FULL_LEVELS) + max(0, level - FULL_LEVELS) / 2


def _power(state):
    return 1 + game.city_stat(state, "beast_power")


def bonus(state, key):
    """The active beast's bonus of this kind right now (0 if it has none, or is still an egg)."""
    beast = active(state)
    if not beast or beast["stage"] == "egg":
        return 0
    return SPECIES[beast["species"]]["bonus"].get(key, 0) * bonus_level(beast["level"]) * _power(state)


def speed_bonus(state, category):
    """(multiplier, label) for buildings of this category, or None."""
    beast = active(state)
    if not beast or beast["stage"] == "egg":
        return None
    per = SPECIES[beast["species"]]["bonus"].get("speed", {})
    extra = (per.get(category, 0) + per.get("all", 0)) * bonus_level(beast["level"]) * _power(state)
    return (1 + extra, title(beast)) if extra else None


def hatch_time(state, beast):
    """Seconds of warmth this egg needs: longer for rarer eggs."""
    return rarity_of(beast["species"])["hatch"] * HOUR / (1 + game.city_stat(state, "hatch_speed"))


def mission_xp(state, beast):
    return round(MISSION_XP * rarity_of(beast["species"])["xp"] * (1 + game.city_stat(state, "beast_xp")))


def mission_period(state):
    return MISSION_TIME / (1 + game.city_stat(state, "mission_speed"))


def give_xp(state, now, beast, amount):
    beast["xp"] += amount
    while beast["level"] < max_level(beast) and beast["xp"] >= xp_needed(beast["level"]):
        beast["xp"] -= xp_needed(beast["level"])
        beast["level"] += 1
        game.tally(state, "beast_levels")
        game.log(state, now, f"*** {title(beast)} has grown to level {beast['level']}. ***")
        if beast["level"] in EGG_LEVELS:
            names = list(RARITIES)
            rarity = names[min(len(names) - 1, names.index(SPECIES[beast["species"]]["rarity"]) + EGG_LEVELS[beast["level"]])]
            new_egg(state, now, random_species(random.Random(), rarity=rarity))
            game.log(state, now, f"{title(beast)} has brought home a {RARITIES[rarity]['name'].lower()} egg.")
    if beast["level"] >= max_level(beast):
        beast["xp"] = 0


# --------------------------------------------------------------- missions --

def _issue(state, now, rng, replacing=False):
    beast = active(state)
    if not beast or beast["stage"] == "egg":
        return
    old = state.get("mission")
    if old and not old["complete"] and not replacing:
        game.log(state, now, f"A mission ran out of time: {old['text']}.")
    kind = _pick_kind(state, rng, beast["level"], old and old["kind"])
    state["mission"] = dict(_make_mission(state, kind, beast["level"], SPECIES[beast["species"]]["rarity"]),
                            issued=now, beast=beast["id"])
    game.log(state, now, f"{title(beast)} has a new mission for you: {state['mission']['text']}.")


def _check_possible(state, now):
    """Replace any mission that can no longer be done (or shrink one that asks for more than is left)."""
    def fix(task):
        if not task or task["complete"] or task["pay"]:
            return task
        left = _possible(state, task["kind"])
        if left == 0:
            return None
        if left is not None and task["need"] - task["done"] > left:
            task["need"] = task["done"] + left
            task["text"] = MISSIONS[task["kind"]]["text"].format(n=task["need"], s="" if task["need"] == 1 else "s")
        return task
    for beast in _waiting_eggs(state):
        if fix(beast["task"]) is None:
            beast["task"] = _egg_task(state, beast["species"], random.Random(), beast["task"]["kind"])
            game.log(state, now, f"{title(beast)} needs something else now: {beast['task']['text']}.")
    mission = state.get("mission")
    if mission and not mission["complete"] and fix(mission) is None:
        _issue(state, now, random.Random(), replacing=True)


def _complete(state, now):
    mission = state["mission"]
    mission["complete"] = True
    beast = get(state, mission["beast"])
    if not beast:
        return
    game.log(state, now, f"Mission complete: {mission['text']}.")
    game.tally(state, "missions")
    if beast["stage"] != "egg":
        give_xp(state, now, beast, mission_xp(state, beast))
    tick(state, now)


def _complete_egg(state, now, beast):
    beast["task"]["complete"] = True
    beast["missions"] += 1
    game.tally(state, "egg_missions")
    game.log(state, now, f"Egg mission complete: {beast['task']['text']}.")
    if beast["missions"] < tasks_needed(beast):      # rarer eggs need more than one, one after another
        beast["task"] = _egg_task(state, beast["species"], random.Random(), beast["task"]["kind"])
        game.log(state, now, f"{title(beast)} needs one more thing ({beast['missions'] + 1} of {tasks_needed(beast)}): "
                             f"{beast['task']['text']}.")
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
        if (beast["stage"] == "egg" and beast["missions"] >= tasks_needed(beast)
                and now - beast["obtained"] >= hatch_time(state, beast)):
            beast.update(stage="hatched", level=1, xp=0, hatched=now)
            game.tally(state, "hatched")
            beast.pop("task", None)
            species = SPECIES[beast["species"]]
            game.log(state, now, f"*** The egg has hatched: a {species['name']} "
                                 f"({RARITIES[species['rarity']]['name'].lower()}), {species['nature'].lower()}. ***")
    _nest(state, now)
    _pick_active(state)
    _check_possible(state, now)
    beast = active(state)
    if not beast or beast["stage"] == "egg":
        return      # beast missions start once the city has a hatched beast
    if now >= state["mission_at"]:
        _issue(state, now, random.Random())
        # one mission per period; after a long absence the clock starts again from now
        state["mission_at"] += mission_period(state)
        if state["mission_at"] <= now:
            state["mission_at"] = now + mission_period(state)


# ------------------------------------------------------- other egg sources --

def tame_egg(state, now, rng):
    """Maybe find an egg in the nest of a wild animal that was just tamed. Returns the egg or None."""
    if rng.random() >= TAME_EGG_CHANCE + game.city_stat(state, "egg_chance"):
        return None
    egg = new_egg(state, now, random_species(rng))
    game.log(state, now, f"There was a {view_name(egg)} hidden in the animal's nest. See the Beast tab.")
    return egg


def tech_egg(state, now, tech):
    """The egg a city is given for reaching tech level `tech` (1 = Village)."""
    rarity = TECH_EGGS[min(len(TECH_EGGS), tech) - 1]
    egg = new_egg(state, now, random_species(random.Random(), rarity=rarity))
    game.log(state, now, f"Travellers drawn by the news left a gift: a {view_name(egg)}. See the Beast tab.")
    return egg


def view_name(beast):
    return f"{RARITIES[SPECIES[beast['species']]['rarity']]['name'].lower()} egg"


def _nest(state, now):
    """A Nesting Ground lays an egg every NEST_TIME, while the city is not already full of eggs."""
    if not game.city_stat(state, "nest"):
        state.pop("nest_at", None)
        return
    if "nest_at" not in state:
        state["nest_at"] = now + NEST_TIME
    if now < state["nest_at"]:
        return
    state["nest_at"] = now + NEST_TIME
    if sum(1 for b in state["beasts"] if b["stage"] == "egg") >= NEST_FULL:
        return
    rng = random.Random()
    rarity = rng.choices(list(NEST_WEIGHTS), weights=list(NEST_WEIGHTS.values()))[0]
    egg = new_egg(state, now, random_species(rng, rarity=rarity))
    game.log(state, now, f"A {view_name(egg)} has been laid at the Nesting Ground. See the Beast tab.")


# ------------------------------------------------------------ expeditions --

def expedition_egg(state, now, distance, rng, env=None):
    """Maybe find an egg on an expedition `distance` steps from home, into land of kind `env`.
    Returns the new beast or None."""
    chance = min(EGG_CHANCE_MAX, EGG_CHANCE + EGG_CHANCE_PER_STEP * distance + game.city_stat(state, "egg_chance"))
    if rng.random() >= chance:
        return None
    return new_egg(state, now, random_species(rng, distance, env=env))


def weather_egg(state, now, rare_areas, rng):
    """At a meal: rare weather in any of these areas may turn up an egg there (not while the city is full of eggs)."""
    if sum(1 for b in state["beasts"] if b["stage"] == "egg") >= NEST_FULL:
        return None
    for ai in rare_areas:
        if rng.random() < WEATHER_EGG_CHANCE:
            area = state["areas"][ai]
            egg = new_egg(state, now, random_species(rng, abs(area["rx"]) + abs(area["ry"]), env=area["env"]))
            game.log(state, now, f"*** The strange weather over {game.area_name(area)} left something behind: "
                                 f"a {view_name(egg)}. See the Beast tab. ***")
            return egg
    return None


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
    if "night_shelter" in per:
        out.append(f"Night slows the city {pct(per['night_shelter'])} less")
    if "weather_shelter" in per:
        out.append(f"Bad weather slows the city {pct(per['weather_shelter'])} less")
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
            entry.update(name=f"{rarity['name']} egg", warm=now - b["obtained"], warm_needed=hatch_time(state, b),
                         missions=b["missions"], tasks_needed=tasks_needed(b), task=b.get("task"))
        else:
            entry.update(name=species["name"], nature=species["nature"], desc=species["desc"],
                         species=b["species"], stats=b["stats"], art="\n".join(ART[b["species"]]),
                         likes=LIKES[b["species"]], duel=bool(b.get("duel")),
                         home=[game.ENVIRONMENTS[e]["name"] for e in species.get("home", [])],
                         xp=b["xp"], xp_needed=xp_needed(b["level"]), max_level=b["level"] >= max_level(b),
                         cap=max_level(b), xp_per_mission=mission_xp(state, b),
                         bonus=_describe(species["bonus"], bonus_level(b["level"]), power),
                         next_bonus=_describe(species["bonus"], bonus_level(min(max_level(b), b["level"] + 1)), power))
        beasts.append(entry)
    return {
        "beasts": beasts,
        "hatched": any(b["stage"] != "egg" for b in state["beasts"]),
        "mission": state.get("mission"),
        "mission_at": state["mission_at"],
        "mission_period": mission_period(state),
        "max_level": MAX_LEVEL,
        "xp_per_mission": round(MISSION_XP * (1 + game.city_stat(state, "beast_xp"))),
        "hatch_speed": game.city_stat(state, "hatch_speed"),
        "egg_chance": round(min(EGG_CHANCE_MAX, EGG_CHANCE + game.city_stat(state, "egg_chance")) * 100),
        "rarities": RARITIES,
        "stats": STATS,
        "species": {k: {"name": s["name"], "rarity": RARITIES[s["rarity"]]["name"]} for k, s in SPECIES.items()},
        "duel": DUEL, "duel_xp": DUEL_XP,
        "nest_at": state.get("nest_at"), "nest_time": NEST_TIME, "nest_full": NEST_FULL,
        "tame_egg": round((TAME_EGG_CHANCE + game.city_stat(state, "egg_chance")) * 100),
        "species_count": len(SPECIES),
        "duels": state.get("duels", []),
    }
