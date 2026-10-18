"""Player-to-player market.

Nothing here creates or destroys goods. A city posts an offer ("I give 20
Wood, I want 5 Gold"); the goods it is giving are taken out of its stock and
held by the market. When another city accepts, that city pays what was asked
and receives the held goods. Cancelling returns the held goods.

A "buy order" is just an offer the other way round: give Gold, want Wood.

An offer can be taken a part at a time. Its price is the ratio between the two
amounts, and the smallest piece that keeps both sides in whole numbers is a
"lot": 1000 Food for 250 Wood sells in lots of 4 Food for 1 Wood. Anyone can
buy any number of lots while there are some left.

A buyer says how much of the thing on sale they want; that has to be a whole
number of lots, and the price follows from it.

An offer never refills by itself. When it sells out it is moved to its owner's
"finished" list, remembered with the amounts it was posted with. From there the
owner can change the amounts, post it again (paying for it out of stock again)
or throw it away.

Every sale from a city's offers is also noted in that city's "sales" list, so
the Market screen can show what sold since the owner last looked.

Beasts and eggs are traded one at a time, for a material or for another beast
(see "Beast trades" at the end). Beasts can also duel for a bet (see "Duels").

A bill is a repeating trade between two named cities ("every 24 hours I send
you 10 Stone and you send me 20 Gold"). One city proposes it, the other has to
accept it, and either can cancel it at any time. When a payment comes due and
either side can't pay, nothing changes hands that time.
"""

import math
import random

import beasts
import game
import moderation

MAX_OFFERS_PER_CITY = 10
MAX_BEAST_OFFERS_PER_CITY = 5
MAX_DUELS_PER_CITY = 3
MAX_QUANTITY = 1_000_000_000_000   # any amount a city could have (the page uses the same limit)
HISTORY_LENGTH = 20
FINISHED_KEPT = 20      # sold-out offers remembered per city, for posting again
SALES_KEPT = 50         # unseen sales remembered per city
MAX_BILLS_PER_CITY = 10
SOCIAL_KEPT = 300       # dealings with other cities remembered per city
MAX_MESSAGE = 500       # characters in one message to another city
MESSAGES_KEPT = 300     # messages (sent and received) remembered per city
MESSAGES_PER_MINUTE = 10
MIN_BILL_HOURS, MAX_BILL_HOURS = 1, 168
MISSES_ALLOWED = 3      # payments in a row that may fail before a bill is cancelled


def social(state, now, other, kind, text):
    """Note a dealing with city `other` in this city's Social history. `kind` is "trade",
    "beast", "bill", "duel" or "ban"; `text` is told from this city's side."""
    if not state:
        return
    book = state.setdefault("social", {"lists": {}, "history": []})
    book["history"].append({"t": now, "city": other, "kind": kind, "text": text})
    del book["history"][:-SOCIAL_KEPT]


def new_market():
    return {"next_id": 1, "offers": [], "history": [], "bills": [], "beast_offers": []}


def _find(market, offer_id):
    return next((o for o in market["offers"] if o["id"] == offer_id), None)


def _valid_qty(q):
    return isinstance(q, int) and not isinstance(q, bool) and 1 <= q <= MAX_QUANTITY


def post(market, state, now, data):
    give, give_qty = data.get("give"), data.get("give_qty")
    want, want_qty = data.get("want"), data.get("want_qty")
    if give not in game.RESOURCES or want not in game.RESOURCES:
        return "Pick what to give and what you want."
    if give in game.UNTRADEABLE or want in game.UNTRADEABLE:
        return "That cannot be traded."
    if give == want:
        return "You can't trade a material for itself."
    if not (_valid_qty(give_qty) and _valid_qty(want_qty)):
        return f"Amounts must be whole numbers from 1 to {MAX_QUANTITY:,}."
    if sum(1 for o in market["offers"] if o["city"] == state["name"]) >= MAX_OFFERS_PER_CITY:
        return f"You can have at most {MAX_OFFERS_PER_CITY} open offers."
    if state["resources"][give] < give_qty:
        return f"You don't have {give_qty:,} {game.RESOURCES[give]} to offer."

    state["resources"][give] -= give_qty   # held by the market until sold or cancelled
    market["offers"].append({
        "id": market["next_id"], "city": state["name"], "posted": now,
        "give": give, "give_qty": give_qty, "want": want, "want_qty": want_qty,
        # the amounts it was posted with: they fix the lot size, and are what it is re-posted with
        "full_give": give_qty, "full_want": want_qty,
    })
    market["next_id"] += 1
    game.log(state, now, f"Offered {give_qty:,} {game.RESOURCES[give]} "
                         f"for {want_qty:,} {game.RESOURCES[want]} on the market.")
    return None


