"""Tags: little titles a city earns, like achievements, shown under its name on the leaderboard.

Most are earned by playing (TAGS, checked as the city's time moves on in game.advance_time). Some are only ever
given by the game's admin (GIVEN: Alpha, Beta and the like, with `dolphincity tag City alpha` or /tag on Discord),
and the admin can also give a tag with any name at all. A city picks up to SHOWN of its tags to show first; the
leaderboard shows those three, and the rest when the pointer is over them.

state["tags"] = {"have": {tag id: when it was earned}, "custom": {tag id: name}, "shown": [tag ids]}
"""
import re

SHOWN = 3
RARITIES = ["common", "uncommon", "rare", "epic", "legendary", "special"]      # "special": given by the admin

# Tags only the admin gives: id -> (name, what it means).
GIVEN = {
    "alpha": ("Alpha", "Played the game in its alpha, before the full release."),
    "beta": ("Beta", "Played the game in its beta, before the full release."),
    "founder": ("Founder", "One of the very first cities."),
    "developer": ("Developer", "Makes the game."),
    "moderator": ("Moderator", "Keeps the game and its Discord friendly."),
    "tester": ("Tester", "Tried out new things before anyone else."),
    "bug_hunter": ("Bug Hunter", "Found and reported a bug that got fixed."),
    "supporter": ("Supporter", "Helped the game along."),
    "event_winner": ("Event Winner", "Won one of the game's events."),
}


def _total(key):
    return lambda s: s.get("totals", {}).get(key, 0)


def _endless(s):
    import ideology
    return max((lvl for n, lvl in s.get("quest_tree", {}).items()
                if ideology.TREE_NODES.get(n, {}).get("kind") == "endless"), default=0)


