"""The ranked arena: one city's Party 1 fights another's, which needn't be online.

The city is offered OPPONENTS cities whose rank points are near its own (each with its Party 1 and how strong it is).
It picks one and the fight is fought at once (adventure.team_fight) against that city's Party 1 as it is now: the
defender's heroes fight even while away on an adventure, as a stand-in. The winner gains rank points and the loser
loses some (more the bigger the surprise, as in chess ratings); the defender's points move half as far. A win brings
materials (more at a higher rank) and experience; reaching a rank for the first time brings a bigger prize.

A city has up to FIGHTS fights stored, and gets one back every FIGHT_TIME. The offered opponents change after every
fight, every REFRESH_TIME on their own, or when the player asks (at most every ASK_TIME).
state["arena"] = {"points", "best", "wins", "losses", "held", "fell", "choices", "chosen_at", "asked_at",
                  "fights", "fights_at", "results"}
"""
import math
import random

import adventure
import beasts

HOUR, MIN = 3600, 60
RANKS = [(0, "Bronze"), (150, "Silver"), (350, "Gold"), (600, "Platinum"), (900, "Diamond"), (1250, "Master"),
         (1700, "Grandmaster"), (2200, "Legend")]
DIVISIONS = ("III", "II", "I")      # each rank but the last is split in three
OPPONENTS = 3
WINDOWS = (150, 300, 600, None)     # how far from the city's own points opponents are looked for, widening if few
REFRESH_TIME = HOUR
ASK_TIME = 10 * MIN
FIGHTS = 5
FIGHT_TIME = 45 * MIN
K_ATTACK = 32                       # rank points at stake for the city that picks the fight...
K_DEFEND = 16                       # ...and for the one defending
MIN_GAIN = 4
RESULTS_KEPT = 12
RECENT_FOES = 3                     # these last opponents are not offered again at once
REWARD_HOURS = 0.75                 # a win brings this many hours of what the city makes, of two materials...
REWARD_HOURS_STEP = 0.25            # ...plus this per rank
REWARD_PLAIN = 3                    # ...or at least this many times the plain adventure loot (and 1 more per rank)
RANK_UP_PRIZE = 4                   # the first time a rank is reached: this many wins' worth
DEFEND_XP = 4                       # experience for each hero of a party that held


def _store(state):
    a = state.setdefault("arena", {})
    for k, v in (("points", 0), ("best", 0), ("wins", 0), ("losses", 0), ("held", 0), ("fell", 0), ("choices", []),
                 ("chosen_at", 0), ("asked_at", 0), ("fights", FIGHTS), ("fights_at", 0), ("results", [])):
        a.setdefault(k, v)
    return a


def points(state):
    return (state.get("arena") or {}).get("points", 0)


def rank_index(pts):
    return max(i for i, (low, _) in enumerate(RANKS) if pts >= low)