def cancel(market, state, now, offer_id):
    offer = _find(market, offer_id)
    if not offer or offer["city"] != state["name"]:
        return "That offer is no longer open."
    market["offers"].remove(offer)
    state["resources"][offer["give"]] += offer["give_qty"]
    game.log(state, now, f"Withdrew an offer; {offer['give_qty']:,} "
                         f"{game.RESOURCES[offer['give']]} returned.")
    return None


def lot(offer):
    """(amount given, amount wanted, lots left) for the smallest piece of an offer."""
    full_give, full_want = offer.get("full_give", offer["give_qty"]), offer.get("full_want", offer["want_qty"])
    lots = math.gcd(full_give, full_want)
    lot_give = full_give // lots
    return lot_give, full_want // lots, offer["give_qty"] // lot_give


def _remember_full(offer):
    """Make sure an offer knows the amounts it was posted with. Offers from before lots existed
    don't, and would otherwise be remembered as 0 for 0 once they sold out."""
    if offer["give_qty"] and offer["want_qty"]:
        offer.setdefault("full_give", offer["give_qty"])
        offer.setdefault("full_want", offer["want_qty"])


def _finish(offer, seller, now):
    """Note a sold-out offer in its owner's finished list."""
    if not seller:
        return
    seller.setdefault("finished", []).append({
        "id": offer["id"], "finished": now, "give": offer["give"], "want": offer["want"],
        "give_qty": offer.get("full_give", offer["give_qty"]), "want_qty": offer.get("full_want", offer["want_qty"])})
    del seller["finished"][:-FINISHED_KEPT]


def tidy(market, now, get_city):
    """Clear away offers with nothing left to sell (left over from when offers could restock)."""
    for offer in market["offers"]:
        _remember_full(offer)
    for offer in [o for o in market["offers"] if not o["give_qty"]]:
        market["offers"].remove(offer)
        _finish(offer, get_city(offer["city"]), now)
    # Duels from when a challenge was open to anyone: call them off and give the bets back.
    for duel in [d for d in market.get("duels", []) if "to" not in d]:
        _end_duel(market, duel, get_city(duel["city"]), refund=True)


def reactivate(market, state, now, finished_id):
    """Post a finished offer again with the amounts it shows. The goods come out of stock again."""
    old = next((f for f in state.get("finished", []) if f["id"] == finished_id), None)
    if not old:
        return "That finished order is no longer in your list."
    if not (_valid_qty(old["give_qty"]) and _valid_qty(old["want_qty"])):
        return "Fill in both amounts on that order before posting it again."
    error = post(market, state, now, {k: old[k] for k in ("give", "give_qty", "want", "want_qty")})
    if not error:
        state["finished"].remove(old)
    return error


def edit(state, finished_id, give_qty, want_qty):
    """Change the amounts a finished offer will be posted with next time."""
    old = next((f for f in state.get("finished", []) if f["id"] == finished_id), None)
    if not old:
        return "That finished order is no longer in your list."
    # An order that lost its amounts is filled in one box at a time, so one side may still be empty (0).
    if not all(_valid_qty(q) or q == 0 for q in (give_qty, want_qty)) or isinstance(give_qty, bool) or not (give_qty or want_qty):
        return f"Amounts must be whole numbers from 1 to {MAX_QUANTITY:,}."
    old["give_qty"], old["want_qty"] = give_qty, want_qty
    return None


def forget(state, finished_id):
    """Throw a finished offer away."""
    state["finished"] = [f for f in state.get("finished", []) if f["id"] != finished_id]
    return None