# What can be earned: (id, name, rarity, how to earn it, what is counted, how many).
_RAW = [
    # resources made over the city's whole life
    ("gold_1m", "Gold Rush", "uncommon", "Make 1,000,000 Gold", _total("made:gold"), 1e6),
    ("gold_10m", "Golden Touch", "rare", "Make 10,000,000 Gold", _total("made:gold"), 1e7),
    ("gold_100m", "Midas", "epic", "Make 100,000,000 Gold", _total("made:gold"), 1e8),
    ("gold_1b", "Dragon's Hoard", "legendary", "Make 1,000,000,000 Gold", _total("made:gold"), 1e9),
    ("food_1m", "Breadbasket", "uncommon", "Make 1,000,000 Food", _total("made:food"), 1e6),
    ("food_100m", "Land of Plenty", "epic", "Make 100,000,000 Food", _total("made:food"), 1e8),
    ("wood_1m", "Timber Baron", "uncommon", "Make 1,000,000 Wood", _total("made:wood"), 1e6),
    ("stone_1m", "Stonemason", "uncommon", "Make 1,000,000 Stone", _total("made:stone"), 1e6),
    ("ore_1m", "Deep Delver", "uncommon", "Make 1,000,000 Ore", _total("made:ore"), 1e6),
    ("tools_10m", "Master Smith", "rare", "Make 10,000,000 Tools", _total("made:tools"), 1e7),
    ("electronics_1m", "Wired", "rare", "Make 1,000,000 Electronics", _total("made:electronics"), 1e6),
    ("knowledge_1m", "Scholar", "uncommon", "Make 1,000,000 Knowledge", _total("made:knowledge"), 1e6),
    ("knowledge_100m", "Sage", "epic", "Make 100,000,000 Knowledge", _total("made:knowledge"), 1e8),
    # growing
    ("town", "Townsfolk", "common", "Become a Town", lambda s: s["tech"], 2),
    ("city", "City Planner", "common", "Become a City", lambda s: s["tech"], 3),
    ("metropolis", "Metropolitan", "uncommon", "Become a Metropolis", lambda s: s["tech"], 4),
    ("megacity", "Skyline", "rare", "Become a Megacity", lambda s: s["tech"], 5),
    ("pop_500", "Bustling", "common", "Have 500 people", lambda s: s["population"], 500),
    ("pop_2500", "Crowded Streets", "uncommon", "Have 2,500 people", lambda s: s["population"], 2500),
    ("pop_10000", "Teeming Millions", "epic", "Have 10,000 people", lambda s: s["population"], 10000),
    ("areas_10", "Landholder", "common", "Own 10 areas", lambda s: len(s["areas"]), 10),
    ("areas_50", "Empire", "rare", "Own 50 areas", lambda s: len(s["areas"]), 50),
    ("areas_100", "Sprawl", "epic", "Own 100 areas", lambda s: len(s["areas"]), 100),
    ("built_1000", "Architect", "uncommon", "Build 1,000 buildings", _total("built"), 1000),
    ("built_10000", "Master Builder", "epic", "Build 10,000 buildings", _total("built"), 10000),
    # knowing
    ("research_50", "Inventor", "uncommon", "Research 50 things", lambda s: len(s["research"]), 50),
    ("research_80", "Know-It-All", "epic", "Research 80 things", lambda s: len(s["research"]), 80),
    ("mastery_10", "Adept", "rare", "Gain 10 Mastery levels", lambda s: sum(s.get("mastery", {}).values()), 10),
    ("mastery_50", "Grandmaster", "legendary", "Gain 50 Mastery levels", lambda s: sum(s.get("mastery", {}).values()), 50),
    # the ideology
    ("quests_5", "Devoted", "uncommon", "Complete 5 ideology quests", lambda s: s.get("quests", {}).get("done", 0), 5),
    ("quests_10", "Zealot", "rare", "Complete 10 ideology quests", lambda s: s.get("quests", {}).get("done", 0), 10),
    ("quests_20", "Living Legend", "legendary", "Complete 20 ideology quests", lambda s: s.get("quests", {}).get("done", 0), 20),
    ("endless_10", "Transcendent", "epic", "Take 10 levels of your tree's endless perk", _endless, 10),
    ("rituals_50", "High Priest", "rare", "Hold 50 rituals", _total("rituals"), 50),
    ("curses_25", "Hexer", "rare", "Hex, sabotage or the like 25 times", _total("curses_cast"), 25),
    # beasts and the wild
    ("hatched_1", "Egg Sitter", "common", "Hatch an egg", _total("hatched"), 1),
    ("hatched_25", "Beast Keeper", "rare", "Hatch 25 eggs", _total("hatched"), 25),
    ("duels_10", "Duellist", "uncommon", "Win 10 duels", _total("duels_won"), 10),
    ("duels_100", "Champion", "epic", "Win 100 duels", _total("duels_won"), 100),
    ("missions_100", "Quartermaster", "rare", "Send beasts on 100 missions", _total("missions"), 100),
    ("tamed_100", "Beast Whisperer", "uncommon", "Tame 100 wild animals", _total("tamed"), 100),
    # the wider world
    ("expeditions_50", "Explorer", "uncommon", "Complete 50 expeditions", _total("expeditions"), 50),
    ("expeditions_500", "Wayfinder", "epic", "Complete 500 expeditions", _total("expeditions"), 500),
    ("sold_100", "Merchant", "uncommon", "Make 100 market sales to other cities", _total("sold"), 100),
    ("sold_1000", "Trade Prince", "epic", "Make 1,000 market sales to other cities", _total("sold"), 1000),
    ("messages_100", "Chatterbox", "common", "Send 100 messages", _total("messages_sent"), 100),
    ("brews_100", "Brewmaster", "uncommon", "Brew 100 times at the Cauldron", _total("brews"), 100),
    ("artifacts_10", "Artificer", "rare", "Craft 10 artifacts", _total("artifacts_crafted"), 10),
    ("trained_1000", "Drill Sergeant", "rare", "Send 1,000 newcomers to training", _total("trained"), 1000),
    ("presents_1", "Gifted", "common", "Open a present", _total("presents"), 1),
]
TAGS = {i: {"name": n, "rarity": r, "how": h, "count": c, "need": need} for i, n, r, h, c, need in _RAW}


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:30]


