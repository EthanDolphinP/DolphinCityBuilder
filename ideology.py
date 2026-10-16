"""Ideologies: what a city believes in, chosen once it becomes a Village.

Each ideology gives a bonus straight away, and then has perks of its own that
fit it: the Old Faith's perks are blessings from its gods, Progress's are great
inventions, and so on. Every tech level from Village up earns one point, spent
on a perk whenever the player likes (Village earns 1, Megacity 5 in all). Each
ideology has eleven perks spread over five tiers; a perk can be taken once the
city has reached its tier, so a city ends up with five of the eleven.

Effects, added up over the ideology and its perks taken:

    speed          {building category or "all": 0.1} = those buildings 10% faster
    explore_speed  0.25 = expeditions travel 25% faster
    explore_cost   0.15 = expeditions need 15% fewer supplies
    wildlife_speed 0.5 = wild animals appear 50% more often
    attracts       extra arrivals per meal
    housing        people housed
    power          0.2 = generators give 20% more power
    night_shelter / weather_shelter   0.5 = half of every slowdown night (or the weather) causes is gone

Rituals: each ideology has five, opened one by one by the ritual research
(game.RESEARCH entries with "ritual": rank, one per tech level from Village
up). A ritual is started by donating gold to the ideology and gives its
effects for a while. The gold asked for depends on the city's tech level
(RITUAL_GOLD); giving up to RITUAL_MAX_GIFT times that makes the ritual
stronger and longer (see ritual_scale). Each rank of research also makes
every ritual stronger and longer. Different rituals can run at once; starting
one that is running starts it again with the new gift.
    beast_xp / beast_power / hatch_speed / egg_chance / mission_speed   as in beasts.py

`game` imports this module and this module uses `game`, so nothing here may
touch `game` at import time: only inside functions.
"""

import game

HOUR = 3600
RITUAL_GOLD = [0, 200, 800, 3000, 10000, 25000]   # least gold a ritual takes, by the city's tech level
RITUAL_MAX_GIFT = 5          # a gift can be up to this many times the least...
RITUAL_GIFT_STRENGTH = 0.25  # ...each extra share makes the ritual this much stronger (2x at 5x the gold)
RITUAL_GIFT_TIME = 0.5       # ...and this much longer (3x at 5x the gold)
RITUAL_RANK_STRENGTH = 0.25  # each rank of research past the first: this much stronger...
RITUAL_TIME = 2 * HOUR       # ...a ritual at rank 1 with the least gold lasts this long...
RITUAL_RANK_TIME = HOUR // 2 # ...and each rank past the first adds this