def accept(market, buyer, now, offer_id, get_city, lots=None, amount=None):
    """Buy `amount` of what an offer is selling (or `lots` lots of it; all that is left if both are None).

    `get_city(name)` must return the seller's up-to-date state (or None).
    """
    offer = _find(market, offer_id)
    if not offer:
        return "That offer is no longer open."
    if offer["city"] == buyer["name"]:
        return "That is your own offer."
    if offer["give"] in game.UNTRADEABLE or offer["want"] in game.UNTRADEABLE:
        return "That offer is for something that can no longer be traded. Its owner can cancel it."
    lot_give, lot_want, left = lot(offer)
    if not left:
        return "That offer is sold out."
    _remember_full(offer)
    selling = game.RESOURCES[offer["give"]]
    if amount is not None:
        if not _valid_qty(amount):
            return f"Type how much {selling} to buy."
        if amount % lot_give:
            return (f"That offer sells {selling} {lot_give} at a time, "
                    f"so buy {lot_give}, {lot_give * 2}, {lot_give * 3} and so on.")
        lots = amount // lot_give
    elif lots is None:
        lots = left
    if not _valid_qty(lots):
        return "Choose how much to buy."
    if lots > left:
        return f"Only {left * lot_give} {selling} is left in that offer."
    give_qty, want_qty = lots * lot_give, lots * lot_want
    if buyer["resources"][offer["want"]] < want_qty:
        return f"You don't have {want_qty:,} {game.RESOURCES[offer['want']]} to pay."

    got = f"{give_qty:,} {game.RESOURCES[offer['give']]}"
    paid = f"{want_qty:,} {game.RESOURCES[offer['want']]}"
    seller = get_city(offer["city"])
    offer["give_qty"] -= give_qty
    offer["want_qty"] -= want_qty
    if not offer["give_qty"]:      # sold out: it ends, and waits in the owner's finished list
        market["offers"].remove(offer)
        _finish(offer, seller, now)
    buyer["resources"][offer["want"]] -= want_qty
    buyer["resources"][offer["give"]] += give_qty
    game.log(buyer, now, f"Traded with {offer['city']}: paid {paid}, received {got}.")
    if seller:
        seller["resources"][offer["want"]] += want_qty
        left_text = (f" {offer['give_qty']:,} {game.RESOURCES[offer['give']]} still on offer."
                     if offer["give_qty"] else " That offer is now sold out.")
        game.log(seller, now, f"{buyer['name']} bought from your offer: gave {got}, received {paid}.{left_text}")
        seller.setdefault("sales", []).append({
            "t": now, "buyer": buyer["name"], "give": offer["give"], "give_qty": give_qty,
            "want": offer["want"], "want_qty": want_qty, "left": offer["give_qty"]})
        del seller["sales"][:-SALES_KEPT]

    _record(market, now, offer["city"], buyer["name"], offer["give"], give_qty, offer["want"], want_qty)
    game.tally(buyer, "bought")
    if seller:
        game.tally(seller, "sold")
    social(buyer, now, offer["city"], "trade", f"You bought {got} from their offer for {paid}.")
    social(seller, now, buyer["name"], "trade", f"They bought {got} from your offer for {paid}.")
    return None


def _record(market, now, seller, buyer, give, give_qty, want, want_qty):
    market["history"].append({"t": now, "seller": seller, "buyer": buyer,
                              "give": give, "give_qty": give_qty, "want": want, "want_qty": want_qty})
    del market["history"][:-HISTORY_LENGTH]


def drop_city(market, name):
    """Remove a city's open offers and bills (used when the city is restarted)."""
    market["offers"] = [o for o in market["offers"] if o["city"] != name]
    market["bills"] = [b for b in market["bills"] if name not in (b["from"], b["to"])]
    market["beast_offers"] = [o for o in market.get("beast_offers", []) if o["city"] != name]
    market["duels"] = [d for d in market.get("duels", []) if d["city"] != name]


def drop_proposals(market, sender, receiver):
    """Remove bills `sender` has proposed to `receiver` that are still unanswered."""
    market["bills"] = [b for b in market["bills"]
                       if not (b["status"] == "proposed" and b["from"] == sender and b["to"] == receiver)]


# ---- Bills ----

def _bill(market, bill_id):
    return next((b for b in market["bills"] if b["id"] == bill_id), None)