def info(state, tag_id):
    """(name, rarity, what it means) of a tag, or None."""
    if tag_id in TAGS:
        t = TAGS[tag_id]
        return t["name"], t["rarity"], t["how"]
    if tag_id in GIVEN:
        return GIVEN[tag_id][0], "special", GIVEN[tag_id][1]
    name = state.get("tags", {}).get("custom", {}).get(tag_id)
    return (name, "special", "Given by the game's admin.") if name else None


def _book(state):
    return state.setdefault("tags", {"have": {}, "custom": {}, "shown": []})


def check(state, now):
    """Give the city every tag it has earned and doesn't have yet."""
    have = state.get("tags", {}).get("have", {})
    new = []
    for tag_id, t in TAGS.items():
        if tag_id not in have:
            try:
                if t["count"](state) >= t["need"]:
                    new.append(tag_id)
            except (KeyError, TypeError):
                continue
    if new:
        import game
        book = _book(state)
        if len(new) <= 3:              # a backlog (the first check after tags came in) is not news
            state.setdefault("tags_news", []).extend(new)
        for tag_id in new:
            book["have"][tag_id] = now
            game.log(state, now, f"New tag earned: {TAGS[tag_id]['name']} ({TAGS[tag_id]['how'].lower()}). "
                                 f"Choose which tags to show on the Social tab.")


def give(state, now, tag):
    """The admin gives a tag: one of GIVEN, or any name (a tag of its own). Returns the tag's name."""
    import game
    book = _book(state)
    tag_id = tag if tag in GIVEN else _slug(tag)
    if tag_id not in GIVEN:
        tag_id = "custom_" + tag_id
        book["custom"][tag_id] = tag.strip()[:30]
    book["have"][tag_id] = now
    name = info(state, tag_id)[0]
    game.log(state, now, f"The game's admin gave you a tag: {name}.")
    return name


def take(state, tag):
    """The admin takes a tag back (by id or name). True if the city had it."""
    book = _book(state)
    for tag_id in list(book["have"]):
        i = info(state, tag_id)
        if tag_id == tag or tag_id == _slug(tag) or (i and i[0].lower() == tag.strip().lower()):
            book["have"].pop(tag_id)
            book["custom"].pop(tag_id, None)
            book["shown"] = [t for t in book["shown"] if t != tag_id]
            return True
    return False


def set_shown(state, tags):
    """The city picks which of its tags to show first (up to SHOWN, in order)."""
    if not isinstance(tags, list) or len(tags) > SHOWN:
        return f"Choose up to {SHOWN} tags."
    have = state.get("tags", {}).get("have", {})
    if any(not isinstance(t, str) or t not in have for t in tags) or len(set(tags)) != len(tags):
        return "You can only show tags you have."
    _book(state)["shown"] = list(tags)
    return None


def ordered(state):
    """The city's tags, the ones it chose to show first, then the rarest."""
    book = state.get("tags", {})
    have = book.get("have", {})
    shown = [t for t in book.get("shown", []) if t in have]
    rest = sorted((t for t in have if t not in shown and info(state, t)),
                  key=lambda t: (-RARITIES.index(info(state, t)[1]), have[t]))
    return shown + rest


def board(state):
    """For the leaderboard: [[name, rarity, what it means], ...], the first SHOWN shown and the rest on hover."""
    return [list(info(state, t)) for t in ordered(state) if info(state, t)]


def view(state):
    """For the Social tab: every tag, earned or not, with how far along the city is."""
    have = state.get("tags", {}).get("have", {})
    shown = [t for t in state.get("tags", {}).get("shown", []) if t in have]
    out = []
    for tag_id, t in TAGS.items():
        try:
            now = t["count"](state)
        except (KeyError, TypeError):
            now = 0
        out.append({"id": tag_id, "name": t["name"], "rarity": t["rarity"], "how": t["how"], "have": tag_id in have,
                    "when": have.get(tag_id), "now": min(now, t["need"]), "need": t["need"]})
    for tag_id in have:
        if tag_id not in TAGS and info(state, tag_id):
            name, rarity, how = info(state, tag_id)
            out.append({"id": tag_id, "name": name, "rarity": rarity, "how": how, "have": True, "when": have[tag_id]})
    return {"list": out, "shown": shown, "order": ordered(state), "max": SHOWN, "rarities": RARITIES}