IDEOLOGIES = {
    "faith": {
        "name": "The Old Faith", "perk_word": "Blessing", "perk_plural": "Blessings of the gods",
        "desc": "The city keeps the old gods, and they keep the city. Their blessings reach every part of life.",
        "effects": {"speed": {"food": 0.10, "knowledge": 0.10}},
        "ritual_word": "Rite", "ritual_plural": "Rites of the temple",
        "rituals": {
            "first_fruits": {"name": "Feast of First Fruits", "effects": {"speed": {"food": 0.15}},
                            "desc": "The first of every harvest goes to the gods, and the fields answer."},
            "vigil": {"name": "Vigil of Lamps", "effects": {"night_shelter": 0.5, "speed": {"knowledge": 0.1}},
                     "desc": "A thousand lamps burn all night; nobody sleeps and nobody minds."},
            "stone_procession": {"name": "Procession of the Stone Father", "effects": {"speed": {"materials": 0.2}},
                                "desc": "The priests carry the god's statue past every mine and quarry."},
            "storm_litany": {"name": "Litany Against the Storm", "effects": {"weather_shelter": 0.5, "speed": {"food": 0.1}},
                            "desc": "Chanted on the temple steps until the sky gives in."},
            "holy_day": {"name": "High Holy Day", "effects": {"speed": {"all": 0.1}, "attracts": 1},
                        "desc": "The whole city stops to give thanks, then works twice as hard."},
        },
        "perks": {
            "storm_father":   {"name": "Blessing of the Storm Father", "tier": 3, "effects": {"weather_shelter": 0.4, "speed": {"food": 0.05}},
                               "desc": "The storms bow to the temple and pass the fields by."},
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
        "ritual_word": "Exhibition", "ritual_plural": "Exhibitions of progress",
        "rituals": {
            "science_fair": {"name": "Science Fair", "effects": {"speed": {"knowledge": 0.2}},
                            "desc": "Prizes for the cleverest idea, and everyone wants one."},
            "overtime": {"name": "Overtime Campaign", "effects": {"speed": {"materials": 0.15}, "night_shelter": 0.4},
                        "desc": "Floodlights, bonuses and the factory whistle at midnight."},
            "power_trial": {"name": "Power Surge Trial", "effects": {"power": 0.25},
                           "desc": "Every generator pushed past its rating, for science."},
            "survey_grant": {"name": "Survey Grant", "effects": {"explore_speed": 0.5, "explore_cost": 0.3},
                            "desc": "Funding for every team that wants to map the unknown."},
            "worlds_fair": {"name": "World's Fair", "effects": {"speed": {"all": 0.1}, "attracts": 1},
                           "desc": "The marvels of the age, all in one city."},
        },
        "perks": {
            "gaslight":    {"name": "Gas Lighting", "tier": 2, "effects": {"night_shelter": 0.5},
                            "desc": "Every street lit and every workshop open after dark."},
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
        "ritual_word": "Fair", "ritual_plural": "Merchant fairs",
        "rituals": {
            "sale_day": {"name": "Great Sale Day", "effects": {"speed": {"trade": 0.25}},
                        "desc": "Everything must go, and somehow everything does."},
            "harvest_auction": {"name": "Harvest Auction", "effects": {"speed": {"food": 0.15, "trade": 0.1}},
                               "desc": "Farmers bid against each other for the best seed and the best land."},
            "caravan_season": {"name": "Caravan Season", "effects": {"explore_speed": 0.3, "explore_cost": 0.4},
                              "desc": "Merchants pay for the roads, and the scouts travel with them."},
            "guild_holiday": {"name": "Guild Holiday", "effects": {"speed": {"materials": 0.15}, "attracts": 1},
                             "desc": "The guilds show off their best work, and new apprentices arrive."},
            "grand_exposition": {"name": "Grand Exposition", "effects": {"speed": {"all": 0.1, "trade": 0.15}},
                                "desc": "Every merchant in the world wants a stall."},
        },
        "perks": {
            "insurance": {"name": "Insurance Charter", "tier": 3, "effects": {"weather_shelter": 0.4, "speed": {"trade": 0.05}},
                          "desc": "Bad weather is somebody else's problem, for a small fee."},
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
        "ritual_word": "Call", "ritual_plural": "Calls of the wild",
        "rituals": {
            "herd_call": {"name": "Call of the Herd", "effects": {"wildlife_speed": 1.0, "speed": {"food": 0.1}},
                         "desc": "Drums on the plain, and the animals come to listen."},
            "moon_howl": {"name": "Moon Howl", "effects": {"night_shelter": 0.6, "beast_power": 0.2},
                         "desc": "The city howls with the wolves, and the night is friendly."},
            "nesting_song": {"name": "Nesting Song", "effects": {"hatch_speed": 1.0, "egg_chance": 0.1},
                            "desc": "Sung softly over every egg in the city."},
            "storm_dance": {"name": "Storm Dance", "effects": {"weather_shelter": 0.6, "speed": {"materials": 0.1}},
                           "desc": "Danced in the rain until the rain grows bored."},
            "great_hunt": {"name": "The Great Hunt", "effects": {"speed": {"all": 0.08}, "beast_xp": 0.5},
                          "desc": "The whole city follows the great beasts across the land."},
        },
        "perks": {
            "moon_pact": {"name": "Pact of the Moon", "tier": 2, "effects": {"night_shelter": 0.4, "wildlife_speed": 0.25},
                          "desc": "The night creatures work alongside the city until dawn."},
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
        "ritual_word": "Ceremony", "ritual_plural": "Ceremonies of the road",
        "rituals": {
            "lantern_sendoff": {"name": "Lantern Send-off", "effects": {"explore_speed": 0.5},
                               "desc": "Lanterns floated downriver for every team that leaves."},
            "star_reading": {"name": "Star Reading", "effects": {"speed": {"knowledge": 0.2}, "weather_shelter": 0.3},
                            "desc": "The navigators read the sky aloud for everyone."},
            "trade_winds": {"name": "Rite of the Trade Winds", "effects": {"speed": {"trade": 0.2}, "explore_cost": 0.3},
                           "desc": "Sails blessed, and the winds blow the right way."},
            "homecoming": {"name": "Homecoming Feast", "effects": {"attracts": 1, "speed": {"food": 0.15}},
                          "desc": "Every traveller who ever left comes back for one night, and some stay."},
            "voyage_of_legends": {"name": "Voyage of Legends", "effects": {"speed": {"all": 0.1}, "egg_chance": 0.1},
                                 "desc": "The old stories retold, and the young set out to make new ones."},
        },
        "perks": {
            "sky_reading":   {"name": "Reading the Skies", "tier": 2, "effects": {"weather_shelter": 0.3, "explore_speed": 0.1},
                              "desc": "Sailors' lore: always know what tomorrow's sky will do."},
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
        "ritual_word": "Gathering", "ritual_plural": "Community gatherings",
        "rituals": {
            "barn_dance": {"name": "Barn Dance", "effects": {"speed": {"food": 0.15}, "housing": 10},
                          "desc": "Fiddles, hay bales and room for everyone."},
            "work_bee": {"name": "Work Bee", "effects": {"speed": {"materials": 0.2}},
                        "desc": "Everyone turns out to help, and the work flies."},
            "lantern_night": {"name": "Lantern Night", "effects": {"night_shelter": 0.5, "speed": {"trade": 0.1}},
                             "desc": "Every window lit, and the market stays open late."},
            "town_meeting": {"name": "Town Meeting", "effects": {"speed": {"knowledge": 0.2}, "mission_speed": 0.5},
                            "desc": "Everyone has their say, and some of it is even useful."},
            "midsummer": {"name": "Midsummer Festival", "effects": {"speed": {"all": 0.1}, "attracts": 2},
                         "desc": "The longest day, the biggest party, and the city's name on every tongue."},
        },
        "perks": {
            "night_watch": {"name": "The Night Watch", "tier": 2, "effects": {"night_shelter": 0.4, "housing": 10},
                            "desc": "Lamps on every corner and neighbours who look out for each other."},
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
    # perks for night and weather
    "storm_father":   [r" _~~~_ ", r"(_/|\_)", r"  /|   "],
    "gaslight":       [r"  [*]  ", r"   |   ", r"  _|_  "],
    "insurance":      [r" .---. ", r"| $ / |", r" '---' "],
    "moon_pact":      [r"  _..  ", r" (  ') ", r"  '-'  "],
    "sky_reading":    [r" ~ o ~ ", r"--( )--", r"  / \  "],
    "night_watch":    [r"[*]  o  ", r" |  /|\ ", r"_|_ / \ "],
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
    for eff in ([ideo["effects"]] + [ideo["perks"][p]["effects"] for p in state.get("perks", []) if p in ideo["perks"]]
                + [_scaled(ideo["rituals"][rid]["effects"], r["scale"]) for rid, r in active_rituals(state)]):
        for key, value in eff.items():
            if key == "speed":
                for cat, x in value.items():
                    total["speed"][cat] = total["speed"].get(cat, 0) + x
            else:
                total[key] = total.get(key, 0) + value
    return total


# ---- rituals ----

def ritual_rank(state):
    """How many ranks of ritual research the city has: 0 to 5."""
    return sum(1 for rid in state["research"] if game.RESEARCH[rid].get("ritual"))


def _scaled(eff, scale):
    return {k: ({c: x * scale for c, x in v.items()} if k == "speed" else v * scale) for k, v in eff.items()}


def active_rituals(state):
    """(id, ritual) for every ritual running at the moment being worked out (see game.advance_time)."""
    t = state.get("ritual_now", state["updated"])
    return [(rid, r) for rid, r in state.get("rituals", {}).items() if r["start"] <= t < r["until"]]


def ritual_terms(state, gold):
    """(strength, seconds) a gift of `gold` buys at the city's rank and tech level, or None if it is out of range."""
    least = RITUAL_GOLD[state["tech"]]
    rank = ritual_rank(state)
    if not least or not rank or not least <= gold <= least * RITUAL_MAX_GIFT:
        return None
    share = gold / least - 1
    strength = (1 + RITUAL_RANK_STRENGTH * (rank - 1)) * (1 + RITUAL_GIFT_STRENGTH * share)
    seconds = (RITUAL_TIME + RITUAL_RANK_TIME * (rank - 1)) * (1 + RITUAL_GIFT_TIME * share)
    return round(strength, 3), round(seconds)


def start_ritual(state, now, ritual_id, gold):
    ideo = chosen(state)
    if not ideo:
        return "Choose an ideology first."
    order = list(ideo["rituals"])
    if ritual_id not in ideo["rituals"]:
        return f"That is not one of your ideology's {ideo['ritual_plural'].lower()}."
    rank = ritual_rank(state)
    if order.index(ritual_id) >= rank:
        return f"That {ideo['ritual_word'].lower()} needs more ritual research first."
    if not (isinstance(gold, int) and not isinstance(gold, bool)):
        return "Say how much gold to give."
    least = RITUAL_GOLD[state["tech"]]
    terms = ritual_terms(state, gold)
    if not terms:
        return f"Give between {least} and {least * RITUAL_MAX_GIFT} Gold."
    if state["resources"]["gold"] < gold:
        return f"You don't have {gold} Gold."
    state["resources"]["gold"] -= gold
    strength, seconds = terms
    state.setdefault("rituals", {})[ritual_id] = {"start": now, "until": now + seconds, "scale": strength, "gold": gold}
    game.tally(state, "rituals")
    game.log(state, now, f"*** {ideo['rituals'][ritual_id]['name']}: {gold} Gold given to {ideo['name']}. "
                         f"For {seconds // 3600}h {seconds % 3600 // 60:02d}m: {', '.join(describe(_scaled(ideo['rituals'][ritual_id]['effects'], strength)))}. ***")
    return None


def tidy_rituals(state):
    """Forget rituals that have finished."""
    for rid in [rid for rid, r in state.get("rituals", {}).items() if r["until"] <= state["updated"]]:
        del state["rituals"][rid]


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
        "night_shelter": lambda x: f"Night slows the city {pct(x)} less",
        "weather_shelter": lambda x: f"Bad weather slows the city {pct(x)} less",
    }
    for key, x in eff.items():
        if key in words and x:
            out.append(words[key](x))
    return out


def defs():
    """The ideologies as the page shows them, with their effects in words."""
    return {iid: {"name": i["name"], "desc": i["desc"], "perk_word": i["perk_word"], "perk_plural": i["perk_plural"],
                  "text": describe(i["effects"]), "color": COLOURS[iid], "art": "\n".join(ART[iid]),
                  "ritual_word": i["ritual_word"], "ritual_plural": i["ritual_plural"],
                  "rituals": {rid: {"name": r["name"], "desc": r["desc"], "effects": r["effects"], "text": describe(r["effects"])}
                              for rid, r in i["rituals"].items()},
                  "perks": {pid: {"name": p["name"], "tier": p["tier"], "desc": p["desc"], "text": describe(p["effects"]),
                                  "art": "\n".join(PERK_ART[pid])}
                            for pid, p in i["perks"].items()}}
            for iid, i in IDEOLOGIES.items()}


def view(state):
    ideo, rank, least = chosen(state), ritual_rank(state), RITUAL_GOLD[state["tech"]]
    rituals = {"rank": rank, "least": least, "most": least * RITUAL_MAX_GIFT,
               "gift_strength": RITUAL_GIFT_STRENGTH, "gift_time": RITUAL_GIFT_TIME,
               "base_strength": 1 + RITUAL_RANK_STRENGTH * (rank - 1) if rank else 0,
               "base_time": RITUAL_TIME + RITUAL_RANK_TIME * (rank - 1) if rank else 0,
               "active": {rid: {"until": r["until"], "scale": r["scale"], "gold": r["gold"],
                                "text": describe(_scaled(ideo["rituals"][rid]["effects"], r["scale"]))}
                          for rid, r in active_rituals(state)} if ideo else {}}
    return {"id": state.get("ideology"), "perks": state.get("perks", []), "points": points(state), "rituals": rituals,
            "total": describe(effects(state)) if chosen(state) else []}