def bill_text(bill):
    hours = bill["every"] // 3600
    return (f"{bill['from']} sends {bill['give_qty']:,} {game.RESOURCES[bill['give']]}, "
            f"{bill['to']} sends {bill['want_qty']:,} {game.RESOURCES[bill['want']]}, "
            f"every {hours} hour{'s' if hours != 1 else ''}")


def propose_bill(market, state, now, data, get_city):
    """`state`'s city offers to send `give` to city `to` and receive `want`, every `hours`."""
    to, hours = data.get("to"), data.get("hours")
    give, give_qty = data.get("give"), data.get("give_qty")
    want, want_qty = data.get("want"), data.get("want_qty")
    target = get_city(to) if to != state["name"] else None
    if not target:
        return "Pick another city that exists to make the bill with."
    if state["name"] in target["banned"]:
        return f"{to} is not accepting bills from your city."
    if give not in game.RESOURCES or want not in game.RESOURCES:
        return "Pick what to send and what to receive."
    if give in game.UNTRADEABLE or want in game.UNTRADEABLE:
        return "That cannot be traded."
    if give == want:
        return "You can't trade a material for itself."
    if not (_valid_qty(give_qty) and _valid_qty(want_qty)):
        return f"Amounts must be whole numbers from 1 to {MAX_QUANTITY:,}."
    if not (_valid_qty(hours) and MIN_BILL_HOURS <= hours <= MAX_BILL_HOURS):
        return f"A bill repeats every {MIN_BILL_HOURS} to {MAX_BILL_HOURS} hours."
    for name in (state["name"], to):
        if sum(1 for b in market["bills"] if name in (b["from"], b["to"])) >= MAX_BILLS_PER_CITY:
            return f"{name} already has {MAX_BILLS_PER_CITY} bills."

    bill = {"id": market["next_id"], "from": state["name"], "to": to, "created": now,
            "give": give, "give_qty": give_qty, "want": want, "want_qty": want_qty,
            "every": hours * 3600, "status": "proposed", "next": None, "missed": 0}
    market["next_id"] += 1
    market["bills"].append(bill)
    game.log(state, now, f"Proposed a bill: {bill_text(bill)}.")
    social(state, now, to, "bill", f"You proposed a bill: {bill_text(bill)}.")
    social(target, now, state["name"], "bill", f"They proposed a bill: {bill_text(bill)}.")
    return None


def accept_bill(market, state, now, bill_id, get_city=None):
    bill = _bill(market, bill_id)
    if not bill or bill["status"] != "proposed" or bill["to"] != state["name"]:
        return "That bill is not waiting for your answer."
    bill.update(status="active", next=now + bill["every"])
    game.log(state, now, f"Agreed to a bill: {bill_text(bill)}.")
    social(state, now, bill["from"], "bill", f"You agreed to their bill: {bill_text(bill)}.")
    social(get_city(bill["from"]) if get_city else None, now, state["name"], "bill",
           f"They agreed to your bill: {bill_text(bill)}.")
    return None


def cancel_bill(market, state, now, bill_id, get_city):
    """Either side may end a bill (or turn down / withdraw a proposal)."""
    bill = _bill(market, bill_id)
    if not bill or state["name"] not in (bill["from"], bill["to"]):
        return "That bill no longer exists."
    market["bills"].remove(bill)
    for name in (bill["from"], bill["to"]):
        city = state if name == state["name"] else get_city(name)
        if city:
            game.log(city, now, f"{state['name']} ended the bill: {bill_text(bill)}.")
            other = bill["to"] if name == bill["from"] else bill["from"]
            social(city, now, other, "bill",
                   f"{'You' if city is state else 'They'} ended the bill: {bill_text(bill)}.")
    return None


