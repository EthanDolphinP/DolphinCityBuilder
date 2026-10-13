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

A bill is a repeating trade between two named cities ("every 24 hours I send
you 10 Stone and you send me 20 Gold"). One city proposes it, the other has to
accept it, and either can cancel it at any time. When a payment comes due and
either side can't pay, nothing changes hands that time.
"""

import math

import game

MAX_OFFERS_PER_CITY = 10
MAX_QUANTITY = 1_000_000
HISTORY_LENGTH = 20
FINISHED_KEPT = 20      # sold-out offers remembered per city, for posting again
SALES_KEPT = 50         # unseen sales remembered per city
MAX_BILLS_PER_CITY = 10
MIN_BILL_HOURS, MAX_BILL_HOURS = 1, 168
MISSES_ALLOWED = 3      # payments in a row that may fail before a bill is cancelled


def new_market():
    return {"next_id": 1, "offers": [], "history": [], "bills": []}


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
        return "Amounts must be whole numbers of 1 or more."
    if sum(1 for o in market["offers"] if o["city"] == state["name"]) >= MAX_OFFERS_PER_CITY:
        return f"You can have at most {MAX_OFFERS_PER_CITY} open offers."
    if state["resources"][give] < give_qty:
        return f"You don't have {give_qty} {game.RESOURCES[give]} to offer."

    state["resources"][give] -= give_qty   # held by the market until sold or cancelled
    market["offers"].append({
        "id": market["next_id"], "city": state["name"], "posted": now,
        "give": give, "give_qty": give_qty, "want": want, "want_qty": want_qty,
        # the amounts it was posted with: they fix the lot size, and are what it is re-posted with
        "full_give": give_qty, "full_want": want_qty,
    })
    market["next_id"] += 1
    game.log(state, now, f"Offered {give_qty} {game.RESOURCES[give]} "
                         f"for {want_qty} {game.RESOURCES[want]} on the market.")
    return None


def cancel(market, state, now, offer_id):
    offer = _find(market, offer_id)
    if not offer or offer["city"] != state["name"]:
        return "That offer is no longer open."
    market["offers"].remove(offer)
    state["resources"][offer["give"]] += offer["give_qty"]
    game.log(state, now, f"Withdrew an offer; {offer['give_qty']} "
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
        return f"You don't have {want_qty} {game.RESOURCES[offer['want']]} to pay."

    got = f"{give_qty} {game.RESOURCES[offer['give']]}"
    paid = f"{want_qty} {game.RESOURCES[offer['want']]}"
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
        left_text = (f" {offer['give_qty']} {game.RESOURCES[offer['give']]} still on offer."
                     if offer["give_qty"] else " That offer is now sold out.")
        game.log(seller, now, f"{buyer['name']} bought from your offer: gave {got}, received {paid}.{left_text}")
        seller.setdefault("sales", []).append({
            "t": now, "buyer": buyer["name"], "give": offer["give"], "give_qty": give_qty,
            "want": offer["want"], "want_qty": want_qty, "left": offer["give_qty"]})
        del seller["sales"][:-SALES_KEPT]

    _record(market, now, offer["city"], buyer["name"], offer["give"], give_qty, offer["want"], want_qty)
    return None


def _record(market, now, seller, buyer, give, give_qty, want, want_qty):
    market["history"].append({"t": now, "seller": seller, "buyer": buyer,
                              "give": give, "give_qty": give_qty, "want": want, "want_qty": want_qty})
    del market["history"][:-HISTORY_LENGTH]


def drop_city(market, name):
    """Remove a city's open offers and bills (used when the city is restarted)."""
    market["offers"] = [o for o in market["offers"] if o["city"] != name]
    market["bills"] = [b for b in market["bills"] if name not in (b["from"], b["to"])]


def drop_proposals(market, sender, receiver):
    """Remove bills `sender` has proposed to `receiver` that are still unanswered."""
    market["bills"] = [b for b in market["bills"]
                       if not (b["status"] == "proposed" and b["from"] == sender and b["to"] == receiver)]


# ---- Bills ----

def _bill(market, bill_id):
    return next((b for b in market["bills"] if b["id"] == bill_id), None)


def bill_text(bill):
    hours = bill["every"] // 3600
    return (f"{bill['from']} sends {bill['give_qty']} {game.RESOURCES[bill['give']]}, "
            f"{bill['to']} sends {bill['want_qty']} {game.RESOURCES[bill['want']]}, "
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
        return "Amounts must be whole numbers of 1 or more."
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
    return None


def accept_bill(market, state, now, bill_id):
    bill = _bill(market, bill_id)
    if not bill or bill["status"] != "proposed" or bill["to"] != state["name"]:
        return "That bill is not waiting for your answer."
    bill.update(status="active", next=now + bill["every"])
    game.log(state, now, f"Agreed to a bill: {bill_text(bill)}.")
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
