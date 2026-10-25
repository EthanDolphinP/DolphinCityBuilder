"""Put the market from a backup back, keeping what was traded since: python3 merge_market.py backup.tar.gz DATA

For a move to a new server where the market did not come across but the cities did (see README, "Your own
server"). The game must be stopped (`dolphincity merge-market` does that). The backup's market goes back exactly
as it was, since the cities restored with it already match it; everything posted on the new server since is kept,
numbered after the backup's own, and the cities that refer to those numbers are changed to match. The current
market is kept as market.before-merge.json, in case anything needs to be undone.
"""
import io
import json
import pathlib
import shutil
import sys
import tarfile

LISTS = ("offers", "beast_offers", "artifact_offers", "bills", "duels")
HISTORY_LENGTH = 20


def main(backup, data):
    data = pathlib.Path(data)
    with tarfile.open(backup) as tar:            # compressed or not: a browser sometimes unpacks it on the way
        member = next((m for m in tar.getmembers() if m.name.lstrip("./") == "market.json"), None)
        if member is None:
            sys.exit(f"{backup} has no market.json in it. Nothing was changed.")
        old = json.load(io.TextIOWrapper(tar.extractfile(member), encoding="utf-8"))
        cutoff = member.mtime                     # when the old server saved it for the last time
    current_file = data / "market.json"
    cur = json.loads(current_file.read_text(encoding="utf-8")) if current_file.exists() else {}

    start = old.get("next_id", 1)
    renumber = {}                                 # id on the new server -> its id from now on
    merged = dict(old)
    for key in LISTS:
        merged[key] = list(old.get(key, []))
        for item in cur.get(key, []):
            renumber[item["id"]] = start + item["id"]
            merged[key].append({**item, "id": renumber[item["id"]]})
    merged["history"] = sorted(old.get("history", []) + cur.get("history", []), key=lambda h: h.get("t", 0))[-HISTORY_LENGTH:]
    merged["next_id"] = start + cur.get("next_id", 1)

    # cities that refer to something renumbered: offers that finished after the move, and beasts waiting in a duel
    duel_beasts = {(d["city"], d["beast_id"]): renumber[d["id"]] for d in cur.get("duels", [])}
    changed = 0
    for path in (data / "saves").glob("*.json"):
        state = json.loads(path.read_text(encoding="utf-8"))
        touched = False
        for f in state.get("finished", []):
            if f.get("finished", 0) > cutoff and f.get("id") in renumber:
                f["id"] = renumber[f["id"]]
                touched = True
        for b in state.get("beasts", []):
            new_id = duel_beasts.get((state.get("name"), b.get("id")))
            if new_id is not None and b.get("duel") is not None:
                b["duel"] = new_id
                touched = True
        if touched:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state), encoding="utf-8")
            tmp.replace(path)
            changed += 1

    if current_file.exists():
        shutil.copy2(current_file, data / "market.before-merge.json")
    tmp = current_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged), encoding="utf-8")
    tmp.replace(current_file)
    counts = ", ".join(f"{len(merged[k])} {k.replace('_', ' ')}" for k in LISTS)
    print(f"Market merged: {counts}; {len(renumber)} posted since the move were kept and renumbered; "
          f"{changed} cities updated to match. The market as it was is in market.before-merge.json.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