def run_bills(market, now, get_city):
    """Make every payment that has come due. `get_city(name)` returns an up-to-date state or None."""
    for bill in [b for b in market["bills"] if b["status"] == "active" and b["next"] <= now]:
        sender, receiver = get_city(bill["from"]), get_city(bill["to"])
        if not sender or not receiver:
            market["bills"].remove(bill)
            continue
        while bill["next"] <= now:
            when, bill["next"] = bill["next"], bill["next"] + bill["every"]
            short = [c["name"] for c, res, qty in ((sender, bill["give"], bill["give_qty"]),
                                                   (receiver, bill["want"], bill["want_qty"]))
                     if c["resources"][res] < qty]
            if not short:
                sender["resources"][bill["give"]] -= bill["give_qty"]
                receiver["resources"][bill["give"]] += bill["give_qty"]
                receiver["resources"][bill["want"]] -= bill["want_qty"]
                sender["resources"][bill["want"]] += bill["want_qty"]
                bill["missed"] = 0
                text = f"Bill paid: {bill_text(bill)}."
                _record(market, when, bill["from"], bill["to"], bill["give"], bill["give_qty"],
                        bill["want"], bill["want_qty"])
            else:
                bill["missed"] += 1
                text = f"Bill missed ({' and '.join(short)} could not pay): {bill_text(bill)}."
                if bill["missed"] >= MISSES_ALLOWED:
                    text += f" It was cancelled after {MISSES_ALLOWED} missed payments in a row."
            game.log(sender, when, text)
            game.log(receiver, when, text)
            social(sender, when, bill["to"], "bill", text)
            social(receiver, when, bill["from"], "bill", text)
            if bill["missed"] >= MISSES_ALLOWED:
                market["bills"].remove(bill)
                break


def bill_rates(market, name):
    """Expected change per hour to city `name`'s resources from its active bills."""
    rates = {}
    for b in market["bills"]:
        if b["status"] != "active" or name not in (b["from"], b["to"]):
            continue
        sign = 1 if b["from"] == name else -1
        per_hour = 3600 / b["every"]
        rates[b["give"]] = rates.get(b["give"], 0) - sign * b["give_qty"] * per_hour
        rates[b["want"]] = rates.get(b["want"], 0) + sign * b["want_qty"] * per_hour
    return rates


# ---- Beast trades ----
# A city offers one beast (or egg) and says what it wants for it: an amount of
# a material, or another beast of a named species and level. The beast is held
# by the market until the trade is taken or cancelled.

def _valid_want(want):
    if not isinstance(want, dict):
        return None
    if want.get("kind") == "resource":
        if want.get("res") in game.RESOURCES and want["res"] not in game.UNTRADEABLE and _valid_qty(want.get("qty")):
            return {"kind": "resource", "res": want["res"], "qty": want["qty"]}
    elif want.get("kind") == "beast":
        level = want.get("level", 1)
        if want.get("species") in beasts.SPECIES and _valid_qty(level) and level <= beasts.MAX_LEVEL:
            return {"kind": "beast", "species": want["species"], "level": level}
    return None


def want_text(want):
    if want["kind"] == "resource":
        return f"{want['qty']:,} {game.RESOURCES[want['res']]}"
    return f"a {beasts.SPECIES[want['species']]['name']} of level {want['level']} or higher"


def _beast_offer(market, offer_id):
    return next((o for o in market.get("beast_offers", []) if o["id"] == offer_id), None)


def post_beast(market, state, now, data):
    want = _valid_want(data.get("want"))
    if not want:
        return "Say what you want for it: an amount of a material, or a kind of beast and a level."
    offers = market.setdefault("beast_offers", [])
    if sum(1 for o in offers if o["city"] == state["name"]) >= MAX_BEAST_OFFERS_PER_CITY:
        return f"You can have at most {MAX_BEAST_OFFERS_PER_CITY} beasts on offer."
    beast, error = beasts.take(state, data.get("beast"))
    if error:
        return error
    offers.append({"id": market["next_id"], "city": state["name"], "posted": now, "beast": beast, "want": want})
    market["next_id"] += 1
    game.log(state, now, f"Offered {beasts.title(beast)} for {want_text(want)}.")
    return None


def cancel_beast(market, state, now, offer_id):
    offer = _beast_offer(market, offer_id)
    if not offer or offer["city"] != state["name"]:
        return "That beast is no longer on offer."
    market["beast_offers"].remove(offer)
    beasts.give(state, now, offer["beast"])
    game.log(state, now, f"Withdrew a beast offer; {beasts.title(offer['beast'])} came home.")
    return None


