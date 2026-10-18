"""Keeps slurs out of the game: city names, area names and messages between cities.

check_name(text) and check_message(text) return why the text is not allowed, or None. Slurs are refused
everywhere; swearing only in names, which every player (and the Discord server) sees.

The text is first made plain: accents dropped, look-alike digits and signs read as letters (n1gg3r, @ss),
CamelCase split into words, and the letters squashed together with every separator taken out
("n.i.g.g.e.r", "n i g g e r"). A letter written many times over ("niiiigger") still matches.
Terms in an "anywhere" list match inside the squashed text; "word" terms only as a whole word, because
they hide inside innocent words (raccoon, Scunthorpe, grape). A few of those also count at the start or
end of a longer word (Fagtown), unless it is one of the INNOCENT words (raccoon, cocktail).

The built-in lists are stored in ROT13 so this file does not spell them out. More words can be blocked
without a code change: the Discord /blockword command (an admin's) adds them to blocked_words.json in
the game's data folder; they count as slurs, matched anywhere.
"""
import codecs
import json
import re
import unicodedata
from pathlib import Path

_r = lambda words: [codecs.decode(w, "rot13") for w in words]
SLURS_ANYWHERE = _r(['avttre', 'avttn', 'avttnu', 'snttbg', 'jrgonpx', 'gbjryurnq', 'enturnq', 'tbyyvjbt', 'fnaqavttre', 'puvanzna', 'gneonol', 'fcrnepuhpxre', 'cbepuzbaxrl', 'whatyrohaal', 'mvccreurnq'])
SLURS_WORD = _r(['snt', 'sntf', 'snttl', 'puvax', 'puvaxf', 'fcvp', 'fcvpf', 'fcvpx', 'xvxr', 'xvxrf', 'genaal', 'genaavrf', 'genaavr', 'qlxr', 'qlxrf', 'pbba', 'pbbaf', 'tbbx', 'tbbxf', 'ornare', 'ornaref', 'cnxv', 'cnxvf', 'ergneq', 'ergneqf', 'ergneqrq', 'jbc', 'jbcf', 'furznyr', 'artebvq', 'qnexvr', 'qnexvrf', 'tlccb', 'xnssve', 'xnssre', 'avt', 'avtf', 'abt', 'wvtnobb', 'zbatbybvq', 'fcnm', 'fcnfgvp'])
RUDE_ANYWHERE = _r(['shpx', 'zbgureshpxre', 'nffubyr', 'ovgpu', 'juber', 'chffl', 'cravf', 'intvan', 'cbea', 'uvgyre', 'crqbcuvyr', 'cnrqbcuvyr', 'zbyrfg', 'phzfubg', 'oybjwbo', 'qvyqb', 'anmv'])
RUDE_WORD = _r(['fuvg', 'fuvgf', 'fuvggl', 'pbpx', 'pbpxf', 'qvpx', 'qvpxf', 'fyhg', 'fyhgf', 'encr', 'encrq', 'gvgf', 'gjng', 'jnax', 'jnaxre', 'phz', 'wvmm', 'nany', 'nahf', 'xxx', 'urvy', 'phag', 'phagf', 'encvfg', 'cvff', 'nefr', 'snc'])
EDGE = _r(['snt', 'xvxr', 'fcvp', 'puvax', 'tbbx', 'genaal', 'ergneq', 'pbba', 'qlxr', 'fuvg', 'phag', 'fyhg', 'gjng', 'jnax', 'qvpx', 'pbpx', 'encr', 'cvff', 'wvmm', 'snc', 'cnxv', 'ornare', 'qnexvr'])
INNOCENT = ['raccoon', 'cocoon', 'tycoon', 'scrape', 'grape', 'drape', 'rapeseed', 'spice', 'spicy', 'spica', 'dickens', 'dickins', 'dickson', 'dickey', 'cockpit', 'cocktail', 'cockatoo', 'cockatiel', 'cockerel', 'cockney', 'cockroach', 'cockburn', 'cockle', 'peacock', 'hancock', 'hitchcock', 'woodcock', 'gamecock', 'weathercock', 'shitake', 'shiitake', 'pissarro', 'fagin', 'fagatogo', 'retardant', 'wankel', 'pakistan', 'chinkapin', 'dykeside', 'slutsk', 'kikeriki', 'gooker', 'beanery', 'coonawarra', 'snowdyke', 'offasdyke', 'dykehead']