def rank_name(pts):
    i = rank_index(pts)
    low, name = RANKS[i]
    if i == len(RANKS) - 1:
        return name
    high = RANKS[i + 1][0]
    div = min(2, int((pts - low) * 3 // (high - low)))
    return f"{name} {DIVISIONS[div]}"


def fights_left(state, now):
    """(fights stored now, when the next comes back or None)."""
    a = _store(state)
    if a["fights"] >= FIGHTS:
        return FIGHTS, None
    got = int((now - a["fights_at"]) // FIGHT_TIME)
    have = min(FIGHTS, a["fights"] + got)
    if have >= FIGHTS:
        return FIGHTS, None
    return have, a["fights_at"] + (got + 1) * FIGHT_TIME


def _use_fight(state, now):
    a = _store(state)
    have, _ = fights_left(state, now)
    if have >= FIGHTS:
        a["fights_at"] = now
    else:
        a["fights_at"] += int((now - a["fights_at"]) // FIGHT_TIME) * FIGHT_TIME
    a["fights"] = have - 1


def expected(mine, theirs):
    return 1 / (1 + 10 ** ((theirs - mine) / 400))


def stakes(mine, theirs):
    """(points the attacker gains by winning, points it loses by losing)."""
    e = expected(mine, theirs)
    return max(MIN_GAIN, round(K_ATTACK * (1 - e))), max(1, round(K_ATTACK * e))


def public_team(units):
    return [{"name": u["name"], "cls": u.get("cls"), "beast": bool(u.get("beast")), "level": u["level"]} for u in units]


def defenders(state):
    """The city's Party 1 as it defends in the arena (the heroes fight even while away), or []."""
    units = adventure.team(state)
    return units if any(u.get("hero") for u in units) else []


# ---- picking opponents ----

def choose(state, now, rows, line, force=False):
    """Offer new opponents if there are none, they are old, or `force`. `rows` are leaderboard rows
    ({"name", "arena", "party", "locked"}); `line` the cities of this city's own vassal line."""
    a = _store(state)
    if not force and a["choices"] and now - a["chosen_at"] < REFRESH_TIME:
        return
    mine = a["points"]
    recent = [r["foe"] for r in a["results"] if r.get("attacked")][-RECENT_FOES:]
    pool = [r for r in rows if r["name"] not in line and r["name"] != state["name"] and not r.get("locked")
            and r.get("party", 0) > 0 and state["name"] not in r.get("banned", [])]
    fresh = [r for r in pool if r["name"] not in recent] or pool
    rng = random.Random()
    picked = []
    for window in WINDOWS:
        near = [r for r in fresh if window is None or abs(r.get("arena", 0) - mine) <= window]
        if len(near) >= OPPONENTS or window is None:
            picked = rng.sample(near, min(OPPONENTS, len(near)))
            break
    a["choices"] = [{"city": r["name"], "points": r.get("arena", 0)} for r in picked]
    a["chosen_at"] = now


def ask(state, now):
    """The player asks for other opponents: (error or None)."""
    a = _store(state)
    if now - a["asked_at"] < ASK_TIME:
        left = ASK_TIME - (now - a["asked_at"])
        mins = math.ceil(left / 60)
        return f"New opponents can be asked for again in {mins} minute{'s' if mins != 1 else ''}."
    a["asked_at"] = now
    return None


# ---- the fight ----

def reward(state, pts, rng, times=1):
    import game
    i = rank_index(pts)
    kinds = rng.sample(adventure.loot_kinds(state), 2)
    more = 1 + adventure.bonus(state, "adv_loot")
    out = {}
    with game.reading():
        for k in kinds:
            plain = adventure.LOOT_BASE[k] * adventure.LOOT_TECH[min(state["tech"], 5)] * (REWARD_PLAIN + i)
            earned = beasts._income(state, k) * (REWARD_HOURS + REWARD_HOURS_STEP * i)
            out[k] = max(1, round(max(plain, earned) * more * times * rng.uniform(0.85, 1.15)))
    return out


def fight(state, target, now, rng=None):
    """Fight `target`'s Party 1 with this city's. Returns (error, Discord line or None)."""
    import game
    import market
    rng = rng or random.Random()
    a = _store(state)
    if not target or target is state:
        return "Pick one of the cities offered.", None
    if not any(c["city"] == target["name"] for c in a["choices"]):
        return "That city is no longer offered: pick one of the cities shown.", None
    if state["name"] in target.get("banned", []):
        return f"{target['name']} has banned your city.", None
    have, _ = fights_left(state, now)
    if have < 1:
        return "No arena fights left: one comes back every 45 minutes.", None
    mine, error = adventure.battle_team(state)
    if error:
        return error, None
    theirs = defenders(target)
    if not theirs:
        a["choices"] = [c for c in a["choices"] if c["city"] != target["name"]]
        return f"{target['name']} has nobody in Party 1 any more. Pick another city.", None
    d = _store(target)
    before_me, before_them = a["points"], d["points"]
    gain, loss = stakes(before_me, before_them)
    winner, rounds, story, left = adventure.team_fight([mine, theirs], rng, labels=("your party", f"{target['name']}'s party"))
    won = winner == 0
    e = expected(before_me, before_them)
    if won:
        a["points"] += gain
        d["points"] = max(0, d["points"] - max(1, round(K_DEFEND * (1 - e))))
    else:
        a["points"] = max(0, a["points"] - loss)
        d["points"] += max(1, round(K_DEFEND * e))
    _use_fight(state, now)
    a["choices"] = []           # new opponents after every fight
    prize, said = {}, None
    if won:
        a["wins"] += 1
        d["fell"] += 1
        prize = reward(state, a["points"], rng)
        if rank_index(a["points"]) > rank_index(a["best"]):
            extra = reward(state, a["points"], rng, RANK_UP_PRIZE)
            for k, v in extra.items():
                prize[k] = prize.get(k, 0) + v
            said = f"**{state['name']}** reached **{RANKS[rank_index(a['points'])][1]}** in the arena."
            game.log(state, now, f"*** Your party reached {RANKS[rank_index(a['points'])][1]} in the arena! ***")
        for k, v in prize.items():
            state["resources"][k] += v
        adventure.battle_won(state, now, [u["hero"] for u in mine if u.get("hero")])
        game.tally(state, "battles_won")
    else:
        a["losses"] += 1
        d["held"] += 1
        for u in theirs:
            h = adventure.get(target, u.get("hero")) if u.get("hero") else None
            if h:
                adventure.give_xp(target, now, h, round(DEFEND_XP * (1 + adventure.bonus(target, "adv_xp"))))
        game.tally(state, "battles_lost")
    a["best"] = max(a["best"], a["points"])
    d["best"] = max(d["best"], d["points"])
    sides = [{"city": c["name"], "power": adventure.power(t), "left": l,
              "party": [dict(public_team([u])[0], hp=u["hp"], atk=u["atk"], **{"def": u["def"]}, spd=u["spd"]) for u in t]}
             for c, t, l in ((state, mine, left[0]), (target, theirs, left[1]))]
    for city, me, foe, ok, change, attacked in (
            (state, 0, 1, won, a["points"] - before_me, True),
            (target, 1, 0, not won, d["points"] - before_them, False)):
        store = _store(city)
        store["results"].append({"t": now, "won": ok, "attacked": attacked, "foe": sides[foe]["city"], "change": change,
                                 "points": store["points"], "rank": rank_name(store["points"]), "rounds": rounds,
                                 "prize": prize if attacked and ok else {}, "sides": [sides[me], sides[foe]], "story": story})
        del store["results"][:-RESULTS_KEPT]
    sign = lambda x: f"+{x}" if x >= 0 else str(x)
    game.log(state, now, f"Arena: your party {'beat' if won else 'lost to'} {target['name']}'s "
                         f"({sign(a['points'] - before_me)} points, now {rank_name(a['points'])})"
                         + (f" and won {game.fmt_goods(prize)}." if won else "."))
    game.log(target, now, f"Arena: {state['name']}'s party attacked yours and {'won' if won else 'lost'} "
                          f"({sign(d['points'] - before_them)} points, now {rank_name(d['points'])}).")
    market.social(state, now, target["name"], "battle", f"Your party {'beat' if won else 'lost to'} theirs in the arena.")
    market.social(target, now, state["name"], "battle", f"Their party attacked yours in the arena and {'won' if won else 'lost'}.")
    return None, said


# ---- what the page gets ----

def view(state, now, get_row=None):
    a = _store(state)
    have, nxt = fights_left(state, now)
    mine = adventure.power(adventure.team(state))
    choices = []
    for c in a["choices"]:
        row = get_row(c["city"]) if get_row else None
        gain, loss = stakes(a["points"], c["points"])
        choices.append({"city": c["city"], "points": c["points"], "rank": rank_name(c["points"]),
                        "party": (row or {}).get("arena_party", []), "power": (row or {}).get("arena_power", 0),
                        "rating": adventure.rating(mine, (row or {}).get("arena_power", 0)), "gain": gain, "loss": loss})
    return {"points": a["points"], "rank": rank_name(a["points"]), "best": rank_name(a["best"]), "best_points": a["best"],
            "wins": a["wins"], "losses": a["losses"], "held": a["held"], "fell": a["fell"],
            "fights": have, "fights_max": FIGHTS, "next_fight": nxt, "power": mine,
            "choices": choices, "refresh_at": a["chosen_at"] + REFRESH_TIME, "ask_at": a["asked_at"] + ASK_TIME,
            "results": a["results"][::-1]}


def defs():
    return {"ranks": [{"points": p, "name": n} for p, n in RANKS], "divisions": DIVISIONS, "fights": FIGHTS,
            "fight_time": FIGHT_TIME, "refresh_time": REFRESH_TIME, "ask_time": ASK_TIME}


def migrate(state):
    """Results of the old party battles (with bets) are not kept: the arena keeps its own."""
    state.pop("battles", None)