def accept_beast(market, buyer, now, offer_id, get_city, pay_beast=None):
    """Take a beast offer, paying what it asks. For a beast-for-beast offer `pay_beast` is the
    id of the buyer's beast to hand over."""
    offer = _beast_offer(market, offer_id)
    if not offer:
        return "That beast is no longer on offer."
    if offer["city"] == buyer["name"]:
        return "That is your own offer."
    seller = get_city(offer["city"])
    if not seller:
        market["beast_offers"].remove(offer)
        return "The city that offered it no longer exists."
    want, name = offer["want"], beasts.title(offer["beast"])
    if want["kind"] == "resource":
        if buyer["resources"][want["res"]] < want["qty"]:
            return f"You don't have {want_text(want)} to pay."
        buyer["resources"][want["res"]] -= want["qty"]
        seller["resources"][want["res"]] += want["qty"]
        paid = want_text(want)
    else:
        mine = beasts.get(buyer, pay_beast)
        if (not mine or mine["stage"] == "egg" or mine["species"] != want["species"]
                or mine["level"] < want["level"]):
            return f"Pick one of your beasts to give: {want_text(want)}."
        mine, error = beasts.take(buyer, pay_beast)
        if error:
            return error
        paid = f"{beasts.title(mine)} (level {mine['level']})"
        beasts.give(seller, now, mine)
    market["beast_offers"].remove(offer)
    beasts.give(buyer, now, offer["beast"])
    game.log(buyer, now, f"Traded with {offer['city']}: gave {paid}, received {name}. See the Beast tab.")
    game.log(seller, now, f"{buyer['name']} took your beast offer: gave {name}, received {paid}.")
    game.tally(buyer, "beast_trades")
    if seller:
        game.tally(seller, "beast_trades")
    social(buyer, now, offer["city"], "beast", f"You took their beast offer: gave {paid}, received {name}.")
    social(seller, now, buyer["name"], "beast", f"They took your beast offer: you gave {name}, received {paid}.")
    return None


def beast_offers_view(market):
    """Beast offers as other cities may see them."""
    return [{"id": o["id"], "city": o["city"], "posted": o["posted"], "beast": beasts.public(o["beast"]),
             "want": dict(o["want"], text=want_text(o["want"]))} for o in market.get("beast_offers", [])]


# ---- Duels ----
# One city challenges another by name: it picks one of its hatched beasts and
# bets some of one material on it. The other city can see the beast but not
# the bet. It either declines, or accepts by picking a beast and a bet of its
# own. Once both have agreed the bets are shown, the beasts fight at once (see
# beasts.fight) and the winner's city takes both bets. The winning beast also
# gains a little experience.
#
# A challenger's bet is held by the market until the duel is fought, declined
# or withdrawn. Its beast stays at home but can't be traded meanwhile.

def _valid_stake(stake):
    if (isinstance(stake, dict) and stake.get("res") in game.RESOURCES and stake["res"] not in game.UNTRADEABLE
            and _valid_qty(stake.get("qty"))):
        return {"res": stake["res"], "qty": stake["qty"]}
    return None


def _goods(stake):
    return f"{stake['qty']:,} {game.RESOURCES[stake['res']]}"


def _duel(market, duel_id):
    return next((d for d in market.get("duels", []) if d["id"] == duel_id), None)


def _fighter(market, state, beast_id):
    """(beast, None) if this city can send that beast to a duel, else (None, why not)."""
    beast = beasts.get(state, beast_id)
    if not beast or beast["stage"] == "egg":
        return None, "Pick one of your hatched beasts to fight."
    if beast.get("duel") and _duel(market, beast["duel"]):
        return None, "That beast is already waiting for a duel."
    return beast, None