LOOKALIKE = str.maketrans({"0": "o", "1": "i", "!": "i", "|": "i", "3": "e", "4": "a", "@": "a", "5": "s", "$": "s",
                           "7": "t", "+": "t", "8": "b", "9": "g", "6": "g", "2": "z"})
EXTRA_FILE = None      # set by the server: DATA / "blocked_words.json"


def _pattern(word):
    """A word with each letter allowed to repeat: niiigger, fuuuck."""
    return "".join(re.escape(c) + "+" for c in word)


def _compile(anywhere, words):
    return (re.compile("|".join(_pattern(w) for w in sorted(anywhere, key=len, reverse=True))) if anywhere else None,
            re.compile("(?:" + "|".join(_pattern(w) for w in sorted(words, key=len, reverse=True)) + ")(?:e?s|z)?") if words else None)


_SLURS = _compile(SLURS_ANYWHERE, SLURS_WORD)
_RUDE = _compile(RUDE_ANYWHERE, RUDE_WORD)
_EDGE_SLURS = re.compile("|".join(f"^{_pattern(w)}|{_pattern(w)}$" for w in EDGE if w in SLURS_WORD))
_EDGE_RUDE = re.compile("|".join(f"^{_pattern(w)}|{_pattern(w)}$" for w in EDGE))


def _edge(words, compiled):
    """A word that starts or ends with one of the EDGE terms, and is not an innocent word that happens to."""
    return any(compiled.search(w) and not any(ok in w for ok in INNOCENT) for w in words)


def extra_words():
    """The words an admin has added (lowercase letters only), or []."""
    try:
        return [w for w in json.loads(Path(EXTRA_FILE).read_text(encoding="utf-8")) if isinstance(w, str) and w]
    except (OSError, TypeError, ValueError):
        return []


def plain(word):
    """A blocked word as the filter compares it: lowercase letters, nothing else."""
    return "".join(c for c in _fold(word).translate(LOOKALIKE) if c.isalpha())


def _fold(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def _forms(text):
    """(whole words, every letter squashed together) of the text, made plain."""
    text = re.sub(r"([a-z])([A-Z])|([A-Z])([A-Z][a-z])", lambda m: " ".join(g for g in m.groups() if g), text)  # CamelCase
    text = _fold(text)
    words = [w for w in re.split(r"[^a-z]+", text.translate(LOOKALIKE)) if w]
    words += [w for w in re.split(r"[^a-z]+", text) if w]          # the digits as written too ("b2b", not "bzb")
    return words, "".join(c for c in text.translate(LOOKALIKE) if c.isalpha())


def _hits(text, compiled, extra=(), edge=None):
    words, squashed = _forms(text)
    anywhere, whole = compiled
    if anywhere and anywhere.search(squashed):
        return True
    if whole and any(whole.fullmatch(w) for w in words):
        return True
    if edge and _edge(words, edge):
        return True
    return any(re.search(_pattern(w), squashed) for w in extra)


def is_slur(text):
    return isinstance(text, str) and _hits(text, _SLURS, extra_words(), _EDGE_SLURS)


def is_rude(text):
    return isinstance(text, str) and (is_slur(text) or _hits(text, _RUDE, edge=_EDGE_RUDE))


def check_name(text):
    """Why this name (of a city or an area) is not allowed, or None."""
    if is_rude(text):
        return "That name is not allowed. Please pick another."
    return None


def check_message(text):
    """Why this message is not allowed, or None."""
    if is_slur(text):
        return "That message has a word in it that is not allowed in the game."
    return None