def post_duel(market, state, now, data, get_city):
    """Challenge the city named in data["to"]."""
    to = data.get("to")
    target = get_city(to) if to != state["name"] else None
    if not target:
        return "Pick another city that exists to challenge."
    if state["name"] in target["banned"]:
        return f"{to} is not accepting challenges from your city."
    bet = _valid_stake(data.get("bet"))
    if not bet:
        return "Say what you bet: a whole amount of 1 or more."
    duels = market.setdefault("duels", [])
    if sum(1 for d in duels if d["city"] == state["name"]) >= MAX_DUELS_PER_CITY:
        return f"You can have at most {MAX_DUELS_PER_CITY} challenges waiting for an answer."
    beast, error = _fighter(market, state, data.get("beast"))
    if error:
        return error
    if state["resources"][bet["res"]] < bet["qty"]:
        return f"You don't have {_goods(bet)} to bet."
    state["resources"][bet["res"]] -= bet["qty"]      # held until the duel is fought, declined or withdrawn
    beast["duel"] = market["next_id"]
    duels.append({"id": market["next_id"], "city": state["name"], "to": to, "posted": now,
                  "beast_id": beast["id"], "beast": beasts.public(beast), "bet": bet})
    market["next_id"] += 1
    # The bet is left out of the log: a city's log can be read by anyone visiting it.
    game.log(state, now, f"Challenged {to} to a duel with {beasts.title(beast)}.")
    game.log(target, now, f"{state['name']} has challenged you to a duel with a {beasts.title(beast)}. "
                          f"Accept or decline it in the Arena on the Beast tab.")
    social(state, now, to, "duel", f"You challenged them to a duel with your {beasts.title(beast)}.")
    social(target, now, state["name"], "duel", f"They challenged you to a duel with their {beasts.title(beast)}.")
    return None


def _end_duel(market, duel, challenger, refund=False):
    """Take a duel off the list and free the challenger's beast; `refund` gives its bet back too."""
    market["duels"].remove(duel)
    if not challenger:
        return
    beast = beasts.get(challenger, duel["beast_id"])
    if beast:
        beast.pop("duel", None)
    if refund:
        challenger["resources"][duel["bet"]["res"]] += duel["bet"]["qty"]


def cancel_duel(market, state, now, duel_id, get_city):
    """The challenger withdraws, or the challenged city declines. Either way the bet goes back."""
    duel = _duel(market, duel_id)
    if not duel or state["name"] not in (duel["city"], duel.get("to")):
        return "That challenge is no longer waiting."
    mine = duel["city"] == state["name"]
    challenger = state if mine else get_city(duel["city"])
    _end_duel(market, duel, challenger, refund=True)
    if mine:
        game.log(state, now, f"Withdrew a challenge; {_goods(duel['bet'])} returned.")
        social(state, now, duel.get("to"), "duel", "You withdrew your challenge.")
        social(get_city(duel.get("to")), now, state["name"], "duel", "They withdrew their challenge.")
    else:
        game.log(state, now, f"Declined a duel with {duel['city']}.")
        social(state, now, duel["city"], "duel", "You declined their duel.")
        social(challenger, now, state["name"], "duel", "They declined your duel.")
        if challenger:
            game.log(challenger, now, f"{state['name']} declined your duel; {_goods(duel['bet'])} returned.")
    return None


def accept_duel(market, state, now, duel_id, get_city, beast_id, bet, rng=None):
    """Accept a challenge with one of this city's beasts and a bet of its own. The fight happens at once."""
    duel = _duel(market, duel_id)
    if not duel or duel.get("to") != state["name"]:
        return "That challenge is no longer waiting."
    challenger = get_city(duel["city"])
    theirs = beasts.get(challenger, duel["beast_id"]) if challenger else None
    if not theirs:      # the challenger or its beast is gone: call it off
        _end_duel(market, duel, challenger, refund=True)
        return "That challenge is no longer open."
    mine, error = _fighter(market, state, beast_id)
    if error:
        return error
    my_bet = _valid_stake(bet)
    if not my_bet:
        return "Say what you bet: a whole amount of 1 or more."
    if state["resources"][my_bet["res"]] < my_bet["qty"]:
        return f"You don't have {_goods(my_bet)} to bet."
    state["resources"][my_bet["res"]] -= my_bet["qty"]

    # Both have agreed. Each beast's stats are raised by what was bet on it, then they fight.
    cities, fighters, bets = (challenger, state), (theirs, mine), (duel["bet"], my_bet)
    boosts = [beasts.duel_boost(b["species"], stake["res"], stake["qty"]) for b, stake in zip(fighters, bets)]
    stats = [{k: max(1, round(v * boost)) for k, v in b["stats"].items()} for b, boost in zip(fighters, boosts)]
    winner, rounds = beasts.fight(stats[0], stats[1], rng or random.Random())
    _end_duel(market, duel, challenger)
    for stake in bets:
        cities[winner]["resources"][stake["res"]] += stake["qty"]
    prize = " and ".join(_goods(stake) for stake in bets)

    sides = [{"city": c["name"], "name": beasts.title(b), "color": beasts.public(b)["color"], "level": b["level"],
              "bet": _goods(stake), "boost": boost, "stats": st}
             for c, b, stake, boost, st in zip(cities, fighters, bets, boosts, stats)]
    for i, city in enumerate(cities):
        # Each city keeps the fight told from its own side: "me" is index 0.
        city.setdefault("duels", []).append({
            "id": duel["id"], "t": now, "won": winner == i, "prize": prize, "xp": beasts.DUEL_XP if winner == i else 0,
            "sides": [sides[i], sides[1 - i]], "rounds": [dict(r, by=int(r["by"] != i)) for r in rounds]})
        del city["duels"][:-beasts.DUEL_RESULTS_KEPT]
        foe = sides[1 - i]
        game.tally(city, "duels_won" if winner == i else "duels_lost")
        game.log(city, now, f"Duel: your {sides[i]['name']} (bet {sides[i]['bet']}) "
                            f"{'beat' if winner == i else 'lost to'} {foe['city']}'s {foe['name']} (bet {foe['bet']}). "
                            + (f"You won {prize}." if winner == i else "You lost your bet."))
        social(city, now, foe["city"], "duel",
               f"Your {sides[i]['name']} (bet {sides[i]['bet']}) {'beat' if winner == i else 'lost to'} their "
               f"{foe['name']} (bet {foe['bet']}). " + (f"You won {prize}." if winner == i else "You lost your bet."))
    beasts.give_xp(cities[winner], now, fighters[winner], beasts.DUEL_XP)
    return None


def duels_view(market, name):
    """The challenges city `name` has sent or been sent. A bet is only shown to the city that made it."""
    out = []
    for d in market.get("duels", []):
        if name not in (d["city"], d.get("to")):
            continue
        entry = {"id": d["id"], "city": d["city"], "to": d.get("to"), "posted": d["posted"], "beast": d["beast"]}
        if d["city"] == name:
            entry["bet"] = dict(d["bet"], text=_goods(d["bet"]))
            entry["boost"] = beasts.duel_boost(d["beast"]["species"], d["bet"]["res"], d["bet"]["qty"])
        out.append(entry)
    return out


# ---- Messages ----
# A private note from one city to another. Each city keeps its own copy of
# what it sent and received, so one city restarting does not lose the other's.

def _mailbox(state):
    return state.setdefault("messages", [])


def send_message(state, now, to, text, get_city):
    target = get_city(to) if to != state["name"] else None
    if not target:
        return "Pick another city that exists to write to."
    if state["name"] in target["banned"]:
        return f"{to} is not accepting messages from your city."
    text = " ".join(text.split()) if isinstance(text, str) else ""
    if not text:
        return "Write a message first."
    if len(text) > MAX_MESSAGE:
        return f"Messages can be at most {MAX_MESSAGE} characters."
    if moderation.check_message(text):
        return moderation.check_message(text)
    recent = [m for m in _mailbox(state) if m["mine"] and now - m["t"] < 60]
    if len(recent) >= MESSAGES_PER_MINUTE:
        return "You are sending messages too quickly. Wait a moment."
    state["message_count"] = state.get("message_count", 0) + 1
    _mailbox(state).append({"id": state["message_count"], "t": now, "city": to, "mine": True, "text": text, "read": True})
    waiting = any(m["city"] == state["name"] and not m["read"] for m in _mailbox(target))
    target["message_count"] = target.get("message_count", 0) + 1
    _mailbox(target).append({"id": target["message_count"], "t": now, "city": state["name"], "mine": False,
                             "text": text, "read": False})
    game.tally(state, "messages_sent")
    game.tally(target, "messages_received")
    for box in (_mailbox(state), _mailbox(target)):
        del box[:-MESSAGES_KEPT]
    if not waiting:     # one line in the log per conversation waiting, not one per message
        game.log(target, now, f"{state['name']} sent you a message. See the Social tab.")
    return None


def read_messages(state, other):
    """The player has looked at what `other` wrote to them."""
    for m in _mailbox(state):
        if m["city"] == other:
            m["read"] = True
    return None
